"""cover_layout.py — 封面正典位置解析的單一真理來源（feature/112，CD-112-1）。

依賴僅 `os`（`os.path` 純字串運算 + `os.path.exists`）。**不 import** `core.config`
（`STEM_IMAGE_MODES`）——本模組目前只有 `resolve_cover_target` 的 stub 版本，本體
無條件回傳同名候選，不會用到白名單常數；T3（PR2）把 stub 換成三步規則時才會加這行
import（Opus 裁決：本 PR 若 import 未使用的名稱，會被 `pyproject.toml` 的 ruff
`select`（含 `"F"`，涵蓋 F401 unused-import）判為錯誤，與 DoD「`ruff check .` 全綠」
直接衝突）。**不 import** `core.path_utils`。

為什麼用 `os.path` 純字串運算、**不違反** CLAUDE.md 的 `path_utils` 規則：
CLAUDE.md 的路徑處理禁止清單針對的是**跨 Zone 的路徑格式轉換**——手動 strip/建構
`file:///` URI、`replace('/', '\\')` 做分隔符轉換、手動 `startswith('file:///')`
判斷、自建 shadow 路徑轉換 helper。本模組三個函式（`cover_base_stem` /
`cover_candidates` / `resolve_cover_target`）做的是**同一個 Zone 內（Zone 1，已由
呼叫端正規化過的後端 FS 原生路徑）、字串尾端的檔名語意運算**：剝副檔名、剝
`-poster` / `-fanart` 後綴、換副檔名——不跨 Zone、不碰路徑分隔符、不處理
`file://` URI，因此不落在 `path_utils.py` 的管轄範圍內。既有先例一致：
`web/routers/scanner.py::_cover_base_stem`（本模組 `cover_base_stem` 的升格前身，
CD-112-9）本來就在 `path_utils.py` 之外用 `os.path.splitext` + 字串切片；
`core/database/migrate.py`、`core/enricher.py`、`core/organizer.py`、
`core/readonly_producer.py` 現有共六處 `Path(...).with_suffix('.jpg')` 也都是同一類
「檔名尾端語意運算」，同樣不在 `path_utils.py` 裡。`path_utils.py` 自身的定位是
「支援 Windows 本地 / WSL 網路路徑 / Unix 路徑」的**跨環境格式轉換**，不是
「副檔名／後綴管理」，兩者職責不重疊。

**單一真理來源（CD-112-1）**：本模組是封面正典位置推導邏輯的唯一實作。任何需要
「從封面路徑還原片級 stem」「列出 stem 級候選」「決定本次封面寫到哪」
「算 NFO 圖片旗標」的呼叫點，一律呼叫這裡的公開函式，**不得各自重新推導一份**
（重新推導會製造鏡像漂移，正是 feature/105／111 已經踩過、CD-112-9 意圖根除的
那一類 bug 的成因）。

**本 PR（T1）的範圍**：四個公開函式全部落地，但 `resolve_cover_target` 是 **stub**
——本體無條件回傳同名候選，不檢查磁碟、不檢查 `external_manager`。三步規則（真正
的解析政策）是 T3（PR2，feature/112b）的範圍。**零呼叫端改動**——本檔與
`tests/unit/test_cover_layout.py` 是本 PR 唯二新增的檔案，既有的六個推導點
（`scanner.py`、`migrate.py`、`enricher.py`、`organizer.py`、`readonly_producer.py`）
維持原樣，換掉它們是 T2b／T2c 的範圍。
"""

import os

COVER_EXT = '.jpg'


