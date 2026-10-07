"""E2E：161a T8 — 分析頁選條件 → 點片數 → 瀏覽頁牆上就是那 N 部（oracle 現場從 API 獨立算）。"""
from __future__ import annotations
import re
import unicodedata
from collections import defaultdict
import pytest
from playwright.sync_api import Page
from tests.e2e._insights_motion_helpers import (
    alpine, chart_years, click_donut_named_maker, click_gantt_actress, click_year_bar,
    load_ready, wait_settled,
)
pytestmark = pytest.mark.e2e
SHOW = '[x-data="showcase"]'

def _norm(s) -> str:
    return unicodedata.normalize("NFKC", str(s).strip()).lower()
def _records(page: Page, base: str) -> list:
    return page.request.get(f"{base}/api/insights/snapshot").json()["records"]
def _oracle(recs: list, sel: dict) -> int:
    p, n = sel["period"], 0
    for r in recs:
        if p["type"] == "year" and r["year"] != p["year"]:
            continue
        if p["type"] == "range" and not (p["from"] <= (r["year"] or -1) <= p["to"]):
            continue
        if sel["actress"] and sel["actress"] not in (r["actresses"] or []):
            continue
        if sel["maker"] and _norm(r["maker"] or "") != _norm(sel["maker"]):
            continue
        n += 1
    return n

def _open(page: Page, base: str) -> list:
    reqs: list = []
    page.on("request", lambda q: reqs.append(q) if (
        q.url.startswith(base + "/api/") and q.method != "GET"
        and not q.url.endswith("/api/client-log")) else None)  # base.html 開機診斷 beacon 每頁都送
    load_ready(page, base)
    page.bring_to_front()
    return reqs

def _sel(page: Page) -> dict:
    return alpine(page, "JSON.parse(JSON.stringify(data.sel))")
def _browse(page: Page) -> dict:
    page.wait_for_function("""() => {
        const el = document.querySelector('%s'), d = el && window.Alpine && Alpine.$data(el);
        if (!d || d.loading !== false) return false;
        const k = d.filteredCount + '|' + [...document.querySelectorAll('.av-card-preview:not(.hero-card)')]
            .filter(e => e.offsetParent !== null).length;
        window.__bn = (k === window.__bk) ? (window.__bn || 0) + 1 : 0; window.__bk = k;
        return window.__bn >= 3;
    }""" % SHOW, polling=100, timeout=20_000)
    return page.evaluate("""() => {
        const d = Alpine.$data(document.querySelector('%s'));
        const bs = document.querySelectorAll('.showcase-footer .footer-count:not(.footer-count--actress) b');
        const inp = document.querySelector('.filter-pill-group input');
        return { fc: d.filteredCount, pp: d.perPage, pills: JSON.parse(JSON.stringify(d.pills)),
            search: d.search, inp: inp ? inp.value : null, page: d.page, fav: d.showFavoriteActresses,
            sort: d.sort, order: d.order, shape: d.cardShape, info: d.infoVisible,
            foot: bs.length ? bs[bs.length - 1].textContent.trim() : null,
            cards: [...document.querySelectorAll('.av-card-preview:not(.hero-card)')]
                .filter(e => e.offsetParent !== null).length };
    }""" % SHOW)

def _jump(page: Page, base: str, reqs: list, recs: list, extra: int | None = None) -> dict:
    sel = _sel(page)
    wait_settled(page)
    want = _oracle(recs, sel)
    assert want > 0, f"前提：條件 {sel} 在快照中數不出片"
    assert alpine(page, "data.scopedCount") == want
    tile = page.inner_text("#tileCount .insights-big-number .insights-tile-value")
    assert re.sub(r"\D", "", tile) == str(want), f"頂排片數 {tile!r} != {want}"
    assert not reqs, f"分析頁階段出現非 GET 同源 API：{[(q.method, q.url) for q in reqs]}"
    with page.expect_navigation() as nav:
        page.click("#tileCount")
    assert nav.value.url == f"{base}/showcase", f"導覽 URL：{nav.value.url}"
    b = _browse(page)
    assert b["fc"] == want, f"瀏覽頁 filteredCount={b['fc']} != 分析頁 {want}（條件 {sel}）"
    if extra is not None:
        assert b["fc"] == extra, f"filteredCount={b['fc']} != 獨立數 {extra}"
    assert b["foot"] == str(b["fc"]), f"頁尾 {b['foot']!r} != {b['fc']}"
    assert b["cards"] == min(b["fc"], b["pp"] or 120), f"牆上卡數 {b['cards']} fc={b['fc']} pp={b['pp']}"
    assert b["inp"] == "" and b["page"] == 1
    return b

def _pick_actress(page: Page) -> str:
    name = alpine(page, "(data.ganttRows||[])[0].name")
    click_gantt_actress(page, name)
    wait_settled(page)
    assert _sel(page)["actress"] == name
    return name

def _year_xy(page: Page, year: int) -> tuple:
    c = page.evaluate("""(year) => {
        const el = document.getElementById('yearsChart');
        const chart = window.echarts && window.echarts.getInstanceByDom(el);
        const idx = chart.getOption().xAxis[0].data.indexOf(String(year));
        if (idx < 0) return null;
        const px = chart.convertToPixel({ xAxisIndex: 0 }, idx);
        const g = chart.getModel().getComponent('grid').coordinateSystem.getRect();
        const r = el.getBoundingClientRect();
        const x = r.left + px, y = r.top + g.y + g.height / 2;
        const hit = document.elementFromPoint(x, y);
        return { x, y, ok: !!(hit && hit.closest('#yearsChart')) };
    }""", year)
    assert c and c["ok"], f"年份 {year} 長條座標取不到或被擋住：{c}"
    return c["x"], c["y"]

