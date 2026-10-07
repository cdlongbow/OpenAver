"""161b T7：真頭像點擊、年表提交與 Top 25 的使用者終態。"""
import re
import pytest
from tests.e2e._insights_motion_helpers import (
    alpine, load_ready, wait_scroll_settled, wait_settled,
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

def test_gantt_film_cell_commits_actress_year_count(page, base_url):
    _open(page, base_url)
    name, cells = _gantt(page)
    year = cells[0]['year']
    recs = page.request.get(f'{base_url}/api/insights/snapshot').json()['records']
    _click(page, _cell(page, name, cells[0]))
    want = sum(r['year'] == year and name in (r['actresses'] or []) for r in recs)
    assert re.sub(r'\D', '', page.locator('#tileCount .insights-big-number .insights-tile-value').inner_text()) == str(want)
    _assert_year(page, name, year)

def test_gantt_same_film_cell_clears_only_year(page, base_url):
    _open(page, base_url)
    name, cells = _gantt(page)
    _click(page, _cell(page, name, cells[0]))
    _assert_year(page, name, cells[0]['year'])
    _click(page, _cell(page, name, cells[0]))
    assert _sel(page) == {'actress': name, 'maker': None, 'period': {'type': 'all'}}
    assert name in page.locator('#tileActress').inner_text()
    assert '全部年份' in page.locator('#tileYear').inner_text()
