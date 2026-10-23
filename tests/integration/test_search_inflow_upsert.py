"""
test_search_inflow_upsert.py — TDD-lite: POST /api/scrape-single 後端 in-flow upsert

4 個 case（既有）：
1. synced  — 在 directories 內，scan_file 回有效 VideoInfo，upsert 成功 → db_sync_status: "synced"
2. not_linked — 不在 directories 內 → find_matched_directory 回 None → db_sync_status: "not_linked"
3. failed  — upsert 拋例外 → except 包裹，response 仍 success: true，db_sync_status: "failed"
4. missing_filename — organize_file 回傳缺 new_filename → db_sync_status: "not_linked"，不 crash

B1 dead-card 守衛（新增）：
I1 — B1 端到端死卡守衛（external_manager=off）
I2 — B1 端到端死卡守衛（external_manager=jellyfin，驗 mode-agnostic）
"""

import pytest
from unittest.mock import MagicMock, patch
from core.database.connection import init_db


@pytest.fixture(autouse=True)
def _t6_isolated_failure_db(tmp_path, monkeypatch):
    """TASK-144-T6：這支檔案裡的測試現在會間接碰到 organize_failures 這張表。

    `POST /api/search/filter-files` 會查失敗記憶、`scrape_single()` 成功時會清失敗記憶，
    兩者都開 sqlite 連線——而這些測試原本完全不碰 DB，於是被 repo-write 守衛（G1，
    `tests/conftest.py:250`）擋成 `RepoWriteGuardViolation`（繼承 `BaseException`，
    產品碼的 `except Exception` 攔不到，整個請求變 500）。

    **這不是放寬守衛**：守衛擋的是「寫進真實 output/openaver.db」，把預設 db_path 指到
    tmp 正是它訊息裡列的四種修法第一種。形狀照 `tests/unit/test_auto_organize.py::isolated_db`
    的既有慣例（T3 建立）。
    """
    db_path = tmp_path / "t6_organize_failures.db"
    init_db(db_path)
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: db_path)
    return db_path


# ─── helper stubs ────────────────────────────────────────────────────────────

def _make_video_info(num="ABC-001"):
    """回傳最小可用的 VideoInfo stub。"""
    from core.gallery_scanner import VideoInfo
    info = VideoInfo()
    info.num = num
    info.path = "file:///tmp/ABC-001/ABC-001.mp4"
    info.title = "Test Title"
    return info


def _organize_ok(new_filename="/tmp/ABC-001/ABC-001.mp4"):
    """organize_file 回傳成功 dict（含 new_filename）。"""
    return {
        "success": True,
        "new_filename": new_filename,
        "new_folder": "/tmp/ABC-001",
        "original_path": "/tmp/ABC-001.mp4",
    }


def _scrape_request_body(file_path="/tmp/ABC-001.mp4"):
    return {
        "file_path": file_path,
        "number": "ABC-001",
        "metadata": {
            "title": "Test Title",
            "number": "ABC-001",
            "cover": "",
            "actresses": [],
            "tags": [],
            "release": "",
        },
    }


# ─── case 1: synced ──────────────────────────────────────────────────────────


# ─── case 2: not_linked ──────────────────────────────────────────────────────

def test_scrape_single_db_sync_status_not_linked(client):
    """
    不在 directories 內 → find_matched_directory 回 None
    → db_sync_status == "not_linked"，不呼叫 scan_file / upsert
    """
    with (
        patch("web.routers.scraper.organize_file", return_value=_organize_ok()),
        patch("core.db_inflow.load_config", return_value={
            "gallery": {"directories": ["/other"], "path_mappings": {}}
        }),
        patch("core.db_inflow.find_matched_directory", return_value=None),
        patch("core.db_inflow.VideoScanner") as MockScanner,
        patch("core.db_inflow.VideoRepository") as MockRepo,
    ):
        resp = client.post("/api/scrape-single", json=_scrape_request_body())

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["db_sync_status"] == "not_linked"
    MockScanner.return_value.scan_file.assert_not_called()
    MockRepo.return_value.upsert.assert_not_called()


# ─── case 3: failed (upsert 拋例外) ──────────────────────────────────────────

