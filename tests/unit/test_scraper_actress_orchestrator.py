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
from core.scrapers.actress.orchestrator import get_actress_profile, get_cached_profile, ProfileResult, _cache, _CACHE_TTL

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

    def test_primary_text_source_wiki_when_wiki_and_xcity_both_have_data(self):
        xcity = _make_xcity()
        wiki    = _make_wiki()
        graphis = _make_graphis()
        gfurl   = _make_gfriends_url()

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=gfurl):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["primary_text_source"] == "wiki"
        assert result.data["text"]["birth"] == xcity["birth"]
        assert result.data["text"]["nickname"] == wiki["nickname"]
        assert result.data["text"]["name_en"] == graphis["name_en"]
        assert result.timed_out is False

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

class TestC1Cascade:

    def test_merge_text_fields_wiki_wins_over_xcity_when_both_have_value(self):
        xcity = _make_xcity(hometown="", height="160cm")
        wiki = _make_wiki(hometown="東京都", height="155cm")

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["text"]["hometown"] == "東京都"
        assert result.data["text"]["height"] == "155cm"

    def test_xcity_none_wiki_wins(self):
        wiki    = _make_wiki()
        graphis = _make_graphis()
        gfurl   = _make_gfriends_url()

        with patch(_PATCH_XCITY, return_value=None), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=gfurl):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["primary_text_source"] == "wiki"
        assert result.data["text"]["birth"] == wiki["birth"]
        assert result.data["text"]["name_en"] == graphis["name_en"]
        assert result.data["name"] == wiki["name_ja"]
        # Photo cascade: Graphis still wins because it has prof_url
        assert result.data["photo_source"] == "graphis"
        assert result.timed_out is False

    def test_xcity_wiki_none_graphis_wins(self):
        graphis = _make_graphis()
        gfurl   = _make_gfriends_url()

        with patch(_PATCH_XCITY, return_value=None), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=gfurl):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["primary_text_source"] == "graphis"
        assert result.data["text"]["name_en"] == graphis["name_en"]
        assert result.data["text"]["height"] == graphis["height"]
        # Bug 2 fix: name falls back to queried name (text.name is "" in _make_graphis,
        # so the final fallback is the queried `name` arg)
        assert result.data["name"] == _ACTRESS_NAME  # queried name fallback via text.name or name arg
        # Graphis has name_en
        assert result.data["name_en"] == graphis["name_en"]
        # Graphis has no birth key
        assert result.data["birth"] is None
        assert result.timed_out is False

    def test_all_four_none_returns_none(self):
        with patch(_PATCH_XCITY, return_value=None), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert isinstance(result, ProfileResult)
        assert result.data is None
        assert result.timed_out is False


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
        (None, _make_wiki(), None, None,
         "wiki",
         "https://upload.wikimedia.org/wikipedia/commons/sample.jpg"),
        # 只有 xcity 有照片 → xcity
        (_make_xcity(), None, None, None,
         "xcity",
         "https://xcity.jp/idol/photo/273627.jpg"),
    ], ids=["graphis_no_prof_url_gfriends_wins", "graphis_none_gfriends_none_wiki_wins", "only_xcity"])
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

    def test_age_before_birthday_in_year(self):
        # Birth 1998-03-31, frozen 2026-01-01 → hasn't reached birthday → age 27
        result = self._call_with_frozen_now(datetime(2026, 1, 1), "1998-03-31")
        assert result.data["current_age"] == 27
        assert result.data["age"] == 27
        assert result.timed_out is False

    def test_age_after_birthday_in_year(self):
        # Birth 1998-03-31, frozen 2026-04-01 → past birthday → age 28
        result = self._call_with_frozen_now(datetime(2026, 4, 1), "1998-03-31")
        assert result.data["current_age"] == 28
        assert result.data["age"] == 28
        assert result.timed_out is False

    def test_age_none_when_birth_none(self):
        xcity = _make_xcity(birth=None)
        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["current_age"] is None
        assert result.data["age"] is None
        assert result.timed_out is False

    def test_age_none_when_birth_invalid(self):
        xcity = _make_xcity(birth="invalid-format")
        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["current_age"] is None
        assert result.data["age"] is None
        assert result.timed_out is False

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

    def test_consistency_full_happy_path(self):
        xcity = _make_xcity()
        graphis = _make_graphis()

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        self._assert_consistency(result.data)
        assert result.timed_out is False


