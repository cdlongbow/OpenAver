"""
寫於 tests/unit/test_scraper_validators.py
涵蓋 is_number_format, is_partial_number, is_prefix_only 的單元測試

注意：測試按照 TASK-139 委派 is_strict_number 行為撰寫：
- is_number_format: 委派 is_strict_number (先清除 -UC/-UNCEN 等後綴)
- is_partial_number: regex ``^([a-zA-Z]+)-?(\\d{1,2})$``
- is_prefix_only: regex ``^[A-Z]{2,6}$``
- 三者都沒有 null guard (.strip() on None raises AttributeError)
"""

import pytest

import core.scraper as scraper_mod
from core.scraper import (
    is_number_format,
    is_partial_number,
    is_prefix_only,
    search_jav,
)


class TestIsNumberFormat:
    def test_standard_format(self):
        assert is_number_format("ABP-001") is True
        assert is_number_format("SNIS-123") is True

    def test_mixed_case(self):
        assert is_number_format("abp-001") is True
        assert is_number_format("AbP-001") is True

    def test_no_dash(self):
        """Letters followed by 3+ digits without dash"""
        assert is_number_format("ABP001") is True

    def test_with_uc_suffix(self):
        """UC/UNCEN suffixes are stripped before matching"""
        assert is_number_format("SONE-103-UC") is True


    def test_too_few_digits(self):
        """Less than 3 digits rejected (belongs to is_partial_number)"""
        assert is_number_format("ABP-01") is False
        assert is_number_format("ABP-1") is False

    def test_positive_f3a_cases(self):
        """F3-a 正向：200GANA-3360, 529STCV-152, T28-103 經 is_number_format 為 True"""
        assert is_number_format("200GANA-3360") is True
        assert is_number_format("529STCV-152") is True
        assert is_number_format("T28-103") is True

    @pytest.mark.parametrize("val", [
        "三上悠亜",
        "https://evil.com/SONE-103"
    ])
    def test_negative_f3a_cases(self, val: str):
        """F3-a 反向鎖：關鍵字與路徑/網址等雜訊字串經 is_number_format 為 False"""
        assert is_number_format(val) is False


class TestIsPartialNumber:
    def test_valid_partial(self):
        assert is_partial_number("SNIS-1") is True
        assert is_partial_number("ABP12") is True  # no dash, 1-2 digits


class TestIsPrefixOnly:
    def test_valid_prefix(self):
        assert is_prefix_only("ABP") is True
        assert is_prefix_only("SNIS") is True
        assert is_prefix_only("ABCDEF") is True  # 6 chars = max


# ============ search_jav source routing (TASK-61a-3) ============

# Scraper classes patched in core.scraper that may get constructed by search_jav.
# Construction must be cheap & must NOT hit the network; we patch them with
# spies recording instantiation and stub .search() so nothing real runs.
_SCRAPER_ATTRS = [
    'DMMScraper', 'JavBusScraper', 'JAV321Scraper', 'JavDBScraper',
    'D2PassScraper', 'HEYZOScraper', 'FC2OfficialScraper', 'AVSOXScraper',
]

# id -> scraper class attr name in core.scraper
_ID_TO_ATTR = {
    'dmm': 'DMMScraper',
    'javbus': 'JavBusScraper',
    'jav321': 'JAV321Scraper',
    'javdb': 'JavDBScraper',
    'd2pass': 'D2PassScraper',
    'heyzo': 'HEYZOScraper',
    'fc2': 'FC2OfficialScraper',
    'avsox': 'AVSOXScraper',
}


def _install_scraper_spies(monkeypatch):
    """Replace each Scraper class on core.scraper with a spy.

    Returns a dict {attr_name: list_of_calls}. Each spy:
    - records its construction (args/kwargs ignored for the count),
    - returns an object whose .search() returns None (no result, no network).
    """
    constructed: dict[str, int] = {attr: 0 for attr in _SCRAPER_ATTRS}

    def make_spy(attr_name):
        def factory(*args, **kwargs):
            constructed[attr_name] += 1

            class _Stub:
                def search(self, number):
                    return None

            return _Stub()

        return factory

    for attr in _SCRAPER_ATTRS:
        monkeypatch.setattr(scraper_mod, attr, make_spy(attr))

    # normalize_number() was previously proxied through JavBusScraper(); now it calls
    # normalize_number_impl() directly. Stub to identity so scraper spies remain isolated.
    monkeypatch.setattr(scraper_mod, 'normalize_number', lambda n: n)

    return constructed


