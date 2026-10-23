"""
Integration tests for core/scrapers/actress/orchestrator.py — Phase 42b T4.1

Tests the 4-route parallel orchestrator with all scrapers mocked via source-module paths.
Covers: C1 text cascade, C3 photo cascade, C4 return shape, TD-1 age fix,
        cache TTL, legacy flat↔nested consistency.

Patch targets (source-module paths):
    core.scrapers.actress.xcity.scrape_xcity
    core.scrapers.actress.wiki_ja.scrape_wiki_ja
    core.scrapers.actress.graphis.scrape_graphis_photo
    core.scrapers.actress.gfriends.lookup_gfriends
"""

import threading
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from core.scrapers.actress import orchestrator
from core.scrapers.actress.orchestrator import get_actress_profile, _cache

# ---------------------------------------------------------------------------
# Patch target constants
# ---------------------------------------------------------------------------
_PATCH_XCITY  = 'core.scrapers.actress.xcity.scrape_xcity'
_PATCH_WIKI     = 'core.scrapers.actress.wiki_ja.scrape_wiki_ja'
_PATCH_GRAPHIS  = 'core.scrapers.actress.graphis.scrape_graphis_photo'
_PATCH_GFRIENDS = 'core.scrapers.actress.gfriends.lookup_gfriends'
_PATCH_AVBASE = 'core.scrapers.actress.avbase.scrape_avbase'

_ACTRESS_NAME = "明里つむぎ"


# ---------------------------------------------------------------------------
# Mock data factories
# ---------------------------------------------------------------------------

def _make_xcity(name="明里つむぎ", birth="1998-03-31", **kwargs):
    return {
        "name_ja": name,
        "birth": birth,
        "hometown": "神奈川県",
        "height": "157cm",
        "bust": "80cm",
        "waist": "58cm",
        "hip": "83cm",
        "cup": "B",
        "blood": "O",
        "hobby": "スポーツ",
        "photo_url": "https://xcity.jp/idol/photo/273627.jpg",
        **kwargs,
    }


def _make_wiki(name="明里つむぎ", birth="1998-03-31", **kwargs):
    return {
        "name_ja": name,
        "nickname": "つむぎ",
        "birth": birth,
        "hometown": "神奈川県",
        "height": "157cm",
        "bust": "80cm",
        "waist": "58cm",
        "hip": "83cm",
        "cup": "B",
        "blood": "O",
        "exclusive_makers": "",
        "debut_year": "2017",
        "photo_url": "https://upload.wikimedia.org/wikipedia/commons/sample.jpg",
        "photo_license": "Commons",
        **kwargs,
    }


def _make_graphis(name_en="Akari Tsumugi", **kwargs):
    return {
        "name": "",
        "prof_url": "https://graphis.ne.jp/photos/akari_tsumugi_prof.jpg",
        "backdrop_url": "https://graphis.ne.jp/photos/akari_tsumugi_back.jpg",
        "name_en": name_en,
        "age": 999,   # intentionally stale — TD-1 must ignore this
        "height": "157cm",
        "cup": "B",
        "bust": "80cm",
        "waist": "58cm",
        "hip": "83cm",
        "hobby": "写真",
        **kwargs,
    }


def _make_gfriends_url():
    return "https://cdn.jsdelivr.net/gh/gfriends/gfriends@master/Content/9-AVDBS/明里つむぎ.jpg"


# ---------------------------------------------------------------------------
# Autouse fixture: clear cache before and after every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_cache():
    _cache.clear()
    yield
    _cache.clear()


# ---------------------------------------------------------------------------
# datetime freeze helper
# ---------------------------------------------------------------------------

class _FrozenDatetime(datetime):
    """Subclass of datetime that overrides now() to return a frozen instant.
    strptime is inherited and works normally."""
    _frozen: datetime = None

    @classmethod
    def now(cls, tz=None):
        return cls._frozen


