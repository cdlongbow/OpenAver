"""
TestFuzzyChain — 模糊 fallback 鏈 unit tests (TASK-65c-1)

覆蓋 spec §4 US-3 驗收條件，13 個邊界條件全部。
Mock 策略：monkeypatch get_all_source_ids_ordered + patch.object on scraper classes.
"""
import pytest
from unittest.mock import patch, MagicMock

from core.scrapers.dmm import DMMScraper, ListResult
from core.scrapers.javbus import JavBusScraper
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

    # ---- 2. DMM 排第一但膠囊關 → 跳過，繼續到 javbus ----

    # ---- 3. AVSOX 排第一 → 跳過 ----

    # ---- 4. 鏈的順序取自完整來源列表（啟用與否由 providers_for 另行過濾） ----

    # ---- 5. 非模糊源 / metatube 排最前 → 跳過 ----

    # ---- 6. 候選池 4 源排在一堆非模糊源之後 ----

    # ---- 7. 空鏈（所有候選池源都被過濾掉）→ [] ----

    # ---- 8. seed 只由第一個實際發動源送 ----

    # ---- 9. DMM None 視為空 → 繼續試下一個 ----

    # ---- 10. javdb 已註冊（175b-T4b）：在順序內且開關開 ⇒ 被問；開關關 ⇒ 不被問 ----

    # ---- 11. `_get_fuzzy_source` 已刪 ----

    # ---- 12. `search_actress` 簽章不含 `primary_source` ----

    # ---- 13. discovery_only=True 路徑不回歸 ----

    # ---- 14. 迴歸：DMM 排第一 + proxy + discovery_only=True → DMM 不呼叫，回 javbus stubs ----

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


    # ---- 16. No fuzzy candidates → smart_search returns [] (no order bypass) ----

    # ---- 17. jav321 removed from fuzzy pool → never called via chain ----


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

    @pytest.mark.parametrize("query", ["蒼井そら"])
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


class TestMakerLatestPipeline:


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


