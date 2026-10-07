"""E2E：156e 頭像飛入 — 粗顆粒結束狀態（真 click、讀 DOM／Alpine）。"""
from __future__ import annotations
import pytest
from playwright.sync_api import Page
from tests.e2e._insights_motion_helpers import (
    ALPINE, ACTRESS_TILE_AV, GHOST, alpine, click_gantt_actress, load_ready, set_prm, wait_scroll_settled, wait_settled,
)
pytestmark = pytest.mark.e2e
def _classify(page: Page) -> dict:
    return page.evaluate("""() => {
        const data = Alpine.$data(document.querySelector('%s'));
        const withPhoto = [], withoutPhoto = [];
        for (const r of (data.ganttRows || []))
            (data.actressHasPhoto(r.name) ? withPhoto : withoutPhoto).push(r.name);
        return { withPhoto, withoutPhoto,
            podium: (data.podiumRows||[]).map(r=>r.name),
            rest: (data.restRows||[]).map(r=>r.name),
            solo: (data.soloRows||[]).map(r=>r.name),
            gantt: (data.ganttRows||[]).map(r=>r.name) };
    }""" % ALPINE)
def _ghost_count(page: Page) -> int:
    return page.evaluate("() => document.querySelectorAll('%s').length" % GHOST)
def _focus(page: Page):
    return alpine(page, "({actress: data.sel.actress, maker: data.sel.maker})")
def _wait_fly_settled(page: Page, timeout: int = 2_000) -> None:
    page.wait_for_function(
        "() => { if (document.querySelectorAll('%s').length > 0) return false;"
        " const t = document.querySelector('%s'); if (!t) return true;"
        " if (t.hasAttribute('data-avatar-fly-hidden')) return false;"
        " const op = t.style.opacity; return op === '' || op === '1'; }"
        % (GHOST, ACTRESS_TILE_AV), timeout=timeout)
    page.wait_for_timeout(50)
def _focus_avatar_ok(page: Page) -> dict:
    return page.evaluate(
        "() => { const el = document.querySelector('%s'); if (!el) return {exists:false};"
        " return {exists:true, opacity:el.style.opacity,"
        " hiddenAttr:el.hasAttribute('data-avatar-fly-hidden')}; }" % ACTRESS_TILE_AV)
def _click_row_not_avatar(page: Page, row_sel: str, name: str, avatar_sel: str) -> None:
    wait_scroll_settled(page)
    c = page.evaluate("""([rowSel, name, avatarSel]) => {
        for (const row of document.querySelectorAll(rowSel)) {
            if (row.offsetParent === null) continue;
            const avatar = row.querySelector(avatarSel);
            if (!avatar) continue;
            const nameEl = row.querySelector(
                '.podium-name,.board-name,.solo-name,.gantt-name,.costar-name');
            const match = nameEl ? nameEl.textContent.trim() === name
                : (row.textContent || '').includes(name);
            if (!match) continue;
            const clickEl = nameEl
                || row.querySelector('.podium-count,.board-count,.gantt-cell') || row;
            clickEl.scrollIntoView({ block: 'center', inline: 'nearest' });
            const ar = avatar.getBoundingClientRect(), cr = clickEl.getBoundingClientRect();
            let x = cr.left + Math.min(cr.width * 0.5, Math.max(8, cr.width - 8));
            let y = cr.top + cr.height / 2;
            if (x >= ar.left && x <= ar.right && y >= ar.top && y <= ar.bottom)
                x = Math.min(cr.right - 4, ar.right + 12);
            if (x >= ar.left && x <= ar.right && y >= ar.top && y <= ar.bottom) {
                const rr = row.getBoundingClientRect();
                x = rr.right - 10; y = rr.top + rr.height / 2;
            }
            return { found: true, x, y };
        }
        return { found: false };
    }""", [row_sel, name, avatar_sel])
    assert c.get("found"), f"找不到 {row_sel} / {name!r}"
    page.mouse.click(c["x"], c["y"])
def _assert_landed(page: Page, name: str) -> None:
    assert _ghost_count(page) == 0
    assert _focus(page) == {"actress": name, "maker": None}
    snap = _focus_avatar_ok(page)
    assert snap.get("exists")
    assert not snap.get("hiddenAttr")
    assert snap.get("opacity") in ("", "1")
def _find_costar_pair(page: Page, candidates: list) -> dict | None:
    set_prm(page, True)
    try:
        for name in candidates:
            click_gantt_actress(page, name)
            page.wait_for_timeout(80)
            other = alpine(page, "(data.costarRows&&data.costarRows[0])"
                           " ? data.costarRows[0].name : null")
            click_gantt_actress(page, name)
            page.wait_for_timeout(40)
            if other:
                return {"self": name, "other": other}
        return None
    finally:
        set_prm(page, False)
