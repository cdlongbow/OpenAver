"""
test_title_writeback_api.py — POST /api/showcase/video/title ＋ needs_translate（TASK-172-T3）

真 sqlite（tmp_db）＋真檔案系統（tmp_path NFO）＋TestClient；只 mock 注入失敗
（write_bytes／update_titles）。唯讀環境準備是模組層純函式（不借 test class）。
"""

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.database import Video, VideoRepository, init_db
from core.gallery_scanner import VideoScanner
from core.path_utils import to_file_uri

import test_readonly_offflavor_e2e as _e2e

JP_TITLE = "日本語のタイトル"
ZH_TITLE = "翻譯後的中文標題"

_SEED_NFO = """<?xml version='1.0' encoding='utf-8'?>
<movie>
  <title>[ABC-123]日本語のタイトル</title>
  <originaltitle></originaltitle>
  <num>ABC-123</num>
  <plot>劇情簡介</plot>
  <rating>7.5</rating>
  <website>https://example.invalid/abc-123</website>
</movie>
"""


# ── 環境準備（模組層純函式）──────────────────────────────────────────────────

def _wire(monkeypatch, tmp_db, config):
    """兩處 patch 缺一不可（BE-TEST-41）：端點讀 web.routers.showcase.*，
    唯讀判定的預設輸出根讀 core.readonly_paths.get_db_path。"""
    monkeypatch.setattr("web.routers.showcase.get_db_path", lambda: tmp_db)
    monkeypatch.setattr("core.readonly_paths.get_db_path", lambda: tmp_db)
    monkeypatch.setattr("web.routers.showcase.load_config", lambda: config)
    from web.app import app
    return TestClient(app)


def _plain_config(lib_dir):
    return {
        "gallery": {"directories": [str(lib_dir)], "path_mappings": {},
                    "min_size_mb": 0, "thumbnail_width": 400},
        "scraper": {},
    }


def _video(uri, **kw):
    base = dict(
        path=uri, number="ABC-123", title=JP_TITLE, original_title="",
        actresses=["坂道みる"], maker="Mk", release_date="2024-03-05",
        nfo_mtime=1.0, size_bytes=10,
    )
    base.update(kw)
    return Video(**base)


def _plain_env(monkeypatch, tmp_db, tmp_path, *, with_nfo=True, **video_kw):
    """一般來源：回傳 (client, repo, uri, nfo_path)。"""
    lib = tmp_path / "lib"
    lib.mkdir(exist_ok=True)
    mp4 = lib / "ABC-123.mp4"
    mp4.write_bytes(b"fake-video")
    nfo = lib / "ABC-123.nfo"
    if with_nfo:
        nfo.write_text(_SEED_NFO, encoding="utf-8")
    uri = to_file_uri(str(mp4))
    repo = VideoRepository(tmp_db)
    repo.upsert(_video(uri, **video_kw))
    return _wire(monkeypatch, tmp_db, _plain_config(lib)), repo, uri, nfo


def setup_readonly_title_env(tmp_db, tmp_path, monkeypatch, *,
                             output_nfos=1, output_dir_empty=False):
    """唯讀來源＋輸出夾，回傳 (client, repo, src_dir, out_dir, uri)。"""
    src_dir = tmp_path / "ro_src"
    src_dir.mkdir()
    mp4 = src_dir / "ABC-123.mp4"
    mp4.write_bytes(b"fake-video")
    (src_dir / "ABC-123.nfo").write_text(_SEED_NFO, encoding="utf-8")

    out_dir = None
    output_dir_uri = ""
    if not output_dir_empty:
        out_dir = tmp_path / "ro_out" / "ABC-123"
        out_dir.mkdir(parents=True)
        for i in range(output_nfos):
            name = "ABC-123.nfo" if i == 0 else f"extra-{i}.nfo"
            (out_dir / name).write_text(_SEED_NFO, encoding="utf-8")
        output_dir_uri = to_file_uri(str(out_dir))

    uri = to_file_uri(str(mp4))
    repo = VideoRepository(tmp_db)
    repo.upsert(_video(uri, output_dir=output_dir_uri))
    config = {
        "gallery": {"directories": [{"path": str(src_dir), "readonly": True,
                                     "output_path": str(tmp_path / "ro_out")}],
                    "path_mappings": {}},
        "scraper": {"external_manager": "jellyfin"},
    }
    return _wire(monkeypatch, tmp_db, config), repo, src_dir, out_dir, uri


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "title_wb.db"
    init_db(db)
    return db