def _frozen_dt_class(frozen: datetime):
    """Return a FrozenDatetime subclass frozen at the given instant."""
    class _Cls(_FrozenDatetime):
        _frozen = frozen
    return _Cls


# ---------------------------------------------------------------------------
# TestHappyPath — all 4 routes return data
# ---------------------------------------------------------------------------

class TestHappyPath:


    def test_photo_cascade_graphis_wins(self):
        xcity = _make_xcity()
        wiki    = _make_wiki()
        graphis = _make_graphis()
        gfurl   = _make_gfriends_url()

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=gfurl):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["photo_source"] == "graphis"
        assert result.data["photo_url"] == graphis["prof_url"]
        assert result.data["backdrop_url"] == graphis["backdrop_url"]
        assert result.timed_out is False


# ---------------------------------------------------------------------------
# TestC1Cascade — text primary source fallback
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TestPhotoCascade — photo source fallback chain
# ---------------------------------------------------------------------------

class TestPhotoCascade:

    @pytest.mark.parametrize("xcity, wiki, graphis, gfriends, source, photo_url", [
        # Graphis 有資料但 prof_url 為空 → 退到 gfriends
        (_make_xcity(), None, _make_graphis(prof_url=""), _make_gfriends_url(),
         "gfriends",
         "https://cdn.jsdelivr.net/gh/gfriends/gfriends@master/Content/9-AVDBS/明里つむぎ.jpg"),
        # graphis、gfriends 都沒有 → wiki
        # 只有 xcity 有照片 → xcity
    ], ids=["graphis_no_prof_url_gfriends_wins", ])
    def test_graphis_no_prof_url_gfriends_wins(self, xcity, wiki, graphis, gfriends, source, photo_url):
        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=gfriends):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["photo_source"] == source
        assert result.data["photo_url"] == photo_url
        assert result.data["img"] == photo_url
        assert result.timed_out is False


# ---------------------------------------------------------------------------
# TestTD1Age — current_age computed from birth, never from source
# ---------------------------------------------------------------------------

class TestTD1Age:

    def _call_with_frozen_now(self, frozen_now: datetime, xcity_birth):
        xcity = _make_xcity(birth=xcity_birth)
        FrozenDT = _frozen_dt_class(frozen_now)

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None), \
             patch('core.scrapers.actress.orchestrator.datetime', FrozenDT):
            return get_actress_profile(_ACTRESS_NAME)


    def test_age_not_read_from_graphis_stale_field(self):
        # Graphis has age=999; orchestrator must compute from birth, not read 999
        xcity = _make_xcity(birth="1998-03-31")
        graphis = _make_graphis()  # age=999 is baked in by factory
        FrozenDT = _frozen_dt_class(datetime(2026, 1, 1))

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=None), \
             patch('core.scrapers.actress.orchestrator.datetime', FrozenDT):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["age"] != 999
        assert result.data["age"] == 27  # computed, not from graphis
        assert result.timed_out is False


# ---------------------------------------------------------------------------
# TestLegacyFlatConsistency — nested↔flat key parity
# ---------------------------------------------------------------------------

class TestLegacyFlatConsistency:

    def _assert_consistency(self, data):
        assert data["img"] == data["photo_url"]
        assert data["backdrop"] == data["backdrop_url"]
        assert data["age"] == data["current_age"]
        text = data.get("text")
        if text is not None:
            assert data["name"] == _ACTRESS_NAME
            assert data["birth"] == text.get("birth")


# ---------------------------------------------------------------------------
# TestCacheTTL — cache hit/miss/expiry behaviour
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TestMeaningfulTextFilter — Bug 1 regression: shell source must not suppress richer fallback
# ---------------------------------------------------------------------------

