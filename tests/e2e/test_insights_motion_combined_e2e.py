"""E2E：TASK-156e-T4 收窄版 — 三項疊加結束狀態（1440/390 × 淺/深）。

換年份 → 馬上點女優榜名單列 → 再換年份 → 真 click 片商扇區 → settle。
斷言：pageerror=0、無殘留替身／非單位 transform、390 無水平捲軸、最終＝PRM 對照組。
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e._insights_motion_helpers import (
    ALPINE,
    assert_no_residue,
    attach_pageerrors,
    chart_years,
    click_donut_named_maker,
    click_year_bar,
    discover_year_chain,
    load_ready,
    wait_scroll_settled,
    wait_settled,
)

pytestmark = pytest.mark.e2e

SETTLE_MS = 1_500
CASES = [(1440, "light"), (1440, "dim"), (390, "light"), (390, "dim")]


def _set_theme(page: Page, theme: str) -> None:
    page.evaluate(
        """(theme) => {
            const d = window.Alpine && Alpine.$data(document.documentElement);
            if (d && 'theme' in d) d.theme = theme;
            document.documentElement.setAttribute('data-theme', theme);
        }""",
        theme,
    )


def _end_snap(page: Page) -> dict:
    return page.evaluate(
        """() => {
            const data = Alpine.$data(document.querySelector('%s'));
            return {
                board: (data.boardRows || []).map(
                    (r) => ({ name: r.name, rank: r.rank, count: r.count })),
                scopedCount: data.scopedCount,
                displayScopedCount: data.displayScopedCount,
                focusName: data.sel.actress != null ? data.sel.actress : null,
                focus: { actress: data.sel.actress, maker: data.sel.maker },
            };
        }""" % ALPINE
    )


def _overflow_ok(page: Page) -> bool:
    return page.evaluate(
        "() => document.documentElement.scrollWidth"
        " <= document.documentElement.clientWidth"
    )


def _sample_overflow(page: Page, n: int = 4, interval_ms: int = 100) -> list:
    bad = []
    for _ in range(n):
        if not _overflow_ok(page):
            bad.append(page.evaluate(
                "() => ({sw: document.documentElement.scrollWidth,"
                " cw: document.documentElement.clientWidth})"
            ))
        page.wait_for_timeout(interval_ms)
    return bad


def _click_year(page: Page, year: int) -> bool:
    page.evaluate(
        """() => {
            const el = document.getElementById('yearsChart');
            if (el) el.scrollIntoView({ block: 'center', inline: 'nearest' });
        }"""
    )
    page.wait_for_timeout(40)
    return click_year_bar(page, year)


def _visible_board_name(page: Page) -> str | None:
    return page.evaluate(
        """() => {
            for (const sel of ['.board-rest-row', '.podium-slot']) {
                for (const row of document.querySelectorAll(sel)) {
                    const rr = row.getBoundingClientRect();
                    if (rr.width < 1 || rr.height < 1) continue;
                    const el = row.querySelector('.board-name, .podium-name');
                    const name = el && el.textContent.trim();
                    if (name) return name;
                }
            }
            return null;
        }"""
    )


def _click_board_list(page: Page, name: str) -> None:
    wait_scroll_settled(page)
    coords = page.evaluate(
        """(name) => {
            for (const sel of ['.board-rest-row', '.podium-slot']) {
                for (const row of document.querySelectorAll(sel)) {
                    const rr = row.getBoundingClientRect();
                    if (rr.width < 1 || rr.height < 1) continue;
                    const nameEl = row.querySelector('.board-name, .podium-name');
                    if (!nameEl || nameEl.textContent.trim() !== name) continue;
                    const av = row.querySelector('.board-avatar, .podium-avatar');
                    nameEl.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const nr = nameEl.getBoundingClientRect();
                    let x = nr.left + Math.min(
                        nr.width * 0.7, Math.max(12, nr.width - 8));
                    let y = nr.top + nr.height / 2;
                    if (av) {
                        const ar = av.getBoundingClientRect();
                        if (x >= ar.left && x <= ar.right
                                && y >= ar.top && y <= ar.bottom) {
                            x = Math.min(nr.right - 4, ar.right + 12);
                        }
                    }
                    return { found: true, x, y };
                }
            }
            return { found: false };
        }""",
        name,
    )
    assert coords.get("found"), f"可見女優榜名單找不到女優 {name!r}"
    page.mouse.click(coords["x"], coords["y"])


def _resolve_y2(page: Page, y1: int, preferred: int | None) -> int | None:
    cats = chart_years(page)
    if preferred is not None and preferred in cats and preferred != y1:
        return preferred
    for y in reversed(cats):
        if y != y1:
            return y
    return None


def _run_sequence(page: Page, y1: int, preferred_y2: int | None,
                  actress: str | None, sample_overflow: bool) -> tuple:
    bad: list = []
    assert _click_year(page, y1), f"yearsChart 找不到 {y1}"
    if sample_overflow:
        bad.extend(_sample_overflow(page, n=3, interval_ms=80))
    if actress is None:
        actress = _visible_board_name(page)
    assert actress, "換年後找不到可見女優榜名單列女優"
    _click_board_list(page, actress)
    page.wait_for_timeout(80)
    focused = _end_snap(page)["focusName"] or actress
    if sample_overflow:
        bad.extend(_sample_overflow(page, n=3, interval_ms=80))
    y2 = _resolve_y2(page, y1, preferred_y2)
    assert y2 is not None, f"焦點 {focused!r} 後 yearsChart 無第二個可點年份"
    assert _click_year(page, y2), f"yearsChart 找不到 {y2}"
    if sample_overflow:
        bad.extend(_sample_overflow(page, n=4, interval_ms=80))
    return bad, focused, y2


def _prm_baseline(page: Page, base_url: str, width: int, theme: str,
                  y1: int, y2: int, actress: str, maker: str | None) -> dict:
    page.emulate_media(reduced_motion="reduce")
    load_ready(page, base_url, width=width)
    _set_theme(page, theme)
    _run_sequence(page, y1, y2, actress, sample_overflow=False)
    if maker:
        # PRM 下重點同名片商（若軸上仍在）；失敗則略過 maker 對照
        got = click_donut_named_maker(page)
        if got:
            wait_settled(page)
    else:
        page.wait_for_timeout(SETTLE_MS)
    return _end_snap(page)


@pytest.mark.parametrize(
    "width,theme", CASES, ids=[f"{w}-{t}" for w, t in CASES],
)
def test_combined_end_state_after_year_actress_year(
    page: Page, base_url: str, width: int, theme: str,
) -> None:
    errors = attach_pageerrors(page)

    load_ready(page, base_url, width=width)
    _set_theme(page, theme)

    chain = discover_year_chain(page, need=2)
    if len(chain) < 1:
        pytest.skip("片庫湊不出會造成女優榜名次變動的年份")
    y1 = chain[0]
    preferred_y2 = chain[1] if len(chain) >= 2 else None

    overflow_bad, actress, y2 = _run_sequence(
        page, y1, preferred_y2, None, sample_overflow=(width == 390),
    )

    # 接手女優榜 dropout-ghost 回歸：真 click 片商扇區 → settle
    maker = click_donut_named_maker(page)
    if not maker:
        pytest.skip("片庫湊不出可點的片商扇形")
    wait_settled(page)

    assert errors == [], f"pageerror 非 0：{errors!r}"
    assert_no_residue(page, "combined")

    if width == 390:
        assert not overflow_bad, f"390 寬動畫中出現水平捲軸：{overflow_bad!r}"
        assert _overflow_ok(page), "settle 後仍有水平捲軸"

    actual = _end_snap(page)
    # 疊加：片商條件生效（以實際點到的為準），女優條件仍在
    assert actual["focus"]["maker"] == maker, (
        f"片商條件應生效，實際 {actual['focus']!r}"
    )
    assert actual["focus"]["actress"] == actress, (
        f"女優條件應保留（疊加不互斥），實際 {actual['focus']!r}"
    )
    assert actual["displayScopedCount"] == actual["scopedCount"], (
        f"頁首顯示未追上真相：display={actual['displayScopedCount']} "
        f"truth={actual['scopedCount']}"
    )

    baseline = _prm_baseline(
        page, base_url, width, theme, y1, y2, actress, maker)
    # 片商焦點後女優榜／scopedCount 應與 PRM 同序列一致
    assert actual["board"] == baseline["board"], (
        f"女優榜與 PRM 對照組不一致：\nactual={actual['board']!r}\n"
        f"baseline={baseline['board']!r}"
    )
    assert actual["scopedCount"] == baseline["scopedCount"], (
        f"頁首片數不一致：{actual['scopedCount']} vs {baseline['scopedCount']}"
    )
    assert actual["focus"] == baseline["focus"], (
        f"焦點不一致：{actual['focus']!r} vs {baseline['focus']!r}"
    )
