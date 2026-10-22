"""
TestDMMProgressiveFacade — DMM progressive SSE facade 測試
（搬自 tests/integration/test_new_scrapers.py TestDMMProgressiveFacade）

3 non-duplicate tests（排除與 TestPipeline 重複的 2 個）
"""
import pytest
from unittest.mock import patch

from core.scrapers.dmm import DMMScraper, ListResult
from core.scrapers.models import Video

pytestmark = pytest.mark.usefixtures("no_entity_lookup", "no_dmm_facts")


# ============================================================
# Helper
# ============================================================


# ============================================================
# Tests
# ============================================================

@pytest.fixture(autouse=True)
def _dmm_capsule(monkeypatch):
    """DMM 開關看膠囊（BE-TEST-01 使用端 patch）：本檔案例都預期 DMM 被呼叫。"""
    monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: True)


class TestDMMProgressiveFacade:
    """DMM progressive SSE facade tests"""


    def test_dmm_progressive_results_order_matches_seed(self):
        """DMM progressive: 最終回傳順序必須與 seed slot 一致，不受 as_completed 亂序影響"""
        from core.scraper import search_actress

        mock_rows = [{"id": "sone00205", "title": "Test Title"}, {"id": "sone00300", "title": "Test Title"}]

        # _fetch_by_id returns enriched videos in predictable order
        enriched1 = Video(number="SONE-205", title="Title 1", source="dmm")
        enriched2 = Video(number="SONE-300", title="Title 2", source="dmm")

        with patch('core.scraper.get_all_source_ids_ordered', return_value=['dmm', 'javbus', 'jav321', 'javdb']), \
             patch.object(DMMScraper, 'list_contents', return_value=ListResult(mock_rows, None, False)), \
             patch.object(DMMScraper, '_fetch_by_id', side_effect=[enriched1, enriched2]), \
             patch('core.scrapers.dmm.rate_limit'):
            results = search_actress(
                "三上悠亜",
            )

        # Results order must match seed order (SONE-205 first, SONE-300 second)
        assert results[0]['number'] == "SONE-205"
        assert results[1]['number'] == "SONE-300"

