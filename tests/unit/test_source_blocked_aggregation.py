"""
test_source_blocked_aggregation.py — TASK-118-T4a

驗證 T2 已經在拋的 SourceBlocked「安全地」流過 core/scraper.py 所有 orchestration：
① 任何 fallback／fan-out 不得因它中斷
② 它永遠不從 core/scraper.py 的公開函式往外拋
③ 改走顯式 out-parameter blocked_out 收集，並寫進 debug.log（AC-4.2）。

Mock 慣例：
- fc2 / avsox / javbus 的 .search() 一律用 patch.object(Class, 'search', ...) 掛在
  共享類別上——patch.object 直接改 class attribute，與 import 路徑無關，不受
  BE-TEST-01 子項 1/3（patch 要對齊消費端 core.scraper.* import）限制。
- 其餘 patch（get_enabled_source_ids / metatube_state / _MetatubeShim）一律指
  core.scraper.* 這個消費端命名空間。
"""
import logging

import pytest
from unittest.mock import patch, MagicMock

from core.scraper import search_jav, smart_search
from core.scrapers.errors import SourceBlocked
from core.scrapers.fc2_official import FC2OfficialScraper
from core.scrapers.avsox import AVSOXScraper
from core.scrapers.models import Video
from core.cf_transport import CfChallengeRequired


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
# 1/2 — 不變式：FC2 被擋，AVSOX 仍能救回結果（CD-118b-16）
# ============================================================

class TestInvariantFc2BlockedAvsoxFallback:
    """CD-118b-16：fc2 被擋 → 對 FC2 番號跑 smart_search() 必須回 AVSOX 的結果，全程不拋例外。"""

    def test_smart_search_returns_avsox_result_when_fc2_blocked(self):
        """必備測試 #1（整個 T4 最重要的一支）"""
        avsox_video = _make_video("avsox", "FC2-PPV-1234567")

        with patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-1234567", status=403)), \
             patch.object(AVSOXScraper, "search", return_value=avsox_video):
            results = smart_search("FC2-PPV-1234567")

        assert len(results) == 1
        assert results[0]["_source"] == "avsox"

    def test_smart_search_empty_result_when_both_fc2_and_avsox_miss_blocked_out_has_fc2(self):
        """必備測試 #2：AVSOX 也回 None → 結果為空，且 blocked_out 收到一筆 source_id='fc2'"""
        with patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-1234567", status=403)), \
             patch.object(AVSOXScraper, "search", return_value=None):
            blocked = []
            results = smart_search("FC2-PPV-1234567", blocked_out=blocked)

        assert results == []
        assert len(blocked) == 1
        assert blocked[0].source_id == "fc2"
        assert blocked[0].article_id == "FC2-PPV-1234567"

    def test_smart_search_uncensored_flag_returns_avsox_result_when_fc2_blocked(self):
        """同不變式，但走明確 uncensored_mode=True 參數分支（「無碼模式」cascade，
        不是 FC2 前綴自動偵測那條）——三條 cascade 各自要有測試覆蓋，不能只靠自動偵測。
        """
        avsox_video = _make_video("avsox", "FC2-PPV-1234567")

        with patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-1234567", status=403)), \
             patch.object(AVSOXScraper, "search", return_value=avsox_video):
            results = smart_search("FC2-PPV-1234567", uncensored_mode=True)

        assert len(results) == 1
        assert results[0]["_source"] == "avsox"

    def test_smart_search_uncensored_flag_blocked_out_records_fc2(self):
        """同上分支，AVSOX 也回 None → 結果為空，blocked_out 收到一筆 source_id='fc2'"""
        with patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-1234567", status=403)), \
             patch.object(AVSOXScraper, "search", return_value=None):
            blocked = []
            results = smart_search("FC2-PPV-1234567", uncensored_mode=True, blocked_out=blocked)

        assert results == []
        assert len(blocked) == 1
        assert blocked[0].source_id == "fc2"


# ============================================================
# 3 — 負向守邊界：search_jav / smart_search 都不往外拋
# ============================================================

