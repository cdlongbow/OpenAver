"""161b T7：真頭像點擊、年表提交與 Top 25 的使用者終態。"""
import re
import pytest
from tests.e2e._insights_motion_helpers import (
    alpine, chart_years, click_donut_named_maker, click_year_bar,
    load_ready, wait_scroll_settled, wait_settled,
)
pytestmark = pytest.mark.e2e
ENTRIES = {
    'podium': '.podium-slot .podium-avatar', 'board-rest': '.board-rest-row .board-avatar',
    'gantt': '.gantt-row .gantt-avatar', 'solo': '#soloList .solo-avatar',
    'costar': '#costarList [data-costar-role="other"]',
}

def _open(page, base, width=1440):
    page.bring_to_front()
    load_ready(page, base, width)
    assert page.evaluate("document.visibilityState === 'visible'")
    wait_settled(page)

def _sel(page):
    return alpine(page, 'JSON.parse(JSON.stringify(data.sel))')

def _xy(page, loc):
    loc.scroll_into_view_if_needed()
    wait_scroll_settled(page)
    c = loc.evaluate("""e => { const r = e.getBoundingClientRect();
        const x = r.left + r.width / 2, y = r.top + r.height / 2;
        const hit = document.elementFromPoint(x, y);
        return {x, y, ok: e.offsetParent !== null && !!hit &&
            (e.closest('.podium-slot,.board-rest-row,.gantt-row,.solo-row,.costar-row') || e).contains(hit)};
    }""")
    assert c['ok'], f'真點擊目標被遮擋：{c}'
    return c['x'], c['y']

def _click(page, loc):
    page.mouse.click(*_xy(page, loc))
    page.mouse.move(1100, 10)
    wait_settled(page)

def _avatar(page, entry, name):
    loc = page.locator(ENTRIES[entry])
    idx = loc.evaluate_all("""(es, name) => es.findIndex(e =>
        e.offsetParent !== null && Alpine.$data(e).row.name === name)""", name)
    assert idx >= 0, f'{entry} 找不到可見頭像：{name}'
    return loc.nth(idx)

def _pick(page, entry, photo):
    if entry == 'costar':
        recs = page.request.get(page.url.split('/insights')[0] + '/api/insights/snapshot').json()['records']
        names = alpine(page, 'data.ganttRows.map(r => r.name)')
        others = list({o for r in recs for o in (r['actresses'] or [])})
        eligible = set(alpine(page, 'arg.names.filter(n => data._hasPreviewPhoto(n) === arg.photo)', {'names': others, 'photo': photo}))
        seed = next((n for n in names if any(n in (r['actresses'] or []) and any(
            o != n and o in eligible for o in (r['actresses'] or [])) for r in recs)), None)
        if seed is None:
            pytest.skip(f'costar 缺共演者照片狀態={photo} 的作品')
        _click(page, page.locator('.gantt-name').filter(has_text=re.compile('^' + re.escape(seed) + '$')))
    candidates = page.locator(ENTRIES[entry]).evaluate_all("""es => es.filter(e => e.offsetParent !== null)
        .map(e => { const d = Alpine.$data(e); return {name: d.row.name,
            photo: d._hasPreviewPhoto(d.row.name)}; })""")
    name = next((r['name'] for r in candidates if r['photo'] == photo), None)
    if name is None:
        pytest.skip(f'{entry} 缺可見照片狀態={photo} 的頭像')
    return name

def _no_preview(page):
    assert alpine(page, 'data.previewActress') is None
    assert not page.locator('.insights-preview').is_visible()

def _year_xy(page, year):
    page.locator('#yearsChart').scroll_into_view_if_needed()
    wait_scroll_settled(page)
    c = page.evaluate("""year => {
        const el = document.getElementById('yearsChart'), chart = echarts.getInstanceByDom(el);
        const idx = chart.getOption().xAxis[0].data.indexOf(String(year));
        if (idx < 0) return null;
        const px = chart.convertToPixel({xAxisIndex: 0}, idx);
        const g = chart.getModel().getComponent('grid').coordinateSystem.getRect(), r = el.getBoundingClientRect();
        const x = r.left + px, y = r.top + g.y + g.height / 2, hit = document.elementFromPoint(x, y);
        return {x, y, ok: !!(hit && hit.closest('#yearsChart'))};
    }""", year)
    assert c and c['ok'], f'年份長條被遮擋：{c}'
    return c['x'], c['y']