def test_scrape_single_db_sync_status_failed_on_upsert_exception(client):
    """
    upsert 拋 Exception → except 包裹
    → response 仍 success: true，db_sync_status == "failed"（整理本身不受影響）
    """
    video_info = _make_video_info()

    with (
        patch("web.routers.scraper.organize_file", return_value=_organize_ok()),
        patch("core.db_inflow.load_config", return_value={
            "gallery": {"directories": ["/tmp"], "path_mappings": {}}
        }),
        patch("core.db_inflow.find_matched_directory", return_value="/tmp"),
        patch("core.db_inflow.VideoScanner") as MockScanner,
        patch("core.db_inflow.VideoRepository") as MockRepo,
        patch("core.db_inflow.Video") as MockVideo,
    ):
        MockScanner.return_value.scan_file.return_value = video_info
        mock_video = MagicMock()
        mock_video.path = "file:///tmp/ABC-001/ABC-001.mp4"
        MockVideo.from_video_info.return_value = mock_video
        # B1: now calls repath() instead of upsert()
        MockRepo.return_value.repath.side_effect = Exception("DB write error")

        resp = client.post("/api/scrape-single", json=_scrape_request_body())

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["db_sync_status"] == "failed"


# ─── case 5: VideoScanner 用 path_mappings= 構建 ────────────────────────────────

def test_scrape_single_video_scanner_receives_path_mappings(client):
    """
    try_inflow_upsert 必須用 path_mappings=... 構建 VideoScanner（P1 fix 驗證）。
    spy VideoScanner constructor，assert call kwargs 含 path_mappings。
    """
    video_info = _make_video_info()
    path_mappings = {"/mnt/e": "E:"}

    with (
        patch("web.routers.scraper.organize_file", return_value=_organize_ok()),
        # db_sync_status=="synced" 觸發 web/routers/scraper.py:295 的
        # focal_repo = VideoRepository()（同上一支 test_..._synced 的理由）。
        patch("web.routers.scraper.VideoRepository") as MockFocalRepo,
        patch("core.db_inflow.load_config", return_value={
            "gallery": {"directories": ["/tmp"], "path_mappings": path_mappings}
        }),
        patch("core.db_inflow.find_matched_directory", return_value="/tmp"),
        patch("core.db_inflow.VideoScanner") as MockScanner,
        patch("core.db_inflow.VideoRepository") as MockRepo,
        patch("core.db_inflow.Video") as MockVideo,
    ):
        MockFocalRepo.return_value.get_by_path.return_value = None
        MockScanner.return_value.scan_file.return_value = video_info
        mock_video = MagicMock()
        mock_video.path = "file:///tmp/ABC-001/ABC-001.mp4"
        MockVideo.from_video_info.return_value = mock_video
        MockRepo.return_value.repath.return_value = None  # B1: repath replaces upsert

        resp = client.post("/api/scrape-single", json=_scrape_request_body())

    assert resp.status_code == 200
    assert resp.json()["db_sync_status"] == "synced"
    # VideoScanner 必須以 path_mappings= 與 nfo_title_format= 構建
    MockScanner.assert_called_once_with(path_mappings=path_mappings, nfo_title_format='[{num}]{title}')


# ─── case 4: missing new_filename ─────────────────────────────────────────────


# ─── T-3: U7 readonly organize guard ─────────────────────────────────────────
#
# guard 插在 handler 最前段（file_path = request.file_path 之後、extract_number/
# search_jav/organize_file 之前）。只依 file_path 判斷所屬來源是否 readonly。
#
# patch targets:
#   organize_file  → web.routers.scraper.organize_file
#   search_jav     → web.routers.scraper.search_jav
#   extract_number → core.scraper.extract_number（handler 內 function-local import）
#   config 注入    → web.routers.scraper.load_config（iter_gallery_sources 用 real）


def _readonly_gallery_config(path, path_mappings=None, readonly=True):
    return {
        "gallery": {
            "directories": [{"path": path, "readonly": readonly}],
            "path_mappings": path_mappings or {},
        }
    }


def _scrape_body_no_metadata(file_path, number="ABC-001"):
    """不帶 metadata → 非 readonly 時會走 search_jav（讓 assert_not_called 有意義）。"""
    body = {"file_path": file_path}
    if number is not None:
        body["number"] = number
    return body