class TestMeaningfulTextFilter:
    """Bug 1 regression: shell/empty text source must not suppress richer fallback."""

    def test_wiki_shell_does_not_suppress_graphis(self):
        """Wiki returning shell dict (name_ja only, no text fields) must not
        win C1 cascade over a Graphis source with actual data."""
        wiki_shell = {
            "name_ja": _ACTRESS_NAME,
            "nickname": "",
            "birth": "",
            "hometown": "",
            "height": "",
            "bust": "", "waist": "", "hip": "",
            "cup": "",
            "blood": "",
            "exclusive_makers": "",
            "debut_year": "",
            "photo_url": "https://upload.wikimedia.org/shell.jpg",
            "photo_license": "Commons",
        }
        graphis = _make_graphis()  # has birth, height, BWH, etc.

        with patch(_PATCH_XCITY, return_value=None), \
             patch(_PATCH_WIKI, return_value=wiki_shell), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data is not None
        # Graphis (with real data) must win C1, not the wiki shell
        assert result.data["primary_text_source"] == "graphis"
        assert result.data["text"]["name_en"] == graphis["name_en"]
        # But wiki dict is still stored in all_sources for reference
        assert result.data["all_sources"]["wiki"] == wiki_shell
        assert result.timed_out is False


    def test_wiki_other_names_only_wins_c1(self):
        """Codex PR #23 P2: Wiki's `other_names` (別名/芸名 row) must count as
        meaningful text. `wiki_ja._parse_wiki_ja_html` explicitly allows alias-only
        infoboxes to return a dict (rather than None). If orchestrator's _MEANINGFUL_TEXT_FIELDS
        omits `other_names`, an alias-only wiki result is silently dropped from the
        C1 cascade even though the parser deliberately preserved it for Phase 43
        alias ingestion.

        Regression: when xcity/graphis/gfriends all miss, a wiki dict with only
        other_names populated MUST win C1 as primary text source (not None).
        """
        wiki_other_names_only = {
            "name_ja": _ACTRESS_NAME,
            "nickname": "",
            "other_names": ["松嶋真麻", "別名2"],  # the only non-empty field
            "birth": "",
            "hometown": "",
            "height": "", "bust": "", "waist": "", "hip": "", "cup": "", "blood": "",
            "exclusive_makers": "",
            "debut_year": "",
            "photo_url": "",
            "photo_license": "",
        }

        with patch(_PATCH_XCITY, return_value=None), \
             patch(_PATCH_WIKI, return_value=wiki_other_names_only), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data is not None, \
            "alias-only wiki must not collapse result to None"
        assert result.data["primary_text_source"] == "wiki", \
            "wiki with only other_names must win C1 cascade when other sources miss"
        assert result.data["text"] == {"aliases": ["松嶋真麻", "別名2"]}
        assert result.data["all_sources"]["wiki"]["other_names"] == ["松嶋真麻", "別名2"]
        assert result.timed_out is False


# ---------------------------------------------------------------------------
# 174-T3: avbase 第五路（五路並行、共享預算不變）
# ---------------------------------------------------------------------------

_AV_XCITY = {"name_ja": "測試女優", "birth": "1990-01-01", "photo_url": "https://x.example/xcity.jpg"}
_AV_WIKI = {"name_ja": "測試女優", "nickname": "維基暱稱", "photo_url": "https://x.example/wiki.jpg"}
_AV_GRAPHIS = {"prof_url": "https://x.example/graphis.jpg"}
_AV_GFRIENDS = "https://x.example/gfriends.jpg"
_AV_AVBASE = {"birth": "1991-02-03", "other_names": ["アヴベース別名"]}
_AV_NAME = "測試女優"
_AV_SAFETY_S = 5  # 替身自己的安全上限：測試中途崩潰也不會讓行程永久卡住


def _hanging_stub(ev, done, result=None):
    """可釋放的卡住替身：等 ev（帶安全上限），結束時發 done 信號。"""
    def _stub(*args, **kwargs):
        try:
            ev.wait(timeout=_AV_SAFETY_S)
            return result
        finally:
            done.release()
    return _stub


