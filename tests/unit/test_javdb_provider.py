"""175b-T2：JavDB parser（候選／列表列／詳情事實）。測試資料全為檔內合成 dict。"""

from __future__ import annotations

from core.search_providers.javdb import (
    list_page,
)


def _rows(n):
    return [{"id": f"m{i}", "number": f"AAA-{i:03d}"} for i in range(n)]


class TestListPage:
    def test_full_page_below_cap_has_next(self):
        p = list_page(_rows(50), 98)
        assert p.has_next is True
        assert len(p.items) == 50
        assert p.total is None


    def test_short_page_has_no_next(self):
        assert list_page(_rows(49), 1).has_next is False

