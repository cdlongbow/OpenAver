"""TASK-142-T3: gallery image/thumb fast-fail when source is unreachable."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest
from PIL import Image

from core.path_utils import to_file_uri, uri_to_fs_path
from core import thumbnail_cache


def _jpeg(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    return path


def _webp(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), (10, 200, 100)).save(path, "WEBP")
    return path


def _exists_side_effect(*existing: str):
    """Path-scoped exists mock — never blanket-True (BE-TEST-12)."""
    existing_set = {os.path.normpath(p) for p in existing}
    real = os.path.exists

    def _side(path):
        n = os.path.normpath(str(path))
        if n in existing_set:
            return True
        return real(path)

    return _side


@pytest.fixture
def thumb_dir(tmp_path, mocker):
    d = tmp_path / "thumb"
    d.mkdir()
    mocker.patch("core.thumbnail_cache._thumb_dir", return_value=d)
    return d


@pytest.fixture
def temp_db(tmp_path, mocker):
    from core.database import init_db, VideoRepository

    db_path = tmp_path / "test.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    mocker.patch("web.routers.scanner.get_db_path", return_value=db_path)
    return db_path, repo


# ── DoD 1 / Integration A ──────────────────────────────────────────────


def test_unreachable_writable_source_image_fast_fails_404(
    client, tmp_path, mocker
):
    """DoD 1: writable source unreachable → /image 404, no Cache-Control."""
    src = tmp_path / "writable"
    src.mkdir()
    img = _jpeg(src / "poster.jpg")
    native = uri_to_fs_path(str(src))

    mocker.patch(
        "web.routers.scanner.load_config",
        return_value={
            "gallery": {
                "directories": [
                    {"path": str(src), "readonly": False, "output_path": ""},
                ],
                "path_mappings": {},
            },
        },
    )
    mocker.patch(
        "core.source_reachability.get_snapshot",
        return_value={native: "unreachable"},
    )
    mocker.patch(
        "os.path.exists",
        side_effect=_exists_side_effect(str(img), str(src)),
    )

    resp = client.get("/api/gallery/image", params={"path": str(img)})

    assert resp.status_code == 404
    assert resp.text == "來源目前無法存取"
    assert "cache-control" not in resp.headers


# ── DoD 2 / Integration B ──────────────────────────────────────────────


def test_readonly_source_cover_not_blocked(
    client, tmp_path, mocker, thumb_dir, temp_db
):
    """DoD 2: readonly source unreachable but cover on local output_path → not blocked."""
    from core.database import Video

    src = tmp_path / "ro_src"
    src.mkdir()
    out = tmp_path / "ro_out"
    out.mkdir()
    cover = _jpeg(out / "MOVIE-001" / "poster.jpg")
    native = uri_to_fs_path(str(src))
    video_uri = to_file_uri(str(src / "MOVIE-001.mp4"))
    cover_uri = to_file_uri(str(cover))

    _, repo = temp_db
    repo.upsert_batch(
        [Video(path=video_uri, mtime=100.0, cover_path=cover_uri)]
    )

    mocker.patch(
        "web.routers.scanner.load_config",
        return_value={
            "thumbnail_cache_enabled": False,
            "gallery": {
                "directories": [
                    {
                        "path": str(src),
                        "readonly": True,
                        "output_path": str(out),
                    },
                ],
                "path_mappings": {},
            },
        },
    )
    mocker.patch(
        "core.source_reachability.get_snapshot",
        return_value={native: "unreachable"},
    )

    resp = client.get("/api/gallery/thumb", params={"path": video_uri})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


# ── DoD 3 / Integration C ──────────────────────────────────────────────


def test_cached_thumb_not_blocked(client, tmp_path, mocker, thumb_dir):
    """DoD 3: cached thumb hit still 200 even when source is unreachable."""
    src = tmp_path / "cache_src"
    src.mkdir()
    native = uri_to_fs_path(str(src))
    video_uri = to_file_uri(str(src / "v1.mp4"))
    _webp(thumbnail_cache.thumb_file_for(video_uri))

    mocker.patch(
        "web.routers.scanner.load_config",
        return_value={
            "thumbnail_cache_enabled": True,
            "gallery": {
                "directories": [
                    {"path": str(src), "readonly": False, "output_path": ""},
                ],
                "path_mappings": {},
            },
        },
    )
    mocker.patch(
        "core.source_reachability.get_snapshot",
        return_value={native: "unreachable"},
    )
    # Hit path must not touch DB / generate
    mocker.patch("web.routers.scanner.VideoRepository")
    mocker.patch("web.routers.scanner.get_db_path")

    resp = client.get("/api/gallery/thumb", params={"path": video_uri})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"


# ── DoD 4 / Integration D ──────────────────────────────────────────────


def test_unknown_status_not_blocked(client, tmp_path, mocker):
    """DoD 4: unknown for this source → same as today (200 when file exists).

    Snapshot also carries an unrelated unreachable entry so the CD-8 healthy-path
    short-circuit does not fire — otherwise the per-source status check (M2) is
    never reached and DoD 4 cannot catch that mutation.
    """
    src = tmp_path / "unknown_src"
    src.mkdir()
    img = _jpeg(src / "poster.jpg")
    native = uri_to_fs_path(str(src))

    mocker.patch(
        "web.routers.scanner.load_config",
        return_value={
            "gallery": {
                "directories": [
                    {"path": str(src), "readonly": False, "output_path": ""},
                ],
                "path_mappings": {},
            },
        },
    )
    mocker.patch(
        "core.source_reachability.get_snapshot",
        return_value={
            native: "unknown",
            "/unrelated/decoy": "unreachable",
        },
    )
    mocker.patch(
        "os.path.exists",
        side_effect=_exists_side_effect(str(img), str(src)),
    )

    resp = client.get("/api/gallery/image", params={"path": str(img)})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


def test_missing_snapshot_key_not_blocked(client, tmp_path, mocker):
    """DoD 4 subset: source absent from snapshot → not blocked."""
    src = tmp_path / "absent_src"
    src.mkdir()
    img = _jpeg(src / "poster.jpg")

    mocker.patch(
        "web.routers.scanner.load_config",
        return_value={
            "gallery": {
                "directories": [
                    {"path": str(src), "readonly": False, "output_path": ""},
                ],
                "path_mappings": {},
            },
        },
    )
    mocker.patch("core.source_reachability.get_snapshot", return_value={})
    mocker.patch(
        "os.path.exists",
        side_effect=_exists_side_effect(str(img), str(src)),
    )

    resp = client.get("/api/gallery/image", params={"path": str(img)})

    assert resp.status_code == 200


# ── DoD 5 / Integration E ──────────────────────────────────────────────


def test_path_mappings_still_fast_fails(
    client, tmp_path, mocker, monkeypatch
):
    """DoD 5: path_mappings mapped namespace still hits fast-fail."""
    import core.path_utils as path_utils

    monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

    nas = tmp_path / "nas"
    nas.mkdir()
    img = _jpeg(nas / "cover.jpg")
    mappings = {str(nas): "//NAS/share"}
    native = uri_to_fs_path(str(nas))

    mocker.patch(
        "web.routers.scanner.load_config",
        return_value={
            "gallery": {
                "directories": [
                    {"path": str(nas), "readonly": False, "output_path": ""},
                ],
                "path_mappings": mappings,
            },
        },
    )
    mocker.patch(
        "core.source_reachability.get_snapshot",
        return_value={native: "unreachable"},
    )
    mocker.patch(
        "os.path.exists",
        side_effect=_exists_side_effect(str(img), str(nas)),
    )

    # Local FS request path; get_image + _canonical_source_prefix both apply
    # path_mappings → mapped-namespace URIs must still match for fast-fail.
    resp = client.get("/api/gallery/image", params={"path": str(img)})

    assert resp.status_code == 404
    assert resp.text == "來源目前無法存取"
    assert "cache-control" not in resp.headers


# ── DoD 6 / Unit F ─────────────────────────────────────────────────────


def test_no_event_loop_thread_no_runtime_error(mocker):
    """DoD 6: pure threading.Thread call must not raise RuntimeError."""
    from core.source_reachability import is_path_on_unreachable_source

    mocker.patch(
        "core.source_reachability.get_snapshot",
        return_value={"/movies": "ok"},
    )
    config = {
        "directories": [{"path": "/movies", "readonly": False}],
        "path_mappings": {},
    }
    uri = to_file_uri("/movies/a.jpg")
    box: dict = {}

    def _run():
        try:
            box["result"] = is_path_on_unreachable_source(uri, config)
            box["error"] = None
        except Exception as exc:
            box["result"] = None
            box["error"] = exc

    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=5)
    assert t.is_alive() is False
    assert box.get("error") is None, f"unexpected error: {box.get('error')!r}"
    assert box.get("result") is False


# ── DoD 8 / Unit G ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"/a": "ok", "/b": "ok"},
        {"/a": "unknown", "/b": "unknown"},
    ],
    ids=["empty", "all_ok", "all_unknown"],
)
def test_dod8_healthy_path_short_circuits(mocker, snapshot):
    """DoD 8: no unreachable in snapshot → False and zero iter_gallery_sources calls."""
    from core.source_reachability import is_path_on_unreachable_source

    mocker.patch("core.source_reachability.get_snapshot", return_value=snapshot)
    iter_spy = mocker.patch(
        "core.source_reachability.iter_gallery_sources",
        side_effect=AssertionError("should not be called on healthy path"),
    )
    config = {
        "directories": [
            {"path": "/a", "readonly": False},
            {"path": "/b", "readonly": False},
        ],
        "path_mappings": {},
    }

    assert is_path_on_unreachable_source(to_file_uri("/a/x.jpg"), config) is False
    assert iter_spy.call_count == 0


# ── DoD 8 端點層（owner 明確要求的「沒斷線的使用者零影響」機械證據）──────


def test_image_fast_fail_precedes_realpath(client, tmp_path, mocker):
    """PR#178 R2 缺陷C：字面式早退必須排在任何 os.path.realpath() 之前——斷線來源上的
    封面請求不能在到達 fast-fail 前就已經先付一次遠端 realpath()（_safe_realpath 與
    _dir_candidate_forms 都會呼叫它）。

    patch 落在 `os.path.realpath`（而非 `web.routers.scanner._safe_realpath` 之類的
    wrapper），因為 _safe_realpath 與 _dir_candidate_forms 都是對同一個 `os` module
    物件做 `os.path.realpath(...)` 查找，兩條路徑會同時被涵蓋。
    """
    import web.routers.scanner as scanner_mod

    # module-level TTL 快取，不清會讓上一支測試的白名單 dir forms 殘留 → 假綠
    scanner_mod._dir_forms_cache.clear()

    src = tmp_path / "unreachable_src"
    src.mkdir()
    img = src / "poster.jpg"
    native = uri_to_fs_path(str(src))

    mocker.patch(
        "web.routers.scanner.load_config",
        return_value={
            "gallery": {
                "directories": [
                    {"path": str(src), "readonly": False, "output_path": ""},
                ],
                "path_mappings": {},
            },
        },
    )
    mocker.patch(
        "core.source_reachability.get_snapshot",
        return_value={native: "unreachable"},
    )

    call_count = {"n": 0}

    def _counting_realpath(p):
        call_count["n"] += 1
        return p  # 記次數＋回傳輸入值，不得一律回真（BE-TEST-12 同精神）

    mocker.patch("os.path.realpath", side_effect=_counting_realpath)

    resp = client.get("/api/gallery/image", params={"path": str(img)})

    assert call_count["n"] == 0, (
        f"os.path.realpath 被呼叫了 {call_count['n']} 次，字面式早退沒有排在它之前"
    )
    assert resp.status_code == 404
    assert resp.text == "來源目前無法存取"


def test_dod8_healthy_snapshot_image_still_200_without_touching_sources(
    client, tmp_path, mocker
):
    """DoD 8（端點層）：全 ok 快照下 /api/gallery/image 仍 200，
    且整條請求路徑上 iter_gallery_sources 一次都沒被呼叫。

    上面那支同名 unit 測試驗的是函式本身；這支驗「接線之後端點真的沒付這個成本」——
    owner 的要求是對沒斷線的使用者零影響，那就得從端點這一側量。
    """
    src = tmp_path / "healthy"
    src.mkdir()
    img = _jpeg(src / "poster.jpg")
    native = uri_to_fs_path(str(src))

    mocker.patch(
        "web.routers.scanner.load_config",
        return_value={
            "gallery": {
                "directories": [
                    {"path": str(src), "readonly": False, "output_path": ""},
                ],
                "path_mappings": {},
            },
        },
    )
    mocker.patch(
        "core.source_reachability.get_snapshot",
        return_value={native: "ok"},
    )
    iter_spy = mocker.patch(
        "core.source_reachability.iter_gallery_sources",
        side_effect=AssertionError("healthy path must not iterate sources"),
    )
    mocker.patch(
        "os.path.exists",
        side_effect=_exists_side_effect(str(img), str(src)),
    )

    resp = client.get("/api/gallery/image", params={"path": str(img)})

    assert resp.status_code == 200
    assert iter_spy.call_count == 0
