# tests/integration/test_static_cache_headers.py
"""
契約測試：/static mount 的 Cache-Control: no-cache + ETag-based revalidation。

依 CLAUDE.md「Lint 守衛規則」：此為「mount ↔ response header API contract」→ pytest 正確，非 eslint 範疇。
"""


def test_static_css_has_no_cache(client):
    resp = client.get("/static/css/theme.css")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"
    assert "etag" in resp.headers  # ETag-based revalidation 仍在


