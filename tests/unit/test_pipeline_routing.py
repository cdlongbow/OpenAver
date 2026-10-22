"""
TestPipeline + TestUnknownSource — Pipeline routing 測試
（搬自 tests/integration/test_new_scrapers.py TestPipeline + TestUnknownSource）

mock scraper.search，驗證路由邏輯（不含 TestClient 測試）
"""
import pytest
from unittest.mock import patch

from core.scrapers.d2pass import D2PassScraper
from core.scrapers.heyzo import HEYZOScraper
from core.scrapers.dmm import DMMScraper
from core.scrapers.javbus import JavBusScraper
from core.scrapers.models import Video
from core.scrapers.utils import SOURCE_ORDER
from core.scraper import search_jav, smart_search
pytestmark = pytest.mark.usefixtures("no_entity_lookup", "no_dmm_facts")


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """跳過 rate_limit / REQUEST_DELAY sleep，加速測試"""
    monkeypatch.setattr("core.scrapers.dmm.rate_limit", lambda *a, **kw: None)
    monkeypatch.setattr("core.scraper.time.sleep", lambda *a: None)


@pytest.fixture(autouse=True)
def _dmm_capsule(monkeypatch):
    """DMM 開關看膠囊（BE-TEST-01：patch 使用端）。預設開；測「關」的案例自行改 False。"""
    monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: True)


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


# ============================================================
# TestPipeline — smart_search routing 測試
# ============================================================

class TestPipeline:
    """Pipeline routing 測試（mock scraper.search，驗證路由邏輯）"""

    @pytest.fixture(autouse=True)
    def _all_sources_enabled(self, monkeypatch):
        """隔離 ambient web/config.json 的啟用來源集合。

        TASK-61a-3 起 search_jav(source='auto') 改讀 get_enabled_source_ids()
        →（讀 live web/config.json）決定 fan-out 來源。本檔的 merge-priority
        測試假設 8 個 builtin 來源（含 dmm/javbus）全部啟用；若開發者把有碼來源
        停用（例如開無碼模式），dmm/javbus 會被排除 → search_jav 回 None →
        assertion 觸發 TypeError，測試變得 config-coupled 且不確定。

        此 fixture 把 search_jav 實際呼叫的 core.scraper.get_enabled_source_ids
        monkeypatch 成回傳全部 8 個 builtin id（canonical 順序），讓 merge
        測試只驗證 MERGER 在所有來源可用時的行為，與環境 config 無關。
        """
        monkeypatch.setattr(
            "core.scraper.get_enabled_source_ids",
            lambda availability_map=None: list(SOURCE_ORDER),
        )

    def test_uncensored_detection_d2pass(self):
        """日期_底線格式番號 → 自動走無碼路徑 → D2PassScraper 被呼叫"""
        mock_video = _make_video("d2pass", "120415_201")

        with patch.object(D2PassScraper, 'search', return_value=mock_video) as mock_d2:
            with patch('core.scrapers.dmm.rate_limit'):
                results = smart_search("120415_201")

        assert len(results) == 1
        assert results[0]['_mode'] == 'uncensored'
        mock_d2.assert_called()


    def test_merge_winner_first_in_order_javbus(self, monkeypatch):
        """merge text-winner = first successful source in drag-sort order.

        Override enabled order so javbus is FIRST (dmm absent / after javbus).
        With javbus first in order + javbus returning data → winner _source == 'javbus',
        even though dmm also returns data.
        This proves drag-order determines the merge winner, NOT primary_source.
        """
        from core.scrapers.jav321 import JAV321Scraper
        # ⚠️ 從「使用端 binding」取 JavDBScraper，不從定義端（139-T1b）：
        # test_javdb_cainfo.py 會 importlib.reload(core.scrapers.javdb)，reload 後定義端是
        # 新的 class 物件，而 core/scraper.py 仍持有舊的 ⇒ patch 打在新的上、被測程式跑的是
        # 舊的真實 scraper（會發真網路請求）。從 core.scraper 取，identity 保證與被測程式一致。
        from core.scraper import JavDBScraper
        from core.scrapers.fc2_official import FC2OfficialScraper
        from core.scrapers.avsox import AVSOXScraper
        dmm_video = _make_video("dmm", "SONE-205")
        javbus_video = _make_video("javbus", "SONE-205")

        # Override the class fixture: javbus first, dmm SECOND (still fanned out + returns
        # data) — proves first-in-order beats a later successful source, not just absence.
        javbus_first_order = ['javbus', 'dmm', 'jav321', 'javdb', 'fc2', 'avsox', 'heyzo']
        monkeypatch.setattr(
            "core.scraper.get_enabled_source_ids",
            lambda availability_map=None: javbus_first_order,
        )

        with patch.object(DMMScraper, 'search', return_value=dmm_video), \
             patch.object(JavBusScraper, 'search', return_value=javbus_video), \
             patch.object(JAV321Scraper, 'search', return_value=None), \
             patch.object(JavDBScraper, 'search', return_value=None), \
             patch.object(FC2OfficialScraper, 'search', return_value=None), \
             patch.object(AVSOXScraper, 'search', return_value=None), \
             patch('core.scrapers.dmm.rate_limit'):
            result = search_jav("SONE-205")

        assert result['_source'] == 'javbus'

    def test_fuzzy_chain_dmm_capsule_off_falls_through(self, monkeypatch):
        """DMM 排第一 + DMM 膠囊關 → 跳過 DMM，fallback 到 javbus（新鏈行為）"""
        from core.scraper import search_actress
        monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: sid == "javbus")
        # ⚠️ 從「使用端 binding」取 JavDBScraper，不從定義端（139-T1b）：
        # test_javdb_cainfo.py 會 importlib.reload(core.scrapers.javdb)，reload 後定義端是
        # 新的 class 物件，而 core/scraper.py 仍持有舊的 ⇒ patch 打在新的上、被測程式跑的是
        # 舊的真實 scraper（會發真網路請求）。從 core.scraper 取，identity 保證與被測程式一致。
        from core.scraper import JavDBScraper

        mock_video = _make_video("javbus", "SONE-205")

        with patch('core.scraper.get_all_source_ids_ordered', return_value=['dmm', 'javbus', 'jav321', 'javdb']), \
             patch.object(DMMScraper, 'list_contents') as mock_dmm_kw, \
             patch.object(JavBusScraper, 'get_ids_from_search', return_value=['SONE-205']), \
             patch('core.scraper.search_jav', return_value=mock_video.to_legacy_dict()), \
             patch.object(JavDBScraper, 'search_by_keyword', return_value=[]):
            results = search_actress("未歩なな", limit=1)

        # DMM must NOT be called when the DMM capsule is off
        mock_dmm_kw.assert_not_called()
        assert len(results) >= 1


