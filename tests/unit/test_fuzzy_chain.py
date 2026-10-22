"""
TestFuzzyChain — 模糊 fallback 鏈 unit tests (TASK-65c-1)

覆蓋 spec §4 US-3 驗收條件，13 個邊界條件全部。
Mock 策略：monkeypatch get_all_source_ids_ordered + patch.object on scraper classes.
"""
import pytest
from unittest.mock import patch, MagicMock, call

from core.scrapers.dmm import DMMScraper, ListResult
from core.scrapers.javbus import JavBusScraper
from core.scrapers.jav321 import JAV321Scraper
from core.scrapers.javdb import JavDBScraper
from core.scrapers.models import Video
pytestmark = pytest.mark.usefixtures("no_entity_lookup", "no_dmm_facts")


# ============================================================
# Helper
# ============================================================

def _make_video(source: str, number: str = "TEST-001") -> Video:
    return Video(
        number=number,
        title="Test Title",
        actresses=[],
        date="2024-01-01",
        maker="Test Maker",
        cover_url="",
        tags=[],
        source=source,
        detail_url="https://example.com",
    )


def _make_dict(source: str, number: str = "TEST-001") -> dict:
    return {"number": number, "title": "Test Title", "source": source}


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """跳過 rate_limit / time.sleep，加速測試"""
    monkeypatch.setattr("core.scrapers.dmm.rate_limit", lambda *a, **kw: None)
    monkeypatch.setattr("core.scraper.time.sleep", lambda *a: None)


@pytest.fixture(autouse=True)
def _dmm_capsule(monkeypatch):
    """DMM 開關看膠囊（BE-TEST-01：patch 使用端 core.scraper.is_source_enabled）。
    預設膠囊開；要測「膠囊關」的案例自己再 setattr 成 False。"""
    monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: True)


# ============================================================
# TestFuzzyChain — 13 boundary conditions
# ============================================================

