"""175b-T8c：smart_search 的 maker 分支。

patch 使用端：core.scraper.search_maker、core.maker_names.known_makers（函式內 import 的名字）。
不連外、不存站方檔（BE-TEST-43）。
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

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


def test_meta_carries_maker_has_more(env):
    """使用者打片商名、這頁有 1 部詳情失敗只剩 19 張 → 「載入更多」仍依來源 has_more"""
    env.sm.return_value = MakerSearchResult(_cards(*[f"SOD-{i}" for i in range(19)]), True, None)
    meta = {}
    smart_search("SOD", resolve_makers=True, meta=meta)
    assert meta == {"has_more": True}
    env.sm.return_value = MakerSearchResult(_cards(*[f"SOD-{i}" for i in range(20)]), False, None)
    meta = {}
    smart_search("SOD", resolve_makers=True, meta=meta)
    assert meta == {"has_more": False}
    assert smart_search("SOD", resolve_makers=True)  # 不傳 meta 不報錯


def test_library_read_failure_gives_empty_titles_and_still_answers():
    with patch("core.maker_names.known_makers", return_value=KNOWN), \
         patch("core.scraper.is_uncensored_route", return_value=False), \
         patch("core.config.get_configured_gallery_dirs", side_effect=RuntimeError("boom")), \
         patch("core.scraper.search_maker") as sm:
        sm.return_value = MakerSearchResult(_cards("SOD-1"), False, None)
        out = smart_search("SOD", resolve_makers=True)
    assert sm.call_args.kwargs["titles"] == []
    assert len(out) == 1


