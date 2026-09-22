"""tests/unit/test_data_layout.py — bootstrap_data_layout 正向鎖（TASK-153b-T2）。

每支測試至少對真實 tmp_path 執行 bootstrap，再檢查磁碟狀態；不全程 mock 磁碟操作。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# windows/ 需在 path 上（standalone 同 launcher runtime）
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WINDOWS_DIR = _REPO_ROOT / "windows"
if str(_WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(_WINDOWS_DIR))


# ── helpers ───────────────────────────────────────────────────────────

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _tree_manifest(root: Path) -> dict[str, str]:
    """相對路徑 → sha256（目錄以空字串標記）。"""
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_dir():
            out[rel] = ""
        else:
            out[rel] = _file_sha(p)
    return out


def _write_legacy_config(path: Path, payload: dict | None = None) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload if payload is not None else {
        "scraper": {"create_folder": True},
        "search": {"search_filter": "legacy-unique-marker-153b"},
        "gallery": {"output_dir": ""},
    }
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _seed_full_legacy_root(root: Path) -> dict[str, str]:
    """完整舊佈局 fixture：DB／WAL-SHM／Gfriends／wishlist_cover／lib／thumb／
    預設 gallery／多個 gallery_custom_*／未知檔。回傳 tree manifest。"""
    root.mkdir(parents=True, exist_ok=True)
    db = root / "openaver.db"
    db.write_bytes(b"SQLite-format-legacy-db-bytes-v1")
    (root / "openaver.db-wal").write_bytes(b"wal-bytes-aaa")
    (root / "openaver.db-shm").write_bytes(b"shm-bytes-bbb")
    (root / "Gfriends").mkdir()
    (root / "Gfriends" / "photo.jpg").write_bytes(b"gfriend-photo")
    (root / "wishlist_cover").mkdir()
    (root / "wishlist_cover" / "ab").mkdir()
    (root / "wishlist_cover" / "ab" / "cover.webp").write_bytes(b"wishlist")
    (root / "lib").mkdir()
    (root / "lib" / "src1").mkdir()
    (root / "lib" / "src1" / "note.txt").write_text("lib-note", encoding="utf-8")
    (root / "thumb").mkdir()
    (root / "thumb" / "aa").mkdir()
    (root / "thumb" / "aa" / "t.webp").write_bytes(b"thumb-bytes")
    (root / "gallery_output.html").write_text("<html>default-gallery</html>", encoding="utf-8")
    (root / "gallery_custom_20240101_120000.html").write_text("custom-a", encoding="utf-8")
    (root / "gallery_custom_20240202_130000.html").write_text("custom-b", encoding="utf-8")
    (root / "user_unknown_notes.txt").write_text("do-not-touch", encoding="utf-8")
    (root / "mystery_dir").mkdir()
    (root / "mystery_dir" / "x.bin").write_bytes(b"\x00\x01\x02")
    return _tree_manifest(root)


def _patch_roots(monkeypatch, *, effective: Path, default: Path, legacy_config: Path):
    """把 resolver／legacy config／CONFIG_DEFAULT 指到測試 fixture。"""
    import core.config as core_config
    import core.data_root as data_root_module

    monkeypatch.setattr(data_root_module, "get_data_root", lambda: effective)
    monkeypatch.setattr(data_root_module, "get_default_data_root", lambda: default)
    # project root → legacy config 落在 <project>/web/config.json
    # 用一個假 project root，其 web/config.json = legacy_config
    fake_project = legacy_config.parent.parent
    monkeypatch.setattr(data_root_module, "get_project_root", lambda: fake_project)
    monkeypatch.setattr(core_config, "CONFIG_PATH", effective / "config.json")
    # CONFIG_DEFAULT_PATH 維持程式區 template（真實檔）
    assert core_config.CONFIG_DEFAULT_PATH.exists()


# ── DoD：既有資料零破壞 ───────────────────────────────────────────────

def test_bootstrap_preserves_existing_root_tree_byte_for_byte(tmp_path, monkeypatch):
    """完整舊佈局跑 bootstrap 後，既有項目（含未知檔）與 legacy config 逐位元組不變。"""
    from core.data_layout import bootstrap_data_layout

    root = tmp_path / "output"
    before = _seed_full_legacy_root(root)
    legacy = tmp_path / "web" / "config.json"
    legacy_bytes = _write_legacy_config(legacy)
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    result = bootstrap_data_layout()

    assert result.status == "finalized_legacy"
    after = _tree_manifest(root)
    # 既有項目逐一相同；允許新增 config.json 與 .layout.json
    for rel, digest in before.items():
        assert rel in after, f"missing after bootstrap: {rel}"
        assert after[rel] == digest, f"changed: {rel}"
    assert legacy.read_bytes() == legacy_bytes
    assert _file_sha(root / "config.json") == _sha256_bytes(legacy_bytes)
    marker = json.loads((root / ".layout.json").read_text(encoding="utf-8"))
    assert marker.get("complete") is True


# ── DoD：recovered-existing ───────────────────────────────────────────

def test_recovered_existing_preserves_db_and_does_not_call_init_db(tmp_path, monkeypatch):
    """root 有 DB、legacy/root config 皆無 → 不呼叫 init_db、DB 不變、status=recovered_existing。"""
    from core.data_layout import bootstrap_data_layout
    import core.data_layout as layout_mod

    root = tmp_path / "output"
    root.mkdir()
    db = root / "openaver.db"
    db_bytes = b"existing-db-must-not-change"
    db.write_bytes(db_bytes)
    legacy = tmp_path / "web" / "config.json"  # 不建立
    legacy.parent.mkdir(parents=True, exist_ok=True)
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    init_calls: list = []
    monkeypatch.setattr(layout_mod, "init_db", lambda *a, **k: init_calls.append((a, k)))

    result = bootstrap_data_layout()

    assert result.status == "recovered_existing"
    assert init_calls == []
    assert db.read_bytes() == db_bytes
    assert (root / "config.json").is_file()
    assert (root / ".layout.json").is_file()
    marker = json.loads((root / ".layout.json").read_text(encoding="utf-8"))
    assert marker.get("complete") is True


# ── DoD：fresh root ───────────────────────────────────────────────────

def test_fresh_root_creates_openable_db_and_reports_fresh(tmp_path, monkeypatch):
    """空 root、無 legacy → 建出可開啟的空 DB，status=fresh（異於 recovered）。"""
    from core.data_layout import bootstrap_data_layout

    root = tmp_path / "output"  # 不預建
    legacy = tmp_path / "web" / "config.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    result = bootstrap_data_layout()

    assert result.status == "fresh"
    db = root / "openaver.db"
    assert db.is_file()
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("SELECT 1").fetchone()
    finally:
        conn.close()
    assert (root / "config.json").is_file()
    assert (root / ".layout.json").is_file()


# ── DoD：owned-artifact 失敗注入 ──────────────────────────────────────

def test_copy_failure_leaves_no_half_written_config(tmp_path, monkeypatch):
    """複製失敗 → 無有效 marker；root config 不存在或與 legacy 相同。"""
    from core.data_layout import bootstrap_data_layout, DataLayoutError
    import shutil

    root = tmp_path / "output"
    root.mkdir()
    (root / "openaver.db").write_bytes(b"db")
    legacy = tmp_path / "web" / "config.json"
    legacy_bytes = _write_legacy_config(legacy)
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    def boom(*a, **k):
        raise OSError("injected copy failure")

    monkeypatch.setattr(shutil, "copy2", boom)

    with pytest.raises(DataLayoutError):
        bootstrap_data_layout()

    marker = root / ".layout.json"
    assert not marker.exists() or json.loads(marker.read_text()).get("complete") is not True
    cfg = root / "config.json"
    assert (not cfg.exists()) or cfg.read_bytes() == legacy_bytes
    assert legacy.read_bytes() == legacy_bytes


def test_config_copy_hash_mismatch_blocks_replace(tmp_path, monkeypatch):
    """hash 不符 → replace 被擋；root config 不存在或與 legacy 相同。"""
    from core.data_layout import bootstrap_data_layout, DataLayoutError
    import core.data_layout as layout_mod

    root = tmp_path / "output"
    root.mkdir()
    (root / "openaver.db").write_bytes(b"db")
    legacy = tmp_path / "web" / "config.json"
    legacy_bytes = _write_legacy_config(legacy)
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    real_sha = layout_mod._sha256
    calls = {"n": 0}

    def mismatching_sha(path):
        calls["n"] += 1
        # 第一次（legacy）與第二次（tmp）回不同值 → 觸發 mismatch 分支
        return f"fake-hash-{calls['n']}"

    monkeypatch.setattr(layout_mod, "_sha256", mismatching_sha)

    with pytest.raises(DataLayoutError):
        bootstrap_data_layout()

    # 確認真的走到了 hash 比對（至少兩次）
    assert calls["n"] >= 2
    marker = root / ".layout.json"
    assert not marker.exists() or json.loads(marker.read_text()).get("complete") is not True
    cfg = root / "config.json"
    assert (not cfg.exists()) or cfg.read_bytes() == legacy_bytes
    # legacy 本身未被改寫
    assert legacy.read_bytes() == legacy_bytes
    # 還原真實 hash 工具供其他斷言可讀
    monkeypatch.setattr(layout_mod, "_sha256", real_sha)


def test_marker_write_failure_leaves_config_consistent_with_legacy(tmp_path, monkeypatch):
    """marker 寫入失敗 → marker 無效／不存在；config 不存在或與 legacy 相同。"""
    from core.data_layout import bootstrap_data_layout, DataLayoutError
    import core.data_layout as layout_mod
    import core.atomic_write as atomic_write_mod

    root = tmp_path / "output"
    root.mkdir()
    (root / "openaver.db").write_bytes(b"db")
    legacy = tmp_path / "web" / "config.json"
    legacy_bytes = _write_legacy_config(legacy)
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    real_atomic_write = atomic_write_mod.atomic_write

    def failing_atomic_write(dest, *a, **k):
        dest = Path(dest)
        if dest.name == ".layout.json":
            raise OSError("injected marker write failure")
        return real_atomic_write(dest, *a, **k)

    monkeypatch.setattr(layout_mod, "atomic_write", failing_atomic_write)
    monkeypatch.setattr(atomic_write_mod, "atomic_write", failing_atomic_write)

    with pytest.raises((DataLayoutError, OSError)):
        bootstrap_data_layout()

    marker = root / ".layout.json"
    assert not marker.exists() or json.loads(marker.read_text()).get("complete") is not True
    cfg = root / "config.json"
    assert (not cfg.exists()) or cfg.read_bytes() == legacy_bytes


# ── mutation：incomplete marker ───────────────────────────────────────

def test_incomplete_marker_is_not_treated_as_finalized(tmp_path, monkeypatch):
    """complete 非 True 的 marker 不得被當成已定版放行。"""
    from core.data_layout import bootstrap_data_layout, DataLayoutError

    root = tmp_path / "output"
    root.mkdir()
    # 放一份可讀 root config，讓「只檢查 marker is not None」的錯誤實作會誤放行
    (root / "config.json").write_text(
        json.dumps({"scraper": {}, "search": {}, "gallery": {}}),
        encoding="utf-8",
    )
    (root / ".layout.json").write_text(
        json.dumps({"version": 1, "complete": False}),
        encoding="utf-8",
    )
    legacy = tmp_path / "web" / "config.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    with pytest.raises(DataLayoutError):
        bootstrap_data_layout()


# ── DoD：地雷一／external-root gate ───────────────────────────────────

def test_external_empty_root_with_local_legacy_is_rejected(tmp_path, monkeypatch):
    """OPENAVER_DATA_DIR 空路徑 + default 有舊資料 → 失敗且 external 零建立。"""
    from core.data_layout import bootstrap_data_layout, DataLayoutError
    import core.data_root as data_root_module

    default_root = tmp_path / "output"
    _seed_full_legacy_root(default_root)
    external = tmp_path / "never_created_external"
    legacy = tmp_path / "web" / "config.json"
    _write_legacy_config(legacy)

    monkeypatch.setenv("OPENAVER_DATA_DIR", str(external))
    monkeypatch.setattr(data_root_module, "get_default_data_root", lambda: default_root)
    monkeypatch.setattr(data_root_module, "get_data_root", lambda: external)
    monkeypatch.setattr(data_root_module, "get_project_root", lambda: legacy.parent.parent)
    import core.config as core_config
    monkeypatch.setattr(core_config, "CONFIG_PATH", external / "config.json")

    with pytest.raises(DataLayoutError):
        bootstrap_data_layout()

    assert not external.exists() or list(external.iterdir()) == []
    assert not (external / "openaver.db").exists()


def test_external_valid_layout_is_accepted(tmp_path, monkeypatch):
    """override 已有有效 layout → 成功，只用 override。"""
    from core.data_layout import bootstrap_data_layout

    default_root = tmp_path / "output"
    _seed_full_legacy_root(default_root)
    external = tmp_path / "data"
    external.mkdir()
    cfg = {
        "scraper": {"create_folder": True},
        "search": {},
        "gallery": {"output_dir": ""},
    }
    (external / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (external / ".layout.json").write_text(
        json.dumps({"version": 1, "complete": True}),
        encoding="utf-8",
    )
    (external / "openaver.db").write_bytes(b"external-db")
    legacy = tmp_path / "web" / "config.json"
    _write_legacy_config(legacy)
    _patch_roots(monkeypatch, effective=external, default=default_root, legacy_config=legacy)

    result = bootstrap_data_layout()
    assert result.status == "already_complete"
    assert result.root == external


def test_both_roots_empty_allows_fresh_on_external(tmp_path, monkeypatch):
    """override 與 default 皆空 → 允許在 override 走 fresh。"""
    from core.data_layout import bootstrap_data_layout

    default_root = tmp_path / "output"  # 不存在
    external = tmp_path / "data"  # 不存在
    legacy = tmp_path / "web" / "config.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    _patch_roots(monkeypatch, effective=external, default=default_root, legacy_config=legacy)

    result = bootstrap_data_layout()
    assert result.status == "fresh"
    assert (external / "openaver.db").is_file()
    assert (external / ".layout.json").is_file()


def test_already_complete_ignores_legacy_config(tmp_path, monkeypatch):
    """有效 marker + 可讀 root config → already_complete，不讀／不改 legacy。"""
    from core.data_layout import bootstrap_data_layout

    root = tmp_path / "output"
    root.mkdir()
    root_cfg = {"scraper": {}, "search": {"search_filter": "root-only"}, "gallery": {}}
    (root / "config.json").write_text(json.dumps(root_cfg), encoding="utf-8")
    (root / ".layout.json").write_text(
        json.dumps({"version": 1, "complete": True}),
        encoding="utf-8",
    )
    legacy = tmp_path / "web" / "config.json"
    legacy_bytes = _write_legacy_config(legacy, {"search": {"search_filter": "legacy-should-ignore"}})
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    result = bootstrap_data_layout()
    assert result.status == "already_complete"
    assert legacy.read_bytes() == legacy_bytes
    assert json.loads((root / "config.json").read_text())["search"]["search_filter"] == "root-only"


def test_root_config_matching_legacy_resumes_marker_only(tmp_path, monkeypatch):
    """無 marker、root config 已與 legacy 相同 → 只補寫 marker。"""
    from core.data_layout import bootstrap_data_layout

    root = tmp_path / "output"
    root.mkdir()
    (root / "openaver.db").write_bytes(b"db")
    legacy = tmp_path / "web" / "config.json"
    legacy_bytes = _write_legacy_config(legacy)
    (root / "config.json").write_bytes(legacy_bytes)
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    result = bootstrap_data_layout()
    assert result.status == "finalized_legacy"
    assert (root / ".layout.json").is_file()
    assert (root / "config.json").read_bytes() == legacy_bytes


# ── CD-114c-9：落地 config.json 必須 0600 ─────────────────────────────

def test_fresh_root_config_mode_is_0600(tmp_path, monkeypatch):
    """fresh（從 config.default.json 建）→ <root>/config.json mode == 0o600。"""
    from core.data_layout import bootstrap_data_layout

    root = tmp_path / "output"
    legacy = tmp_path / "web" / "config.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    result = bootstrap_data_layout()
    assert result.status == "fresh"
    mode = (root / "config.json").stat().st_mode & 0o777
    assert mode == 0o600


def test_finalized_legacy_config_mode_is_0600(tmp_path, monkeypatch):
    """finalized_legacy（從 legacy 複製）→ <root>/config.json mode == 0o600。"""
    from core.data_layout import bootstrap_data_layout

    root = tmp_path / "output"
    root.mkdir()
    (root / "openaver.db").write_bytes(b"db")
    legacy = tmp_path / "web" / "config.json"
    _write_legacy_config(legacy)
    legacy.chmod(0o600)  # 來源已是 0600 的正常路徑
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    result = bootstrap_data_layout()
    assert result.status == "finalized_legacy"
    mode = (root / "config.json").stat().st_mode & 0o777
    assert mode == 0o600


def test_finalized_legacy_forces_0600_even_when_source_is_0644(tmp_path, monkeypatch):
    """legacy 來源刻意 0644 時，落地仍須 0600（真正守住 copy2 陷阱）。"""
    from core.data_layout import bootstrap_data_layout

    root = tmp_path / "output"
    root.mkdir()
    (root / "openaver.db").write_bytes(b"db")
    legacy = tmp_path / "web" / "config.json"
    _write_legacy_config(legacy)
    legacy.chmod(0o644)
    assert (legacy.stat().st_mode & 0o777) == 0o644
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    result = bootstrap_data_layout()
    assert result.status == "finalized_legacy"
    mode = (root / "config.json").stat().st_mode & 0o777
    assert mode == 0o600
    # 來源本身不被改寫權限（copy 後再 chmod dest，不動 source）
    assert (legacy.stat().st_mode & 0o777) == 0o644


# ── 地雷二：啟動順序（呼叫順序記錄，非行號）──────────────────────────

def test_standalone_bootstrap_runs_before_server_start(monkeypatch):
    """desktop：bootstrap 必須在 server_thread.start() 之前。"""
    import standalone

    order: list[str] = []

    def fake_bootstrap():
        order.append("bootstrap")
        return MagicMock(status="already_complete")

    monkeypatch.setattr(standalone, "bootstrap_data_layout", fake_bootstrap)
    monkeypatch.setattr(standalone, "_ensure_webview2_runtime", lambda logger: None)
    monkeypatch.setattr(standalone, "find_free_port", lambda *a, **k: 49152)
    monkeypatch.setattr(standalone, "setup_logging", lambda **k: None)
    monkeypatch.setattr(standalone, "get_logger", lambda name: MagicMock())

    def tracking_start(self):
        order.append("server")

    monkeypatch.setattr(threading.Thread, "start", tracking_start)

    def stop_after_start(*a, **k):
        raise SystemExit(0)

    monkeypatch.setattr(standalone, "_wait_for_server_or_exit", stop_after_start)

    with pytest.raises(SystemExit):
        standalone.main()

    assert order == ["bootstrap", "server"]


async def test_lifespan_bootstrap_runs_before_init_db(monkeypatch):
    """web.app lifespan：bootstrap 必須在 init_db() 之前。"""
    import asyncio
    import web.app as webapp

    order: list[str] = []

    def fake_bootstrap():
        order.append("bootstrap")
        return MagicMock(status="already_complete")

    def fake_init_db(*a, **k):
        order.append("init_db")

    monkeypatch.setattr(webapp, "bootstrap_data_layout", fake_bootstrap)
    monkeypatch.setattr(webapp, "init_db", fake_init_db)
    monkeypatch.setattr(webapp, "start_notification_persistence", lambda: None)
    monkeypatch.setattr(webapp, "ensure_schema", lambda: None)
    monkeypatch.setattr(webapp, "load_config", lambda: {"gallery": {}, "general": {}, "search": {}})
    monkeypatch.setattr(webapp, "backfill_readonly_nfo_mtime", lambda **k: 0)
    monkeypatch.setattr(webapp, "startup_reconnect", lambda cfg: None)
    monkeypatch.setattr(webapp, "stop_notification_persistence", lambda: None)
    monkeypatch.setattr(
        webapp.source_reachability,
        "probe_all_enabled",
        lambda: None,
        raising=False,
    )

    async def _noop_loop():
        while True:
            await asyncio.sleep(3600)

    monkeypatch.setattr(webapp, "auto_organize_loop", _noop_loop)

    class _FakeState:
        auto_organize_task = None

    webapp.app.state = _FakeState()

    async with webapp.lifespan(webapp.app):
        pass

    assert order[:2] == ["bootstrap", "init_db"]