class TestFuzzyChain:
    """模糊鏈邊界條件測試（spec §4 US-3 驗收條件 1-13）"""

    # ---- 1. 鏈順序跟 Active Row（非寫死） ----
    def test_chain_follows_active_row_order(self, monkeypatch):
        """mock order=['javbus','dmm']，javbus 空 → dmm 命中（TASK-65g: 2 源池）"""
        from core.scraper import search_actress

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['javbus', 'dmm'])

        with patch.object(JavBusScraper, 'get_ids_from_search', return_value=[]) as mock_jb, \
             patch.object(DMMScraper, 'list_contents',
                          return_value=ListResult([{'id': 'mide00100', 'title': 'Test Title'}], None, False)) as mock_dmm, \
             patch.object(DMMScraper, '_fetch_by_id', return_value=_make_video('dmm', 'MIDE-100')):
            results = search_actress("some actress")

        mock_jb.assert_called()          # javbus reached but returned empty
        mock_dmm.assert_called_once()    # dmm reached and hit
        assert len(results) == 1
        assert results[0]['source'] == 'dmm'  # order-driven: javbus empty → dmm hit

    # ---- 2. DMM 排第一但膠囊關 → 跳過，繼續到 javbus ----
    def test_dmm_first_capsule_off_falls_through_to_javbus(self, monkeypatch):
        """DMM 排第一 + DMM 膠囊關 → DMM 不呼叫，javbus 命中"""
        from core.scraper import search_actress

        monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: sid == 'javbus')

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['dmm', 'javbus', 'jav321', 'javdb'])

        with patch.object(DMMScraper, 'list_contents') as mock_dmm, \
             patch.object(JavBusScraper, 'get_ids_from_search',
                          return_value=['SONE-205']) as mock_jb, \
             patch('core.scraper.search_jav',
                   return_value=_make_dict("javbus", "SONE-205")):
            results = search_actress("三上悠亜")

        mock_dmm.assert_not_called()  # DMM bypassed — capsule off
        mock_jb.assert_called()
        assert len(results) >= 1
        assert results[0]['source'] == 'javbus'

    # ---- 3. AVSOX 排第一 → 跳過 ----
    def test_non_fuzzy_source_avsox_skipped(self, monkeypatch):
        """avsox 不在 search provider 註冊表 → 跳過，直達 javbus"""
        from core.scraper import search_actress
        from core.scrapers.avsox import AVSOXScraper

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['avsox', 'javbus', 'dmm', 'jav321', 'javdb'])

        # side_effect: first page returns ids, subsequent pages empty (stops pagination)
        with patch.object(AVSOXScraper, 'search', return_value=None) as mock_avsox, \
             patch.object(JavBusScraper, 'get_ids_from_search',
                          side_effect=[['TEST-001'], []]) as mock_jb, \
             patch('core.scraper.search_jav',
                   return_value=_make_dict("javbus", "TEST-001")):
            results = search_actress("actress")

        mock_avsox.assert_not_called()
        mock_jb.assert_called()
        assert len(results) >= 1
        assert results[0]['source'] == 'javbus'

    # ---- 4. 鏈的順序取自完整來源列表（啟用與否由 providers_for 另行過濾） ----
    def test_chain_order_reads_full_source_list(self, monkeypatch):
        """鏈的順序讀 get_all_source_ids_ordered 的完整列表，列表含 javbus 即能到達並命中"""
        from core.scraper import search_actress

        # get_all_source_ids_ordered 回完整列表（不依 enabled 過濾）
        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['javbus'])

        with patch.object(JavBusScraper, 'get_ids_from_search',
                          side_effect=[['SONE-111'], []]) as mock_jb, \
             patch('core.scraper.search_jav',
                   return_value=_make_dict("javbus", "SONE-111")):
            results = search_actress("actress")

        mock_jb.assert_called()
        assert len(results) >= 1

    # ---- 5. 非模糊源 / metatube 排最前 → 跳過 ----
    def test_metatube_and_fc2_skipped(self, monkeypatch):
        """metatube:abc 和 fc2 不在 search provider 註冊表 → 鏈從 javbus 開始"""
        from core.scraper import search_actress
        from core.scrapers.fc2_official import FC2OfficialScraper

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['metatube:abc', 'fc2', 'javbus', 'dmm'])

        with patch.object(FC2OfficialScraper, 'search', return_value=None) as mock_fc2, \
             patch.object(JavBusScraper, 'get_ids_from_search',
                          side_effect=[['FC2-TEST'], []]) as mock_jb, \
             patch('core.scraper.search_jav',
                   return_value=_make_dict("javbus", "FC2-TEST")):
            results = search_actress("actress")

        mock_fc2.assert_not_called()
        mock_jb.assert_called()
        assert len(results) >= 1
        assert results[0]['source'] == 'javbus'

    # ---- 6. 候選池 4 源排在一堆非模糊源之後 ----
    def test_fuzzy_sources_reached_after_non_fuzzy_sources(self, monkeypatch):
        """heyzo、d2pass、metatube:x 排前面，javbus 排後面 → 鏈最終到達 javbus"""
        from core.scraper import search_actress
        from core.scrapers.heyzo import HEYZOScraper
        from core.scrapers.d2pass import D2PassScraper

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['heyzo', 'd2pass', 'metatube:x', 'javbus', 'dmm'])

        with patch.object(HEYZOScraper, 'search', return_value=None), \
             patch.object(D2PassScraper, 'search', return_value=None), \
             patch.object(JavBusScraper, 'get_ids_from_search',
                          side_effect=[['SONE-001'], []]) as mock_jb, \
             patch('core.scraper.search_jav',
                   return_value=_make_dict("javbus", "SONE-001")):
            results = search_actress("actress")

        mock_jb.assert_called()
        assert len(results) >= 1

    # ---- 7. 空鏈（所有候選池源都被過濾掉）→ [] ----
    def test_empty_chain_returns_empty_list(self, monkeypatch):
        """get_all_source_ids_ordered 只回 heyzo、fc2 → chain=[] → 回 []"""
        from core.scraper import search_actress

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['heyzo', 'fc2'])

        results = search_actress("actress")
        assert results == []

    # ---- 8. seed 只由第一個實際發動源送 ----
    def test_seed_sent_exactly_once_by_first_dispatched_source(self, monkeypatch):
        """order=['dmm','javbus']，DMM 膠囊關（DMM 被跳過）→ seed 由 javbus 送，恰好 1 次"""
        from core.scraper import search_actress

        monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: sid == 'javbus')

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['dmm', 'javbus', 'jav321', 'javdb'])

        seed_calls = []

        def mock_result_callback(slot, data):
            if slot == -1:
                seed_calls.append(data)

        with patch.object(DMMScraper, 'list_contents') as mock_dmm, \
             patch.object(JavBusScraper, 'get_ids_from_search',
                          side_effect=[['SONE-205'], []]) as mock_jb, \
             patch('core.scraper.search_jav',
                   return_value=_make_dict("javbus", "SONE-205")):
            results = search_actress(
                "三上悠亜",
                result_callback=mock_result_callback,
            )

        mock_dmm.assert_not_called()
        assert len(seed_calls) == 1, f"Expected 1 seed, got {len(seed_calls)}"
        assert 'SONE-205' in seed_calls[0]

    # ---- 9. DMM None 視為空 → 繼續試下一個 ----
    def test_dmm_none_result_falls_through_to_javbus(self, monkeypatch):
        """DMM list_contents 回空 ListResult（progressive 回 None）→ adapter 轉 []
        → 鏈繼續，javbus 命中"""
        from core.scraper import search_actress

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['dmm', 'javbus', 'jav321', 'javdb'])

        with patch.object(DMMScraper, 'list_contents',
                          return_value=ListResult([], None, False)) as mock_dmm, \
             patch.object(JavBusScraper, 'get_ids_from_search',
                          side_effect=[['SONE-205'], []]) as mock_jb, \
             patch('core.scraper.search_jav',
                   return_value=_make_dict("javbus", "SONE-205")), \
             patch('core.scrapers.dmm.rate_limit'):
            results = search_actress("actress")

        mock_dmm.assert_called_once()  # DMM called but returned nothing
        mock_jb.assert_called()        # JavBus tried as next
        assert len(results) == 1

    # ---- 10. javdb 已註冊（175b-T4b）：在順序內且開關開 ⇒ 被問；開關關 ⇒ 不被問 ----
    def test_javdb_asked_when_enabled_and_not_asked_when_disabled(self, monkeypatch):
        """R27 翻轉：order=['javdb'] 且開關開 ⇒ JavDBProvider.run 被呼叫；開關關 ⇒ 0 次（patch 使用端，不連外）"""
        from unittest.mock import MagicMock

        from core.scraper import search_actress
        from core.search_providers.javdb import JavDBProvider

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: ['javdb'])
        run = MagicMock(return_value=[])
        monkeypatch.setattr(JavDBProvider, "run", run)
        monkeypatch.setattr(JavDBProvider, "resolve", lambda self, kind, name: None)

        monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: True)
        assert search_actress("actress") == []
        assert run.call_count == 1

        monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: False)
        assert search_actress("actress") == []
        assert run.call_count == 1  # 開關關了沒再被問

    # ---- 11. `_get_fuzzy_source` 已刪 ----
    def test_get_fuzzy_source_deleted(self):
        """_get_fuzzy_source 函式已從 core.scraper 移除 → ImportError / AttributeError"""
        import core.scraper
        assert not hasattr(core.scraper, '_get_fuzzy_source'), \
            "_get_fuzzy_source 應已刪除，但仍存在於 core.scraper"

    # ---- 12. `search_actress` 簽章不含 `primary_source` ----
    def test_search_actress_no_primary_source_param(self):
        """search_actress(primary_source='dmm') → TypeError"""
        from core.scraper import search_actress
        with pytest.raises(TypeError, match="primary_source"):
            search_actress("actress", primary_source="dmm")

    # ---- 13. discovery_only=True 路徑不回歸 ----
    def test_discovery_only_returns_stub_list(self, monkeypatch):
        """search_actress("abc", discovery_only=True) → [{'number':..., 'title':''}]"""
        from core.scraper import search_actress

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['javbus', 'dmm', 'jav321', 'javdb'])

        with patch.object(JavBusScraper, 'get_ids_from_search',
                          side_effect=[['TEST-001'], []]):
            results = search_actress("abc", discovery_only=True)

        assert len(results) == 1
        assert results[0] == {'number': 'TEST-001', 'title': ''}

    # ---- 14. 迴歸：DMM 排第一 + proxy + discovery_only=True → DMM 不呼叫，回 javbus stubs ----
    def test_dmm_first_discovery_only_skips_dmm(self, monkeypatch):
        """Regression: DMM first in Active Row + discovery_only=True
        → DMMScraper.list_contents must NOT be called;
        result must be javbus stub list [{'number': ..., 'title': ''}]."""
        from core.scraper import search_actress

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['dmm', 'javbus', 'jav321', 'javdb'])

        with patch.object(DMMScraper, 'list_contents') as mock_dmm, \
             patch.object(JavBusScraper, 'get_ids_from_search',
                          side_effect=[['SONE-999'], []]):
            results = search_actress(
                "三上悠亜",
                discovery_only=True,
            )

        # DMM keyword search must NOT be called in discovery_only mode
        mock_dmm.assert_not_called()
        assert len(results) == 1
        assert results[0] == {'number': 'SONE-999', 'title': ''}, \
            f"Expected javbus stub, got {results[0]}"

    # ---- 15. discovery_only=True, javbus 排第一 → stubs 回傳，無 enrichment ----
    def test_discovery_only_javbus_first_returns_stubs_no_enrichment(self, monkeypatch):
        """Companion: discovery_only=True with javbus first → javbus stubs returned,
        no ThreadPool enrichment (search_jav not called)."""
        from core.scraper import search_actress

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['javbus', 'dmm', 'jav321', 'javdb'])

        search_jav_calls = []

        def fake_search_jav(num, source='javbus'):
            search_jav_calls.append(num)
            return {'number': num, 'title': f'Title {num}'}

        with patch.object(JavBusScraper, 'get_ids_from_search',
                          side_effect=[['ABC-001', 'ABC-002'], []]), \
             patch('core.scraper.search_jav', side_effect=fake_search_jav):
            results = search_actress("actress", discovery_only=True)

        assert search_jav_calls == [], \
            f"search_jav must not be called in discovery_only mode, got {search_jav_calls}"
        assert len(results) == 2
        for r in results:
            assert r['title'] == '', f"Expected empty title stub, got title={r['title']!r}"