def cover_base_stem(cover_fs: str) -> str:
    """從封面路徑還原「片級 stem」：剝掉副檔名，再剝掉 -poster / -fanart 後綴。

    <dir>/ABC-123-fanart.jpg → <dir>/ABC-123

    升格自 web/routers/scanner.py::_cover_base_stem（CD-112-9），行為**逐字等價**
    ——包含它的既有限制，本函式不修正、不擴充：
    - `os.path.splitext` 只剝**最後一個**副檔名（中段的 `.` 不受影響，例如
      `ABC-123.vol1.jpg` → `ABC-123.vol1`）。
    - 用 `str.endswith` + 切片剝一次後綴，**大小寫敏感**（`-FANART` 不會被剝）。
    - 只剝一次（`break`）：先剝掉尾端 `-fanart`，即使剝完後仍以 `-poster` 結尾
      也不會連著剝掉第二層。
    - 純尾碼比對，**不消歧義**：`my-fanart.jpg` 這種本來就以 `-fanart` 結尾的
      原生檔名，一樣會被剝成 `my`——這是既有的結構性二義性（CD-112-9 是純升格，
      不是這裡順手修掉）。

    回傳形狀：`str`，與輸入同一個路徑格式（不做任何 Zone 轉換）。
    """
    stem = os.path.splitext(cover_fs)[0]
    for suffix in ('-poster', '-fanart'):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    return stem


def cover_candidates(base_stem: str) -> tuple[str, str]:
    """(同名, fanart) 兩個 stem 級候選，順序即優先序（CD-112-3）。

    純字串串接，零 I/O——不呼叫 `os.path.exists`，呼叫端自行決定要不要檢查磁碟。
    """
    return (base_stem + COVER_EXT, base_stem + '-fanart' + COVER_EXT)


def resolve_cover_target(base_stem: str, external_manager: str) -> str:
    """本次封面應該寫到哪 / 記帳該指哪（spec §2.1.1）。

    **本 PR（T1）是 stub**：無條件回傳 `base_stem + COVER_EXT`，不檢查磁碟、不檢查
    `external_manager`（該參數本 PR 完全不會被讀取，但簽名必須與最終版一致，
    T3 只換函式本體、不改呼叫端簽名）。

    PR2（112b）會把本體換成三步規則；在此之前刻意維持改動前行為，讓 T2b 的代換可證明為零行為變更。
    三步規則細節（T3 才落地，本 PR 不實作）：① 同名已存在 → 沿用 ② fanart 已存在 → 沿用
    ③ 皆無 → external_manager in STEM_IMAGE_MODES ? fanart : 同名。
    """
    return base_stem + COVER_EXT


def nfo_image_flag(base_stem: str, suffix: str, wrote_this_run: bool) -> bool:
    """餵給 generate_nfo 的 has_poster / has_fanart（CD-112-16）。

    = wrote_this_run or os.path.exists(base_stem + suffix + COVER_EXT)

    Why 磁碟真相而非「本次寫了什麼」：唯讀路徑的 NFO 是無條件重寫，preserve
    命中時「本次沒產圖」，若照實傳 False，`generate_nfo` 會把圖片標籤退回指向
    同名 `.jpg`——那個檔在新佈局可能不存在。

    ⚠️ 只准餵 generate_nfo，不得回灌 _clean_stale_singletons：後者必須維持
    「本次真的產了新檔才刪舊檔」這個既有語意，否則會把還在服役的正典封面
    當成過期檔案刪掉。
    """
    return wrote_this_run or os.path.exists(base_stem + suffix + COVER_EXT)


