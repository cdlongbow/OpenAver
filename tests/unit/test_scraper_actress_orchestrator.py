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

import time
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from core.scrapers.actress import orchestrator
from core.scrapers.actress.orchestrator import get_actress_profile, get_cached_profile, ProfileResult, _cache, _CACHE_TTL, _compute_age_from_birth

# ---------------------------------------------------------------------------
# Patch target constants
# ---------------------------------------------------------------------------
_PATCH_XCITY  = 'core.scrapers.actress.xcity.scrape_xcity'
_PATCH_WIKI     = 'core.scrapers.actress.wiki_ja.scrape_wiki_ja'
_PATCH_GRAPHIS  = 'core.scrapers.actress.graphis.scrape_graphis_photo'
_PATCH_GFRIENDS = 'core.scrapers.actress.gfriends.lookup_gfriends'

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

    def test_all_four_routes_not_none(self):
        xcity = _make_xcity()
        wiki    = _make_wiki()
        graphis = _make_graphis()
        gfurl   = _make_gfriends_url()

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=gfurl):
            result = get_actress_profile(_ACTRESS_NAME)

        assert isinstance(result, ProfileResult)
        assert result.data is not None
        assert result.timed_out is False

    def test_primary_text_source_xcity(self):
        xcity = _make_xcity()
        wiki    = _make_wiki()
        graphis = _make_graphis()
        gfurl   = _make_gfriends_url()

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=gfurl):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["primary_text_source"] == "xcity"
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

    def test_all_sources_dict(self):
        xcity = _make_xcity()
        wiki    = _make_wiki()
        graphis = _make_graphis()
        gfurl   = _make_gfriends_url()

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=gfurl):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["all_sources"]["xcity"] == xcity
        assert result.data["all_sources"]["wiki"] == wiki
        assert result.data["all_sources"]["graphis"] == graphis
        assert result.data["all_sources"]["gfriends"] == gfurl
        assert result.timed_out is False

    def test_legacy_flat_name_and_img(self):
        xcity = _make_xcity()
        graphis = _make_graphis()

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["name"] == xcity["name_ja"]
        assert result.data["img"] == result.data["photo_url"]
        assert result.timed_out is False


# ---------------------------------------------------------------------------
# TestC1Cascade — text primary source fallback
# ---------------------------------------------------------------------------

class TestC1Cascade:

    def test_merge_text_fields_xcity_wins_over_wiki_when_both_have_value(self):
        xcity = _make_xcity(hometown="", height="160cm")
        wiki = _make_wiki(hometown="東京都", height="155cm")

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["text"]["hometown"] == "東京都"
        assert result.data["text"]["height"] == "160cm"

    def test_merge_aliases_from_wiki_other_names(self):
        wiki = _make_wiki(other_names=["別名1", "別名2"])

        with patch(_PATCH_XCITY, return_value=None), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["text"]["aliases"] == ["別名1", "別名2"]

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

    def test_graphis_no_prof_url_gfriends_wins(self):
        xcity = _make_xcity()
        # Graphis present but prof_url missing/empty
        graphis = _make_graphis(prof_url="")
        gfurl   = _make_gfriends_url()

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=gfurl):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["photo_source"] == "gfriends"
        assert result.data["photo_url"] == gfurl
        assert result.data["img"] == gfurl
        assert result.timed_out is False

    def test_graphis_none_gfriends_none_wiki_wins(self):
        wiki = _make_wiki()

        with patch(_PATCH_XCITY, return_value=None), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["photo_source"] == "wiki"
        assert result.data["photo_url"] == wiki["photo_url"]
        assert result.timed_out is False

    def test_only_xcity_has_photo(self):
        xcity = _make_xcity()

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["photo_source"] == "xcity"
        assert result.data["photo_url"] == xcity["photo_url"]
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

    def test_age_consistency_age_equals_current_age(self):
        xcity = _make_xcity(birth="1995-06-15")
        FrozenDT = _frozen_dt_class(datetime(2026, 7, 1))

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=None), \
             patch(_PATCH_GFRIENDS, return_value=None), \
             patch('core.scrapers.actress.orchestrator.datetime', FrozenDT):
            result = get_actress_profile(_ACTRESS_NAME)

        assert result.data["age"] == result.data["current_age"]
        assert result.timed_out is False


# ---------------------------------------------------------------------------
# TestComputeAgeUnit — unit tests for _compute_age_from_birth directly
# ---------------------------------------------------------------------------

class TestComputeAgeUnit:

    def test_compute_age_before_birthday(self):
        FrozenDT = _frozen_dt_class(datetime(2026, 1, 1))
        with patch('core.scrapers.actress.orchestrator.datetime', FrozenDT):
            assert _compute_age_from_birth("1998-03-31") == 27

    def test_compute_age_after_birthday(self):
        FrozenDT = _frozen_dt_class(datetime(2026, 4, 1))
        with patch('core.scrapers.actress.orchestrator.datetime', FrozenDT):
            assert _compute_age_from_birth("1998-03-31") == 28

    def test_compute_age_none_birth(self):
        assert _compute_age_from_birth(None) is None

    def test_compute_age_invalid_birth(self):
        assert _compute_age_from_birth("not-a-date") is None


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

    def test_consistency_wiki_as_text_source(self):
        wiki    = _make_wiki()
        graphis = _make_graphis()

        with patch(_PATCH_XCITY, return_value=None), \
             patch(_PATCH_WIKI, return_value=wiki), \
             patch(_PATCH_GRAPHIS, return_value=graphis), \
             patch(_PATCH_GFRIENDS, return_value=None):
            result = get_actress_profile(_ACTRESS_NAME)

        self._assert_consistency(result.data)
        assert result.timed_out is False

    def test_consistency_only_xcity(self):
        xcity = _make_xcity()

        with patch(_PATCH_XCITY, return_value=xcity), \
             patch(_PATCH_WIKI, return_value=None), \
             patch(_PATCH_GRAPHIS, return_value=None), \
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


def test_get_actress_profile_preview_all_sources_miss():
    sources = {"xcity": None, "wiki": None, "graphis": None, "gfriends": None}

    with patch.object(orchestrator, "_fetch_all_sources", return_value=sources):
        result = orchestrator.get_actress_profile_preview("某女優")

    assert result == {"name": "某女優", "sources": sources}