# ---------------------------------------------------------------------------
# TestCacheTTL — cache hit/miss/expiry behaviour
# ---------------------------------------------------------------------------

class TestCacheTTL:

    def test_cache_hit_returns_stale_result(self):
        """Second call within TTL returns cached result; scrapers called only once."""
        xcity_first  = _make_xcity(name="初回結果")
        xcity_second = _make_xcity(name="二回目結果")

        mock_xcity = MagicMock(side_effect=[xcity_first, xcity_second])

        with patch(_PATCH_XCITY, mock_xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result1 = get_actress_profile(_ACTRESS_NAME)
            result2 = get_actress_profile(_ACTRESS_NAME)

        # Scraper should have been called exactly once (cache hit on second call)
        assert mock_xcity.call_count == 1
        # Both results should be identical (from cache)
        assert result1.data["all_sources"]["xcity"]["name_ja"] == "初回結果"
        assert result2.data == result1.data
        assert result1.timed_out is False
        assert result2.timed_out is False

    def test_cache_expired_fetches_fresh(self):
        """Stale cache entry (older than TTL) causes fresh scraper call."""
        from core.scrapers.actress.orchestrator import _cache, _CACHE_TTL

        stale_result = {"__stale__": True, "name": "stale"}
        cache_key = "明里つむぎ"   # _normalize_name of _ACTRESS_NAME
        _cache[cache_key] = {
            "data": stale_result,
            "timestamp": time.time() - _CACHE_TTL - 10,  # expired
        }

        xcity = _make_xcity(name="fresh")
        mock_xcity = MagicMock(return_value=xcity)

        with patch(_PATCH_XCITY, mock_xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        # Fresh scraper should have been called
        assert mock_xcity.call_count == 1
        assert result.data["all_sources"]["xcity"]["name_ja"] == "fresh"
        assert result.timed_out is False


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

    def test_xcity_shell_does_not_suppress_wiki(self):
        """Parallel safety: if xcity returns a shell (no meaningful text), wiki wins."""
        xcity_shell = {
            "name_ja": _ACTRESS_NAME,
            "birth": "",
            "hometown": "",
            "height": "",
            "bust": "", "waist": "", "hip": "",
            "cup": "",
            "blood": "",
            "hobby": "",
            "photo_url": "https://xcity.jp/idol/shell.jpg",
        }
        wiki = _make_wiki()

        with patch(_PATCH_XCITY, return_value=xcity_shell), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data is not None
        assert result.data["primary_text_source"] == "wiki"
        assert result.timed_out is False

    def test_all_shells_no_text_source(self):
        """All text sources return shells (no meaningful text) → primary_text_source None.
        xcity_shell/wiki_shell are truthy dicts, so orchestrator edge-case guard
        (not any([...])) does NOT fire early-return None. Result is non-None but
        primary_text_source=None and text=None; name falls back to queried arg."""
        xcity_shell = {"name_ja": _ACTRESS_NAME}
        wiki_shell = {"name_ja": _ACTRESS_NAME}

        with patch(_PATCH_XCITY, return_value=xcity_shell), \
             patch(_PATCH_WIKI, return_value=wiki_shell), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        # xcity_shell is truthy → not any([...]) guard does not fire
        # but neither shell has meaningful text, so cascade picks no text source
        assert result.data is not None
        assert result.data["primary_text_source"] is None
        assert result.data["text"] is None
        assert result.data["current_age"] is None
        # Bug 2 fix: name falls back to queried arg when text is None
        assert result.data["name"] == _ACTRESS_NAME
        assert result.timed_out is False

    def test_wiki_other_names_only_wins_c1(self):
        """Codex PR #23 P2: Wiki's `other_names` (別名/芸名 row) must count as
        meaningful text. `wiki_ja._parse_wiki_ja_html` explicitly allows alias-only
        infoboxes to return a dict (rather than None) — see test_bieimei_only_infobox_returns_dict_not_none
        in test_scraper_actress_wiki_ja.py. If orchestrator's _MEANINGFUL_TEXT_FIELDS
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


def test_get_actress_profile_preview_does_not_pollute_cache():
    name = "某女優"
    first_sources = {"xcity": {"photo_url": "https://faws.xcity.jp/first.jpg"},
                     "wiki": None, "graphis": None, "gfriends": None}
    second_sources = {"xcity": {"photo_url": "https://faws.xcity.jp/second.jpg"},
                      "wiki": None, "graphis": None, "gfriends": None}
    cache_size_before = len(_cache)
    cache_before = dict(_cache)

    with patch.object(orchestrator, "_fetch_all_sources", side_effect=[first_sources, second_sources]) as fetch:
        first = orchestrator.get_actress_profile_preview(name)
        second = orchestrator.get_actress_profile_preview(name)

    assert first == {"name": name, "sources": first_sources}
    assert second == {"name": name, "sources": second_sources}
    assert fetch.call_count == 2
    assert len(_cache) == cache_size_before
    assert _cache == cache_before
    assert orchestrator._normalize_name(name) not in _cache


def test_sources_to_photo_candidates_xcity_only():
    sources = {"xcity": {"photo_url": "https://faws.xcity.jp/x.jpg"},
               "wiki": None, "graphis": None, "gfriends": None}

    assert orchestrator._sources_to_photo_candidates(sources) == [
        {"source": "xcity", "url": "https://faws.xcity.jp/x.jpg"}
    ]


def test_sources_to_photo_candidates_no_photos():
    sources = {"xcity": {"photo_url": ""}, "wiki": {},
               "graphis": {"prof_url": None}, "gfriends": None}

    assert orchestrator._sources_to_photo_candidates(sources) == []


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

    def test_avbase_value_reaches_sources_and_each_source_called_once(self):
        xcity = MagicMock(return_value=_AV_XCITY)
        wiki = MagicMock(return_value=_AV_WIKI)
        graphis = MagicMock(return_value=_AV_GRAPHIS)
        gfriends = MagicMock(return_value=_AV_GFRIENDS)
        avbase = MagicMock(return_value=_AV_AVBASE)

        sources, _ = _run_fetch(xcity, wiki, graphis, gfriends, avbase)

        assert dict(sources) == {
            "xcity": _AV_XCITY,
            "wiki": _AV_WIKI,
            "graphis": _AV_GRAPHIS,
            "gfriends": _AV_GFRIENDS,
            "avbase": _AV_AVBASE,
        }
        assert sources.timed_out is False
        for stub in (xcity, wiki, graphis, gfriends, avbase):
            assert stub.call_count == 1
        xcity.assert_called_once_with(_AV_NAME)
        wiki.assert_called_once_with(_AV_NAME)
        graphis.assert_called_once_with(_AV_NAME)
        gfriends.assert_called_once_with(_AV_NAME, ["S1"])
        avbase.assert_called_once_with(_AV_NAME)

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
        MagicMock(return_value=None),
        MagicMock(side_effect=RuntimeError("avbase boom")),
    ], ids=["returns_none", "raises"])
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

    def test_existing_sources_all_hang_avbase_still_delivered(self, monkeypatch):
        monkeypatch.setattr(orchestrator, "_FETCH_BUDGET_S", 0.3)
        ev = threading.Event()
        done = threading.Semaphore(0)
        try:
            sources, elapsed = _run_fetch(
                _hanging_stub(ev, done),
                _hanging_stub(ev, done),
                _hanging_stub(ev, done),
                _hanging_stub(ev, done),
                MagicMock(return_value=_AV_AVBASE),
            )
            assert elapsed <= 0.3 + 0.5
            assert sources.timed_out is True
            assert dict(sources) == {
                "xcity": None,
                "wiki": None,
                "graphis": None,
                "gfriends": None,
                "avbase": _AV_AVBASE,
            }
        finally:
            ev.set()
        for _ in range(4):
            assert done.acquire(timeout=_AV_SAFETY_S + 1), "卡住的 worker 未結束"


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

    def test_wiki_lacks_hobby_xcity_supplies_it(self):
        data = _fo_profile(_FO_XCITY, _FO_WIKI, _FO_GRAPHIS, _FO_AVBASE)
        assert "hobby" not in _FO_WIKI
        assert data["text"].get("hobby") == "xcity趣味"

    def test_front_three_lack_birth_avbase_supplies_it(self):
        wiki = {k: v for k, v in _FO_WIKI.items() if k != "birth"}
        xcity = {k: v for k, v in _FO_XCITY.items() if k != "birth"}
        graphis = {k: v for k, v in _FO_GRAPHIS.items() if k != "birth"}
        data = _fo_profile(xcity, wiki, graphis, _FO_AVBASE)
        text = data["text"]
        assert text.get("birth") == _FO_AVBASE["birth"]
        assert text.get("height") == _FO_WIKI["height"]
        assert text.get("hobby") == "xcity趣味"

    def test_avbase_never_used_when_first_three_together_cover_every_field(self):
        # 前三家各供一部分欄位、分攤在三個名次：avbase 排進任何一家之前都會紅
        wiki = {"name_ja": _AV_NAME, "birth": "1991-01-01", "height": "151cm", "hometown": "東京都"}
        xcity = {"name_ja": _AV_NAME, "bust": "82cm", "waist": "62cm", "cup": "D"}
        graphis = {"hip": "93cm", "hobby": "graphis趣味"}
        data = _fo_profile(xcity, wiki, graphis, _FO_AVBASE)
        expected = {
            "birth": "1991-01-01", "height": "151cm", "hometown": "東京都",
            "bust": "82cm", "waist": "62cm", "cup": "D",
            "hip": "93cm", "hobby": "graphis趣味",
        }
        assert data["text"] == expected
        assert not (set(data["text"].values()) & set(_FO_AVBASE.values()))

    def test_only_avbase_has_data_text_and_primary_from_avbase(self):
        data = _fo_profile(avbase=_FO_AVBASE)
        assert data["text"] == _FO_AVBASE
        assert data["primary_text_source"] == "avbase"

    def test_primary_xcity_when_wiki_absent(self):
        data = _fo_profile(_FO_XCITY, None, _FO_GRAPHIS, _FO_AVBASE)
        assert data["primary_text_source"] == "xcity"

    def test_avbase_alias_only_is_not_primary_text_source(self):
        data = _fo_profile(avbase={"other_names": ["二階堂れい"]})
        assert data is not None
        assert data["primary_text_source"] is None


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

    def test_clean_aliases_drops_own_name_keeps_other_name(self):
        names = ["二階堂麗", "あかね麗"]
        assert orchestrator._clean_aliases(names, "二階堂麗") == ["あかね麗"]
        assert orchestrator._clean_aliases(names, "あかね麗") == ["二階堂麗"]

    def test_clean_aliases_drops_at_prefixed_accounts(self):
        assert orchestrator._clean_aliases(
            ["@Faerina", "@久世ミコト", "久世ミコト"], "別人") == ["久世ミコト"]
        assert orchestrator._clean_aliases(["＠abc", "真別名"], "別人") == ["真別名"]

    def test_clean_aliases_treats_fullwidth_own_name_as_same(self):
        assert orchestrator._clean_aliases(["ABC", "別名"], "ＡＢＣ") == ["別名"]

    def test_clean_aliases_dedupes_and_ignores_blank_and_non_str(self):
        names = ["甲", "甲", "", "   ", None, 123, "乙"]
        assert orchestrator._clean_aliases(names, "own") == ["甲", "乙"]
        assert orchestrator._clean_aliases(None, "own") == []


_AL_OWN = "二階堂麗"
_AL_WIKI_ALIAS = "維基別名"
_AL_AV_NAMES = ["avbase別名甲", "avbase別名乙", "avbase別名丙"]


class TestAliasChain:

    def test_wiki_aliases_win_over_avbase_even_when_avbase_has_more(self):
        data = _al_profile(
            _AL_OWN,
            wiki={"name_ja": _AL_OWN, "other_names": [_AL_WIKI_ALIAS]},
            avbase={"other_names": list(_AL_AV_NAMES)},
        )
        assert data["text"]["aliases"] == [_AL_WIKI_ALIAS]

    def test_wiki_with_only_own_name_falls_through_to_avbase(self):
        for wiki_names in ([_AL_OWN], ["@wikiacct"]):
            orchestrator._cache.clear()
            data = _al_profile(
                _AL_OWN,
                wiki={"name_ja": _AL_OWN, "other_names": list(wiki_names)},
                avbase={"other_names": [_AL_OWN, "@acct", *_AL_AV_NAMES]},
            )
            assert data["text"]["aliases"] == _AL_AV_NAMES

    def test_wiki_aliases_are_filtered_too_and_still_win(self):
        data = _al_profile(
            _AL_OWN,
            wiki={"name_ja": _AL_OWN, "other_names": [_AL_OWN, _AL_WIKI_ALIAS]},
            avbase={"other_names": list(_AL_AV_NAMES)},
        )
        assert data["text"]["aliases"] == [_AL_WIKI_ALIAS]

    def test_avbase_aliases_used_when_wiki_absent_for_both_query_names(self):
        av = ["二階堂麗", "あかね麗"]
        data = _al_profile("二階堂麗", avbase={"other_names": list(av)})
        assert data["text"]["aliases"] == ["あかね麗"]
        orchestrator._cache.clear()
        data = _al_profile("あかね麗", avbase={"other_names": list(av)})
        assert data["text"]["aliases"] == ["二階堂麗"]

    def test_alias_only_avbase_result_becomes_text_aliases(self):
        data = _al_profile("二階堂麗", avbase={"other_names": ["二階堂麗", "あかね麗"]})
        assert data is not None
        assert data["text"] == {"aliases": ["あかね麗"]}
        assert data["primary_text_source"] is None

    def test_no_aliases_key_when_neither_source_has_any(self):
        data = _al_profile(
            _AL_OWN,
            wiki={"name_ja": _AL_OWN, "birth": "1991-01-01", "other_names": [_AL_OWN]},
            avbase={"other_names": ["@acct"]},
        )
        assert data["text"] == {"birth": "1991-01-01"}
        assert "aliases" not in data["text"]
        orchestrator._cache.clear()
        data = _al_profile(
            _AL_OWN,
            graphis={"prof_url": "https://example.com/p.jpg"},
            avbase={"other_names": [_AL_OWN, "@acct"]},
        )
        assert data["text"] is None

    def test_aliases_do_not_change_other_field_sources(self):
        data = _al_profile(
            _AL_OWN,
            wiki={"name_ja": _AL_OWN, "other_names": [_AL_WIKI_ALIAS]},
            avbase={"birth": "1994-04-04", "other_names": list(_AL_AV_NAMES)},
        )
        assert data["text"]["birth"] == "1994-04-04"
        assert data["text"]["aliases"] == [_AL_WIKI_ALIAS]

    def test_all_sources_other_names_stay_unfiltered(self):
        wiki_names = [_AL_OWN, "@wikiacct", _AL_WIKI_ALIAS]
        av_names = [_AL_OWN, "@avacct", *_AL_AV_NAMES]
        wiki_copy, av_copy = list(wiki_names), list(av_names)
        data = _al_profile(
            _AL_OWN,
            wiki={"name_ja": _AL_OWN, "other_names": wiki_names},
            avbase={"other_names": av_names},
        )
        assert data["all_sources"]["wiki"]["other_names"] == wiki_copy
        assert data["all_sources"]["avbase"]["other_names"] == av_copy