def is_same_target(src: str, dst: str) -> bool:
    """判斷 src / dst 是否指向磁碟上同一份檔案（字串相等，或 inode 別名）。

    Codex PR review P1（feature/112a-T2c，2026-08-04）：`generate_jellyfin_images`
    的同檔短路原本只比對字串相等，但 `cover_path`（DB 路徑映射）與
    `poster_path` / `fanart_path`（lexical stem 拼出）之間**沒有「不得
    symlink／hardlink」的保證**。外部庫工具（MDCX/Javinizer 等）常把
    `<stem>-poster.jpg` 建成 `<stem>.jpg` 的 hardlink 或 symlink——此時字串
    不等但兩個路徑是同一個 inode，`crop_to_poster` 會**就地覆寫使用者的封面
    原檔**（實測 800×538 → 379×538，md5 改變），直接違反 prd.md 技術決策 #6
    承重牆「衍生產物不回寫原檔」。CD-112-8 原文即為「路徑相等**或**
    `os.path.samefile`」，本函式是把原文落實成單一真理來源（CD-112-1），
    供 `organizer.py`（本 PR）、`enricher.py:294`、`readonly_producer.py:763`
    （T3）共三處呼叫。

    **fail-closed，但只對「未知」錯誤**：`os.path.samefile` 在權限被拒、或部分
    網路磁碟／Windows 共用資源上會拋 `OSError` 子類（實測 `PermissionError`
    可重現：對父目錄 `chmod 0o000` 後 `os.path.samefile` 直接拋出，不是回傳
    False）。這類**未知**例外拋出時**視為同一檔**（回傳 `True`，呼叫端因此
    跳過寫入）——兩個方向的後果不對稱：誤判「不同檔」而照常寫入，最壞情況是
    **就地毀損使用者原檔（不可逆）**；誤判「同一檔」而跳過寫入，最壞情況只是
    **少產一張衍生圖（可由齒輪重刮／掃描頁批次補齊救回）**。不確定時一律選
    代價小的那邊。

    **`FileNotFoundError` 是唯一的例外，獨立分流、不落入上面的 fail-closed**：
    `dst` 通常是尚未產生的衍生檔（`-poster.jpg` / `-fanart.jpg`），這是最常見
    的情況，`samefile` 對不存在的路徑（`src` 或 `dst` 任一邊）一律拋
    `FileNotFoundError`——這是「沒有可被覆寫的同一檔」，不是「不確定」，回傳
    `False` 讓正常產圖流程繼續。**這個分流本身就是本函式修過一次的 TOCTOU
    洞**：舊版先呼叫 `os.path.exists(dst)` 判斷要不要進 `samefile`，但
    `exists()` 回傳與 `samefile()` 執行之間存在檔案可被外部程序刪除的窗口——
    `exists()` 剛好回 `True`，`dst` 隨即被刪，`samefile` 才拋出
    `FileNotFoundError`，卻被舊版的 `except OSError` 一併吞成 `True`，讓呼叫端
    誤報「已產圖」而目的檔實際不存在，等於重新製造 NFO 懸空引用（Codex PR
    review 第二輪 P1，2026-08-04）。現在的寫法**不再先 `exists()` 探測**，直接
    呼叫 `samefile`，`FileNotFoundError` 由專屬的 `except` 分支承接、與其他
    `OSError` 分開判——沒有「探測」與「使用」分成兩步的時間窗，這條 race 在
    結構上不存在了。**broken symlink**（`os.path.lexists` 為 True 但目標不
    存在）在這裡的行為與「檔案不存在」一致：`samefile` 對 broken symlink 會
    follow 到不存在的目標並拋 `FileNotFoundError`，同樣走「視為不同檔、照常
    寫入」這條路——這是安全的，因為 broken symlink 底下沒有真正的檔案內容
    可以被誤判成 `src` 的別名。

    `st_ino` 在 Windows／FAT32／部分網路磁碟上可能不可靠（不支援 file id 的
    檔案系統上恆為 0），導致把兩個實際不同的檔案誤判成「同一檔」。但這個
    誤判方向一樣落在 fail-closed 那一側（結果等同上面的 fail-closed 例外
    路徑）——後果只是少產一張衍生圖，可接受，不是資料毀損。

    ⚠️ **刻意接受的殘留邊界**：未知 `OSError`（權限被拒、網路磁碟逾時等）時
    fail-closed 回 `True`，但此時 `dst` 是否真的存在、內容是否真的與 `src`
    相同——**都無法確定**。呼叫端可能因此回報「已產圖」而該檔實際不存在（例如
    磁碟在 `samefile` 呼叫當下恰好斷線）。這不是被解決的問題，是相對於「誤判
    不同檔、就地毀損原檔」這個不可逆後果，刻意選擇的較輕代價（可由使用者手動
    重新整理／批次補齊救回）。要徹底排除，需要呼叫端在跳過寫入後另外驗證
    `dst` 確實存在且內容正確，本函式的職責只到「同檔判斷」為止，不做這件事。
    """
    if src == dst:
        return True
    try:
        return os.path.samefile(src, dst)
    except FileNotFoundError:
        return False
    except OSError:
        return True
