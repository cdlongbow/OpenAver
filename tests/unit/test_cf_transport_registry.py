"""
Unit tests for core.cf_transport.get_cf_available_sites() — TASK-118a-T9.

register_cf_transport() 的既有測試在 tests/unit/test_cf_transport.py；本檔只加
get_cf_available_sites() 的四條分支（新檔，該行為是本 task 才新增）。
"""
import pytest

import core.cf_transport as m


@pytest.fixture(autouse=True)
def reset_transport():
    """Reset module-level singleton before and after each test to prevent cross-test pollution."""
    m.register_cf_transport(None)
    yield
    m.register_cf_transport(None)


def test_no_transport_registered_returns_empty_list():
    """沒 register → []（dev / LAN server：nothing is usable）。"""
    assert m.get_cf_available_sites() == []


def test_transport_without_available_sites_returns_none():
    """register 一個沒有 available_sites 的物件 → None（fail-open 分支）。

    這條特別重要：一個 predates available_sites() 的 transport 不代表它的
    視窗死了，回 [] 會讓一個能用的 JavLibrary 被灰掉。
    """
    class LegacyTransport:
        def begin_solve(self, origin_url: str, cache_key: str) -> None: ...
        def is_ready(self, cache_key: str) -> bool: return True
        def fetch(self, url: str, cache_key: str) -> str: return ""

    m.register_cf_transport(LegacyTransport())
    assert m.get_cf_available_sites() is None


def test_transport_reports_live_sites_returns_sorted_list():
    """register 一個回 ['fc-javten', 'javlibrary'] 的 → 排序後的 list。"""
    class FakeTransport:
        def begin_solve(self, origin_url: str, cache_key: str) -> None: ...
        def is_ready(self, cache_key: str) -> bool: return True
        def fetch(self, url: str, cache_key: str) -> str: return ""
        def available_sites(self) -> list[str]:
            return ['javlibrary', 'fc-javten']

    m.register_cf_transport(FakeTransport())
    assert m.get_cf_available_sites() == ['fc-javten', 'javlibrary']


def test_transport_available_sites_raises_returns_none_not_propagated():
    """available_sites() 拋例外 → None，且不往外拋。"""
    class BrokenTransport:
        def begin_solve(self, origin_url: str, cache_key: str) -> None: ...
        def is_ready(self, cache_key: str) -> bool: return True
        def fetch(self, url: str, cache_key: str) -> str: return ""
        def available_sites(self) -> list[str]:
            raise RuntimeError("boom")

    m.register_cf_transport(BrokenTransport())
    assert m.get_cf_available_sites() is None