class TestNeverRaisesSourceBlocked:
    """必備測試 #3：search_jav() 與 smart_search() 在 fc2 被擋時都不往外拋 SourceBlocked
    （blocked_out 傳 None 與傳 list 兩種都測）——T4b 那 9 個 log-only 呼叫端零改動的唯一依據。
    """

    def test_search_jav_explicit_fc2_blocked_out_none_default_no_raise(self):
        with patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-1", status=403)):
            result = search_jav("FC2-PPV-1", source="fc2")  # blocked_out 未傳

        assert result is None

    def test_search_jav_explicit_fc2_blocked_out_list_no_raise(self):
        with patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-1", status=403)):
            blocked: list = []
            result = search_jav("FC2-PPV-1", source="fc2", blocked_out=blocked)

        assert result is None
        assert len(blocked) == 1

    def test_smart_search_fc2_blocked_out_none_default_no_raise(self):
        with patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-1", status=403)), \
             patch.object(AVSOXScraper, "search", return_value=None):
            results = smart_search("FC2-PPV-1")  # blocked_out 未傳

        assert results == []

    def test_smart_search_fc2_blocked_out_list_no_raise(self):
        with patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-1", status=403)), \
             patch.object(AVSOXScraper, "search", return_value=None):
            blocked: list = []
            results = smart_search("FC2-PPV-1", blocked_out=blocked)

        assert results == []
        assert len(blocked) == 1


# ============================================================
# 4 — auto fan-out：fc2 被擋不中斷 fan-out（記錄點 #1）
# ============================================================

class TestAutoFanoutRecordPoint:
    def test_auto_fanout_continues_and_merges_when_fc2_blocked(self):
        """必備測試 #4：fc2 被擋時，其他 builtin 來源仍被呼叫且結果照常合併"""
        avsox_video = _make_video("avsox", "SONE-205")

        with patch("core.scraper.get_enabled_source_ids", return_value=["fc2", "avsox"]), \
             patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "SONE-205", status=403)) as mock_fc2, \
             patch.object(AVSOXScraper, "search", return_value=avsox_video) as mock_avsox:
            blocked = []
            result = search_jav("SONE-205", source="auto", blocked_out=blocked)

        mock_fc2.assert_called_once()
        mock_avsox.assert_called_once()
        assert result is not None
        assert result["_source"] == "avsox"
        assert len(blocked) == 1
        assert blocked[0].source_id == "fc2"


# ============================================================
# 5 — metatube 分支：記錄點 #2（父執行緒收 fut.result()）
# ============================================================

class TestMetatubeRecordPoint:
    def test_metatube_shim_blocked_recorded_other_shim_unaffected(self):
        """必備測試 #5：某個 metatube shim 拋 SourceBlocked → 記得到，其他 shim 結果不受影響"""
        heyzo_video = _make_video("metatube:HEYZO", "HEYZO-0001")

        def _shim_factory(provider, base_url, token):
            mock = MagicMock()
            mock.source = f"metatube:{provider}"
            if provider == "FANZA":
                mock.search.side_effect = SourceBlocked(
                    "metatube:FANZA", "HEYZO-0001", status=403
                )
            else:
                mock.search.return_value = heyzo_video
            return mock

        mock_mt_state = MagicMock()
        mock_mt_state.is_connected = True
        mock_mt_state.base_url = "http://mt.local"
        mock_mt_state.token = ""
        mock_mt_state.availability_map.return_value = {
            "metatube:FANZA": True,
            "metatube:HEYZO": True,
        }

        with patch("core.scraper.metatube_state", mock_mt_state), \
             patch("core.scraper.get_enabled_source_ids",
                   return_value=["metatube:FANZA", "metatube:HEYZO"]), \
             patch("core.scraper._MetatubeShim", side_effect=_shim_factory):
            blocked = []
            result = search_jav("HEYZO-0001", source="auto", blocked_out=blocked)

        assert result is not None
        assert result["_source"] == "metatube:HEYZO"
        assert len(blocked) == 1
        assert blocked[0].source_id == "metatube:FANZA"


# ============================================================
# 6 — explicit 分支：記錄點 #3 ＋ CF 例外白名單不變
# ============================================================

class TestExplicitBranchRecordPoint:
    def test_explicit_fc2_blocked_records_and_returns_none(self):
        """必備測試 #6（前半）：source='fc2' 被擋 → 回 None 且 blocked_out 有記錄"""
        with patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-999", status=403)):
            blocked = []
            result = search_jav("FC2-PPV-999", source="fc2", blocked_out=blocked)

        assert result is None
        assert len(blocked) == 1
        assert blocked[0].source_id == "fc2"
        assert blocked[0].article_id == "FC2-PPV-999"
        assert blocked[0].status == 403

    def test_explicit_cf_challenge_still_reraises(self):
        """必備測試 #6（後半，回歸守衛）：CF 兩個例外仍然 re-raise，不被 SourceBlocked 記錄機制攔截"""
        with patch.object(FC2OfficialScraper, "search",
                           side_effect=CfChallengeRequired("cf challenge")):
            with pytest.raises(CfChallengeRequired):
                search_jav("FC2-PPV-999", source="fc2", blocked_out=[])


# ============================================================
# 7 — exact cascade（有碼番號）：cascade #3
# ============================================================

