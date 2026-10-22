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


# ---- cf_available_here()（168d-T1）----


def test_cf_available_here_exception_false():
    class T:
        def available_here(self): raise RuntimeError("boom")

    m.register_cf_transport(T())
    assert m.cf_available_here() is False