# ============================================================
# TestUnknownSource (2 mock-only tests)
# ============================================================


# ============================================================
# TestFc2Dispatch — TASK-118-T3：fc2 source id 建的是官方站類別
# ============================================================


class TestFcJavtenDispatch:
    """TASK-118a-T4：dispatch 表必須含 fc-javten → FC2JavtenScraper。"""

    def test_source_to_scraper_includes_fc_javten(self):
        """search_jav(source='fc-javten') 必須建構並呼叫 FC2JavtenScraper.search。"""
        from core.scrapers.fc2_javten import FC2JavtenScraper

        with patch.object(FC2JavtenScraper, 'search', return_value=None) as mock_search:
            result = search_jav("FC2-PPV-1234567", source="fc-javten")

        mock_search.assert_called()
        assert result is None


# ============================================================
# TestFcJavtenDoesNotAffectOtherSources — TASK-118a-T5 AC-2.6
# ============================================================

class TestFcJavtenDoesNotAffectOtherSources:
    """fc-javten 壞掉／不可用時，不拖累 auto 對 FC2 番號的官方站結果。

    獨立 class：不繼承 TestPipeline，必須自帶 BE-TEST-02 隔離 fixture。
    """

    @pytest.fixture(autouse=True)
    def _all_sources_enabled(self, monkeypatch):
        """隔離 ambient web/config.json 的啟用來源集合（BE-TEST-02）。

        TASK-61a-3 起 search_jav(source='auto') 改讀 get_enabled_source_ids()
        →（讀 live web/config.json）決定 fan-out 來源。

        ⚠️ **本 class 需要隔離的理由與 TestPipeline 不同，不要照抄那邊的說明。**
        這裡的斷言只看「FC2 番號仍由官方站（`fc2`）供應」，所以弄壞它的不是
        dmm/javbus 被停用，而是**開發者在自己的 web/config.json 裡把 `fc2` 停用**
        ——那時 cascade 根本不會試官方站，結果變空，這支就會在某些人的機器上紅、
        某些人的機器上綠。（T5 review 階段以 mutation 實測確認：只停 dmm/javbus
        這支照樣綠，停 `fc2` 才會紅——所以這個 fixture 是承重的，不是裝飾。）

        此 fixture 把 core.scraper.get_enabled_source_ids monkeypatch 成回傳
        全部 8 個 builtin id（canonical 順序），讓本 class 只驗證
        「`fc-javten` 不可用時不影響其他來源」，與環境 config 無關。
        """
        monkeypatch.setattr(
            "core.scraper.get_enabled_source_ids",
            lambda availability_map=None: list(SOURCE_ORDER),
        )

    def test_auto_search_fc2_number_still_gets_official_when_javten_unavailable(self):
        """AC-2.6：transport=None 時，search_jav(source='auto') 對 FC2 番號仍拿 fc2。

        不 patch FC2JavtenScraper：它結構上不在 SOURCE_ORDER，auto 不該呼叫它。
        """
        from core.scrapers.avsox import AVSOXScraper
        from core.scrapers.fc2_official import FC2OfficialScraper
        from core.scrapers.jav321 import JAV321Scraper
        # ⚠️ 從「使用端 binding」取 JavDBScraper，不從定義端（139-T1b）：
        # test_javdb_cainfo.py 會 importlib.reload(core.scrapers.javdb)，reload 後定義端是
        # 新的 class 物件，而 core/scraper.py 仍持有舊的 ⇒ patch 打在新的上、被測程式跑的是
        # 舊的真實 scraper（會發真網路請求）。從 core.scraper 取，identity 保證與被測程式一致。
        from core.scraper import JavDBScraper

        mock_video = _make_video("fc2", "FC2-PPV-1234567")

        with patch.object(FC2OfficialScraper, 'search', return_value=mock_video), \
             patch.object(D2PassScraper, 'search', return_value=None), \
             patch.object(HEYZOScraper, 'search', return_value=None), \
             patch.object(DMMScraper, 'search', return_value=None), \
             patch.object(JavBusScraper, 'search', return_value=None), \
             patch.object(JAV321Scraper, 'search', return_value=None), \
             patch.object(JavDBScraper, 'search', return_value=None), \
             patch.object(AVSOXScraper, 'search', return_value=None), \
             patch('core.scrapers.fc2_javten.get_cf_transport', return_value=None):
            result = search_jav("FC2-PPV-1234567", source="auto")

        assert result is not None
        assert result['_source'] == 'fc2'


