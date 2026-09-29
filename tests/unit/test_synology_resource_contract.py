"""Contract tests for Synology conf/resource and its integration with privilege and wizard."""

import json
from pathlib import Path

RESOURCE_PATH = Path(__file__).resolve().parents[2] / "synology/spk-src/conf/resource"
PRIVILEGE_PATH = Path(__file__).resolve().parents[2] / "synology/spk-src/conf/privilege"

WIZARD_KEY = "wizard_library_share"
EXPECTED_RW_USERS = ["openaver-svc"]


def _load_resource():
    return json.loads(RESOURCE_PATH.read_text(encoding="utf-8"))


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