# ============================================================
# Regression: smart_search fuzzy else-branch — no post-chain jav321 fallback (CD-plan-65-5)
# ============================================================

class TestSmartSearchFuzzyNoPostChainFallback:
    """Regression tests for Codex finding: smart_search fuzzy else-branch must NOT
    call search_jav321_keyword after the chain is exhausted (CD-plan-65-5).

    The Active Row order is the single source of truth.  A hardcoded jav321
    fallback after search_actress（relay）returns [] would:
      (a) bypass Active Row ordering entirely, and
      (b) call jav321 a second time if it was already in the chain.
    """

    # ---- 16. No fuzzy candidates → smart_search returns [] (no order bypass) ----
    def test_smart_search_no_fuzzy_candidates_returns_empty(self, monkeypatch):
        """Codex regression: get_all_source_ids_ordered=['heyzo','fc2'] (no fuzzy
        candidates) + non-number keyword → smart_search returns [] and
        JAV321Scraper.search_by_keyword is NEVER called."""
        from core.scraper import smart_search
        from core.scrapers.jav321 import JAV321Scraper

        monkeypatch.setattr(
            "core.scraper.get_all_source_ids_ordered",
            lambda: ['heyzo', 'fc2'],
        )

        with patch.object(JAV321Scraper, 'search_by_keyword', return_value=[_make_video('jav321')]) as mock_jav321:
            results = smart_search("蒼井そら", limit=5)

        # JAV321Scraper.search_by_keyword must NOT be called when jav321 is not in the Active Row
        mock_jav321.assert_not_called()
        assert results == [], \
            f"Expected [] when chain has no fuzzy candidates, got {results}"

    # ---- 17. jav321 removed from fuzzy pool → never called via chain ----
    def test_jav321_removed_from_fuzzy_pool_not_called(self, monkeypatch):
        """jav321 is NOT in search provider 註冊表 (TASK-65g) → order=['javbus'],
        javbus empty → chain exhausted → search_jav321_keyword call_count == 0."""
        from core.scraper import smart_search

        monkeypatch.setattr(
            "core.scraper.get_all_source_ids_ordered",
            lambda: ['javbus'],
        )

        call_count = []

        def fake_jav321_search(query, limit=20, status_callback=None):
            call_count.append(1)
            return []

        with patch('core.scraper.search_jav321_keyword', side_effect=fake_jav321_search), \
             patch.object(JavBusScraper, 'get_ids_from_search', return_value=[]):
            results = smart_search("some keyword query", limit=5)

        assert len(call_count) == 0, \
            f"search_jav321_keyword must NOT be called via fuzzy chain (jav321 removed from pool), got {len(call_count)} calls"
        assert results == [], \
            f"Expected [] when chain exhausted, got {results}"