# ============================================================
# TestFuzzyGuard — 模糊鏈來源順序與 partial 能力約束護欄
# （T4，CD-85-7；175b 起開關由 registry.providers_for 過濾，此處只守順序來源）
# ============================================================


# ============================================================
# TestCascadeExactBranch — TDD-lite RED→GREEN cascade 測試
# （T1a，spec-85 B1，CD-85-1/2）
# ============================================================

class TestCascadeExactBranch:
    """exact 番號分支新 cascade：依 get_enabled_source_ids 優先序串接直打、命中即回。

    standalone（不繼承 TestPipeline），自行 patch get_enabled_source_ids 以控制
    enabled 順序，避免 autouse fixture 干擾。
    Patch target 一律指使用端 core.scraper.*（gotchas-backend.md §Mock Patch Target）。
    """


    def test_fastpath_sequential_miss_then_hit(self):
        """enabled=['dmm','javbus']，dmm miss → javbus 命中 → call_count==2。

        突變有效性：若 miss 後不繼續下一個 sid → call_count==1 → RED。
        """
        from core.scraper import smart_search

        mock_result = {'number': 'HMN-706', 'title': 'T', '_source': 'javbus'}

        def _single_source(number, source):
            if source == 'javbus':
                return mock_result
            return None  # dmm miss

        with patch('core.scraper.get_enabled_source_ids', return_value=['dmm', 'javbus']), \
             patch('core.scraper.metatube_state') as mock_mt, \
             patch('core.scraper.search_jav_single_source', side_effect=_single_source) as mock_ss:
            mock_mt.availability_map.return_value = {}
            mock_mt.routing_availability_map.return_value = {}
            results = smart_search('HMN-706')

        assert len(results) == 1
        assert results[0]['_source'] == 'javbus'
        assert mock_ss.call_count == 2  # dmm 試了、javbus 試了

    def test_fastpath_exception_no_propagate(self):
        """enabled=['dmm','javbus']，dmm 拋 Exception → 不 propagate，繼續試 javbus。

        突變有效性：去掉 try/except → TEST RED（例外 propagate）。
        """
        from core.scraper import smart_search

        mock_result = {'number': 'HMN-706', 'title': 'T', '_source': 'javbus'}

        def _single_source(number, source):
            if source == 'dmm':
                raise Exception('timeout')
            return mock_result

        with patch('core.scraper.get_enabled_source_ids', return_value=['dmm', 'javbus']), \
             patch('core.scraper.metatube_state') as mock_mt, \
             patch('core.scraper.search_jav_single_source', side_effect=_single_source):
            mock_mt.availability_map.return_value = {}
            mock_mt.routing_availability_map.return_value = {}
            results = smart_search('HMN-706')  # must not raise

        assert len(results) == 1
        assert results[0]['_source'] == 'javbus'


