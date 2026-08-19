"""TASK-121a-T5: GET /api/cover-badges/manifest 端點契約。

策略：TDD-lite。消費 core.cover_attributes.manifest_payload()，證明端點
沒有自己再硬編一份短名表。
"""

from core.cover_attributes import manifest_payload

MANIFEST_PATH = "/api/cover-badges/manifest"
EXPECTED_KEYS = {
    "id",
    "canonical_tag",
    "display_name",
    "match_aliases",
    "display_order",
    "i18n_key",
}
EXPECTED_IDS = {"subtitle", "cracked", "leaked", "4k", "vr"}
EXPECTED_DISPLAY_ORDER = {
    "subtitle": 1,  # 中字
    "cracked": 2,  # AI
    "leaked": 2,  # LEAK
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

    def test_each_item_has_exactly_six_fields_no_tokens_no_source(self, client):
        """邊界 2：每筆恰六欄，不含 tokens / source。"""
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
        """邊界 4：display_order 中字=1、AI=2、LEAK=2、VR=3、4K=4。"""
        data = client.get(MANIFEST_PATH).json()
        orders = {item["id"]: item["display_order"] for item in data}
        assert orders == EXPECTED_DISPLAY_ORDER

    def test_response_equals_manifest_payload(self, client):
        """邊界 5：端點回傳與 core.cover_attributes.manifest_payload() 逐筆相等。"""
        data = client.get(MANIFEST_PATH).json()
        assert data == manifest_payload()

    def test_display_name_and_match_aliases_literal_contract(self, client):
        """邊界 5b（BE-TEST-01）：寫死字面，對兩邊同時改錯仍敏感。"""
        data = client.get(MANIFEST_PATH).json()
        by_id = {item["id"]: item for item in data}
        assert by_id["cracked"]["display_name"] == "AI"
        assert by_id["leaked"]["display_name"] == "LEAK"
        assert "克破" in by_id["cracked"]["match_aliases"]
        assert by_id["subtitle"]["display_name"] == "中字"
        assert by_id["4k"]["display_name"] == "4K"
        assert by_id["vr"]["display_name"] == "VR"
        for item in data:
            assert item["match_aliases"][0] == item["canonical_tag"]
            assert isinstance(item["match_aliases"], list)

    def test_existing_routes_remain_mounted(self, client):
        """邊界 6：掛載 cover-badges 後既有路由仍在 OpenAPI。"""
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/tag-aliases" in paths
        assert "/api/cover-badges/manifest" in paths
