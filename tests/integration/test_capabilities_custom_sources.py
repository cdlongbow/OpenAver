"""TASK-165-T6: capabilities 揭露四個自訂來源工具＋三個既有工具 source 描述補 custom:<id> 句。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.access_auth as access_auth


@pytest.fixture(autouse=True)
def auth_db(tmp_path, monkeypatch):
    """GET /api/capabilities 冷啟動會呼叫 load_snapshot()，未 mock 前連上 output/openaver.db。"""
    db_path = tmp_path / "access.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.reset_state_for_tests()
    yield db_path
    access_auth.reset_state_for_tests()


@pytest.fixture
def client():
    from web.app import app
    return TestClient(app)


def _tool(data: dict, name: str) -> dict:
    return next(t for t in data["tools"] if t["name"] == name)


def _collect_enums(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "enum" and isinstance(v, list):
                out.append(v)
            _collect_enums(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_enums(v, out)
    return out


@pytest.mark.parametrize(
    "name,method,path,side_effect,confirm",
    [
        ("custom_source_upload", "POST", "/api/custom-sources", True, True),
        ("custom_sources_list", "GET", "/api/custom-sources", False, False),
        ("custom_source_remove", "DELETE", "/api/custom-sources/{id}", True, True),
    ],
)
def test_custom_source_tool_flags(client, name, method, path, side_effect, confirm):
    t = _tool(client.get("/api/capabilities").json(), name)
    assert t["method"] == method
    assert t["path"] == path
    assert t["side_effect"] is side_effect
    if confirm:
        assert t["confirmation_required"] is True
    else:
        assert t.get("confirmation_required") is not True
    assert t["example"].startswith("curl ")


def test_custom_sources_paths_exactly_four_and_no_enable_applicable(client):
    tools = client.get("/api/capabilities").json()["tools"]
    cs = sorted((t["method"], t["path"]) for t in tools if "custom-sources" in t["path"])
    assert cs == sorted([
        ("POST", "/api/custom-sources"),
        ("POST", "/api/custom-sources/{id}/verify"),
        ("GET", "/api/custom-sources"),
        ("DELETE", "/api/custom-sources/{id}"),
    ])
    assert all("/enabled" not in t["path"] and "/applicable" not in t["path"] for t in tools)
    assert all("enabled" not in t["name"] and "applicable" not in t["name"] for t in tools)