# case 1: readonly 來源擋 organize（核心）— 三下游 assert_not_called
def test_scrape_single_readonly_blocks_organize(client):
    with (
        patch("web.routers.scraper.load_config",
              return_value=_readonly_gallery_config("/tmp/ro_src")),
        patch("web.routers.scraper.organize_file") as mock_org,
        patch("web.routers.scraper.search_jav") as mock_search,
        patch("core.scraper.extract_number", return_value="ABC-001") as mock_extract,
    ):
        # number=None → 無 guard 時 `if not number:` 為真 → extract_number 會被呼叫；
        # 有 guard 時 guard 早於番號解析 → 三下游皆 assert_not_called 皆為 live lock。
        resp = client.post(
            "/api/scrape-single",
            json=_scrape_body_no_metadata("/tmp/ro_src/ABC-001.mp4", number=None),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "唯讀" in data["error"]
    mock_org.assert_not_called()
    mock_search.assert_not_called()
    mock_extract.assert_not_called()


# case 2: 無番號 + 檔名不可解析 在 readonly 來源下 → 仍回唯讀提示（Acceptance #12 哨兵）


# case 3: UNC readonly 來源 → guard 不拋 ValueError（Codex P2 哨兵）
def test_scrape_single_readonly_unc_no_valueerror(client):
    with (
        patch("web.routers.scraper.load_config",
              return_value=_readonly_gallery_config(r"\\server\share")),
        patch("web.routers.scraper.organize_file") as mock_org,
        patch("web.routers.scraper.search_jav") as mock_search,
    ):
        resp = client.post(
            "/api/scrape-single",
            json=_scrape_body_no_metadata(r"\\server\share\ABC-001.mp4"),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "唯讀" in data["error"]
    mock_org.assert_not_called()
    mock_search.assert_not_called()


# case 4: 非 readonly 來源放行 → 走既有 organize
def test_scrape_single_non_readonly_passes_through(client):
    with (
        patch("web.routers.scraper.load_config",
              return_value=_readonly_gallery_config("/tmp/rw_src", readonly=False)),
        patch("web.routers.scraper.organize_file",
              return_value=_organize_ok("/tmp/rw_src/ABC-001/ABC-001.mp4")) as mock_org,
        patch("web.routers.scraper.search_jav"),
    ):
        resp = client.post(
            "/api/scrape-single",
            json=_scrape_request_body(file_path="/tmp/rw_src/ABC-001.mp4"),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    mock_org.assert_called_once()


# case 5: 不屬任何來源放行 → guard 不誤擋


# case 6: 訊息描述清楚（AI 友善）


# case 7: file_path 是 canonical file:/// URI（DB / 鄰近寫入路徑格式）在 readonly
#          來源下 → guard 仍須觸發（Codex P1：to_file_uri 會雙重包 file:///file:///
#          繞過 guard；coerce_to_file_uri 對已是 URI 原樣回才能命中）。
def test_scrape_single_readonly_file_uri_input_blocks_organize(client):
    from core.path_utils import to_file_uri
    # DB canonical file:/// URI（drive-letter，真實 Windows/WSL 部署形態）。
    # 舊碼 to_file_uri 對它再包一層 → file:///file:/// → guard 繞過（RED）；
    # coerce_to_file_uri 對已是 URI 原樣回 → guard 命中（GREEN）。
    src_path = "C:/ro_src"
    file_uri = to_file_uri("C:/ro_src/ABC-001.mp4", {})  # 'file:///C:/ro_src/ABC-001.mp4'
    with (
        patch("web.routers.scraper.load_config",
              return_value=_readonly_gallery_config(src_path)),
        patch("web.routers.scraper.organize_file") as mock_org,
        patch("web.routers.scraper.search_jav") as mock_search,
        patch("core.scraper.extract_number", return_value="ABC-001") as mock_extract,
    ):
        resp = client.post(
            "/api/scrape-single",
            json=_scrape_body_no_metadata(file_uri, number=None),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "唯讀" in data["error"]
    mock_org.assert_not_called()
    mock_search.assert_not_called()
    mock_extract.assert_not_called()


# ─── B1 helpers ──────────────────────────────────────────────────────────────

def _seed_old_card_b1(repo, old_uri: str, user_tags=None, created_at_str: str = None):
    """Seed an old card in the given repo. Returns the stored Video row."""
    from core.database import Video
    with patch("core.similar.ranker_cache.SimilarRankerCache"):
        repo.upsert(Video(
            path=old_uri,
            number="ABC-001",
            title="Old Title",
            original_title="",
            actresses=[],
            maker="",
            director="",
            series=None,
            label="",
            tags=[],
            user_tags=user_tags or ["看過"],
            sample_images=[],
            duration=None,
            size_bytes=0,
            cover_path="old_cover.jpg",
            release_date="",
            mtime=0.0,
            nfo_mtime=0.0,
        ))
    if created_at_str:
        conn = repo._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE videos SET created_at = ? WHERE path = ?",
                (created_at_str, old_uri),
            )
            conn.commit()
        finally:
            conn.close()
    return repo.get_by_path(old_uri)


def _make_scan_info_for_new_b1(new_uri: str, num: str = "ABC-001"):
    """Build a VideoInfo stub for the newly-scanned file (no browse tags)."""
    from core.gallery_scanner import VideoInfo
    info = VideoInfo()
    info.path = new_uri
    info.num = num
    info.title = "New Title"
    info.originaltitle = ""
    info.actor = ""
    info.genre = ""
    info.maker = ""
    info.director = ""
    info.series = None
    info.label = ""
    info.user_tags = []   # scrape NFO does not carry browse tags
    info.sample_images = []
    info.duration = None
    info.size = 0
    info.img = ""
    info.date = ""
    info.mtime = 0
    return info


# ─── I1: B1 死卡守衛（external_manager=off） ────────────────────────────────

def test_b1_repath_no_dead_card_off(client, tmp_path):
    """
    I1 — B1 端到端死卡守衛（external_manager=off）：
    seed 舊卡（user_tags=['看過'] + 已知 created_at + 記下 id）
    → POST /api/scrape-single
    → count() 不增、舊 URI 消失、新 URI 有效、
      id==舊 id（browse 不跳位）、user_tags⊇['看過']、created_at==舊值
    """
    from core.database import Video, VideoRepository, init_db
    from core.path_utils import normalize_path, to_file_uri

    db_file = tmp_path / "b1_off_test.db"
    init_db(db_file)
    repo = VideoRepository(db_path=db_file)

    old_fs = str(tmp_path / "ABC-001.mp4")
    new_fs = str(tmp_path / "[ABC-001] New Title.mp4")
    old_uri = to_file_uri(normalize_path(old_fs), None)
    new_uri = to_file_uri(normalize_path(new_fs), None)
    old_created = "2024-02-01 10:00:00"

    old_row = _seed_old_card_b1(repo, old_uri, user_tags=["看過"], created_at_str=old_created)
    old_id = old_row.id
    count_before = repo.count()

    video_info = _make_scan_info_for_new_b1(new_uri)

    with (
        patch("web.routers.scraper.organize_file", return_value={
            "success": True,
            "new_filename": new_fs,
            "new_folder": str(tmp_path),
            "original_path": old_fs,
        }),
        patch("core.db_inflow.load_config", return_value={
            "gallery": {"directories": [str(tmp_path)], "path_mappings": None}
        }),
        patch("core.db_inflow.find_matched_directory", return_value=str(tmp_path)),
        patch("core.db_inflow.VideoScanner") as MockScanner,
        patch("core.db_inflow.VideoRepository", return_value=repo),
        patch("core.db_inflow.Video") as MockVideo,
        patch("core.similar.ranker_cache.SimilarRankerCache"),
        patch("web.routers.scraper.VideoRepository", return_value=repo),
    ):
        MockScanner.return_value.scan_file.return_value = video_info
        MockVideo.from_video_info.return_value = Video(
            path=new_uri, number="ABC-001", title="New Title",
            original_title="", actresses=[], maker="", director="",
            series=None, label="", tags=[], user_tags=[],
            sample_images=[], duration=None, size_bytes=0,
            cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0,
        )

        resp = client.post("/api/scrape-single", json=_scrape_request_body(file_path=old_fs))

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["db_sync_status"] == "synced"

    # 死卡守衛：count 不增
    assert repo.count() == count_before, \
        f"count 應不增（{count_before}），得 {repo.count()}"

    # 舊路徑消失
    assert repo.get_by_path(old_uri) is None, "舊 URI 應消失（無死卡）"

    # 新路徑有效
    new_card = repo.get_by_path(new_uri)
    assert new_card is not None, "新 URI 應存在"

    # browse 不跳位：id 不變
    assert new_card.id == old_id, \
        f"id 應保留 {old_id}（browse ORDER BY id 不跳位），得 {new_card.id}"

    # browse tag 存活（union，非被 NFO 覆寫沖掉）
    assert "看過" in new_card.user_tags, \
        f"user_tags 應含 '看過'，實際: {new_card.user_tags}"

    # created_at 不變
    ca_str = str(new_card.created_at) if new_card.created_at else ""
    assert "2024-02-01" in ca_str, \
        f"created_at 應保留 2024-02-01，得 {ca_str!r}"


# ─── I2: B1 死卡守衛（external_manager=jellyfin） ─────────────────────


# ─── TASK-98b-T2: 首刮重建 URI == DB row key（focal silent-miss 回歸鎖） ─────────
#
# 最關鍵回歸：scraper.py 用 to_file_uri(target_file, path_mappings) 重建 focal 的
# video_path_uri，必須 byte-equal db_inflow 寫入的 DB row key，否則 update_auto_focal
# WHERE path=? rowcount=0 → silent-miss。跑真 VideoScanner（不 mock scan_file）取得
# 真實 DB key，再用 scraper 的重建公式比對。

def _scraper_rebuild_uri(target_file, config):
    """複製 web/routers/scraper.py 的 focal video_path_uri 重建公式。"""
    from core.path_utils import to_file_uri
    path_mappings = config.get('gallery', {}).get('path_mappings', {})
    return to_file_uri(target_file, path_mappings)


# ─── TASK-98b-T2 DoD-4: scraper 首刮 focal wire gate（驅動真 route，spy helper） ──
#
# 上面兩個 test 只驗「重建公式」與 DB key 對齊（手抄 _scraper_rebuild_uri），沒有
# 驅動 web/routers/scraper.py 真正的接線點（~:214 `if db_sync_status == "synced"`）。
# DoD-4「db_sync_status != 'synced' → 不 submit」因此無鎖。以下 spy
# web.routers.scraper.maybe_submit_video_focal 並打真 route 驗接線閘。
#
# 接線閘只看兩件事：`target_file` 為真 AND `db_sync_status == "synced"`。無 censor
# 閘、無 cover 存在閘——那兩者活在 helper 內部（helper 被 spy，不會實跑）。


def _organize_ok_with_cover(new_filename="/tmp/ABC-001/ABC-001.mp4",
                            cover_path="/tmp/ABC-001/ABC-001-fanart.jpg"):
    d = _organize_ok(new_filename)
    d["cover_path"] = cover_path
    return d


def _scrape_body_with_maker(file_path="/tmp/ABC-001.mp4", maker="S1"):
    body = _scrape_request_body(file_path=file_path)
    body["metadata"]["maker"] = maker
    return body


# ─── 99b-T2 caller #5：首刮 read-back 真 DB fixture 驅動 ──────────────────────
#
# 案 A（下方 test_focal_wire_called_on_synced）原本用 mock 位置參數斷言
# `args[3] == result['cover_path']`——caller #5 改 read-back 後這組斷言直接失效
# （新實作不再把 result['cover_path'] 傳給 maybe_submit_video_focal，而是先
# focal_repo.get_by_path() 讀 row.cover_path 再反解）。改走真 DB + 真
# try_inflow_upsert + 真 VideoScanner.scan_file（只 mock organize_file 與網路面），
# 讓 read-back 邏輯被真正驅動——純 mock `get_by_path` 回傳值會削弱 DoD ⑤
# 「external-manager 模式下 scan_file 選到不同 sidecar」這個真實情境的覆蓋力。


def _real_scrape_focal_fixture(client, tmp_path, video_stem, cover_layout,
                                claimed_cover_suffix=".jpg", existing_cover_path=None):
    """建立真實檔案 fixture 並打真 route，只 mock organize_file（不搬檔）與
    web.routers.scraper.maybe_submit_video_focal（spy，不真跑 pigo）。

    Args:
        cover_layout: "off"（同 stem 封面，scan_file L1 命中）或
            "external_manager"（{stem}-fanart 命名，scan_file L1.5 命中，
            與 result['cover_path']（同 stem 假設）不同源，即 DoD ⑤ 地雷情境）。
        existing_cover_path: 若提供，先在真 DB seed 一筆帶此 cover_path 的既有
            row（DoD ⑥ 既有 row race 情境；None 則不預先 seed，模擬全新首刮）。

    Returns: (resp, repo, captured, video_file, real_cover_file)
    """
    from core.database import init_db, VideoRepository, Video
    from core.path_utils import to_file_uri

    lib_dir = tmp_path / "lib"
    lib_dir.mkdir(exist_ok=True)
    video_file = lib_dir / f"{video_stem}.mp4"
    video_file.write_bytes(b"x")

    if cover_layout == "off":
        real_cover_file = lib_dir / f"{video_stem}{claimed_cover_suffix}"
    else:
        real_cover_file = lib_dir / f"{video_stem}-fanart{claimed_cover_suffix}"
    real_cover_file.write_bytes(b"cover")

    # scraper 自己「以為」下載到的位置：一律同 stem（off 模式下與磁碟一致；
    # external-manager 模式下磁碟並無此檔，代表 db_inflow.try_inflow_upsert 內部
    # VideoScanner.scan_file() 重新偵測到的是別張圖，CD-99b-4 要治的分歧）。
    claimed_cover_path = str(lib_dir / f"{video_stem}{claimed_cover_suffix}")

    db_file = tmp_path / f"scrape_focal_{video_stem}.db"
    init_db(db_file)
    repo = VideoRepository(db_path=db_file)

    video_uri = to_file_uri(str(video_file))
    if existing_cover_path is not None:
        with patch("core.similar.ranker_cache.SimilarRankerCache"):
            repo.upsert(Video(path=video_uri, number=video_stem, maker="S1",
                               cover_path=existing_cover_path))

    captured = {}

    def _capture_submit(number, maker, video_path_uri, cover_fs, *, cover_path_uri, db_path=None):
        captured["number"] = number
        captured["maker"] = maker
        captured["video_path_uri"] = video_path_uri
        captured["cover_fs"] = cover_fs
        captured["cover_path_uri"] = cover_path_uri

    with (
        patch("web.routers.scraper.maybe_submit_video_focal", side_effect=_capture_submit),
        patch("web.routers.scraper.VideoRepository", return_value=repo),
        patch("web.routers.scraper.load_config", return_value={
            "gallery": {"directories": [], "path_mappings": {}}
        }),
        patch("web.routers.scraper.organize_file", return_value={
            "success": True,
            "new_filename": str(video_file),
            "new_folder": str(lib_dir),
            "original_path": str(video_file),
            "cover_path": claimed_cover_path,
        }),
        patch("core.db_inflow.load_config", return_value={
            "gallery": {"directories": [str(lib_dir)], "path_mappings": {}}
        }),
        patch("core.db_inflow.VideoRepository", return_value=repo),
        patch("core.similar.ranker_cache.SimilarRankerCache"),
    ):
        body = _scrape_body_with_maker(file_path=str(video_file))
        body["number"] = video_stem
        body["metadata"]["number"] = video_stem
        resp = client.post("/api/scrape-single", json=body)

    return resp, repo, captured, video_file, real_cover_file


# case A（重寫）：off 模式首刮 read-back——分析檔 == 反解自 row.cover_path，
# cover_path_uri == row.cover_path，commit 命中非 0 列。


# DoD ⑤：external-manager 模式——scan_file 選到與 result['cover_path']（同 stem
# 假設）不同的 sidecar（-fanart 命名），read-back 讓分析檔與 expected URI 對齊
# 真正裁切的那張圖。mutation：若改回傳 to_file_uri(result['cover_path']) 當
# expected，此 fixture 下 commit 必然 0 列（見本測試最後一段直接示範）。


# DoD ⑥：首刮落在既有 row 的 race 鎖（推翻「首刮=新 row 無 race」的錯誤直覺）。
# 既有 row 的 cover_path 是「上一輪」的舊封面（模擬先前掃描留下的 in-flight job
# 分析對象）；本輪首刮發現封面已換成 disk 上的新檔 → upsert 的 CD-10/CD-99b 換封面
# 語意重置 auto_focal/focal_attempted_at，read-back 拿到新值。


# DoD ⑦：row is None（read-back 之後才 commit 完成的極端時序）→ 不排、不炸。


# DoD ⑦：row.cover_path == '' → 不排、不炸（封面下載失敗的合法值，非 bug）。


# DoD ⑧(a)：無 user_tags 的正常刮削路徑（最常見路徑，scrape_single :177 分支不執行、
# 外層 `repo` 變數未綁定）走完 read-back 不 UnboundLocalError——本測試請求 body 本就
# 沒有 metadata.user_tags（_scrape_request_body 預設無此欄），off 模式 fixture 全程
# 200 即已隱含證明沒有 UnboundLocalError（若誤用外層 repo 名稱會直接 500）。


# DoD ⑧(b)：read-back 內部任何呼叫（此處 get_by_path）拋例外 → 刮削仍回 200 + 原
# result 形狀，只 logger.warning，不冒泡打斷已成功的整理結果。
def test_focal_readback_get_by_path_raises_still_returns_200(client):
    video_info = _make_video_info()

    with (
        patch("web.routers.scraper.maybe_submit_video_focal") as mock_focal,
        patch("web.routers.scraper.load_config", return_value={
            "gallery": {"directories": [], "path_mappings": {}}
        }),
        patch("web.routers.scraper.organize_file",
              return_value=_organize_ok_with_cover()),
        patch("web.routers.scraper.VideoRepository") as MockFocalRepo,
        patch("core.db_inflow.load_config", return_value={
            "gallery": {"directories": ["/tmp"], "path_mappings": {}}
        }),
        patch("core.db_inflow.find_matched_directory", return_value="/tmp"),
        patch("core.db_inflow.VideoScanner") as MockScanner,
        patch("core.db_inflow.VideoRepository") as MockRepo,
        patch("core.db_inflow.Video") as MockVideo,
    ):
        MockFocalRepo.return_value.get_by_path.side_effect = RuntimeError("DB locked")
        MockScanner.return_value.scan_file.return_value = video_info
        mock_video = MagicMock()
        mock_video.path = "file:///tmp/ABC-001/ABC-001.mp4"
        MockVideo.from_video_info.return_value = mock_video
        MockRepo.return_value.repath.return_value = None  # → synced

        resp = client.post("/api/scrape-single", json=_scrape_body_with_maker())

    assert resp.status_code == 200, "read-back 內部例外不得冒泡打斷已成功的刮削請求"
    body = resp.json()
    assert body["success"] is True
    assert body["db_sync_status"] == "synced"
    mock_focal.assert_not_called()


# case B（DoD-4 核心）：db_sync_status == "not_linked"（非 synced）→ helper NOT called


# case B'（DoD-4 補強）：db_sync_status == "failed"（upsert 拋例外）→ helper NOT called


# ─── T4：organizer 路徑 DB 記帳直接鎖（真理表 Table 1 #7） ────────────────
#
# 上面的 I2（test_b1_repath_no_dead_card_jellyfin）與
# test_focal_read_back_external_manager_mode_real_fixture 都用
# `patch("web.routers.scraper.organize_file", return_value={...})` 把
# organize_file 本體整個 mock 掉——resolve_cover_target／⑨ 完全不會被執行，
# 兩者驗的是別的東西（B1 死卡邏輯／read-back 對齊），與封面正典位置正交
# （TASK-112b-T4.md §A-3）。本測試不 mock organize_file，真跑
# organize_file() + try_inflow_upsert()，才會真的踩到
# resolve_cover_target → find_cover_image 的往返鏈（§B-2）。
#
# patch 組合逐字複製契約表 C `_run`（tests/unit/test_cover_canonical_contract.py
# :1473-1509）：`core.organizer.requests.get` 是 download_image 的網路邊界；
# `core.db_inflow.VideoRepository` 必須 patch（`get_db_path()`
# 硬編碼 repo-root、不讀 config，漏了這行測試會真的寫進專案
# `output/openaver.db`，§D #4 最高風險項）。