# ============================================================
# 175b-T5b — smart_search prefix 分支：三家全關＝查無、jav321 退路看自己的開關
# ============================================================

_ALL_IDS = ['dmm', 'javbus', 'javdb', 'jav321']


def _run_smart(query, enabled, *, jav321_results=(), javbus_ids=()):
    """從 smart_search 入口跑；回 (results, jav321 mock, javbus get_ids_from_search mock)。
    開關 patch 使用端 core.scraper.is_source_enabled（BE-TEST-01/02）；jav321 計數 patch 使用端。"""
    from core.scraper import smart_search

    with patch("core.scraper.get_all_source_ids_ordered", lambda: list(_ALL_IDS)), \
         patch("core.scraper.is_source_enabled", lambda sid: sid in enabled), \
         patch("core.scraper.search_jav321_keyword",
               return_value=list(jav321_results)) as jav321, \
         patch.object(JavBusScraper, "get_ids_from_search",
                      return_value=list(javbus_ids)) as javbus:
        results = smart_search(query, limit=5)
    return results, jav321, javbus


class TestSmartSearchPrefixSwitches:

    def test_prefix_all_sources_off_returns_empty_without_jav321(self):
        """(7a) 三家全關＋jav321 開 → [] 且 jav321 / JavBus 都 0 次。"""
        results, jav321, javbus = _run_smart("MIDV", {"jav321"},
                                             jav321_results=[_make_dict("jav321", "MIDV-001")])
        assert results == []
        assert jav321.call_count == 0
        assert javbus.call_count == 0

    def test_prefix_retreat_skips_jav321_when_its_switch_is_off(self):
        """(7b) JavBus 開（兩鏈皆空）＋jav321 關 → [] 且 jav321 0 次。"""
        results, jav321, _ = _run_smart("MIDV", {"javbus"},
                                        jav321_results=[_make_dict("jav321", "MIDV-001")])
        assert results == []
        assert jav321.call_count == 0

    def test_prefix_retreat_reaches_jav321_when_its_switch_is_on(self):
        """(7c) JavBus 開（兩鏈皆空）＋jav321 開 → 退路照今天：jav321 問 1 次、_mode=keyword。"""
        results, jav321, _ = _run_smart("MIDV", {"javbus", "jav321"},
                                        jav321_results=[_make_dict("jav321", "MIDV-001")])
        assert jav321.call_count == 1
        assert len(results) == 1
        assert results[0]["_mode"] == "keyword"

    def test_prefix_with_only_dmm_on_still_reaches_actress_retreat(self):
        """只開 DMM：前綴鏈（CODE）無人可問，但 DMM 的 KEYWORD 要接得住 actress 退路。"""
        video = _make_video("dmm", "MIDV-001")
        with patch.object(DMMScraper, "list_contents",
                          lambda self, *a, **kw: ListResult([{"id": "midv00001", "title": "Test Title"}], None, False)), \
             patch.object(DMMScraper, "_fetch_by_id", lambda self, cid: video):
            results, jav321, javbus = _run_smart("MIDV", {"dmm"})
        assert len(results) == 1
        assert results[0]["_mode"] == "actress"
        assert jav321.call_count == 0
        assert javbus.call_count == 0

    @pytest.mark.parametrize("query", ["MIDV", "SONE-0", "蒼井そら"])
    def test_all_sources_off_returns_empty_not_raise(self, query):
        """(3) 三家全關（含 jav321 關）：prefix／partial／actress 三種查詢都回 [] 且不拋。"""
        results, jav321, javbus = _run_smart(query, set())
        assert results == []
        assert jav321.call_count == 0
        assert javbus.call_count == 0


