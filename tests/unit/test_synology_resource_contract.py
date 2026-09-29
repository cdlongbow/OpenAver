"""Contract tests for Synology conf/resource and its integration with privilege and wizard."""

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path

RESOURCE_PATH = Path(__file__).resolve().parents[2] / "synology/spk-src/conf/resource"
PRIVILEGE_PATH = Path(__file__).resolve().parents[2] / "synology/spk-src/conf/privilege"
WIZARD_PATH = Path(__file__).resolve().parents[2] / "synology/spk-src/WIZARD_UIFILES/install_uifile.sh"

WIZARD_KEY = "wizard_library_share"
EXPECTED_RW_USERS = ["openaver-svc"]


def _load_resource():
    return json.loads(RESOURCE_PATH.read_text(encoding="utf-8"))


def _load_wizard():
    spec = importlib.util.spec_from_file_location(
        "install_uifile_resource_contract", WIZARD_PATH,
        loader=SourceFileLoader("install_uifile_resource_contract", str(WIZARD_PATH)),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wizard_combobox_key_is_wizard_key():
    items = _load_wizard().build_items([], False)
    assert [s["key"] for it in items if it.get("type") == "combobox" for s in it["subitems"]] == [WIZARD_KEY]


def test_resource_is_valid_json_with_single_share():
    data = _load_resource()
    shares = data.get("data-share", {}).get("shares")
    assert isinstance(shares, list), f"Expected 'data-share.shares' to be a list, got {type(shares)}"
    assert len(shares) == 1, f"Expected exactly 1 share entry, got {len(shares)}"


def test_resource_placeholder_key_is_wizard_key():
    data = _load_resource()
    shares = data.get("data-share", {}).get("shares", [])
    assert len(shares) == 1, "Expected single share entry"
    share = shares[0]
    expected_placeholder = f"{{{{{WIZARD_KEY}}}}}"
    assert share.get("name") == expected_placeholder


def test_resource_rw_matches_privilege_username():
    data = _load_resource()
    shares = data.get("data-share", {}).get("shares", [])
    assert len(shares) == 1, "Expected single share entry"
    rw_users = shares[0].get("permission", {}).get("rw")
    assert rw_users == EXPECTED_RW_USERS

    privilege_data = json.loads(PRIVILEGE_PATH.read_text(encoding="utf-8"))
    assert rw_users == [privilege_data.get("username")]