def _run_fetch(xcity, wiki, graphis, gfriends, avbase):
    """五個來源函式全部替身後跑 _fetch_all_sources；回傳 (sources, 牆鐘秒數)。"""
    with patch(_PATCH_XCITY, xcity), patch(_PATCH_WIKI, wiki), \
         patch(_PATCH_GRAPHIS, graphis), patch(_PATCH_GFRIENDS, gfriends), \
         patch(_PATCH_AVBASE, avbase):
        t0 = time.perf_counter()
        sources = orchestrator._fetch_all_sources(_AV_NAME, ["S1"])
        return sources, time.perf_counter() - t0


class TestFetchAllSourcesAvbase:
    """_fetch_all_sources 多一路 avbase（CD-174-9）；avbase 失敗不影響其餘四源。"""


    def test_avbase_hang_returns_within_budget(self, monkeypatch):
        monkeypatch.setattr(orchestrator, "_FETCH_BUDGET_S", 0.3)
        ev = threading.Event()
        done = threading.Semaphore(0)
        try:
            sources, elapsed = _run_fetch(
                MagicMock(return_value=_AV_XCITY),
                MagicMock(return_value=_AV_WIKI),
                MagicMock(return_value=_AV_GRAPHIS),
                MagicMock(return_value=_AV_GFRIENDS),
                _hanging_stub(ev, done, result=_AV_AVBASE),
            )
            assert elapsed <= 0.3 + 0.5
            assert sources.timed_out is True
            assert dict(sources) == {
                "xcity": _AV_XCITY,
                "wiki": _AV_WIKI,
                "graphis": _AV_GRAPHIS,
                "gfriends": _AV_GFRIENDS,
                "avbase": None,
            }
        finally:
            ev.set()
        assert done.acquire(timeout=_AV_SAFETY_S + 1), "avbase worker 未結束"

    @pytest.mark.parametrize("avbase_failure", [
        MagicMock(side_effect=RuntimeError("avbase boom")),
    ], ids=["raises"])
    def test_avbase_failure_leaves_other_sources_untouched(self, avbase_failure):
        def _others():
            return (MagicMock(return_value=_AV_XCITY), MagicMock(return_value=_AV_WIKI),
                    MagicMock(return_value=_AV_GRAPHIS), MagicMock(return_value=_AV_GFRIENDS))

        baseline, _ = _run_fetch(*_others(), MagicMock(return_value=None))
        sources, _ = _run_fetch(*_others(), avbase_failure)

        assert dict(sources) == {
            "xcity": _AV_XCITY,
            "wiki": _AV_WIKI,
            "graphis": _AV_GRAPHIS,
            "gfriends": _AV_GFRIENDS,
            "avbase": None,
        }
        assert sources.timed_out is False
        assert baseline.timed_out is False
        assert dict(sources) == dict(baseline)
        assert avbase_failure.call_count == 1


# ---------------------------------------------------------------------------
# 174-T4a: 文字欄位順序「維基 → xcity → graphis → avbase」、primary 納入 avbase
# ---------------------------------------------------------------------------

_FO_FIELDS = ("birth", "height", "bust", "waist", "hip", "cup", "hometown")

# 四源互異值（BE-TEST-23）：換不換順序都看得出取到哪一家
_FO_WIKI = {"name_ja": _AV_NAME, "birth": "1991-01-01", "height": "151cm", "bust": "81cm",
            "waist": "61cm", "hip": "91cm", "cup": "C", "hometown": "東京都"}
_FO_XCITY = {"name_ja": _AV_NAME, "birth": "1992-02-02", "height": "152cm", "bust": "82cm",
             "waist": "62cm", "hip": "92cm", "cup": "D", "hometown": "大阪府", "hobby": "xcity趣味"}
_FO_GRAPHIS = {"birth": "1993-03-03", "height": "153cm", "bust": "83cm", "waist": "63cm",
               "hip": "93cm", "cup": "E", "hometown": "京都府", "hobby": "graphis趣味"}