# ============================================================
# TestFuzzyDmmSource — DMM _source 一致性（TASK-65g）
# ============================================================

class TestFuzzyDmmSource:
    """DMM 模糊結果攜帶 _source='dmm'（TASK-65g）"""

    def test_dmm_fuzzy_result_carries_internal_source(self, monkeypatch):
        """DMM 命中時，每個結果 dict 應含 _source='dmm'（鏡像 javbus 在 search_jav L354 的行為）"""
        from core.scraper import search_actress

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered",
                            lambda: ['dmm', 'javbus'])

        # DMM returns 1 result (no _source yet — DMMProvider.run must add it)
        video = _make_video('dmm', 'STARS-001')
        monkeypatch.setattr(DMMScraper, 'list_contents',
                            lambda self, *a, **kw: ListResult([{'id': 'stars00001', 'title': 'Test Title'}], None, False))
        monkeypatch.setattr(DMMScraper, '_fetch_by_id', lambda self, cid: video)

        # 膠囊開（autouse fixture）所以 DMM 閘放行
        results = search_actress("actress")

        assert len(results) == 1, f"Expected 1 result, got {results}"
        assert results[0]['_source'] == 'dmm', \
            f"Expected _source='dmm', got {results[0].get('_source')!r}"


# ============================================================
# TestMakerLatestPipeline — 173-T5 ids_provider ＋ search_maker_latest
# ============================================================

