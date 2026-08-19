"""TASK-121a-T5: GET /api/cover-badges/manifest 端點契約。

策略：TDD-lite。消費 core.cover_attributes.manifest_payload()，證明端點
沒有自己再硬編一份短名表。
"""

from core.cover_attributes import manifest_payload

MANIFEST_PATH = "/api/cover-badges/manifest"
EXPECTED_KEYS = {"id", "canonical_tag", "short_name", "display_order", "i18n_key"}
EXPECTED_IDS = {"subtitle", "cracked", "leaked", "4k", "vr"}
EXPECTED_DISPLAY_ORDER = {
    "subtitle": 1,  # 中字
    "cracked": 2,  # 破解
    "leaked": 2,  # 流出
    "vr": 3,  # VR
    "4k": 4,  # 4K
}


class TestCoverBadgesManifest:
    """GET /api/cover-badges/manifest"""

    def test_returns_200_with_five_items(self, client):
        """邊界 1：200，回傳 5 筆。"""
        resp = client.get(MANIFEST_PATH)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 5

    def test_each_item_has_exactly_five_fields_no_tokens_no_source(self, client):
        """邊界 2：每筆恰五欄，不含 tokens / source。"""
        data = client.get(MANIFEST_PATH).json()
        for item in data:
            assert set(item.keys()) == EXPECTED_KEYS
            assert "tokens" not in item
            assert "source" not in item

    def test_id_set_is_exactly_the_five_rules(self, client):
        """邊界 3：id 集合恰為 {subtitle, cracked, leaked, 4k, vr}。"""
        data = client.get(MANIFEST_PATH).json()
        assert {item["id"] for item in data} == EXPECTED_IDS

    def test_display_order_matches_t1_table(self, client):
        """邊界 4：display_order 中字=1、破解=2、流出=2、VR=3、4K=4。"""
        data = client.get(MANIFEST_PATH).json()
        orders = {item["id"]: item["display_order"] for item in data}
        assert orders == EXPECTED_DISPLAY_ORDER

    def test_response_equals_manifest_payload(self, client):
        """邊界 5：端點回傳與 core.cover_attributes.manifest_payload() 逐筆相等。"""
        data = client.get(MANIFEST_PATH).json()
        assert data == manifest_payload()

    def test_existing_routes_remain_mounted(self, client):
        """邊界 6：掛載 cover-badges 後既有路由仍在 OpenAPI。"""
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/tag-aliases" in paths
        assert "/api/cover-badges/manifest" in paths