_FO_AVBASE = {"birth": "1994-04-04", "height": "154cm", "bust": "84cm", "waist": "64cm",
              "hip": "94cm", "cup": "F", "hometown": "北海道", "hobby": "avbase趣味"}


def _fo_profile(xcity=None, wiki=None, graphis=None, avbase=None):
    with patch(_PATCH_XCITY, return_value=xcity), \
         patch(_PATCH_WIKI, return_value=wiki), \
         patch(_PATCH_GRAPHIS, return_value=graphis), \
         patch(_PATCH_GFRIENDS, return_value=None), \
         patch(_PATCH_AVBASE, return_value=avbase):
        return get_actress_profile(_AV_NAME).data


class TestWikiFirstFieldOrder:

    def test_all_four_sources_differ_wiki_wins_every_shared_field(self):
        data = _fo_profile(_FO_XCITY, _FO_WIKI, _FO_GRAPHIS, _FO_AVBASE)
        assert {f: data["text"].get(f) for f in _FO_FIELDS} == {f: _FO_WIKI[f] for f in _FO_FIELDS}
        assert data["primary_text_source"] == "wiki"

    def test_front_three_lack_birth_avbase_supplies_it(self):
        wiki = {k: v for k, v in _FO_WIKI.items() if k != "birth"}
        xcity = {k: v for k, v in _FO_XCITY.items() if k != "birth"}
        graphis = {k: v for k, v in _FO_GRAPHIS.items() if k != "birth"}
        data = _fo_profile(xcity, wiki, graphis, _FO_AVBASE)
        text = data["text"]
        assert text.get("birth") == _FO_AVBASE["birth"]
        assert text.get("height") == _FO_WIKI["height"]
        assert text.get("hobby") == "xcity趣味"


# ---------------------------------------------------------------------------
# 174-T4b: 別名過濾器 ＋ 別名來源鏈「維基 → avbase」
# ---------------------------------------------------------------------------

def _al_profile(name, xcity=None, wiki=None, graphis=None, avbase=None):
    with patch(_PATCH_XCITY, return_value=xcity), \
         patch(_PATCH_WIKI, return_value=wiki), \
         patch(_PATCH_GRAPHIS, return_value=graphis), \
         patch(_PATCH_GFRIENDS, return_value=None), \
         patch(_PATCH_AVBASE, return_value=avbase):
        return get_actress_profile(name).data


class TestCleanAliases:


    def test_clean_aliases_drops_at_prefixed_accounts(self):
        assert orchestrator._clean_aliases(
            ["@Faerina", "@久世ミコト", "久世ミコト"], "別人") == ["久世ミコト"]
        assert orchestrator._clean_aliases(["＠abc", "真別名"], "別人") == ["真別名"]


_AL_OWN = "二階堂麗"
_AL_AV_NAMES = ["avbase別名甲", "avbase別名乙", "avbase別名丙"]


class TestAliasChain:


    def test_wiki_with_only_own_name_falls_through_to_avbase(self):
        for wiki_names in ([_AL_OWN], ["@wikiacct"]):
            orchestrator._cache.clear()
            data = _al_profile(
                _AL_OWN,
                wiki={"name_ja": _AL_OWN, "other_names": list(wiki_names)},
                avbase={"other_names": [_AL_OWN, "@acct", *_AL_AV_NAMES]},
            )
            assert data["text"]["aliases"] == _AL_AV_NAMES


    def test_avbase_aliases_used_when_wiki_absent_for_both_query_names(self):
        av = ["二階堂麗", "あかね麗"]
        data = _al_profile("二階堂麗", avbase={"other_names": list(av)})
        assert data["text"]["aliases"] == ["あかね麗"]
        orchestrator._cache.clear()
        data = _al_profile("あかね麗", avbase={"other_names": list(av)})
        assert data["text"]["aliases"] == ["二階堂麗"]


