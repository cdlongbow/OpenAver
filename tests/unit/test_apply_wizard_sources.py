"""Contracts for the Synology wizard source helper."""

import copy
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "synology/spk-src/scripts/apply_wizard_sources.py"
POSTINST = SCRIPT.with_name("postinst")


def _load_module():
    spec = importlib.util.spec_from_file_location("apply_wizard_sources", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path, *, layout=True, directories=None):
    data = tmp_path / "data"
    data.mkdir()
    if layout:
        (data / ".layout.json").write_text("{}", encoding="utf-8")
    cfg = {"general": {"server_mode": False}, "access": {"key": "keep"},
           "gallery": {"directories": directories if directories is not None else []}}
    (data / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    default = tmp_path / "default.json"
    default.write_text(json.dumps(cfg), encoding="utf-8")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"pkgwizard_share_0": "/volume1/extra"}), encoding="utf-8")
    shares = tmp_path / "shares"
    shares.mkdir()
    target = tmp_path / "volume1" / "我的 影片"
    target.mkdir(parents=True)
    os.symlink(target, shares / "我的 影片")
    legacy = tmp_path / "legacy.json"
    kwargs = dict(data_dir=str(data), legacy_cfg=str(legacy), default_cfg=str(default),
                  mapping_path=str(mapping), shares_root=str(shares), app_dir=str(ROOT))
    env = {"wizard_library_share": "我的 影片", "pkgwizard_share_0": "true"}
    return cfg, kwargs, env, target


def _written(kwargs):
    return json.loads((Path(kwargs["data_dir"]) / "config.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("existing,paths", [
    ([], ["/new"]),
    (["/old"], ["/new"]),
    ([{"path": "/old", "readonly": True, "output_path": "/output"}], ["/new"]),
    (["/old"], ["/old", "/new"]),
    (["/old/"], ["/old", "/new"]),
    (["/Old"], ["/old"]),
])
def test_merge_keeps_input_as_prefix_and_other_keys_equal(existing, paths):
    mod = _load_module()
    cfg = {"gallery": {"directories": existing, "other": [1]}, "access": {"password": "keep"}}
    before = copy.deepcopy(cfg)
    result = mod.merge_directories(cfg, paths)
    assert result["gallery"]["directories"][:len(existing)] == existing
    assert {**result, "gallery": {**result["gallery"], "directories": existing}} == before
    assert cfg == before


def test_merge_case_differs_keeps_both():
    result = _load_module().merge_directories({"gallery": {"directories": ["/Video"]}}, ["/video"])
    assert result["gallery"]["directories"] == ["/Video", {"path": "/video", "readonly": False,
                                                      "output_path": ""}]


@pytest.mark.parametrize("existing,new_path", [
    (["/old/"], "/old"),
    (["/old"], "/old/"),
])
def test_merge_trailing_slashes_are_duplicates(existing, new_path):
    result = _load_module().merge_directories({"gallery": {"directories": existing}}, [new_path])
    assert result["gallery"]["directories"] == existing


@pytest.mark.parametrize("uri,fs_path", [
    ("file:///volume1/av", "/volume1/av"),
    ("file:////volume1/av", "/volume1/av"),
    ("file:////volume1/AV#1", "/volume1/AV#1"),
    ("file:///volume1/a?b", "/volume1/a?b"),
    ("file:///volume1/AV%231", "/volume1/AV#1"),
])
def test_merge_file_uri_readonly_source_not_duplicated(uri, fs_path):
    existing = {"path": uri, "readonly": True, "output_path": "/volume1/output"}
    result = _load_module().merge_directories({"gallery": {"directories": [existing]}},
                                               [fs_path], app_dir=str(ROOT))
    assert result["gallery"]["directories"] == [existing]
    assert result["gallery"]["directories"][0]["readonly"] is True


def test_merge_file_uri_percent_encoded_space_not_duplicated():
    existing = "file:///volume1/oa%20中文"
    result = _load_module().merge_directories({"gallery": {"directories": [existing]}}, ["/volume1/oa 中文"])
    assert result["gallery"]["directories"] == [existing]


def test_merge_fs_path_and_new_file_uri_not_duplicated():
    existing = "/volume1/av"
    result = _load_module().merge_directories({"gallery": {"directories": [existing]}},
                                               ["file:///volume1/av/"], app_dir=str(ROOT))
    assert result["gallery"]["directories"] == [existing]


