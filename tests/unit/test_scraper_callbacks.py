"""
test_scraper_callbacks.py - result_callback 參數行為單元測試

測試範圍：
- result_callback slot index 正確性
- seed event 時機（found:N 後送出）
- 空 target_ids 守衛（不呼叫 result_callback(-1, [])）
- 向後相容性（result_callback=None 不改變行為）
"""

import pytest
from unittest.mock import patch, MagicMock, call
from concurrent.futures import ThreadPoolExecutor
pytestmark = pytest.mark.usefixtures("no_entity_lookup", "no_dmm_facts")


@pytest.fixture(autouse=True)
def _dmm_capsule_off(monkeypatch):
    """預設只開 JavBus、DMM 膠囊關：這份檔的案例走 JavBus 路徑，不要依賴本機 config（BE-TEST-01 使用端 patch）。
    175b：JavBus 也跟開關走，所以要明確開它。"""
    monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: sid == "javbus")


@pytest.fixture(autouse=True)
def _no_request_delay(monkeypatch):
    """本檔把 REQUEST_DELAY 歸零（只影響本檔）：外站呼叫都已 mock，節流秒數
    沒有驗證對象，不歸零只是白等。"""
    monkeypatch.setattr("core.scraper.REQUEST_DELAY", 0)


# ============ Fixtures ============

def make_mock_scraper_prefix(ids):
    """Mock JavBusScraper for prefix search.
    Returns ids on the first call, then [] on subsequent calls (simulates single page).
    """
    mock_scraper = MagicMock()
    mock_scraper.get_ids_from_search.side_effect = [ids, []]
    return mock_scraper


def make_mock_scraper_actress(ids_per_page):
    """Mock JavBusScraper for actress search (multi-page).
    ids_per_page: list of list[str] — each inner list is one page of IDs.
    For single page, pass [ids].
    """
    mock_scraper = MagicMock()
    # side_effect 讓每次呼叫回傳下一頁，用完後回傳 []
    mock_scraper.get_ids_from_search.side_effect = list(ids_per_page) + [[]]
    return mock_scraper


# ============ search_prefix result_callback 測試 ============

class TestSearchPrefixResultCallback:
    """測試 search_prefix() 的 result_callback 行為"""


    def test_slot_index_matches_target_ids_order(self, make_mock_search_jav):
        """result-item slot index 必須對應 target_ids 的原始 index"""
        from core.scraper import search_prefix

        ids = ['SONE-100', 'SONE-101', 'SONE-102']
        results_map = {
            'SONE-100': {'number': 'SONE-100', 'title': 'Title 100'},
            'SONE-101': {'number': 'SONE-101', 'title': 'Title 101'},
            'SONE-102': {'number': 'SONE-102', 'title': 'Title 102'},
        }

        mock_scraper = make_mock_scraper_prefix(ids)
        callback_calls = []

        def result_callback(slot, data):
            callback_calls.append((slot, data))

        with patch('core.scraper.JavBusScraper', return_value=mock_scraper), \
             patch('core.scraper.search_jav', side_effect=make_mock_search_jav(results_map)):
            search_prefix('SONE', limit=20, result_callback=result_callback)

        # Collect result-item calls (slot >= 0)
        item_calls = [(s, d) for s, d in callback_calls if s >= 0]
        assert len(item_calls) == 3, f"Expected 3 item calls, got {len(item_calls)}"

        # Each slot must correspond to target_ids[slot]
        for slot, data in item_calls:
            expected_number = ids[slot]
            assert data['number'] == expected_number, (
                f"Slot {slot} should correspond to {expected_number}, "
                f"but got {data['number']}"
            )


    def test_search_prefix_cross_page_boundary(self, make_mock_search_jav):
        """offset=20 + limit=20 需要跨頁抓取，不能只拿 10 筆"""
        from core.scraper import search_prefix
        from core.search_providers import cursor as cursor_codec

        # offset>0 ⇒ 載入更多必須帶有效 token（175d）
        token = cursor_codec.encode(cursor_codec.Token('javbus', 'keyword'))

        # 模擬兩頁：page 1 有 30 筆，page 2 有 30 筆
        page1_ids = [f'SONE-{i:03d}' for i in range(1, 31)]   # SONE-001 ~ SONE-030
        page2_ids = [f'SONE-{i:03d}' for i in range(31, 61)]  # SONE-031 ~ SONE-060

        mock_scraper = MagicMock()
        mock_scraper.get_ids_from_search.side_effect = [page1_ids, page2_ids, []]

        # 每筆 search_jav 都回傳有效結果
        all_ids = page1_ids + page2_ids
        results_map = {num: {'number': num, 'title': f'Title {num}'} for num in all_ids}

        with patch('core.scraper.JavBusScraper', return_value=mock_scraper), \
             patch('core.scraper.search_jav', side_effect=make_mock_search_jav(results_map)):
            results = search_prefix('SONE', limit=20, offset=20, cursor=token)

        # offset=20 意味著跳過前 20 筆，應該拿到 SONE-021 ~ SONE-040（20 筆）
        assert len(results) == 20, f"Expected 20 results, got {len(results)}"

    def test_search_prefix_results_sorted_by_date(self, make_mock_search_jav):
        """同步 API 回傳結果應按日期排序"""
        from core.scraper import search_prefix

        ids = ['SONE-100', 'SONE-101', 'SONE-102']
        results_map = {
            'SONE-100': {'number': 'SONE-100', 'title': 'T1', 'date': '2025-01-01'},
            'SONE-101': {'number': 'SONE-101', 'title': 'T2', 'date': '2025-03-01'},
            'SONE-102': {'number': 'SONE-102', 'title': 'T3', 'date': '2025-02-01'},
        }

        mock_scraper = MagicMock()
        mock_scraper.get_ids_from_search.side_effect = [ids, []]

        with patch('core.scraper.JavBusScraper', return_value=mock_scraper), \
             patch('core.scraper.search_jav', side_effect=make_mock_search_jav(results_map)):
            results = search_prefix('SONE', limit=20)

        dates = [r['date'] for r in results]
        assert dates == sorted(dates, reverse=True), f"Results not sorted by date: {dates}"


