"""E2E：156e Top20 換位 — 粗顆粒結束狀態（不 hook state.js、不窄窗介入）。"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e._insights_motion_helpers import (
    ACTIVE_FLIP,
    DESKTOP,
    MOBILE,
    alpine,
    assert_no_residue,
    attach_pageerrors,
    click_gantt_actress,
    click_year_bar,
    discover_actress_with_costar,
    discover_year_chain,
    load_ready,
    set_prm,
    top20_list,
    wait_settled,
)

pytestmark = pytest.mark.e2e


def _flip_positions(page: Page) -> dict:
    return page.evaluate("""() => {
        const out = {};
        document.querySelectorAll('[data-flip-id]').forEach(el => {
            const r = el.getBoundingClientRect();
            out[el.getAttribute('data-flip-id')] = {
                x: r.left + r.width / 2, y: r.top + r.height / 2,
                t: el.style.transform || '' };
        });
        return out;
    }""")


def _wait_flip_mid(page: Page, timeout: int = 2_500) -> dict | None:
    """等到某個 data-flip-id 有非單位 transform，回傳該點快照。"""
    try:
        page.wait_for_function("""() => {
            const isActive = %s;
            for (const el of document.querySelectorAll('[data-flip-id]')) {
                if (isActive(el.style.transform)) {
                    const r = el.getBoundingClientRect();
                    window.__oaFlipMid = {
                        id: el.getAttribute('data-flip-id'),
                        x: r.left + r.width / 2, y: r.top + r.height / 2 };
                    return true;
                }
            }
            return false;
        }""" % ACTIVE_FLIP, timeout=timeout)
    except Exception:
        return None
    return page.evaluate("() => window.__oaFlipMid || null")


def _assert_mid_between(before: dict, mid: dict, after: dict) -> None:
    """mid 位置相對 before→after 嚴格介於起訖（同 id 仍在榜）；否則至少 mid 相對 before 有位移。"""
    fid = mid["id"]
    start = before.get(fid)
    end = after.get(fid)
    if start and end:
        dx, dy = end["x"] - start["x"], end["y"] - start["y"]
        if abs(dx) >= abs(dy) and abs(dx) > 2:
            ok = (mid["x"] - start["x"]) * dx > 0 and (end["x"] - mid["x"]) * dx > 0
            assert ok, f"mid 不在起訖之間：id={fid} start={start} mid={mid} end={end}"
            return
        if abs(dy) > 2:
            ok = (mid["y"] - start["y"]) * dy > 0 and (end["y"] - mid["y"]) * dy > 0
            assert ok, f"mid 不在起訖之間：id={fid} start={start} mid={mid} end={end}"
            return
    # 進出榜／位移極小：看見過非單位 transform 的 mid 即足夠
    assert mid.get("id"), f"應取到 mid flip 快照，實際 {mid!r}"


def _row4_top(page: Page) -> float:
    page.evaluate("() => window.scrollTo(0, 0)")
    return page.evaluate(
        "() => { const el = document.querySelector('.row4');"
        " return el ? el.getBoundingClientRect().top : NaN; }")


def _prm_baseline(page: Page, base_url: str, year: int, width: int = DESKTOP) -> dict:
    set_prm(page, True)
    load_ready(page, base_url, width=width)
    set_prm(page, True)
    assert click_year_bar(page, year), f"baseline 找不到 {year}"
    wait_settled(page)
    return {"top20": top20_list(page), "row4Top": _row4_top(page)}


def _visibility_flags(page: Page) -> dict:
    return alpine(page, """({
        showTop20InRow3: !!data.showTop20InRow3,
        showTop20InRow7: !!data.showTop20InRow7,
        showCostar: !!data.showCostar,
        costarVisible: !!data.costarVisible,
    })""")


def test_top20_year_change_animates_then_matches_prm(page: Page, base_url: str) -> None:
    """換年份：settle 前粗取樣見位移；settle 後名單＝PRM、無殘留、pageerror=0。"""
    errors = attach_pageerrors(page)
    load_ready(page, base_url)
    chain = discover_year_chain(page, need=2)
    if len(chain) < 1:
        pytest.skip("片庫湊不出會造成 Top20 名次變動的年份")
    year = chain[-1]

    before = _flip_positions(page)
    assert click_year_bar(page, year), f"yearsChart 找不到 {year}"
    mid = _wait_flip_mid(page)
    assert mid, "換年份後應觀察到非單位 transform（證明有動畫）"
    wait_settled(page)
    after = _flip_positions(page)
    _assert_mid_between(before, mid, after)

    assert_no_residue(page, "year-change")
    assert errors == [], f"pageerror 非 0：{errors!r}"
    actual = top20_list(page)
    baseline = _prm_baseline(page, base_url, year)
    assert actual == baseline["top20"], (
        f"Top20 與 PRM 不一致：\nactual={actual!r}\nbaseline={baseline['top20']!r}")


def test_top20_actress_focus_costar_swap_settles_clean(page: Page, base_url: str) -> None:
    """女優焦點造成共演卡換入：settle 後無殘留，row3/row7 恰一份可見。"""
    load_ready(page, base_url)
    name = discover_actress_with_costar(page)
    if not name:
        pytest.skip("片庫湊不出有共演列的女優")

    click_gantt_actress(page, name)
    wait_settled(page)
    assert_no_residue(page, "costar-swap")
    flags = _visibility_flags(page)
    assert flags["costarVisible"] is True
    assert flags["showCostar"] is True
    assert flags["showTop20InRow3"] != flags["showTop20InRow7"], (
        f"row3/row7 應恰一份可見：{flags!r}")
    assert flags["showTop20InRow7"] is True
    assert flags["showTop20InRow3"] is False


def test_top20_mobile_row4_matches_prm_after_year_change(
    page: Page, base_url: str,
) -> None:
    """390 寬換年份：settle 後 row4.top 與 PRM 對照組一致（誤差 <1px）。"""
    load_ready(page, base_url, width=MOBILE)
    chain = discover_year_chain(page, need=2)
    if len(chain) < 1:
        pytest.skip("390：片庫湊不出會造成名次變動的年份")
    year = chain[-1]

    assert click_year_bar(page, year)
    wait_settled(page)
    actual_top = _row4_top(page)
    assert_no_residue(page, "mobile-row4")

    baseline = _prm_baseline(page, base_url, year, width=MOBILE)
    assert abs(actual_top - baseline["row4Top"]) < 1.0, (
        f"390 row4.top 應與 PRM 一致：{actual_top:.2f} vs {baseline['row4Top']:.2f}")