def test_merge_uri_import_failure_preserves_all_sources(tmp_path, capsys):
    existing = {"path": "file:///volume1/av", "readonly": True, "output_path": "/volume1/output"}
    cfg = {"gallery": {"directories": [existing]}, "access": {"key": "keep"}}
    result = _load_module().merge_directories(cfg, ["/volume1/av", "/volume1/new"], app_dir=str(tmp_path))
    assert result == cfg
    assert "URI" in capsys.readouterr().err


def test_merge_uri_parse_failure_preserves_all_sources(monkeypatch, capsys):
    from core import path_utils

    def boom(_path):
        raise ValueError("unreadable URI")

    monkeypatch.setattr(path_utils, "uri_to_fs_path", boom)
    existing = {"path": "file:///volume1/av", "readonly": True, "output_path": "/volume1/output"}
    cfg = {"gallery": {"directories": [existing]}, "access": {"key": "keep"}}
    result = _load_module().merge_directories(cfg, ["/volume1/av", "/volume1/new"], app_dir=str(ROOT))
    assert result == cfg
    assert "unreadable URI" in capsys.readouterr().err


def test_library_and_extra_same_path_appears_once(tmp_path):
    mod = _load_module()
    _, kwargs, env, target = _fixture(tmp_path)
    Path(kwargs["mapping_path"]).write_text(json.dumps({"pkgwizard_share_0": str(target)}), encoding="utf-8")
    assert mod.run(env, **kwargs) == 0
    assert _written(kwargs)["gallery"]["directories"] == [
        {"path": str(target), "readonly": False, "output_path": ""}]


def test_existing_sources_preserved_verbatim(tmp_path):
    mod = _load_module()
    existing = [{"path": "/old", "readonly": True, "output_path": "/kept"}, "/string",
                {"path": "/another/", "readonly": True, "output_path": "/other"}]
    cfg, kwargs, env, target = _fixture(tmp_path, directories=existing)
    assert mod.run(env, **kwargs) == 0
    written = _written(kwargs)
    assert written["gallery"]["directories"] == existing + [
        {"path": str(target), "readonly": False, "output_path": ""},
        {"path": "/volume1/extra", "readonly": False, "output_path": ""}]
    written["gallery"]["directories"] = existing
    assert written == cfg


def test_upgrade_skips_writing(tmp_path):
    mod = _load_module()
    _, kwargs, env, _ = _fixture(tmp_path)
    env["SYNOPKG_OLD_PKGVER"] = "1.0"
    config = Path(kwargs["data_dir"]) / "config.json"
    before = config.read_bytes()
    assert mod.run(env, **kwargs) == 0
    assert config.read_bytes() == before


def test_empty_library_env_skips_writing(tmp_path):
    mod = _load_module()
    _, kwargs, env, _ = _fixture(tmp_path)
    env["wizard_library_share"] = ""
    config = Path(kwargs["data_dir"]) / "config.json"
    before = config.read_bytes()
    assert mod.run(env, **kwargs) == 0
    assert config.read_bytes() == before


def test_corrupt_data_config_not_overwritten(tmp_path):
    mod = _load_module()
    _, kwargs, env, _ = _fixture(tmp_path)
    config = Path(kwargs["data_dir"]) / "config.json"
    config.write_bytes(b"not-json")
    assert mod.run(env, **kwargs) == 0
    assert config.read_bytes() == b"not-json"


def test_layout_absent_never_writes_data_root(tmp_path):
    mod = _load_module()
    _, kwargs, env, _ = _fixture(tmp_path, layout=False)
    config = Path(kwargs["data_dir"]) / "config.json"
    before = config.read_bytes()
    assert mod.run(env, **kwargs) == 0
    assert config.read_bytes() == before
    legacy = Path(kwargs["legacy_cfg"])
    assert legacy.is_file()
    assert json.loads(legacy.read_text(encoding="utf-8"))["general"]["server_mode"] is True
    assert stat.S_IMODE(legacy.stat().st_mode) == 0o600


def test_layout_present_writes_data_config_not_legacy(tmp_path):
    mod = _load_module()
    _, kwargs, env, target = _fixture(tmp_path)
    assert mod.run(env, **kwargs) == 0
    assert _written(kwargs)["gallery"]["directories"][0]["path"] == str(target)
    assert stat.S_IMODE((Path(kwargs["data_dir"]) / "config.json").stat().st_mode) == 0o600
    assert not Path(kwargs["legacy_cfg"]).exists()


