"""175b-T8c：smart_search 的 maker 分支。

patch 使用端：core.scraper.search_maker、core.maker_names.known_makers（函式內 import 的名字）。
不連外、不存站方檔（BE-TEST-43）。
"""

import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.maker_names import maker_key_of
from core.scraper import smart_search
from core.search_providers.types import MakerSearchResult

KNOWN = frozenset({"sod", "s1"})


def _cards(*nums):
    return [{"number": n, "title": n} for n in nums]


@pytest.fixture
def env():
    with patch("core.maker_names.known_makers", return_value=KNOWN), \
         patch("core.scraper.is_uncensored_route", return_value=False), \
         patch("core.scraper._library_title_list", return_value=["T"]) as lib, \
         patch("core.scraper.search_maker") as sm:
        sm.return_value = MakerSearchResult(_cards("SOD-1", "SOD-2"), True, None)
        yield SimpleNamespace(sm=sm, lib=lib)


def test_maker_branch_no_longer_raises_and_returns_list(env):
    out = smart_search("SOD", resolve_makers=True)
    assert [c["number"] for c in out] == ["SOD-1", "SOD-2"]
    env.sm.assert_called_once()


def test_maker_cards_are_tagged_with_maker_mode(env):
    out = smart_search("SOD", resolve_makers=True)
    assert out and all(c["_mode"] == "maker" for c in out)


def test_typed_and_capsule_share_the_same_maker_key(env):
    smart_search("S1", resolve_makers=True)
    args, kwargs = env.sm.call_args
    assert args[0] == maker_key_of("S1")
    assert args[1] == "S1"


def test_passes_spellings_limit_offset_titles_today(env):
    with patch("core.maker_names.load_name_mapping", return_value={"SOD": "SOD Create"}), \
         patch("core.maker_names.load_search_aliases", return_value={}):
        smart_search("SOD", limit=7, offset=3, resolve_makers=True)
    args, kwargs = env.sm.call_args
    assert "SOD Create" in args[2] and args[2][0] == "SOD"
    assert args[3] == 3
    assert kwargs["limit"] == 7
    assert kwargs["titles"] == ["T"]
    assert kwargs["today"] == datetime.date.today()
    assert kwargs["db_path"] is not None


def test_library_read_failure_gives_empty_titles_and_still_answers():
    with patch("core.maker_names.known_makers", return_value=KNOWN), \
         patch("core.scraper.is_uncensored_route", return_value=False), \
         patch("core.config.get_configured_gallery_dirs", side_effect=RuntimeError("boom")), \
         patch("core.scraper.search_maker") as sm:
        sm.return_value = MakerSearchResult(_cards("SOD-1"), False, None)
        out = smart_search("SOD", resolve_makers=True)
    assert sm.call_args.kwargs["titles"] == []
    assert len(out) == 1


def test_not_found_is_plain_empty(env):
    env.sm.return_value = MakerSearchResult([], False, "maker_not_found")
    assert smart_search("SOD", resolve_makers=True) == []


def test_without_resolve_makers_branch_not_entered(env):
    with patch("core.scraper.search_actress", return_value=[]), \
         patch("core.scraper.search_prefix", return_value=[]), \
         patch("core.scraper.search_jav321_keyword", return_value=[]):
        smart_search("SOD", resolve_makers=False)
    env.sm.assert_not_called()
    env.lib.assert_not_called()