class TestExactCascadeRecordPoint:
    def test_exact_cascade_blocked_source_continues_and_records(self):
        """必備測試 #7：某來源拋 SourceBlocked → 後續來源仍被試，記錄併回"""
        avsox_video = _make_video("avsox", "SONE-205")

        with patch("core.scraper.get_enabled_source_ids", return_value=["fc2", "avsox"]), \
             patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "SONE-205", status=403)), \
             patch.object(AVSOXScraper, "search", return_value=avsox_video):
            blocked = []
            results = smart_search("SONE-205", blocked_out=blocked)

        assert len(results) == 1
        assert results[0]["_source"] == "avsox"
        assert results[0]["_mode"] == "exact"
        assert len(blocked) == 1
        assert blocked[0].source_id == "fc2"


# ============================================================
# 8 — not_found ≠ blocked（CD-118b-4）
# ============================================================

class TestNotFoundNotBlocked:
    def test_not_found_blocked_out_stays_empty(self):
        """必備測試 #8：scraper 回 None（軟 404）→ blocked_out 保持空"""
        with patch.object(FC2OfficialScraper, "search", return_value=None):
            blocked = []
            result = search_jav("FC2-PPV-000", source="fc2", blocked_out=blocked)

        assert result is None
        assert blocked == []


# ============================================================
# 9 — log 契約（AC-4.2）
# ============================================================

class TestLogContract:
    def test_log_omits_status_number_when_status_none(self, caplog):
        """必備測試 #9（前半）：status is None 時訊息不得出現 status 數字（逾時／DNS 失敗無回應）"""
        with caplog.at_level(logging.WARNING, logger="OpenAver.core.scraper"):
            with patch.object(FC2OfficialScraper, "search",
                               side_effect=SourceBlocked("fc2", "FC2-PPV-777", status=None)):
                search_jav("FC2-PPV-777", source="fc2")

        blocked_records = [r for r in caplog.records if "FC2-PPV-777" in r.getMessage()]
        assert blocked_records, "應有一筆含 article_id 的 log"
        for r in blocked_records:
            msg = r.getMessage()
            assert "status=None" not in msg
            import re
            assert not re.search(r"status=\d", msg), f"status is None 時不應出現 status 數字: {msg}"

    def test_log_includes_status_number_when_present(self, caplog):
        """必備測試 #9（後半）：status=403 時訊息含 status 數字"""
        with caplog.at_level(logging.WARNING, logger="OpenAver.core.scraper"):
            with patch.object(FC2OfficialScraper, "search",
                               side_effect=SourceBlocked("fc2", "FC2-PPV-778", status=403)):
                search_jav("FC2-PPV-778", source="fc2")

        blocked_records = [r for r in caplog.records if "FC2-PPV-778" in r.getMessage()]
        assert blocked_records, "應有一筆含 article_id 的 log"
        assert any("403" in r.getMessage() for r in blocked_records)
        assert any("fc2" in r.getMessage() for r in blocked_records)


# ============================================================
# 10 — blocked_out 預設 None 時零行為變化
# ============================================================

class TestZeroBehaviorChangeWhenBlockedOutOmitted:
    def test_search_jav_omitted_matches_explicit_none(self):
        """必備測試 #10：blocked_out 不傳與明確傳 None 的回傳值逐位元相同"""
        avsox_video = _make_video("avsox", "FC2-PPV-321")

        with patch("core.scraper.get_enabled_source_ids", return_value=["fc2", "avsox"]), \
             patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-321", status=None)), \
             patch.object(AVSOXScraper, "search", return_value=avsox_video):
            result_omitted = search_jav("FC2-PPV-321", source="auto")

        with patch("core.scraper.get_enabled_source_ids", return_value=["fc2", "avsox"]), \
             patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-321", status=None)), \
             patch.object(AVSOXScraper, "search", return_value=avsox_video):
            result_explicit_none = search_jav("FC2-PPV-321", source="auto", blocked_out=None)

        assert result_omitted == result_explicit_none

    def test_smart_search_omitted_matches_explicit_none(self):
        avsox_video = _make_video("avsox", "FC2-PPV-322")

        with patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-322", status=None)), \
             patch.object(AVSOXScraper, "search", return_value=avsox_video):
            results_omitted = smart_search("FC2-PPV-322")

        with patch.object(FC2OfficialScraper, "search",
                           side_effect=SourceBlocked("fc2", "FC2-PPV-322", status=None)), \
             patch.object(AVSOXScraper, "search", return_value=avsox_video):
            results_explicit_none = smart_search("FC2-PPV-322", blocked_out=None)

        assert results_omitted == results_explicit_none