def test_resolve_symlink_chinese_space_name(tmp_path):
    mod = _load_module()
    _, kwargs, _, target = _fixture(tmp_path)
    assert mod.resolve_share("我的 影片", kwargs["shares_root"]) == str(target)


def test_resolve_missing_symlink_returns_none_even_if_plain_dir_exists(tmp_path):
    mod = _load_module()
    _, kwargs, _, _ = _fixture(tmp_path)
    (Path(kwargs["shares_root"]) / "我的 影片").unlink()
    assert mod.resolve_share("我的 影片", kwargs["shares_root"]) is None


def test_run_missing_symlink_writes_nothing_for_library(tmp_path):
    mod = _load_module()
    _, kwargs, env, target = _fixture(tmp_path)
    (Path(kwargs["shares_root"]) / "我的 影片").unlink()
    assert target.is_dir()
    assert mod.run(env, **kwargs) == 0
    assert _written(kwargs)["gallery"]["directories"] == [
        {"path": "/volume1/extra", "readonly": False, "output_path": ""}]


def test_atomic_write_failure_keeps_original_no_temp(tmp_path, monkeypatch):
    mod = _load_module()
    _, kwargs, env, _ = _fixture(tmp_path)
    data = Path(kwargs["data_dir"])
    config = data / "config.json"
    before = config.read_bytes()
    names = set(os.listdir(data))

    def boom(*_args):
        raise OSError("replace failed")

    monkeypatch.setattr(mod.os, "replace", boom)
    assert mod.run(env, **kwargs) == 0
    assert config.read_bytes() == before
    assert set(os.listdir(data)) == names


def test_postinst_references_existing_helper():
    text = POSTINST.read_text(encoding="utf-8")
    assert 'HELPER="$(dirname "$0")/apply_wizard_sources.py"' in text
    assert '"$PY_BIN" "$HELPER"' in text
    assert 'if [ ! -f "$HELPER" ]; then' in text
    assert 'echo "### [postinst] helper 找不到：$HELPER" >&2' in text
    assert "SYNOPKG_PKGDEST}/scripts" not in text
    assert '"${SYNOPKG_PKGDEST}/app" >&2 || true' in text
    assert SCRIPT.is_file()


def test_helper_exception_still_returns_zero(tmp_path, monkeypatch, capsys):
    mod = _load_module()
    _, kwargs, env, _ = _fixture(tmp_path)

    def boom(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "pick_paths", boom)
    assert mod.run(env, **kwargs) == 0
    assert "boom" in capsys.readouterr().err


def test_seed_writes_legacy_with_server_mode_and_paths_in_order(tmp_path):
    mod = _load_module()
    _, kwargs, env, target = _fixture(tmp_path, layout=False)
    assert mod.run(env, **kwargs) == 0
    legacy = Path(kwargs["legacy_cfg"])
    cfg = json.loads(legacy.read_text(encoding="utf-8"))
    assert cfg["general"]["server_mode"] is True
    assert [item["path"] for item in cfg["gallery"]["directories"]] == [str(target), "/volume1/extra"]
    assert stat.S_IMODE(legacy.stat().st_mode) == 0o600


def test_seed_without_wizard_env_still_sets_server_mode(tmp_path):
    mod = _load_module()
    _, kwargs, env, _ = _fixture(tmp_path, layout=False)
    env["wizard_library_share"] = ""
    assert mod.run(env, **kwargs) == 0
    cfg = json.loads(Path(kwargs["legacy_cfg"]).read_text(encoding="utf-8"))
    assert cfg["general"]["server_mode"] is True
    assert cfg["gallery"]["directories"] == []


def test_seed_without_core_import_still_sets_server_mode(tmp_path):
    mod = _load_module()
    _, kwargs, env, _ = _fixture(tmp_path, layout=False)
    kwargs["app_dir"] = str(tmp_path / "app_without_core")
    assert mod.run(env, **kwargs) == 0
    cfg = json.loads(Path(kwargs["legacy_cfg"]).read_text(encoding="utf-8"))
    assert cfg["general"]["server_mode"] is True


def test_main_reinstall_writes_config(tmp_path):
    _, kwargs, env, target = _fixture(tmp_path)
    proc = subprocess.run([sys.executable, str(SCRIPT), *kwargs.values()],
                          env={**os.environ, **env}, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert _written(kwargs)["gallery"]["directories"][0]["path"] == str(target)