_MK_REF = ('censored', '7q')
_MK_TODAY = '2026-10-21'


def _mk_found():
    from core.maker_latest import Resolution
    return Resolution('found', 'censored', '7q')


def _mk_nums(n, start=1):
    return [f'MKR-{i:03d}' for i in range(start, start + n)]


def _mk_detail(missing=(), dates=None):
    """search_jav 替身：missing 內的番號查不到；dates 指定發行日。"""
    def fake(num, source=None, *a, **kw):
        if num in missing:
            return None
        d = {'number': num, 'title': f't-{num}', 'source': 'javbus'}
        if dates:
            d['date'] = dates[num]
        return d
    return fake


def _mk_call(offset=0, cursor=None):
    from core.scraper import search_maker_latest
    return search_maker_latest(
        'mk', '片商', ['片商'], offset,
        titles=[], today=_MK_TODAY,
        status_callback=None, result_callback=None, db_path=None, cursor=cursor,
    )


def _mk_token(provider_id='javbus'):
    """載入更多帶的續頁 token（k=maker；175d）。"""
    from core.search_providers import cursor as cursor_codec
    return cursor_codec.encode(cursor_codec.Token(provider_id, 'maker'))


def _run_maker(offset=0, studio_side_effect=None, detail=None, resolution=None):
    with patch('core.scraper.resolve_maker_studio',
               return_value=resolution or _mk_found()) as res, \
         patch.object(JavBusScraper, 'get_ids_from_studio',
                      side_effect=studio_side_effect) as st, \
         patch('core.scraper.search_jav', side_effect=detail or _mk_detail()) as sj:
        out = _mk_call(offset, cursor=_mk_token() if offset > 0 else None)
    return out, res, st, sj


