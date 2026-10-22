"""
test_scraper_smoke_pure_logic.py — 桶 D 純邏輯守衛（TASK-73e-T1）

搬自 tests/smoke/test_scrapers.py 的純離線測試（從不連網）。
不加 pytestmark = pytest.mark.smoke，CI 正常收錄。
"""
import pytest

from core.scrapers import (
    JavBusScraper, FC2JavtenScraper, FC2OfficialScraper,
)


# ============================================================
# FC2 番號正規化（5-case 版，保留純數字 case，源自 test_scrapers.py:144–150）
# ============================================================

class TestFC2NormalizePureLogic:
    """FC2 番號正規化——純字串邏輯，零連網"""

    @pytest.fixture
    def scraper(self):
        return FC2JavtenScraper()


class TestFC2OfficialNormalizePureLogic:
    """FC2OfficialScraper 番號正規化——與 javten 版等價（CD-118b-2）"""

    @pytest.fixture
    def scraper(self):
        return FC2OfficialScraper()

    def test_normalize_fc2_number(self, scraper):
        """測試：官方站版 FC2 番號正規化（5 case 含純數字輸入）"""
        assert scraper._normalize_fc2_number("FC2-PPV-1723984") == "1723984"
        assert scraper._normalize_fc2_number("FC2PPV1723984") == "1723984"
        assert scraper._normalize_fc2_number("FC2-1723984") == "1723984"
        assert scraper._normalize_fc2_number("fc2ppv-1723984") == "1723984"
        assert scraper._normalize_fc2_number("1723984") == "1723984"


# ============================================================
# JavBus 番號正規化（源自 test_scrapers.py:92–96）
# ============================================================

class TestJavBusNormalizePureLogic:
    """JavBus 番號正規化——純字串邏輯，零連網"""

    @pytest.fixture
    def scraper(self):
        return JavBusScraper()


# ============================================================
# 向後相容性——舊 API（源自 test_scrapers.py:196–205）
# 只搬 extract_number() 斷言（不連網段落）
# ============================================================


# ============================================================
# 多來源整合——介面與唯一性（源自 test_scrapers.py:231–266）
# ============================================================

