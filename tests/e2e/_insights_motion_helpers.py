"""156e motion e2e 共用 helper：開頁、PRM、探測、真 click、settle、殘留、pageerror。"""
from __future__ import annotations
from playwright.sync_api import Page
ALPINE = '[x-data="libraryInsights"]'
DESKTOP, MOBILE = 1440, 390
GHOST = "[data-avatar-fly-ghost]"
ACTRESS_TILE_AV = "#tileActress .insights-focus-avatar:not(.mk)"
SETTLE_MS = 3_500
ACTIVE_FLIP = """(t) => {
    if (!t || t === 'none' || t === '') return false;
    if (t === 'matrix(1, 0, 0, 1, 0, 0)') return false;
    if (/^translate(3d)?\\(\\s*0(px)?\\s*,\\s*0(px)?(\\s*,\\s*0(px)?)?\\s*\\)$/.test(t)) return false;
    if (/^matrix3d\\(1,\\s*0,\\s*0,\\s*0,\\s*0,\\s*1,\\s*0,\\s*0,\\s*0,\\s*0,\\s*1,\\s*0,\\s*0,\\s*0,\\s*0,\\s*1\\)$/.test(t)) return false;
    return true;
}"""
def attach_pageerrors(page: Page) -> list[str]:
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    return errs
def load_ready(page: Page, base_url: str, width: int = DESKTOP, height: int = 900) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/insights")
    page.wait_for_function(
        "window.Alpine && !!document.querySelector('%s')?._x_dataStack" % ALPINE, timeout=15_000)
    page.wait_for_function(
        "() => { const d = Alpine.$data(document.querySelector('%s'));"
        " return !!(d && d.ganttRows && d.ganttRows.length > 0); }" % ALPINE, timeout=15_000)
    page.wait_for_timeout(900)
def set_prm(page: Page, on: bool) -> None:
    page.evaluate("(on) => { window.OpenAver.prefersReducedMotion = !!on; }", on)
def alpine(page: Page, expr: str, arg=None):
    return page.evaluate(
        "(arg) => { const data = Alpine.$data(document.querySelector('%s'));"
        " if (!data) return null; return (%s); }" % (ALPINE, expr), arg)
def wait_scroll_settled(page: Page, timeout: int = 800) -> None:
    page.evaluate("() => { window.__oaSY = -1; window.__oaSN = 0; }")
    page.wait_for_function(
        "() => { const y = window.scrollY;"
        " window.__oaSN = Math.abs(y - window.__oaSY) < 0.5 ? (window.__oaSN||0)+1 : 0;"
        " window.__oaSY = y; return window.__oaSN >= 3; }", timeout=timeout)
def wait_settled(page: Page, timeout: int = SETTLE_MS) -> None:
    page.evaluate("() => { window.__oaSettleN = 0; }")
    page.wait_for_function("""() => {
        const isActive = %s, d = Alpine.$data(document.querySelector('%s'));
        if (!d) return false;
        const flipBusy = [...document.querySelectorAll('[data-flip-id]')]
            .some(el => isActive(el.style.transform));
        const drop = document.querySelectorAll('[data-board-dropout-ghost]').length;
        const fly = document.querySelectorAll('%s').length;
        const t = document.querySelector('%s');
        const flyOk = !t || (!t.hasAttribute('data-avatar-fly-hidden')
            && (t.style.opacity === '' || t.style.opacity === '1'));
        const countOk = d.displayScopedCount === d.scopedCount
            && Object.keys(d.boardDisplayCounts || {}).length === 0;
        const opOk = ['boardRow3El','costarEl','row7El'].every(ref => {
            const el = document.querySelector(`[x-ref="${ref}"]`);
            if (!el) return true;
            const op = el.style.opacity;
            return op === '' || op === '0' || op === '1';
        });
        if (flipBusy || drop || fly || !flyOk || !countOk || !opOk)
            { window.__oaSettleN = 0; return false; }
        window.__oaSettleN = (window.__oaSettleN || 0) + 1;
        return window.__oaSettleN >= 3;
    }""" % (ACTIVE_FLIP, ALPINE, GHOST, ACTRESS_TILE_AV), timeout=timeout)
    page.wait_for_timeout(50)
def residue(page: Page) -> dict:
    return page.evaluate("""() => {
        const isActive = %s, transforms = [];
        document.querySelectorAll('[data-flip-id]').forEach(el => {
            if (isActive(el.style.transform)) transforms.push({
                id: el.getAttribute('data-flip-id'), transform: el.style.transform });
        });
        return { transforms,
            dropoutGhosts: document.querySelectorAll('[data-board-dropout-ghost]').length,
            avatarGhosts: document.querySelectorAll('%s').length };
    }""" % (ACTIVE_FLIP, GHOST))
def assert_no_residue(page: Page, label: str = "") -> None:
    r = residue(page)
    p = f"{label}: " if label else ""
    assert r["dropoutGhosts"] == 0, f"{p}dropout={r['dropoutGhosts']}"
    assert r["avatarGhosts"] == 0, f"{p}avatar ghost={r['avatarGhosts']}"
    assert not r["transforms"], f"{p}transform={r['transforms']!r}"