def _snap(root):
    return _e2e._snapshot(root)


def _post(client, uri, title, **extra):
    body = {"file_path": uri, "title": title}
    body.update(extra)
    return client.post("/api/showcase/video/title", json=body)


def _nfo_texts(nfo: Path) -> dict:
    root = ET.fromstring(nfo.read_bytes())
    return {c.tag: (c.text or "") for c in root}


# ── T3b：needs_translate ─────────────────────────────────────────────────────

def _list_videos(client):
    resp = client.get("/api/showcase/videos")
    assert resp.status_code == 200
    return {v["path"]: v for v in resp.json()["videos"]}


def _list_env(monkeypatch, tmp_db, tmp_path, rows):
    lib = tmp_path / "lib"
    lib.mkdir()
    uris = []
    repo = VideoRepository(tmp_db)
    for i, kw in enumerate(rows):
        uri = to_file_uri(str(lib / f"V{i}.mp4"))
        uris.append(uri)
        repo.upsert(_video(uri, number=f"V-{i}", **kw))
    return _wire(monkeypatch, tmp_db, _plain_config(lib)), uris


def test_needs_translate_true_for_kana_without_original(monkeypatch, tmp_db, tmp_path):
    client, (u,) = _list_env(monkeypatch, tmp_db, tmp_path, [dict(title=JP_TITLE, nfo_mtime=5.0)])
    assert _list_videos(client)[u]["needs_translate"] is True


def test_needs_translate_false_when_original_title_present(monkeypatch, tmp_db, tmp_path):
    client, (u,) = _list_env(monkeypatch, tmp_db, tmp_path,
                             [dict(title=JP_TITLE, original_title="原文タイトル", nfo_mtime=5.0)])
    assert _list_videos(client)[u]["needs_translate"] is False


def test_needs_translate_false_for_chinese_title(monkeypatch, tmp_db, tmp_path):
    client, (u,) = _list_env(monkeypatch, tmp_db, tmp_path, [dict(title=ZH_TITLE, nfo_mtime=5.0)])
    assert _list_videos(client)[u]["needs_translate"] is False


def test_needs_translate_false_when_no_nfo(monkeypatch, tmp_db, tmp_path):
    client, (u,) = _list_env(monkeypatch, tmp_db, tmp_path, [dict(title=JP_TITLE, nfo_mtime=0)])
    assert _list_videos(client)[u]["needs_translate"] is False


# ── T3c：成功路徑 ────────────────────────────────────────────────────────────