# ============ search_actress result_callback 測試 ============

class TestSearchActressResultCallback:
    """測試 search_actress() 的 result_callback 行為"""


    @staticmethod
    def _dmm_video(number):
        from core.scrapers.models import Video
        return Video(number=number, title='T', source='dmm', date='2024-01-01')


    def test_fallback_source_gets_none_after_seed_sent(self, monkeypatch):
        """JavBus 已送出 seed、詳情全失敗 → DMM 拿到 None，不再送第二組骨架卡（R28，I-S3）"""
        from core.scraper import search_actress
        from core.scrapers.dmm import DMMScraper, ListResult

        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: ['javbus', 'dmm'])
        monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: True)
        callback_calls = []
        mock_scraper = make_mock_scraper_actress([['SONE-001', 'SONE-002']])

        with patch('core.scraper.JavBusScraper', return_value=mock_scraper), \
             patch('core.scraper.search_jav', return_value=None), \
             patch.object(DMMScraper, 'list_contents',
                          return_value=ListResult([{'id': 'sone00100', 'title': 'T'}], None, False)) as mock_dmm, \
             patch.object(DMMScraper, '_fetch_by_id', return_value=self._dmm_video('SONE-100')):
            results = search_actress('三上悠亜', limit=20,
                                     result_callback=lambda s, d: callback_calls.append((s, d)))

        mock_dmm.assert_called_once()
        assert len(results) == 1
        assert callback_calls == [(-1, ['SONE-001', 'SONE-002'])]  # 只有 JavBus 的 seed，DMM 沒送任何事件


# ============ smart_search result_callback 透傳測試 ============


# ============ discovery_only 參數測試 ============

class TestDiscoveryOnly:
    """測試 discovery_only=True 讓各子函數跳過 Step 2 enrichment"""

    def test_search_prefix_discovery_only_returns_ids_no_enrich(self, make_mock_search_jav):
        """discovery_only=True: search_prefix 只做 get_ids_from_search，不呼叫 search_jav"""
        from core.scraper import search_prefix

        ids = ['SONE-100', 'SONE-101', 'SONE-102']
        mock_scraper = make_mock_scraper_prefix(ids)
        search_jav_calls = []

        def fake_search_jav(num, source='javbus'):
            search_jav_calls.append(num)
            return {'number': num, 'title': f'Title {num}'}

        with patch('core.scraper.JavBusScraper', return_value=mock_scraper), \
             patch('core.scraper.search_jav', side_effect=fake_search_jav):
            results = search_prefix('SONE', limit=20, discovery_only=True)

        assert search_jav_calls == [], \
            f"discovery_only=True: search_jav should not be called, but was called for {search_jav_calls}"
        assert len(results) == 3
        for r in results:
            assert 'number' in r
            assert r.get('title', '') == ''  # title is empty in discovery mode


# ============ Disabled source absent from auto-search routing (EC-6) ============

class TestDisabledSourceRouting:
    """停用 / 不在 Active Row 的來源不出現在自動搜尋 fan-out 序列；全關仍不 crash（EC-8）。"""

    @staticmethod
    def _instantiated_scraper_mocks():
        """回傳一組 (patch context managers, searched tracker) — 每個 scraper class
        被 patch 成 mock：instance.search() 記錄被搜尋的來源並回 None。

        以 .search() 而非建構為準（normalize_number() 已解耦至 utils.py，不再建立 JavBusScraper）：
        用建構計數仍可能誤報其他 scraper，故以 .search() 側錄為準。"""
        instantiated = []

        def make_cls(name):
            def factory(*args, **kwargs):
                inst = MagicMock()
                def _search(*a, **k):
                    instantiated.append(name)
                    return None
                inst.search.side_effect = _search
                return inst
            return factory

        cms = [
            patch('core.scraper.JavBusScraper', side_effect=make_cls('javbus')),
            patch('core.scraper.JAV321Scraper', side_effect=make_cls('jav321')),
            patch('core.scraper.JavDBScraper', side_effect=make_cls('javdb')),
            patch('core.scraper.D2PassScraper', side_effect=make_cls('d2pass')),
            patch('core.scraper.HEYZOScraper', side_effect=make_cls('heyzo')),
            patch('core.scraper.FC2OfficialScraper', side_effect=make_cls('fc2')),
            patch('core.scraper.AVSOXScraper', side_effect=make_cls('avsox')),
            patch('core.scraper.DMMScraper', side_effect=make_cls('dmm')),
        ]
        return cms, instantiated

    def test_disabled_source_absent_from_auto_fanout(self, make_mock_search_jav):
        """auto fan-out 只跑 get_enabled_source_ids() 子集 — 停用來源不被建立 / 搜尋"""
        from core.scraper import search_jav
        from contextlib import ExitStack

        cms, instantiated = self._instantiated_scraper_mocks()
        with ExitStack() as stack:
            for cm in cms:
                stack.enter_context(cm)
            # 只啟用 jav321 + javdb（停用 javbus / dmm 等）
            stack.enter_context(
                patch('core.scraper.get_enabled_source_ids', return_value=['jav321', 'javdb'])
            )
            result = search_jav('SONE-100', source='auto')

        assert 'javbus' not in instantiated, \
            f"disabled javbus should not be instantiated, got {instantiated}"
        assert 'dmm' not in instantiated
        assert set(instantiated) <= {'jav321', 'javdb'}