def _gantt(page, kind='main', axis='year', need=1):
    rows = alpine(page, 'data.ganttView(arg).rows', axis)
    row = next((r for r in rows if len([c for c in r['cells'] if c['state'] == kind]) >= need), None)
    if row is None:
        pytest.skip(f'年表缺 {axis} 軸、至少 {need} 個 {kind} 格的女優')
    return row['name'], [c for c in row['cells'] if c['state'] == kind]

def _cell(page, name, cell, axis='year'):
    row = page.locator('.gantt-row').filter(has=page.locator('.gantt-name', has_text=re.compile('^' + re.escape(name) + '$')))
    cells = alpine(page, 'data.ganttView(arg[0]).rows.find(r => r.name === arg[1]).cells', [axis, name])
    idx = next(i for i, c in enumerate(cells) if c.get(axis) == cell.get(axis))
    return row.locator('.gantt-cell').nth(idx)

def _assert_year(page, name, year):
    assert _sel(page)['actress'] == name
    assert _sel(page)['period'] == {'type': 'year', 'year': year}
    assert page.locator('#tileActress .insights-focus-name').inner_text() == name
    assert str(year) in page.locator('#tileYear').inner_text()

@pytest.mark.parametrize('entry', ENTRIES, ids=ENTRIES)
@pytest.mark.parametrize('photo', [False, True], ids=['no-photo', 'photo'])
def test_avatar_click_selects_and_clears(page, base_url, entry, photo):
    _open(page, base_url)
    name = _pick(page, entry, photo)
    _click(page, _avatar(page, entry, name))
    assert _sel(page)['actress'] == name
    assert name in page.locator('#tileActress').inner_text()
    _no_preview(page)
    if entry != 'costar':
        _click(page, _avatar(page, entry, name))
        assert _sel(page)['actress'] is None
        _no_preview(page)
        assert '全部女優' in page.locator('#tileActress').inner_text()

@pytest.mark.parametrize('entry', ENTRIES, ids=ENTRIES)
def test_photo_hover_preview_opens_and_leaves(page, base_url, entry):
    _open(page, base_url)
    name = _pick(page, entry, True)
    page.mouse.move(*_xy(page, _avatar(page, entry, name)))
    page.locator('.insights-preview').wait_for(state='visible')
    assert page.locator('.insights-preview-name').inner_text() == name
    page.mouse.move(1100, 10)
    page.locator('.insights-preview').wait_for(state='hidden')
    _no_preview(page)

@pytest.mark.parametrize('entry', ENTRIES, ids=ENTRIES)
def test_touch_photo_tap_selects_without_preview(browser, base_url, entry):
    context = browser.new_context(has_touch=True, viewport={'width': 1440, 'height': 900})
    try:
        page = context.new_page()
        _open(page, base_url)
        name = _pick(page, entry, True)
        target = _avatar(page, entry, name)
        _xy(page, target)
        idx = target.evaluate('(e, selector) => [...document.querySelectorAll(selector)].indexOf(e)', ENTRIES[entry])
        page.tap(f'{ENTRIES[entry]} >> nth={idx}')
        wait_settled(page)
        assert _sel(page)['actress'] == name
        assert name in page.locator('#tileActress').inner_text()
        _no_preview(page)
    finally:
        context.close()

def test_gantt_film_cell_commits_actress_year_count(page, base_url):
    _open(page, base_url)
    name, cells = _gantt(page)
    year = cells[0]['year']
    recs = page.request.get(f'{base_url}/api/insights/snapshot').json()['records']
    _click(page, _cell(page, name, cells[0]))
    want = sum(r['year'] == year and name in (r['actresses'] or []) for r in recs)
    assert re.sub(r'\D', '', page.locator('#tileCount .insights-big-number .insights-tile-value').inner_text()) == str(want)
    _assert_year(page, name, year)

@pytest.mark.parametrize('period', ['year', 'range'], ids=['year', 'range'])
def test_gantt_film_cell_replaces_period(page, base_url, period):
    _open(page, base_url)
    name, cells = _gantt(page, need=2)
    years = chart_years(page)
    if len(years) < 2:
        pytest.skip('年份長條不足 2 年')
    if period == 'range':
        x0, y0 = _year_xy(page, years[1] if len(years) >= 3 else years[0])
        x1, y1 = _year_xy(page, years[-1])
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x1, y1, steps=12)
        page.mouse.up()
        wait_settled(page)
        assert _sel(page)['period']['type'] == 'range'
        assert _sel(page)['period']['from'] < _sel(page)['period']['to']
    else:
        _year_xy(page, cells[0]['year'])
        assert click_year_bar(page, cells[0]['year'])
        wait_settled(page)
        assert _sel(page)['period'] == {'type': 'year', 'year': cells[0]['year']}
    _click(page, _cell(page, name, cells[1]))
    _assert_year(page, name, cells[1]['year'])