def _pick_target(page: Page, pool: list) -> str | None:
    if not pool:
        return None
    for n in pool:
        if alpine(page, "data.actressHasPhoto(arg)", n):
            return n
    return pool[0]
ENTRIES = [
    ("podium", ".podium-slot", ".podium-avatar", "podium"),
    ("board-rest", ".board-rest-row", ".board-avatar", "rest"),
    ("costar", ".costar-row", '[data-costar-role="other"]', "costar"),
    ("gantt", ".gantt-table .gantt-row:not(.gantt-head-row)", ".gantt-avatar", "gantt"),
    ("solo", ".solo-row", ".solo-avatar", "solo"),
]

@pytest.mark.parametrize(
    "entry,row_sel,avatar_sel,picker", ENTRIES,
    ids=[e[0] for e in ENTRIES],
)
def test_avatar_fly_entry_flies_and_lands(
    page: Page, base_url: str, entry: str, row_sel: str, avatar_sel: str, picker: str,
) -> None:
    """五入口：點擊後出現 ghost → settle 後 ghost=0、焦點對、頭像可見。"""
    load_ready(page, base_url)
    names = _classify(page)
    if entry == "costar":
        pair = _find_costar_pair(page, names["withPhoto"] or names["gantt"])
        if not pair:
            pytest.skip("與她同片：片庫湊不出有共演列的女優")
        click_gantt_actress(page, pair["self"])
        try:
            _wait_fly_settled(page, timeout=1_500)
        except Exception:
            page.wait_for_timeout(400)
        page.wait_for_function(
            "() => document.querySelectorAll('.costar-row').length > 0", timeout=3_000)
        target = pair["other"]
        _click_row_not_avatar(page, row_sel, target, avatar_sel)
    else:
        pool = names.get(picker) or []
        if not pool:
            pytest.skip(f"{entry} 入口目前無列可點")
        target = _pick_target(page, pool)
        if entry == "gantt":
            click_gantt_actress(page, target)
        else:
            _click_row_not_avatar(page, row_sel, target, avatar_sel)
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('%s').length > 0" % GHOST, timeout=1_500)
    except Exception:
        pytest.fail(f"{entry}: 點擊後未出現 [data-avatar-fly-ghost]")
    assert _ghost_count(page) >= 1
    _wait_fly_settled(page)
    _assert_landed(page, target)


def test_avatar_fly_prm_skips_ghost(page: Page, base_url: str) -> None:
    """PRM：不出現 ghost。"""
    page.emulate_media(reduced_motion="reduce")
    load_ready(page, base_url)
    names = _classify(page)
    target = (names["withPhoto"] or names["gantt"])[0]
    click_gantt_actress(page, target)
    page.wait_for_timeout(120)
    samples = [_ghost_count(page) for _ in range(8)]
    assert max(samples) == 0, f"PRM 不應建立 ghost：{samples}"
    assert _focus(page) == {"actress": target, "maker": None}
    snap = _focus_avatar_ok(page)
    assert snap.get("exists") and not snap.get("hiddenAttr")
    assert snap.get("opacity") in ("", "1")

def test_avatar_fly_rapid_clicks_third_wins(page: Page, base_url: str) -> None:
    """快速連點 3 位：settle 後 ghost=0、focus＝第 3 位。"""
    load_ready(page, base_url)
    names = _classify(page)
    pool = names.get("rest") or []
    if len(pool) < 3:
        pytest.skip(f"精簡名單女優不足 3 位（{len(pool)}）")
    a, b, c = pool[0], pool[1], pool[2]
    def _click_rest(name: str) -> None:
        coords = page.evaluate("""name => {
            const el = [...document.querySelectorAll('.board-rest-row .board-name')]
                .filter(e => e.offsetParent !== null && e.textContent.trim() === name).at(-1);
            if (!el) return null;
            el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
            const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
            const hit = document.elementFromPoint(x, y);
            return { x, y, ok: !!hit && el.contains(hit) };
        }""", name)
        assert coords and coords["ok"], f"可見名單名字被遮擋：{name!r} / {coords}"
        page.mouse.click(coords["x"], coords["y"])
    _click_rest(a)
    page.wait_for_timeout(60)
    _click_rest(b)
    page.wait_for_timeout(60)
    _click_rest(c)
    _wait_fly_settled(page)
    wait_settled(page)
    _assert_landed(page, c)
