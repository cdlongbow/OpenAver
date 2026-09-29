"""Synology install wizard items for first install and reinstall."""

import builtins
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import pytest


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


@pytest.mark.parametrize("existing_data", [False, True])
@pytest.mark.parametrize("pairs", [[], [("share1", "/volume1/share1")]])
def test_build_items_library_combobox_shape(capsys, monkeypatch, existing_data, pairs):
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
    items = module.build_items(pairs, existing_data)
    comboboxes = [item for item in items if item.get("type") == "combobox"]
    assert len(comboboxes) == 1
    combobox = comboboxes[0]
    assert set(combobox) == {"type", "desc", "subitems"}
    assert len(combobox["subitems"]) == 1
    subitem = combobox["subitems"][0]
    assert subitem == {
        "key": subitem["key"],
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
    }
    multiselects = [item for item in items if item.get("type") == "multiselect"]
    assert len(multiselects) == (1 if pairs else 0)
    if pairs:
        assert multiselects[0]["subitems"] == [
            {"key": "pkgwizard_share_0", "desc": "share1", "defaultValue": False},
        ]
    else:
        assert "下拉是空的" in " ".join(item.get("desc", "") for item in items)

    monkeypatch.setattr(module.os, "uname", lambda: SimpleNamespace(machine="armv7l"))
    assert "這台 NAS 無法安裝 OpenAver" in module.build_items(pairs, existing_data)[0]["desc"]


# [lint-guard: pytest-justified] 斷言的是 Python 函式 build_items() 產出的精靈文案（授權承諾），不是靜態 HTML/JS/CSS
@pytest.mark.parametrize("existing_data", [False, True])
def test_build_items_copy_anchors(existing_data):
    module = _load_module()
    items = module.build_items([("share1", "/volume1/share1")], existing_data)
    copy = " ".join(item.get("desc", "") for item in items)
    for anchor in (
        "自動取得", "讀寫權限", "會被授予讀寫權限",
        "無法自動授權，裝好後請到控制台手動授權",
        "在控制台拿掉這個權限，下次 OpenAver 啟動時會自動加回來",
        "要收回：先移除套件", "openaver-svc",
    ):
        assert anchor in copy
    for obsolete in ("Synology 不允許", "系統內部使用者", "Jellyfin"):
        assert obsolete not in copy
    if existing_data:
        for anchor in ("偵測到既有資料", "加進", "區網密碼"):
            assert anchor in copy
    else:
        for absent in ("偵測到既有資料", "區網密碼"):
            assert absent not in copy


def test_shares_single_entry_error_keeps_others(monkeypatch):
    module = _load_module()
    original_isdir = module.os.path.isdir

    def fake_isdir(path):
        if path == "/volume1":
            return True
        if path == "/volume1/bad":
            raise OSError("bad entry")
        if path.startswith("/volume1/"):
            return True
        if path.startswith("/volume"):
            return False
        return original_isdir(path)

    original_listdir = module.os.listdir

    def fake_listdir(path):
        if path == "/volume1":
            return ["@eaDir", "#recycle", "OpenAver", "bad", "good", "中文 空白"]
        return original_listdir(path)

    monkeypatch.setattr(module.os.path, "isdir", fake_isdir)
    monkeypatch.setattr(module.os, "listdir", fake_listdir)
    assert module.shares() == [
        ("good", "/volume1/good"),
        ("中文 空白", "/volume1/中文 空白"),
    ]


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