class TestValidateSourceIntegration:
    """validate_source_id wiring: known ids + 'auto' accepted; unknown -> None."""

    def test_unknown_source_returns_none_no_raise(self, monkeypatch):
        # Should not raise; should short-circuit to None before constructing scrapers.
        _install_scraper_spies(monkeypatch)
        result = search_jav("ABP-001", source="not-a-real-source")
        assert result is None


    def test_known_explicit_source_accepted(self, monkeypatch):
        # 'javbus' must pass validation and construct exactly JavBusScraper.
        constructed = _install_scraper_spies(monkeypatch)
        result = search_jav("ABP-001", source="javbus")
        assert result is None  # stub .search returns None
        assert constructed['JavBusScraper'] == 1
        # No other scrapers constructed for an explicit single source.
        for attr in _SCRAPER_ATTRS:
            if attr != 'JavBusScraper':
                assert constructed[attr] == 0


class TestAutoFanOutReadsEnabledIds:
    """auto path fans out over get_enabled_source_ids()."""

    def test_auto_only_constructs_enabled_subset(self, monkeypatch):
        constructed = _install_scraper_spies(monkeypatch)
        monkeypatch.setattr(
            scraper_mod, 'get_enabled_source_ids', lambda availability_map=None: ['javbus', 'javdb']
        )
        search_jav("ABP-001", source="auto")
        assert constructed['JavBusScraper'] == 1
        assert constructed['JavDBScraper'] == 1
        # Everything else (incl. DMM) must not be constructed.
        for attr in _SCRAPER_ATTRS:
            if attr not in ('JavBusScraper', 'JavDBScraper'):
                assert constructed[attr] == 0


class TestDmmBuiltRegardlessOfProxyField:
    """DMM 能不能被用只看膠囊（auto fan-out 的 enabled 清單），與 Proxy 欄無關（163a）。"""

    def test_search_jav_builds_dmm_regardless_of_proxy_field(self, monkeypatch):
        # explicit 指定 dmm：Proxy 欄空白（預設）也照建，不再被靜默略過。
        constructed = _install_scraper_spies(monkeypatch)
        search_jav("ABP-001", source="dmm")
        assert constructed['DMMScraper'] == 1

    def test_auto_dmm_in_enabled_list_constructed(self, monkeypatch):
        # 膠囊開（在 enabled 清單內）→ auto fan-out 建 DMM。
        constructed = _install_scraper_spies(monkeypatch)
        monkeypatch.setattr(
            scraper_mod, 'get_enabled_source_ids', lambda availability_map=None: ['dmm', 'javbus']
        )
        search_jav("ABP-001", source="auto")
        assert constructed['DMMScraper'] == 1
        assert constructed['JavBusScraper'] == 1


# ============ TASK-73a-T1: 入口 gate + search_jav 整合 ============


class TestTokyoHotSearchJavIntegration:
    """search_jav('n0762', source='javbus') 傳進 scraper 的番號必須是 N0762（不是 N-0762）"""

    def test_search_jav_n0762_passes_N0762_to_scraper(self, monkeypatch):
        """n0762 normalize 後以 N0762 傳入 scraper.search()"""
        received_numbers = []

        # Subclass the REAL JavBusScraper so the inherited (real) normalize_number
        # runs through the production module-level wrapper
        # (scraper.py → normalize_number_impl()); only .search() is
        # overridden to capture. No normalize_number patching → the full real
        # normalize path is exercised, not a stand-in wrapper.
        from core.scrapers import JavBusScraper as _RealJavBusScraper

        class _CapturingJavBusScraper(_RealJavBusScraper):
            def search(self, number):
                received_numbers.append(number)
                return None

        # Patch the USE-SITE binding in core.scraper (same pattern as existing tests).
        monkeypatch.setattr(scraper_mod, 'JavBusScraper', _CapturingJavBusScraper)

        search_jav('n0762', source='javbus')

        # scraper must have been called exactly once with N0762 (not N-0762)
        assert len(received_numbers) == 1, f"expected 1 call, got {received_numbers}"
        assert received_numbers[0] == 'N0762', (
            f"expected 'N0762' but scraper received {received_numbers[0]!r}"
        )