def test_translate_writes_nfo_and_db_consistently(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    data = _post(client, uri, ZH_TITLE).json()
    assert data["success"] is True and data["nfo_updated"] is True
    assert data["title"] == ZH_TITLE and data["original_title"] == JP_TITLE
    assert data["needs_translate"] is False

    texts = _nfo_texts(nfo)
    assert texts["title"] == f"[ABC-123]{ZH_TITLE}"
    assert texts["originaltitle"] == JP_TITLE
    # 其他元素原封不動
    assert texts["plot"] == "劇情簡介"
    assert texts["rating"] == "7.5"
    assert texts["website"] == "https://example.invalid/abc-123"
    assert texts["num"] == "ABC-123"

    row = repo.get_by_path(uri)
    info = VideoScanner().parse_nfo(str(nfo))
    assert (row.title, row.original_title) == (ZH_TITLE, JP_TITLE)
    assert (info.title, info.originaltitle) == (ZH_TITLE, JP_TITLE)
    assert row.nfo_mtime == nfo.stat().st_mtime


def test_first_translate_moves_old_title_to_original(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    _post(client, uri, ZH_TITLE)
    assert repo.get_by_path(uri).original_title == JP_TITLE
    assert _nfo_texts(nfo)["originaltitle"] == JP_TITLE


def test_retranslate_keeps_original_title(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path,
                                        title=ZH_TITLE, original_title=JP_TITLE)
    _post(client, uri, "再翻一次的標題")
    row = repo.get_by_path(uri)
    assert row.title == "再翻一次的標題" and row.original_title == JP_TITLE
    assert _nfo_texts(nfo)["originaltitle"] == JP_TITLE


def test_undo_with_empty_original_clears_original_title(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    _post(client, uri, ZH_TITLE)
    data = _post(client, uri, JP_TITLE, original_title="").json()
    assert data["success"] is True
    assert data["original_title"] == "" and data["needs_translate"] is True
    row = repo.get_by_path(uri)
    assert (row.title, row.original_title) == (JP_TITLE, "")
    assert _nfo_texts(nfo)["originaltitle"] == ""
    assert VideoScanner().parse_nfo(str(nfo)).originaltitle == ""


def test_original_title_null_same_as_omitted(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    _post(client, uri, ZH_TITLE, original_title=None)
    assert repo.get_by_path(uri).original_title == JP_TITLE


def test_translate_then_back_both_rounds_correct(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    _post(client, uri, ZH_TITLE)
    assert (repo.get_by_path(uri).title, _nfo_texts(nfo)["title"]) == (ZH_TITLE, f"[ABC-123]{ZH_TITLE}")
    _post(client, uri, JP_TITLE, original_title="")
    row = repo.get_by_path(uri)
    assert (row.title, row.original_title) == (JP_TITLE, "")
    texts = _nfo_texts(nfo)
    assert texts["title"] == f"[ABC-123]{JP_TITLE}" and texts["originaltitle"] == ""


def test_etag_changes_after_writeback(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    before = client.get("/api/showcase/videos").headers["ETag"]
    assert _post(client, uri, ZH_TITLE).json()["success"] is True
    after = client.get("/api/showcase/videos").headers["ETag"]
    assert before != after


def test_response_needs_translate_recomputed_after_write(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    assert _post(client, uri, ZH_TITLE).json()["needs_translate"] is False
    assert _post(client, uri, JP_TITLE, original_title="").json()["needs_translate"] is True


# ── T3c：失敗路徑 ────────────────────────────────────────────────────────────

def _row_state(repo, uri):
    r = repo.get_by_path(uri)
    return (r.title, r.original_title, r.nfo_mtime)


def test_title_only_number_prefix_returns_title_empty(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    before_db, before_nfo = _row_state(repo, uri), nfo.read_bytes()
    data = _post(client, uri, "ABC-123").json()
    assert data["success"] is False and data["error"] == "title_empty"
    assert _row_state(repo, uri) == before_db and nfo.read_bytes() == before_nfo


def test_blank_title_returns_title_empty(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    assert _post(client, uri, "   ").json()["error"] == "title_empty"


def test_unknown_path_returns_not_found_and_creates_no_stub(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    ghost = to_file_uri(str(tmp_path / "lib" / "GHOST.mp4"))
    data = _post(client, ghost, ZH_TITLE).json()
    assert data["success"] is False and data["error"] == "not_found"
    assert repo.get_by_path(ghost) is None


def test_plain_source_without_nfo_returns_no_nfo(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path, with_nfo=False)
    before = _row_state(repo, uri)
    data = _post(client, uri, ZH_TITLE).json()
    assert data["success"] is False and data["error"] == "no_nfo"
    assert _row_state(repo, uri) == before and not nfo.exists()


def test_unparseable_nfo_returns_nfo_unreadable(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    nfo.write_bytes(b"<movie><title>broken")
    before = _row_state(repo, uri)
    data = _post(client, uri, ZH_TITLE).json()
    assert data["error"] == "nfo_unreadable"
    assert _row_state(repo, uri) == before and nfo.read_bytes() == b"<movie><title>broken"


def test_nfo_write_failure_leaves_db_untouched(monkeypatch, tmp_db, tmp_path):
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    before_db, before_nfo = _row_state(repo, uri), nfo.read_bytes()
    real = Path.write_bytes

    def guarded(self, data):
        if Path(self) == nfo:
            raise PermissionError("denied")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", guarded)
    data = _post(client, uri, ZH_TITLE).json()
    assert data["success"] is False and data["error"] == "nfo_write_failed"
    assert _row_state(repo, uri) == before_db
    assert nfo.read_bytes() == before_nfo


def test_db_write_failure_returns_code_and_scan_converges(monkeypatch, tmp_db, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    mp4 = lib / "ABC-123.mp4"
    mp4.write_bytes(b"fake-video")
    nfo = lib / "ABC-123.nfo"
    nfo.write_text(_SEED_NFO, encoding="utf-8")
    VideoScanner().scan_to_sqlite(str(lib), tmp_db)
    repo = VideoRepository(tmp_db)
    uri = repo.get_all()[0].path
    client = _wire(monkeypatch, tmp_db, _plain_config(lib))

    import time
    time.sleep(0.05)
    with monkeypatch.context() as m:
        def boom(*a, **k):
            raise RuntimeError("db down")
        m.setattr(VideoRepository, "update_titles", boom)
        data = _post(client, uri, ZH_TITLE).json()
    assert data["success"] is False and data["error"] == "db_write_failed"
    assert _nfo_texts(nfo)["title"] == f"[ABC-123]{ZH_TITLE}"
    assert repo.get_by_path(uri).title == JP_TITLE

    VideoScanner().scan_to_sqlite(str(lib), tmp_db)
    assert repo.get_by_path(uri).title == ZH_TITLE


def test_scan_after_writeback_does_not_overwrite(monkeypatch, tmp_db, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "ABC-123.mp4").write_bytes(b"fake-video")
    (lib / "ABC-123.nfo").write_text(_SEED_NFO, encoding="utf-8")
    VideoScanner().scan_to_sqlite(str(lib), tmp_db)
    repo = VideoRepository(tmp_db)
    uri = repo.get_all()[0].path
    client = _wire(monkeypatch, tmp_db, _plain_config(lib))
    import time
    time.sleep(0.05)
    assert _post(client, uri, ZH_TITLE).json()["success"] is True
    VideoScanner().scan_to_sqlite(str(lib), tmp_db)
    row = repo.get_by_path(uri)
    assert (row.title, row.original_title) == (ZH_TITLE, JP_TITLE)


# ── T3c：唯讀來源 ────────────────────────────────────────────────────────────

def test_readonly_one_output_nfo_updated_source_untouched(monkeypatch, tmp_db, tmp_path):
    client, repo, src, out, uri = setup_readonly_title_env(tmp_db, tmp_path, monkeypatch)
    before = _snap(src)
    data = _post(client, uri, ZH_TITLE).json()
    assert data["success"] is True
    assert _snap(src) == before
    texts = _nfo_texts(out / "ABC-123.nfo")
    assert texts["title"] == f"[ABC-123]{ZH_TITLE}" and texts["originaltitle"] == JP_TITLE
    assert texts["plot"] == "劇情簡介"
    row = repo.get_by_path(uri)
    assert (row.title, row.original_title) == (ZH_TITLE, JP_TITLE)


def test_readonly_zero_output_nfo_returns_no_nfo(monkeypatch, tmp_db, tmp_path):
    client, repo, src, out, uri = setup_readonly_title_env(tmp_db, tmp_path, monkeypatch, output_nfos=0)
    before_src, before = _snap(src), _row_state(repo, uri)
    data = _post(client, uri, ZH_TITLE).json()
    assert data["error"] == "no_nfo"
    assert _row_state(repo, uri) == before and _snap(src) == before_src


def test_readonly_empty_output_dir_stub_returns_no_nfo(monkeypatch, tmp_db, tmp_path):
    client, repo, src, out, uri = setup_readonly_title_env(
        tmp_db, tmp_path, monkeypatch, output_dir_empty=True)
    before_src, before = _snap(src), _row_state(repo, uri)
    data = _post(client, uri, ZH_TITLE).json()
    assert data["error"] == "no_nfo"
    assert _row_state(repo, uri) == before and _snap(src) == before_src


def test_readonly_two_nfos_returns_ambiguous_and_writes_nothing(monkeypatch, tmp_db, tmp_path):
    client, repo, src, out, uri = setup_readonly_title_env(tmp_db, tmp_path, monkeypatch, output_nfos=2)
    before_src, before_db = _snap(src), _row_state(repo, uri)
    before_out = _snap(out)
    data = _post(client, uri, ZH_TITLE).json()
    assert data["success"] is False and data["error"] == "nfo_ambiguous"
    assert _row_state(repo, uri) == before_db
    assert _snap(src) == before_src and _snap(out) == before_out


@pytest.mark.skipif(os.name == "nt", reason="chmod 語意不同")
def test_readonly_unreadable_output_dir_returns_nfo_unreadable(monkeypatch, tmp_db, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root 不受 chmod 限制")
    client, repo, src, out, uri = setup_readonly_title_env(tmp_db, tmp_path, monkeypatch)
    before_src, before_db = _snap(src), _row_state(repo, uri)
    out.chmod(0)
    try:
        data = _post(client, uri, ZH_TITLE).json()
    finally:
        out.chmod(0o755)
    assert data["success"] is False and data["error"] == "nfo_unreadable"
    assert _row_state(repo, uri) == before_db and _snap(src) == before_src


def test_path_outside_gallery_dirs_returns_not_found(monkeypatch, tmp_db, tmp_path):
    """DB 有列、NFO 存在，但該片不在設定的片庫目錄內 → not_found，NFO 與 DB 皆不變。"""
    client, repo, uri, nfo = _plain_env(monkeypatch, tmp_db, tmp_path)
    other = tmp_path / "other_lib"
    other.mkdir()
    monkeypatch.setattr("web.routers.showcase.load_config", lambda: _plain_config(other))
    before_db, before_nfo = _row_state(repo, uri), nfo.read_bytes()
    data = _post(client, uri, ZH_TITLE).json()
    assert data["success"] is False and data["error"] == "not_found"
    assert _row_state(repo, uri) == before_db and nfo.read_bytes() == before_nfo


def test_readonly_output_dir_outside_current_root_returns_no_nfo(monkeypatch, tmp_db, tmp_path):
    """唯讀列的 output_dir 在舊輸出根、設定的輸出根已換到別處 → no_nfo，舊夾 NFO 與 DB 不動。"""
    client, repo, src, out, uri = setup_readonly_title_env(tmp_db, tmp_path, monkeypatch)
    new_root = tmp_path / "new_out_root"
    new_root.mkdir()
    config = {
        "gallery": {"directories": [{"path": str(src), "readonly": True,
                                     "output_path": str(new_root)}],
                    "path_mappings": {}},
        "scraper": {"external_manager": "jellyfin"},
    }
    monkeypatch.setattr("web.routers.showcase.load_config", lambda: config)
    nfo = out / "ABC-123.nfo"
    before_db, before_nfo = _row_state(repo, uri), nfo.read_bytes()
    data = _post(client, uri, ZH_TITLE).json()
    assert data["success"] is False and data["error"] == "no_nfo"
    assert _row_state(repo, uri) == before_db and nfo.read_bytes() == before_nfo
