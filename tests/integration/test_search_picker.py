"""63c-3: 進階 picker explicit dispatch — metatube 選定單源整包贏（US8）。

picker 前端元件不改（B1 已 data-driven）；本檔驗 validate + dispatch 閉合：
exact + source=metatube:FANZA → search_jav_single_source → explicit 分支整包贏。
另驗 get_common_context 注入 routable/available（bootstrap 資料來源）。
"""
import pytest

from core.metatube.state import metatube_state
from core.scrapers.models import Video


@pytest.fixture(autouse=True)
def _reset_metatube_state():
    """metatube_state 是 process-global singleton；每個 test 前後 disconnect。"""
    metatube_state.disconnect()
    yield
    metatube_state.disconnect()


def test_explicit_metatube_source_wins(client, temp_config_path, monkeypatch):
    """exact + source=metatube:FANZA + connected → shim 結果整包贏（source 正確）。"""
    metatube_state.connect("http://localhost:8080", "tok", ["FANZA"])
    fixture = Video(
        number="SSIS-001", title="T", source="metatube:FANZA",
        summary="plot text", rating=4.0,
    )
    monkeypatch.setattr("core.scraper._MetatubeShim.search", lambda self, number: fixture)

    resp = client.get(
        "/api/search",
        params={"mode": "exact", "source": "metatube:FANZA", "q": "SSIS-001"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["data"]) == 1
    item = body["data"][0]
    assert item["source"] == "metatube:FANZA"  # 整包贏（explicit 分支）
    # 147c-T1：internal carrier 保留；canonical 無底線 key 仍不出現
    assert item["_summary"] == "plot text"
    assert item["_rating"] == 4.0
    assert "summary" not in item
    assert "rating" not in item


def test_bootstrap_injects_routable_and_available(client, temp_config_path):
    """get_common_context 注入：builtin sources 帶 routable=true、available=true。"""
    html = client.get("/search").text
    assert '"routable": true' in html, "builtin source 應帶 routable=true（config.sources|tojson 自動帶出）"
    assert '"available": true' in html, "builtin source 應帶 available=true"


def test_bootstrap_injects_cf_sites_when_transport_reports_them(client, temp_config_path, monkeypatch):
    """118a-T9：有 transport 且回報 per-site 可用性 → bootstrap 含正確的 cf_sites。

    patch 在消費端會呼叫到的名字（BE-TEST-01）——web/app.py 的 get_common_context()
    是函式內 `from core.cf_transport import get_cf_available_sites as _get_cf_sites`
    （每次呼叫時才 import），所以呼叫當下解析到的一律是 core.cf_transport 模組屬性，
    patch target 是 core.cf_transport.get_cf_available_sites。
    """
    monkeypatch.setattr("core.cf_transport.get_cf_available_sites", lambda: ["javlibrary"])
    # 168d：SSR 窄化——要有殼才亮（?oa_shell=windows）且此請求的殼可用（cf_available_here）。
    monkeypatch.setattr("core.cf_transport.cf_available_here", lambda: True)
    html = client.get("/search?oa_shell=windows").text
    # [lint-guard: pytest-justified] 驗的是 get_common_context() → Jinja render 的跨層
    # 序列化結果，不是模板原始碼。static_guard_lint 讀得到模板裡有沒有寫 cf_sites，
    # 讀不到「transport 回報 ['javlibrary'] 時真的 render 出這個值」——要 render 才知道。
    # 模板側的靜態存在性另有 [118a-T9] required-string 規則守著，兩者不重複。
    assert 'cf_sites: ["javlibrary"]' in html, (
        "bootstrap 應含 cf_sites: [\"javlibrary\"]，實際未找到於 HTML 中"
    )