def test_handoff_maker_merged_single_slice(page: Page, base_url: str):
    reqs = _open(page, base_url)
    recs = _records(page, base_url)
    groups: dict = defaultdict(lambda: [set(), 0])
    for r in recs:
        if r["maker"] and r["maker"].strip():
            g = groups[_norm(r["maker"])]
            g[0].add(r["maker"])
            g[1] += 1
    multi = {k: v for k, v in groups.items() if len(v[0]) >= 2}
    if not multi:
        pytest.fail("前提缺：快照中沒有「原始寫法 >=2 種」的片商")
    key = max(multi, key=lambda k: multi[k][1])
    total = multi[key][1]
    c = page.evaluate("""(key) => {
        const n = s => String(s).normalize('NFKC').trim().toLowerCase();
        const el = document.getElementById('donutChart');
        const chart = window.echarts && window.echarts.getInstanceByDom(el);
        const s = chart.getOption().series.find(s => s.id === 'donut-inner') || chart.getOption().series[0];
        const named = (s.data || []).map((d, i) => ({ d, i })).filter(o => o.d.kind === 'named' && o.d.name);
        const names = named.map(o => n(o.d.name));
        const hit = named.find(o => n(o.d.name) === key);
        if (!hit) return { names };
        const l = chart.getModel().getSeriesByIndex(0).getData().getItemLayout(hit.i);
        const mid = (l.startAngle + l.endAngle) / 2, rr = (l.r + (l.r0 || 0)) / 2;
        const rect = el.getBoundingClientRect();
        const x = rect.left + l.cx + Math.cos(mid) * rr, y = rect.top + l.cy + Math.sin(mid) * rr;
        const top = document.elementFromPoint(x, y);
        return { names, x, y, ok: !!(top && top.closest('#donutChart')) };
    }""", key)
    assert len(set(c["names"])) == len(c["names"]), f"圓餅同一片商分成多塊：{c['names']}"
    if "x" not in c:
        pytest.fail(f"前提缺：圓餅 named 扇區找不到合併後片商 {key!r}")
    assert c["ok"], "圓餅座標被別的元素擋住"
    page.mouse.click(c["x"], c["y"])
    wait_settled(page)
    assert _norm(_sel(page)["maker"]) == key
    _jump(page, base_url, reqs, recs, extra=total)

def test_handoff_year_only_includes_year_only_films(page: Page, base_url: str):
    reqs = _open(page, base_url)
    recs = _records(page, base_url)
    vids = page.request.get(f"{base_url}/api/showcase/videos").json()["videos"]
    ys = [v["release_date"] for v in vids if re.fullmatch(r"\d{4}", v.get("release_date") or "")]
    if not ys:
        pytest.fail("前提缺：/api/showcase/videos 中沒有 release_date 只有年份的片")
    year = int(ys[0])
    assert click_year_bar(page, year), f"年份長條找不到 {year}"
    wait_settled(page)
    assert _sel(page)["period"] == {"type": "year", "year": year}
    n = sum(1 for v in vids if (v.get("release_date") or "").startswith(str(year)))
    _jump(page, base_url, reqs, recs, extra=n)

def test_handoff_three_conditions_with_range_drag(page: Page, base_url: str):
    reqs = _open(page, base_url)
    recs = _records(page, base_url)
    name = _pick_actress(page)
    assert click_donut_named_maker(page), "前提缺：圓餅沒有可點的 named 扇區"
    wait_settled(page)
    assert _sel(page)["maker"], "點圓餅後 sel.maker 為空"
    years = chart_years(page)
    if len(years) < 2:
        pytest.fail(f"前提缺：年份長條欄數 {len(years)} < 2")
    x0, y0 = _year_xy(page, years[1] if len(years) >= 3 else years[0])
    x1, y1 = _year_xy(page, years[-1])
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x1, y1, steps=12)
    page.mouse.up()
    wait_settled(page)
    sel = _sel(page)
    p = sel["period"]
    if p["type"] != "range":
        pytest.fail(f"拖曳沒有產生 range：{p}")
    assert p["from"] < p["to"]
    b = _jump(page, base_url, reqs, recs)
    got = sorted((q["dim"], q.get("op"), q["value"], q.get("value2")) for q in b["pills"])
    assert got == sorted([("actress", None, name, None), ("maker", None, sel["maker"], None),
                          ("release", "range", str(p["from"]), str(p["to"]))]), got

def test_handoff_replaces_old_showcase_state_keeps_prefs(page: Page, base_url: str):
    reqs = _open(page, base_url)
    recs = _records(page, base_url)
    page.evaluate("""() => localStorage.setItem('showcase_state', JSON.stringify({
        sort: 'num', order: 'asc', cardShape: 'poster', infoVisible: true, mode: 'grid', page: 3,
        search: 'zzz', pills: [{dim: 'pick', value: '1'}, {dim: 'maker', value: '__不存在__'}],
        showFavoriteActresses: true }))""")
    name = _pick_actress(page)
    b = _jump(page, base_url, reqs, recs)
    assert [(p["dim"], p["value"]) for p in b["pills"]] == [("actress", name)], b["pills"]
    assert (b["search"], b["page"], b["fav"]) == ("", 1, False)
    assert (b["sort"], b["order"], b["shape"], b["info"]) == ("num", "asc", "poster", True)