def chart_years(page: Page) -> list:
    return page.evaluate(
        "() => { const el = document.getElementById('yearsChart');"
        " const c = window.echarts && window.echarts.getInstanceByDom(el);"
        " if (!c) return [];"
        " return (c.getOption().xAxis[0].data||[]).map(Number).filter(Number.isFinite); }")
def click_year_bar(page: Page, year: int) -> bool:
    coords = page.evaluate("""(year) => {
        const el = document.getElementById('yearsChart');
        const chart = window.echarts && window.echarts.getInstanceByDom(el);
        if (!chart) return null;
        const idx = chart.getOption().xAxis[0].data.indexOf(String(year));
        if (idx < 0) return null;
        const px = chart.convertToPixel({ xAxisIndex: 0 }, idx);
        const g = chart.getModel().getComponent('grid').coordinateSystem.getRect();
        const r = el.getBoundingClientRect();
        return { x: r.left + px, y: r.top + g.y + g.height / 2 };
    }""", year)
    if not coords:
        return False
    page.mouse.click(coords["x"], coords["y"])
    return True
def reset_period_all(page: Page) -> None:
    period = alpine(page, "data.sel ? {...data.sel.period} : null")
    if period and period.get("type") == "year":
        page.click("#tileYear .insights-x-btn")
        page.wait_for_function(
            "() => { const d = Alpine.$data(document.querySelector('%s'));"
            " return !!(d && d.sel && d.sel.period.type === 'all'); }" % ALPINE, timeout=3_000)
        page.wait_for_timeout(40)
def click_donut_named_maker(page: Page) -> str | None:
    coords = page.evaluate("""() => {
        const el = document.getElementById('donutChart');
        const chart = window.echarts && window.echarts.getInstanceByDom(el);
        if (!chart) return null;
        const series = (chart.getOption().series || [])
            .find(s => s.id === 'donut-inner') || (chart.getOption().series || [])[0];
        const data = (series && series.data) || [];
        let idx = -1, maker = null;
        for (let i = 0; i < data.length; i++) {
            const d = data[i];
            if (d && d.kind === 'named' && d.name && d.value > 0)
                { idx = i; maker = d.name; break; }
        }
        if (idx < 0) return null;
        const layout = chart.getModel().getSeriesByIndex(0).getData().getItemLayout(idx);
        if (!layout) return null;
        const mid = (layout.startAngle + layout.endAngle) / 2;
        const rr = (layout.r + (layout.r0 || 0)) / 2, rect = el.getBoundingClientRect();
        return { x: rect.left + layout.cx + Math.cos(mid) * rr,
                 y: rect.top + layout.cy + Math.sin(mid) * rr, maker };
    }""")
    if not coords:
        return None
    page.mouse.click(coords["x"], coords["y"])
    return coords["maker"]
def click_gantt_actress(page: Page, name: str) -> None:
    wait_scroll_settled(page)
    c = page.evaluate("""(name) => {
        for (const row of document.querySelectorAll(
            '.gantt-table .gantt-row:not(.gantt-head-row)')) {
            const n = row.querySelector('.gantt-name');
            if (!n || n.textContent.trim() !== name) continue;
            const cell = row.querySelector('.gantt-name') || row;
            cell.scrollIntoView({ block: 'center', inline: 'center' });
            const r = cell.getBoundingClientRect();
            return { found: true, x: r.left + r.width / 2, y: r.top + r.height / 2 };
        }
        return { found: false };
    }""", name)
    assert c.get("found"), f"年表找不到 {name!r}"
    page.mouse.click(c["x"], c["y"])
def discover_actress_with_costar(page: Page) -> str | None:
    set_prm(page, True)
    try:
        names = alpine(page, "(data.ganttRows||[]).map(r=>r.name)") or []
        for name in names[:16]:
            click_gantt_actress(page, name)
            page.wait_for_timeout(60)
            n = alpine(page, "(data.costarRows||[]).length") or 0
            click_gantt_actress(page, name)
            page.wait_for_timeout(40)
            if n > 0:
                return name
        return None
    finally:
        set_prm(page, False)
def discover_year_chain(page: Page, need: int = 2) -> list:
    set_prm(page, True)
    years = chart_years(page)[-10:]
    tops: dict = {}
    try:
        for y in years:
            if not click_year_bar(page, y):
                continue
            page.wait_for_timeout(40)
            tops[y] = alpine(
                page, "(data.boardRows||[]).map(r=>({name:r.name,rank:r.rank}))")
        reset_period_all(page)
    finally:
        set_prm(page, False)
    def movers(a, b):
        ma = {r["name"]: r["rank"] for r in tops.get(a, [])}
        mb = {r["name"]: r["rank"] for r in tops.get(b, [])}
        return [n for n in ma if n in mb and ma[n] != mb[n]]
    keyed = [y for y in years if y in tops]
    for i in range(len(keyed) - need, -1, -1):
        chain = keyed[i:i + need]
        if all(movers(chain[j], chain[j + 1]) for j in range(need - 1)):
            return chain
    for i in range(len(keyed) - 2, -1, -1):
        if movers(keyed[i], keyed[i + 1]):
            return [keyed[i], keyed[i + 1]]
    return []
def board_list(page: Page) -> list:
    return alpine(page,
        "(data.boardRows||[]).map(r=>({name:r.name,rank:r.rank,count:r.count}))") or []
