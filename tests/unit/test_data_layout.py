"""tests/unit/test_data_layout.py — bootstrap_data_layout 正向鎖（TASK-153b-T2）。

每支測試至少對真實 tmp_path 執行 bootstrap，再檢查磁碟狀態；不全程 mock 磁碟操作。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock

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

def test_consume_reset_access_auth_marker_when_present(tmp_path, monkeypatch):
    import core.data_layout as layout_mod
    import core.data_root as data_root_module

    root = tmp_path / "output"
    root.mkdir()
    marker = root / ".reset_access_auth"
    marker.touch()
    set_auth = Mock()
    monkeypatch.setattr(data_root_module, "get_data_root", lambda: root)
    monkeypatch.setattr(layout_mod, "set_auth", set_auth)

    assert layout_mod.consume_reset_access_auth_marker() is True
    set_auth.assert_called_once_with(False, "")
    assert not marker.exists()


def test_consume_reset_access_auth_marker_noop_when_marker_absent(tmp_path, monkeypatch):
    import core.data_layout as layout_mod
    import core.data_root as data_root_module

    root = tmp_path / "output"
    root.mkdir()
    set_auth = Mock()
    monkeypatch.setattr(data_root_module, "get_data_root", lambda: root)
    monkeypatch.setattr(layout_mod, "set_auth", set_auth)

    assert layout_mod.consume_reset_access_auth_marker() is False
    set_auth.assert_not_called()
    assert list(root.iterdir()) == []


def test_consume_reset_access_auth_marker_unlink_failure_keeps_auth(tmp_path, monkeypatch):
    import core.data_layout as layout_mod
    import core.data_root as data_root_module

    root = tmp_path / "output"
    root.mkdir()
    marker = root / ".reset_access_auth"
    marker.touch()
    set_auth = Mock()
    monkeypatch.setattr(data_root_module, "get_data_root", lambda: root)
    monkeypatch.setattr(layout_mod, "set_auth", set_auth)

    def fail_unlink(self, *args, **kwargs):
        assert self == marker
        raise OSError("injected unlink failure")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(OSError, match="injected unlink failure"):
        layout_mod.consume_reset_access_auth_marker()
    set_auth.assert_not_called()
    assert marker.exists()


def test_consume_reset_access_auth_marker_set_auth_failure_restores_marker(tmp_path, monkeypatch):
    import core.data_layout as layout_mod
    import core.data_root as data_root_module

    root = tmp_path / "output"
    root.mkdir()
    marker = root / ".reset_access_auth"
    marker.touch()
    monkeypatch.setattr(data_root_module, "get_data_root", lambda: root)
    monkeypatch.setattr(
        layout_mod, "set_auth",
        Mock(side_effect=sqlite3.OperationalError("database is locked")),
    )

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        layout_mod.consume_reset_access_auth_marker()
    assert marker.exists()  # 下次重啟會重試

    ok = Mock()
    monkeypatch.setattr(layout_mod, "set_auth", ok)
    assert layout_mod.consume_reset_access_auth_marker() is True
    ok.assert_called_once_with(False, "")
    assert not marker.exists()


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

    monkeypatch.setattr(shutil, "copyfile", boom)

    with pytest.raises(DataLayoutError):
        bootstrap_data_layout()

    marker = root / ".layout.json"
    assert not marker.exists() or json.loads(marker.read_text()).get("complete") is not True
    cfg = root / "config.json"
    assert (not cfg.exists()) or cfg.read_bytes() == legacy_bytes
    assert legacy.read_bytes() == legacy_bytes


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


def test_marker_valid_config_missing_rebuilds_default_and_recovers(tmp_path, monkeypatch):
    """有效 marker + config 不存在 → default 重建、recovered_existing；legacy／DB 不變。"""
    from core.config import CONFIG_DEFAULT_PATH
    from core.data_layout import bootstrap_data_layout
    import core.data_layout as layout_mod

    root = tmp_path / "output"
    root.mkdir()
    db = root / "openaver.db"
    db_bytes = b"existing-db-must-survive-config-rebuild"
    db.write_bytes(db_bytes)
    (root / ".layout.json").write_text(
        json.dumps({"version": 1, "complete": True}),
        encoding="utf-8",
    )
    legacy = tmp_path / "web" / "config.json"
    legacy_bytes = _write_legacy_config(
        legacy, {"search": {"search_filter": "legacy-must-not-be-copied"}}
    )
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    init_calls: list = []
    monkeypatch.setattr(layout_mod, "init_db", lambda *a, **k: init_calls.append((a, k)))

    result = bootstrap_data_layout()

    assert result.status == "recovered_existing"
    assert init_calls == []
    assert db.read_bytes() == db_bytes
    assert legacy.read_bytes() == legacy_bytes
    cfg = root / "config.json"
    assert cfg.is_file()
    assert (cfg.stat().st_mode & 0o777) == 0o600
    assert cfg.read_bytes() == CONFIG_DEFAULT_PATH.read_bytes()
    assert json.loads(cfg.read_text(encoding="utf-8")) != json.loads(
        legacy_bytes.decode("utf-8")
    )


def test_marker_valid_config_damaged_still_raises_and_preserves_bytes(tmp_path, monkeypatch):
    """有效 marker + config 存在但損壞 → 仍阻斷；位元組不變。"""
    from core.data_layout import bootstrap_data_layout, DataLayoutError

    root = tmp_path / "output"
    root.mkdir()
    damaged = b"{not-valid-json"
    cfg = root / "config.json"
    cfg.write_bytes(damaged)
    (root / ".layout.json").write_text(
        json.dumps({"version": 1, "complete": True}),
        encoding="utf-8",
    )
    legacy = tmp_path / "web" / "config.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    with pytest.raises(DataLayoutError, match="root config unreadable"):
        bootstrap_data_layout()

    assert cfg.read_bytes() == damaged


def test_install_config_from_source_opens_writable_fd_for_fsync(tmp_path, monkeypatch):
    """fsync 前的 os.open 必須帶寫入權限（Windows FlushFileBuffers 需要可寫 handle）。"""
    import os

    import core.data_layout as layout_mod

    source = tmp_path / "source.json"
    source.write_text('{"ok": true}\n', encoding="utf-8")
    dest = tmp_path / "dest" / "config.json"
    dest.parent.mkdir()

    # 只收「已存在的 staging temp」那次 open（排除 mkstemp 的 O_CREAT 建檔，
    # 否則 mkstemp 自帶 O_RDWR 會讓 O_RDONLY 回歸假綠）。
    fsync_open_flags: list[int] = []
    real_open = os.open

    def spy_open(path, flags, *args, **kwargs):
        path_s = str(path)
        if path_s.endswith(".config.tmp") and not (flags & os.O_CREAT):
            fsync_open_flags.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(layout_mod.os, "open", spy_open)

    layout_mod._install_config_from_source(source, dest)

    assert fsync_open_flags, "應有一次對 staging .config.tmp 的 fsync 用 os.open"
    assert all(f & (os.O_RDWR | os.O_WRONLY) for f in fsync_open_flags), (
        "Windows 的 fsync 需要可寫 handle；"
        f"got fsync-open flags={fsync_open_flags!r}（應含 O_RDWR 或 O_WRONLY）"
    )
    assert dest.is_file()


# ── CD-114c-9：落地 config.json 必須 0600 ─────────────────────────────


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


# ── TASK-153b-T3fix2：F3／F2／F1 狀態矩陣補齊 ───────────────────────


def test_root_config_matching_legacy_resume_forces_0600_even_when_0644(tmp_path, monkeypatch):
    """F1：hash 相同只補 marker 時，起始 0644 的 root config 必須被修成 0600。"""
    from core.data_layout import bootstrap_data_layout

    root = tmp_path / "output"
    root.mkdir()
    (root / "openaver.db").write_bytes(b"db")
    legacy = tmp_path / "web" / "config.json"
    legacy_bytes = _write_legacy_config(legacy)
    root_config = root / "config.json"
    root_config.write_bytes(legacy_bytes)
    root_config.chmod(0o644)
    assert (root_config.stat().st_mode & 0o777) == 0o644
    _patch_roots(monkeypatch, effective=root, default=root, legacy_config=legacy)

    result = bootstrap_data_layout()
    assert result.status == "finalized_legacy"
    assert (root_config.stat().st_mode & 0o777) == 0o600


# ── 地雷二：啟動順序（呼叫順序記錄，非行號）──────────────────────────


