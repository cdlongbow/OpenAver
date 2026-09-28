#!/usr/bin/env python
import json, os, subprocess, sys
PKGUSER = "openaver-svc"

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

pairs = shares()

# key 用 index，不要拿共用資料夾名字 sanitize 後重建路徑——中文／空白／連字號都會壞掉。
# 名字→真實路徑的對照寫成檔案交給 postinst 讀（postinst 是 package user，讀得到 0644）。
try:
    with open("/tmp/openaver_wizard_shares.json", "w") as f:
        json.dump({f"pkgwizard_share_{i}": p for i, (n, p) in enumerate(pairs)}, f)
    os.chmod("/tmp/openaver_wizard_shares.json", 0o644)
except Exception:
    pass

items = []
if os.uname().machine not in ("aarch64", "x86_64"):
    # preinst 會擋下安裝，但它的訊息使用者看不到（只進 log）⇒ 這裡是唯一講得出原因的地方（§K15）
    items.append({"desc": "<b>這台 NAS 無法安裝 OpenAver。</b><br>OpenAver 需要 64 位元處理器，這台是 "
                  + os.uname().machine + "（例如 DS218j／DS216j 等 32 位元機種）。按下一步後安裝會失敗。"})
items.append({"desc": "選擇你的影片片庫在哪個共用資料夾。OpenAver 會把它設成掃描來源，裝好就能直接用。"})
if pairs:
    items.append({"type": "multiselect",
                  "subitems": [{"key": f"pkgwizard_share_{i}", "desc": n, "defaultValue": False}
                               for i, (n, p) in enumerate(pairs)]})
else:
    items.append({"desc": "（找不到共用資料夾，裝好之後可以在掃描頁自己加）"})

items.append({"desc": (
    "<br><b>安裝完成後還有一步，OpenAver 沒有辦法代勞：</b><br>"
    "Synology 不允許第三方套件自行變更資料夾權限，所以請到<br>"
    "<b>控制台 → 共用資料夾 →（上面選的那個）→ 編輯 → 權限 →"
    " 左上下拉選「系統內部使用者」→ 勾選 <code>" + PKGUSER + "</code> → 可讀寫</b><br>"
    "沒有做這一步，OpenAver 會掃到 0 部影片。<br>"
    "（Jellyfin、Plex、Emby 在 Synology 上同樣需要這一步，而且它們要勾兩個。）")})

page = [{"step_title": "OpenAver 影片資料夾", "items": items}]

out = os.environ.get("SYNOPKG_TEMP_LOGFILE")
if out:
    with open(out, "w") as f:
        json.dump(page, f, ensure_ascii=False)
else:                      # 沒有該環境變數時退回 stdout，方便手動執行除錯
    sys.stdout.write(json.dumps(page, ensure_ascii=False))