class TestMakerLatestPipeline:

    def test_failed_detail_does_not_clear_has_more(self):
        nums = _mk_nums(30)
        out, _, st, _ = _run_maker(
            studio_side_effect=lambda ref, page: nums if page == 1 else [],
            detail=_mk_detail(missing={nums[7]}),
        )
        assert len(out.results) == 29
        assert out.has_more is True
        assert out.error_code is None
        assert nums[7] not in [r['number'] for r in out.results]
        assert st.call_count == 1

    def test_last_page_requests_only_the_requested_page(self):
        nums = _mk_nums(12)

        def studio(ref, page):
            if page == 2:
                return nums
            raise TimeoutError('page 3 must not be requested')

        out, _, st, _ = _run_maker(offset=30, studio_side_effect=studio)
        assert len(out.results) == 12
        assert out.has_more is False
        assert out.error_code is None
        assert st.call_count == 1
        assert st.call_args_list[0] == call(_MK_REF, 2)

    def test_last_page_session_layer_single_list_request(self):
        fake_session = MagicMock()
        fake_session.get.return_value = MagicMock(status_code=200, text='x')
        nums = _mk_nums(12)
        with patch.object(JavBusScraper, '_new_session', return_value=fake_session), \
             patch.object(JavBusScraper, '_has_waterfall', return_value=True), \
             patch.object(JavBusScraper, '_parse_search_ids', return_value=nums), \
             patch('core.scraper.resolve_maker_studio', return_value=_mk_found()), \
             patch('core.scraper.search_jav', side_effect=_mk_detail()):
            out = _mk_call(30, cursor=_mk_token())
        list_gets = [c for c in fake_session.get.call_args_list if '/studio/' in str(c.args[0])]
        assert len(list_gets) == 1
        assert list_gets[0].args[0].endswith('/studio/7q/2')
        assert len(out.results) == 12
        assert out.has_more is False

    def test_maker_path_orders_results_like_keyword_path(self, monkeypatch):
        from core.scraper import _javbus_keyword_search
        monkeypatch.setattr('core.scraper.MAX_WORKERS', 1)
        nums = ['MKR-001', 'MKR-002', 'MKR-003', 'MKR-004']
        dates = {'MKR-001': '2024-03-01', 'MKR-002': '2025-06-01',
                 'MKR-003': '2023-01-01', 'MKR-004': '2025-12-01'}
        out, _, _, _ = _run_maker(
            studio_side_effect=lambda ref, page: nums if page == 1 else [],
            detail=_mk_detail(dates=dates),
        )
        maker_order = [r['number'] for r in out.results]
        with patch.object(JavBusScraper, 'get_ids_from_search',
                          side_effect=lambda name, page=1: nums if page == 1 else []), \
             patch('core.scraper.search_jav', side_effect=_mk_detail(dates=dates)):
            kw = _javbus_keyword_search('x', 30, 0, None, None)
        assert maker_order == [r['number'] for r in kw]
        assert maker_order == ['MKR-004', 'MKR-002', 'MKR-001', 'MKR-003']

    def test_default_path_still_calls_get_ids_from_search_with_name_page(self):
        from core.scraper import _javbus_keyword_search
        with patch.object(JavBusScraper, 'get_ids_from_search',
                          side_effect=lambda name, page=1: []) as gi:
            _javbus_keyword_search('abc', 30, 0, None, None)
        assert gi.call_args_list == [call('abc', page=1)]
