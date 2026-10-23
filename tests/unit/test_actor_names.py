"""175d-T1：名稱組純函式（actor_names）。期望值字面寫死，輸入全是我們自己的字串與 tmp sqlite。"""


import pytest

from core.search_providers.actor_names import (
    expand_actor_names,
    load_alias_groups,
)

G_AKANE = ("二階堂麗", ["あかね麗"])
G_MIRU = ("坂道みる", ["miru"])
# ---------- expand_actor_names ----------


@pytest.mark.parametrize("q", ["あかね麗"])
def test_expand_same_list_from_any_member(q):
    assert expand_actor_names(q, [G_AKANE]) == ["二階堂麗", "あかね麗"]


@pytest.mark.parametrize("q", ["ｍｉｒｕ"])
def test_expand_folds_width_and_case(q):
    assert expand_actor_names(q, [G_AKANE, G_MIRU]) == ["坂道みる", "miru"]


@pytest.mark.parametrize(
    "q,groups",
    [("山田花子", [G_AKANE, G_MIRU]), ],
)
def test_expand_miss_returns_query_itself(q, groups):
    assert expand_actor_names(q, groups) == [q]


# ---------- needs_swap_first ----------


# ---------- swap_candidates ----------


# ---------- load_alias_groups ----------


@pytest.fixture
def db_dir(tmp_path, monkeypatch):
    """DB 路徑導到 tmp 下一個『目錄存在、檔案不存在』的位置。"""
    d = tmp_path / "dbdir"
    d.mkdir()
    path = d / "openaver.db"
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: path)
    return path


def test_load_alias_groups_returns_groups_from_tmp_db(db_dir):
    from core.database import AliasRepository, init_db

    init_db(db_dir)
    repo = AliasRepository(db_dir)
    repo.add("二階堂麗", ["あかね麗"])
    repo.add("坂道みる", ["miru", "Miru S"])
    assert load_alias_groups() == [("二階堂麗", ["あかね麗"]), ("坂道みる", ["miru", "Miru S"])]


# =====================================================================
# 175d-T2：provider 可選方法（JavBus resolve_all／JavDB alt_names）
# 輸入全是我們自己構造的 StarCard／Candidate／EntityRef；私有縫 _lookup 被 stub，不碰傳輸。
# =====================================================================
from core.scrapers.errors import SourceUnreachable  # noqa: E402
from core.scrapers.javbus import StarCard  # noqa: E402
from core.search_providers.javbus import JavBusProvider, _pick_stars  # noqa: E402
from core.search_providers.types import EntityRef, Kind  # noqa: E402

# ---------- _pick_stars ----------


def test_pick_stars_rejects_substring_and_accepts_width_case():
    cards = [StarCard("star/x", "美咲愛子", False), StarCard("star/m", "ＭＩＲＵ", False)]
    assert _pick_stars(cards, "美咲愛") == []
    assert [c.id for c in _pick_stars(cards, "miru")] == ["star/m"]


# ---------- actor_alt_names ----------


# ---------- JavBus resolve_all ----------

_REF_C = EntityRef(Kind.ACTOR, "star/36h", "美咲愛")


def _stub_lookup(monkeypatch, results):
    calls = []

    def stub(self, kind, name):
        calls.append((kind, name))
        r = results[min(len(calls), len(results)) - 1]
        if isinstance(r, BaseException):
            raise r
        return r

    monkeypatch.setattr(JavBusProvider, "_lookup", stub)
    return calls


def test_javbus_lookup_exception_is_not_cached(monkeypatch):
    calls = _stub_lookup(monkeypatch, [SourceUnreachable("down"), (_REF_C,)])
    p = JavBusProvider()
    with pytest.raises(SourceUnreachable):
        p.resolve_all(Kind.ACTOR, "美咲愛")
    assert p.resolve_all(Kind.ACTOR, "美咲愛") == [_REF_C]
    assert len(calls) == 2


# ---------- JavDB alt_names ----------

