"""頁面路由 TemplateResponse 渲染守衛（防 Starlette 簽名漂移 → 靜默 500）。

緣起：`web/routers/motion_lab.py` 沿用舊版兩參數 `TemplateResponse(name, context)`，
Starlette 1.0 移除該簽名後（改 `TemplateResponse(request, name, context)`），
`/motion-lab` 把 dict 當 template 名查 cache → `TypeError: unhashable type: 'dict'` → 500。
沙盒頁無人開、且既有測試只打 `/api/motion-lab/data`（JSON 端點）+ 自建 mini-app，
頁面渲染從未被測到。此守衛對「真實 web.app」每個頁面路由斷言 200，涵蓋所有
TemplateResponse 頁、擋住此類簽名漂移再次靜默回流。
"""
import pytest
from fastapi.testclient import TestClient


PAGE_ROUTES = [
    "/search",
    "/showcase",
    "/scanner",
    "/settings",
    "/help",
    "/design-system",
    "/motion-lab",
]


@pytest.fixture(scope="module")
def client():
    from web.app import app
    return TestClient(app)


@pytest.mark.parametrize("route", PAGE_ROUTES)
def test_page_route_renders_200(client, route):
    """每個頁面路由的 TemplateResponse 都能成功渲染（200），非簽名漂移 500"""
    resp = client.get(route)
    assert resp.status_code == 200, \
        f"{route} 回 {resp.status_code}（TemplateResponse 渲染失敗 / 簽名漂移？）"
    assert b"<html" in resp.content.lower() or b"<!doctype" in resp.content.lower(), \
        f"{route} 回 200 但非 HTML 文件"
