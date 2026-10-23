"""
test_javdb_resolve.py - JavDB「名字→實體」resolve（175b-T3）

候選全為檔內合成列；patch javdb_api.api_search_typed（模組屬性）與 javdb.py 內兩個對照表載入函式。
不連外、不存站方 fixture。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.scrapers import javdb_api
from core.scrapers.errors import SourceBlocked
from core.search_providers import javdb as jp
from core.search_providers.javdb import JavDBProvider, clear_resolve_cache
from core.search_providers.types import Kind


class _Scraper:
    def _proxy_kwargs(self):
        return {}


@pytest.fixture(autouse=True)
def _clean():
    clear_resolve_cache()
    with patch.object(jp, "_sleep", lambda s: None):
        yield
    clear_resolve_cache()


class _Site:
    """依 (type, q) 回合成列並記錄呼叫。"""

    def __init__(self, table=None, default=None, exc=None):
        self.table = table or {}
        self.default = default if default is not None else []
        self.exc = exc
        self.calls: list[tuple[str, str]] = []

    def __call__(self, t, q, proxies=None):
        self.calls.append((t, q))
        if self.exc is not None:
            raise self.exc
        return self.table.get((t, q), self.default)


def _resolve(kind, q, site, name_map=None, search_aliases=None):
    with patch.object(javdb_api, "api_search_typed", site), \
         patch.object(jp, "load_name_mapping", lambda: name_map or {}), \
         patch.object(jp, "load_search_aliases", lambda: search_aliases or {}):
        return JavDBProvider(scraper=_Scraper()).resolve(kind, q)


# ------------------------------------------------------------------ MAKER


def test_maker_requests_are_spaced():
    # 使用者搜一個要試好幾個別名的片商 → 若連打不間隔，壓力高於今天，IP 更容易被擋
    nm = {"a1": "Canon", "a2": "Canon"}
    sleeps: list[float] = []
    site = _Site(default=[])
    with patch.object(jp, "_sleep", sleeps.append):
        _resolve(Kind.MAKER, "Canon", site, name_map=nm)
    assert len(site.calls) == 3
    # 175b-T4a：節流併入單一後置點（每次請求完成後 sleep），3 次請求 ⇒ 3 次
    assert len(sleeps) == 3 and all(s >= 0.3 for s in sleeps)


# ------------------------------------------------------------------ 快取


@pytest.mark.parametrize("exc", [SourceBlocked("b")])
@pytest.mark.parametrize("kind", [Kind.ACTOR])
def test_exception_not_cached_and_propagates(kind, exc):
    bad = _Site(exc=exc)
    with pytest.raises(type(exc)):
        _resolve(kind, "名前", bad)
    n_bad = len(bad.calls)
    assert n_bad > 0
    good = _Site(default=[])
    _resolve(kind, "名前", good)
    assert len(good.calls) > 0  # 例外沒有被記成「確定查無」


# ------------------------------------------------------------------ provider 面


