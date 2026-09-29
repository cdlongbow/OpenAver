"""Synology install wizard items for first install and reinstall."""

import importlib.util
import builtins
from importlib.machinery import SourceFileLoader
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "synology/spk-src/WIZARD_UIFILES/install_uifile.sh"


def _load_module():
    # Python does not infer a loader for the .sh suffix, even though the file is Python.
    spec = importlib.util.spec_from_file_location(
        "install_uifile_wizard", SCRIPT_PATH,
        loader=SourceFileLoader("install_uifile_wizard", str(SCRIPT_PATH)),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_items_existing_data_true_omits_multiselect(capsys, monkeypatch):
    opened = []
    original_open = builtins.open

    def track_open(path, *args, **kwargs):
        if str(path) == "/tmp/openaver_wizard_shares.json":
            opened.append(str(path))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", track_open)
    module = _load_module()
    assert capsys.readouterr().out == ""
    assert opened == []
    assert callable(getattr(module, "build_items", None))
    items = module.build_items(pairs=[], existing_data=True)
    assert not any(item.get("type") == "multiselect" for item in items)
    assert any("偵測到既有資料" in item.get("desc", "") for item in items)
    assert not any("選擇你的影片片庫" in item.get("desc", "") for item in items)
    assert not any("找不到共用資料夾" in item.get("desc", "") for item in items)
    assert any("系統內部使用者" in item.get("desc", "") for item in items)
    with_shares = module.build_items([("share1", "/volume1/share1")], existing_data=True)
    assert not any(item.get("type") == "multiselect" for item in with_shares)


def test_build_items_new_install_keeps_multiselect_and_empty_message():
    module = _load_module()
    assert callable(getattr(module, "build_items", None))
    items = module.build_items([("share1", "/volume1/share1")], existing_data=False)
    assert any(item.get("type") == "multiselect" for item in items)
    assert any("選擇你的影片片庫" in item.get("desc", "") for item in items)
    empty_items = module.build_items([], existing_data=False)
    assert any("找不到共用資料夾" in item.get("desc", "") for item in empty_items)


def test_has_existing_data_permission_error_falls_back_to_first_install(monkeypatch):
    module = _load_module()
    assert callable(getattr(module, "has_existing_data", None))

    def deny(_path):
        raise PermissionError("cannot read layout marker")

    monkeypatch.setattr(module.os.path, "exists", deny)
    assert module.has_existing_data() is False


def test_has_existing_data_var_path_true(tmp_path):
    module = _load_module()
    var_path = tmp_path / "var_data" / ".layout.json"
    var_path.parent.mkdir(parents=True)
    var_path.write_text("{}", encoding="utf-8")
    appdata_path = tmp_path / "volume1" / "@appdata" / "OpenAver" / "data" / ".layout.json"
    assert module.has_existing_data(candidates=[str(var_path), str(appdata_path)]) is True


def test_has_existing_data_appdata_fallback_true(tmp_path):
    module = _load_module()
    var_path = tmp_path / "var_data" / ".layout.json"
    appdata_path = tmp_path / "volume1" / "@appdata" / "OpenAver" / "data" / ".layout.json"
    appdata_path.parent.mkdir(parents=True)
    appdata_path.write_text("{}", encoding="utf-8")
    assert module.has_existing_data(candidates=[str(var_path), str(appdata_path)]) is True


def test_has_existing_data_neither_path_false(tmp_path):
    module = _load_module()
    var_path = tmp_path / "var_data" / ".layout.json"
    appdata_path = tmp_path / "volume1" / "@appdata" / "OpenAver" / "data" / ".layout.json"
    assert module.has_existing_data(candidates=[str(var_path), str(appdata_path)]) is False

