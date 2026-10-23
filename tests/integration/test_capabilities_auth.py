from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import core.access_auth as access_auth
from web.app import app

REMOTE_CLIENT = ("192.168.1.50", 12345)


@pytest.fixture(autouse=True)
def auth_db(tmp_path, monkeypatch):
    db_path = tmp_path / "access.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.reset_state_for_tests()
    yield db_path
    access_auth.reset_state_for_tests()


@pytest.fixture(autouse=True)
def server_mode_true(monkeypatch):
    """Card 原文漏了這條：REMOTE_CLIENT 必須先過外層 lan_access_gate。

    單機模式（server_mode=False）下非 loopback 會被 403 Forbidden 擋下，
    請求到不了 access_gate 的 Bearer 驗票。與 T2 gated_client / T3
    server_mode_true 同構。回報 §5 會標為與 card 的偏差。
    """
    monkeypatch.setattr(
        "web.app.load_config",
        lambda: {"general": {"server_mode": True}},
    )


def _iter_strings(obj):
    """走訪整份 JSON-like 結構（dict/list/str）的所有字串葉節點。"""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_strings(item)


def _enabled_capabilities_json() -> dict:
    """開認證 -> 帶合法 Bearer（agent 票）打 /api/capabilities -> 回傳 JSON body。

    用 REMOTE_CLIENT（非 loopback）而非預設 TestClient host：loopback 在
    access_gate 第 2 步會直接短路放行（不論有沒有帶 token），用它驗不出
    Bearer 真的在做事——這裡刻意逼真 middleware 第 8 步（cookie 或 bearer
    任一命中即通過）真的被走到。
    """
    access_auth.set_auth(True, "1234")
    token = access_auth.snapshot().agent_token
    client = TestClient(app, client=REMOTE_CLIENT)
    resp = client.get(
        "/api/capabilities", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    return resp.json()


class TestCapabilitiesAuthDisabledByteIdentical:

    def test_no_authorization_string_anywhere(self):
        client = TestClient(app)
        data = client.get("/api/capabilities").json()
        for s in _iter_strings(data):
            assert "Authorization" not in s, f"AC8 違反，回應含 'Authorization': {s!r}"


class TestCapabilitiesCurlAuthProperty:
    """性質測試——認證開啟時，任何以 "curl " 開頭的字串都必須含
    "Authorization: Bearer"。目的是抓「未來新增的第 40 支 tool 忘了帶
    header」，不需要逐條斷言每支 tool。
    """

    def test_all_curl_strings_have_auth_header(self):
        data = _enabled_capabilities_json()
        offenders = [
            s for s in _iter_strings(data)
            if s.startswith("curl ") and "Authorization: Bearer" not in s
        ]
        assert not offenders, (
            "以下字串以 'curl ' 開頭卻缺少 'Authorization: Bearer'（認證已開啟）：\n"
            + "\n".join(offenders)
        )


    def test_shell_compat_alternative_windows_has_auth_header(self):
        """盲區 1（CD-114b-8 明文列出）：PowerShell 語法不以 "curl " 開頭，
        上面的性質測試看不到這格，必須獨立斷言。"""
        data = _enabled_capabilities_json()
        ps = data["agent_instructions"]["shell_compat"]["alternative_windows"]
        assert '-Headers @{Authorization = "Bearer $OPENAVER_TOKEN"}' in ps

    def test_image_display_curl_step_has_auth_header(self):
        """盲區 2（TASK-114b-T5 驗證階段新發現，plan-114b.md CD-114b-8 原文
        只列了 PowerShell 那一格）：這一格字面值是 "2. curl -H \"...\" -o
        ..."，因為前面帶步驟編號 "2. "，不是以 "curl " 開頭 —— `_iter_strings`
        的 `.startswith("curl ")` 過濾器天然看不到它，必須跟
        alternative_windows 一樣單獨蓋一條。

        v0.14.6：改成**按內容找**而不是按 `steps[1]` 找。原本寫死索引，結果
        126 在前面插一格 metatube preview_* 的說明時，這支測試就紅了——而它
        要守的東西（curl 那格帶不帶 auth header）根本沒變。位置不是它的不變式。
        """
        data = _enabled_capabilities_json()
        steps = data["image_display"]["steps"]
        curl_steps = [s for s in steps if "curl " in s]
        assert len(curl_steps) == 1, (
            f"image_display.steps 裡的 curl 指令應恰好一條，實際 {len(curl_steps)} 條："
            f"{curl_steps}——找不到就代表這支測試什麼都沒驗到"
        )
        assert "Authorization: Bearer" in curl_steps[0]


class TestCapabilitiesNoRealTokenLeak:
    def test_response_never_contains_real_token(self):
        access_auth.set_auth(True, "1234")
        token = access_auth.snapshot().agent_token
        client = TestClient(app, client=REMOTE_CLIENT)
        resp = client.get(
            "/api/capabilities", headers={"Authorization": f"Bearer {token}"}
        )
        blob = json.dumps(resp.json(), ensure_ascii=False)
        assert "oav_" not in blob
        assert token not in blob


class TestCapabilitiesNetworkAuthEnabled:
    def test_network_auth_is_object_with_bearer_shape(self):
        data = _enabled_capabilities_json()
        auth = data["network"]["auth"]
        assert isinstance(auth, dict)
        assert auth["type"] == "bearer"
        assert auth["header"] == "Authorization: Bearer <token>"
        assert "/help" in auth["note"]
        assert "/api/health" in auth["note"]


class TestCapabilitiesTokenSetupInstruction:
    def test_token_setup_present_when_enabled(self):
        data = _enabled_capabilities_json()
        text = data["agent_instructions"]["token_setup"]
        assert 'export OPENAVER_TOKEN="<token>"' in text
        assert '$env:OPENAVER_TOKEN = "<token>"' in text
