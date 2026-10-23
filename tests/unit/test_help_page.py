"""
TDD-lite 測試 — help_page() context 注入 base_url
Phase 38b T3b / BUG2 修正
"""
import pytest
from fastapi.testclient import TestClient


def _make_client():
    from web.app import app
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _isolate_access_auth_db(tmp_path, monkeypatch):
    """GET /help 會經過 access_gate middleware，其冷啟動
    `await asyncio.to_thread(ensure_schema)`（web/app.py:327）未 mock 前連上
    output/openaver.db。三支測試皆各自新建 TestClient，但 core.access_auth._snapshot
    是 module-level 全域快取，跨測試持續存在——只 mock 第一支會讓後兩支被
    「已經 warm」意外遮蔽，故此處用檔案層級 autouse fixture 逐支重置
    （同手法見 tests/integration/test_capabilities_auth.py 的 auth_db fixture／
    127b-T4 已修正的 test_capabilities.py）。"""
    import core.access_auth as access_auth

    monkeypatch.setattr("core.access_auth.get_db_path", lambda: tmp_path / "access.db")
    access_auth.ensure_schema()
    access_auth.reset_state_for_tests()
    yield
    access_auth.reset_state_for_tests()


class TestHelpPageContext:
    """help_page() 必須注入 base_url 到 template context"""


    def test_help_page_base_url_from_request(self):
        """base_url 來自 request，TestClient 預設為 http://testserver"""
        client = _make_client()
        response = client.get("/help")
        assert response.status_code == 200
        html = response.text
        # TestClient 的 base_url 是 http://testserver
        assert "http://testserver/api/capabilities" in html, \
            "base_url 應從 request.base_url 取得並渲染到 curl 指令中"