def test_gantt_same_film_cell_clears_only_year(page, base_url):
    _open(page, base_url)
    name, cells = _gantt(page)
    _click(page, _cell(page, name, cells[0]))
    _assert_year(page, name, cells[0]['year'])
    _click(page, _cell(page, name, cells[0]))
    assert _sel(page) == {'actress': name, 'maker': None, 'period': {'type': 'all'}}
    assert name in page.locator('#tileActress').inner_text()
    assert '全部年份' in page.locator('#tileYear').inner_text()

@pytest.mark.parametrize('axis', ['year', 'age'], ids=['empty', 'age'])
@pytest.mark.parametrize('selected', [True, False], ids=['selected', 'unselected'])
def test_gantt_non_year_cell_only_selects_unfocused_actress(page, base_url, axis, selected):
    _open(page, base_url)
    if axis == 'age':
        _click(page, page.locator('.insights-gantt-toggle button').nth(1))
    name, cells = _gantt(page, 'empty' if axis == 'year' else 'main', axis)
    if selected:
        _click(page, page.locator('.gantt-name', has_text=re.compile('^' + re.escape(name) + '$')))
    before = _sel(page)
    _click(page, _cell(page, name, cells[0], axis))
    assert _sel(page) == (before if selected else {**before, 'actress': name})
    assert page.locator('[data-avatar-fly-ghost]').count() == 0
    assert name in page.locator('#tileActress').inner_text()
    assert '全部年份' in page.locator('#tileYear').inner_text()

def test_gantt_film_cell_keeps_maker(page, base_url, monkeypatch):
    _open(page, base_url)
    _xy(page, page.locator('#donutChart'))
    original = page.mouse.click
    def checked(x, y):
        assert page.evaluate('([x,y]) => !!document.elementFromPoint(x,y)?.closest("#donutChart")', [x, y])
        original(x, y)
    with monkeypatch.context() as patch:
        patch.setattr(page.mouse, 'click', checked)
        maker = click_donut_named_maker(page)
    if not maker:
        pytest.skip('圓餅缺 named 片商扇區')
    wait_settled(page)
    assert _sel(page)['maker'] == maker
    name, cells = _gantt(page)
    _click(page, _cell(page, name, cells[0]))
    assert _sel(page)['maker'] == maker
    _assert_year(page, name, cells[0]['year'])

@pytest.mark.parametrize('width,podium,rest,title', [(1440, 5, 20, '第 6–25 名'),
    (1180, 5, 20, '第 6–25 名'), (390, 3, 22, '第 4–25 名')], ids=['1440', '1180', '390'])
def test_top25_responsive_visible_layout(page, base_url, width, podium, rest, title):
    _open(page, base_url, width)
    assert _sel(page)['actress'] is None
    def visible(selector):
        return page.locator(selector).evaluate_all('es => es.filter(e => e.offsetParent !== null).length')
    assert visible('.podium-slot') == podium
    assert visible('.board-rest-row') == rest
    assert page.evaluate("""() => [...document.querySelectorAll('.podium-slot,.board-podium-card')]
        .filter(e => e.offsetParent !== null).every(e => e.getBoundingClientRect().right <= innerWidth)""")
    name = page.locator('.podium-name:visible').first
    original = name.inner_text()
    try:
        fit = name.evaluate("e => { e.textContent = 'あいうえお'; return {sw: e.scrollWidth, cw: e.clientWidth}; }")
        assert fit['sw'] <= fit['cw'], fit
        overflow = name.evaluate("e => { e.textContent = 'あいうえおかきくけこ'; return {sw: e.scrollWidth, cw: e.clientWidth, ellipsis: getComputedStyle(e).textOverflow}; }")
        assert overflow['sw'] > overflow['cw'] and overflow['ellipsis'] == 'ellipsis', overflow
    finally:
        name.evaluate('(e, text) => { e.textContent = text; }', original)
    assert page.locator('.board-podium-card h2').evaluate_all('es => es.filter(e => e.offsetParent !== null).map(e => e.textContent)') == ['女優 Top 25']
    assert page.locator('.board-rest-card h2').evaluate_all('es => es.filter(e => e.offsetParent !== null).map(e => e.textContent)') == [title]
