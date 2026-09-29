#!/usr/bin/env python
import json, os, subprocess, sys
PKGUSER = "openaver-svc"
LAYOUT_JSON_PATH = "/var/packages/OpenAver/var/data/.layout.json"

def shares():
    """列出本機共用資料夾。回 [(顯示名, 路徑)]。

    ⚠️ 不要用 /usr/syno/sbin/synoshare：**安裝精靈是以 package user 身分執行的**
    （DS918+ / DSM 7.3.1 實測 uid=package user、cwd=/usr/syno/synoman/webapi），
    而 synoshare 是 `-r-x------ root`（0500）⇒ PermissionError，清單會變空、
    使用者看到「找不到共用資料夾」。/etc/space 同樣讀不到。
    純 os.listdir 是 package user 讀得到的唯一一條路，且跨 volume 可用。
    """
    SKIP = {"#recycle", "lost+found", "#snapshot", "OpenAver"}
    out = []
    for n in range(1, 9):
        vol = "/volume%d" % n
        if not os.path.isdir(vol):
            continue
        try:
            entries = sorted(os.listdir(vol))
        except Exception:
            continue
        for name in entries:
            if name.startswith("@") or name in SKIP:
                continue
            p = os.path.join(vol, name)
            try:
                if os.path.isdir(p):
                    out.append((name if n == 1 else "%s (%s)" % (name, vol), p))
            except Exception:
                pass
    return out

def has_existing_data(candidates=None):
    """var 底下的 symlink 只在安裝完成後才建立，重裝時精靈跑在安裝之前讀不到，退回檢查真實落點 @appdata。"""
    if candidates is None:
        candidates = [LAYOUT_JSON_PATH] + [
            "/volume%d/@appdata/OpenAver/data/.layout.json" % n for n in range(1, 9)
        ]
    for path in candidates:
        try:
            if os.path.exists(path):
                return True
        except Exception:
            continue
    return False


def build_items(pairs, existing_data):
    items = []
    if os.uname().machine not in ("aarch64", "x86_64"):
        # preinst 會擋下安裝，但它的訊息使用者看不到（只進 log）⇒ 這裡是唯一講得出原因的地方（§K15）
        items.append({"desc": "<b>這台 NAS 無法安裝 OpenAver。</b><br>OpenAver 需要 64 位元處理器，這台是 "
                      + os.uname().machine + "（例如 DS218j／DS216j 等 32 位元機種）。按下一步後安裝會失敗。"})
    if existing_data:
        items.append({"desc": "偵測到既有資料，設定都會保留；這裡選的資料夾會加進掃描來源，OpenAver 也會自動取得它的讀寫權限。"})
        items.append({"desc": "重新安裝會清除區網密碼，裝好後請重新設定。"})
    else:
        items.append({"desc": "選擇你的影片片庫在哪個共用資料夾。OpenAver 會自動取得這個資料夾的讀寫權限，並設成掃描來源，裝好就能直接用。"})

    items.append({
        "type": "combobox",
        "desc": "選擇影片片庫所在的共用資料夾：",
        "subitems": [{
            "key": "wizard_library_share",
            "desc": "片庫",
            "mode": "remote",
            "editable": False,
            "valueField": "name",
            "displayField": "name",
            "api_store": {
                "api": "SYNO.Core.Share",
                "method": "list",
                "version": 1,
                "baseParams": {
                    "limit": -1,
                    "offset": 0,
                    "shareType": "local",
                    "additional": ["vol_path", "is_usb_share"],
                },
                "root": "shares",
                "idProperty": "name",
                "fields": ["name", "vol_path", "is_usb_share"],
            },
            "validator": {"allowBlank": False},
        }],
    })
    items.append({"desc": "請確認上面選的是你的影片資料夾——它會被授予讀寫權限。"})
    items.append({"desc": "下拉是空的？請先到控制台建立共用資料夾，再重新安裝 OpenAver。"})
    items.append({"desc": "還有其他共用資料夾也放了影片？勾起來一併加進掃描來源："})
    if pairs:
        items.append({"type": "multiselect",
                      "subitems": [{"key": f"pkgwizard_share_{i}", "desc": n, "defaultValue": False}
                                   for i, (n, p) in enumerate(pairs)]})
    else:
        items.append({"desc": "（沒有其他可勾選的共用資料夾）"})
    items.append({"desc": "勾選的這些 OpenAver 無法自動授權，裝好後請到控制台手動授權，步驟見說明文件。"})
    items.append({"desc": (
        "選為『片庫』的資料夾會授予 OpenAver 讀寫權限。"
        "套件裝著的期間，在控制台拿掉這個權限，下次 OpenAver 啟動時會自動加回來。"
        "要收回：先移除套件，再到控制台拿掉 <code>" + PKGUSER + "</code> 的權限（移除套件不會自動收回）。")})
    return items


if __name__ == "__main__":
    pairs = shares()

    # key 用 index，不要拿共用資料夾名字 sanitize 後重建路徑——中文／空白／連字號都會壞掉。
    # 名字→真實路徑的對照寫成檔案交給 postinst 讀（postinst 是 package user，讀得到 0644）。
    try:
        with open("/tmp/openaver_wizard_shares.json", "w") as f:
            json.dump({f"pkgwizard_share_{i}": p for i, (n, p) in enumerate(pairs)}, f)
        os.chmod("/tmp/openaver_wizard_shares.json", 0o644)
    except Exception:
        pass

    items = build_items(pairs, has_existing_data())
    page = [{"step_title": "OpenAver 影片資料夾", "items": items}]

    out = os.environ.get("SYNOPKG_TEMP_LOGFILE")
    if out:
        with open(out, "w") as f:
            json.dump(page, f, ensure_ascii=False)
    else:                      # 沒有該環境變數時退回 stdout，方便手動執行除錯
        sys.stdout.write(json.dumps(page, ensure_ascii=False))
