"""E2E：156e 片數滾動 — 粗顆粒結束狀態（不 hook playCountUp）。"""
from __future__ import annotations
import pytest
from playwright.sync_api import Page
from tests.e2e._insights_motion_helpers import (
    ALPINE, alpine, chart_years, click_year_bar,
    load_ready, reset_period_all, set_prm, board_list, wait_settled,
)
pytestmark = pytest.mark.e2e
def _scoped(page: Page) -> dict:
    return alpine(page, "({scopedCount:data.scopedCount,"
                  "displayScopedCount:data.displayScopedCount})") or {}
def _tile(page: Page) -> str:
    return page.evaluate(
        "() => { const el = document.querySelector("
        "'#tileCount .insights-big-number .insights-tile-value');"
        " return el ? el.textContent.trim() : ''; }")
def _assert_locale(tile: str, value: int) -> None:
    assert tile in (format(value, ","), str(value)), (
        f"千分位不符：tile={tile!r} value={value}")
def _discover_count_years(page: Page) -> dict:
    """PRM 下掃年份，回傳 {all, by_year, years, pairs}。"""
    set_prm(page, True)
    try:
        reset_period_all(page)
        all_c = alpine(page, "data.scopedCount")
        years = chart_years(page)
        if len(years) > 12:
            years = years[-12:]
        by_year = {}
        for y in years:
            if not click_year_bar(page, y):
                continue
            page.wait_for_timeout(40)
            by_year[y] = alpine(page, "data.scopedCount")
        reset_period_all(page)
        keyed = [y for y in years if y in by_year]
        pairs = []
        for y in keyed:
            if by_year[y] != all_c:
                pairs.append({
                    "from": None, "to": y,
                    "from_count": all_c, "to_count": by_year[y]})
        for i, a in enumerate(keyed):
            for b in keyed[i + 1:]:
                if by_year[a] != by_year[b]:
                    pairs.append({
                        "from": a, "to": b,
                        "from_count": by_year[a], "to_count": by_year[b]})
        return {"all": all_c, "by_year": by_year, "years": keyed, "pairs": pairs}
    finally:
        set_prm(page, False)
def _start_sampler(page: Page) -> None:
    page.evaluate("""() => {
        const root = document.querySelector('%s');
        window.__oaCountSamples = [];
        if (window.__oaCountSampleTimer) clearInterval(window.__oaCountSampleTimer);
        const push = () => {
            const data = window.Alpine && Alpine.$data(root);
            if (!data) return;
            const el = document.querySelector(
                '#tileCount .insights-big-number .insights-tile-value');
            window.__oaCountSamples.push({
                display: data.displayScopedCount,
                truth: data.scopedCount,
                tile: el ? el.textContent.trim() : '',
            });
        };
        push();
        window.__oaCountSampleTimer = setInterval(push, 16);
    }""" % ALPINE)
def _stop_sampler(page: Page) -> list:
    return page.evaluate("""() => {
        if (window.__oaCountSampleTimer) {
            clearInterval(window.__oaCountSampleTimer);
            window.__oaCountSampleTimer = null;
        }
        return window.__oaCountSamples || [];
    }""")
def _assert_strict_mid(samples: list, from_v: int, to_v: int) -> None:
    lo, hi = (from_v, to_v) if from_v < to_v else (to_v, from_v)
    tile_nums = []
    for s in samples:
        raw = (s.get("tile") or "").replace(",", "")
        if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
            tile_nums.append(int(raw))
        elif s.get("display") is not None:
            tile_nums.append(int(s["display"]))
    mids = [v for v in tile_nums if lo < v < hi]
    assert mids, (
        f"應至少一次取樣嚴格介於 {from_v} 與 {to_v} 之間，序列={tile_nums}")
def _dom_board_counts(page: Page) -> dict:
    """讀可見女優榜列顯示的片數文字 → {name: int}。"""
    return page.evaluate("""() => {
        const out = {};
        document.querySelectorAll('.podium-slot, .board-rest-row').forEach(row => {
            const nameEl = row.querySelector('.podium-name, .board-name');
            const countEl = row.querySelector('.podium-count, .board-count');
            if (!nameEl || !countEl) return;
            const name = nameEl.textContent.trim();
            const raw = countEl.textContent.trim().replace(/,/g, '');
            if (name && /^-?\\d+$/.test(raw)) out[name] = parseInt(raw, 10);
        });
        return out;
    }""")

def test_count_up_year_change_animates_to_scoped(page: Page, base_url: str) -> None:
    """換年份：settle 前至少一次介於起訖；settle 後＝scopedCount、千分位正確。"""
    load_ready(page, base_url)
    info = _discover_count_years(page)
    cands = [p for p in info["pairs"]
             if p["from"] is None and abs(p["to_count"] - p["from_count"]) >= 5]
    if not cands:
        cands = [p for p in info["pairs"]
                 if p["from"] is None and p["to_count"] != p["from_count"]]
    if not cands:
        pytest.skip("片庫湊不出『全部年份 → 某年』片數不同的組合")
    pair = max(cands, key=lambda p: abs(p["to_count"] - p["from_count"]))
    from_c, to_c, year = pair["from_count"], pair["to_count"], pair["to"]
    reset_period_all(page)
    assert _scoped(page)["scopedCount"] == from_c
    _start_sampler(page)
    assert click_year_bar(page, year), f"yearsChart 找不到 {year}"
    wait_settled(page)
    samples = _stop_sampler(page)
    after = _scoped(page)
    assert after["scopedCount"] == to_c
    assert after["displayScopedCount"] == to_c
    _assert_locale(_tile(page), to_c)
    _assert_strict_mid(samples, from_c, to_c)

def test_count_up_first_load_shows_final(page: Page, base_url: str) -> None:
    """首次載入頁首直接是最終值。"""
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{base_url}/insights")
    page.wait_for_function(
        """() => {
            const d = window.Alpine && Alpine.$data(
                document.querySelector('%s'));
            return !!(d && d.ganttRows && d.ganttRows.length > 0
                      && d.scopedCount > 0
                      && d.displayScopedCount === d.scopedCount);
        }""" % ALPINE, timeout=15_000)
    page.wait_for_timeout(900)
    after = _scoped(page)
    assert after["scopedCount"] > 0
    assert after["displayScopedCount"] == after["scopedCount"]
    _assert_locale(_tile(page), after["scopedCount"])

def test_count_up_rapid_two_years_settles_clean(page: Page, base_url: str) -> None:
    """快速連換兩個年份：settle 後頁首＝scopedCount，女優榜列顯示＝row.count。"""
    load_ready(page, base_url)
    info = _discover_count_years(page)
    by = info["by_year"]
    years = [y for y in info["years"] if by[y] != info["all"]]
    if len(years) < 2:
        pytest.skip("片庫湊不出兩個片數都與全部不同的年份")
    y1 = years[-1]
    y2 = next((y for y in reversed(years[:-1]) if by[y] != by[y1]), None)
    if y2 is None:
        pytest.skip("片庫湊不出兩個彼此片數也不同的年份")
    reset_period_all(page)
    assert click_year_bar(page, y1)
    page.wait_for_timeout(80)
    assert click_year_bar(page, y2)
    wait_settled(page)
    after = _scoped(page)
    assert after["displayScopedCount"] == after["scopedCount"] == by[y2]
    _assert_locale(_tile(page), by[y2])
    rows = board_list(page)
    displayed = _dom_board_counts(page)
    for row in rows:
        name, count = row["name"], row["count"]
        if name in displayed:
            assert displayed[name] == count, (
                f"{name!r} 顯示片數 {displayed[name]} ≠ row.count {count}")
