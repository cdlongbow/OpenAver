"""
E2E 安全網：TASK-156d-T7 — 快速連點最終一致性＋PRM 全域整合驗收（片庫分析頁）

依 `feature/156-library-insights2/TASK-156d-T7.md` ＋ plan CD-156d-5「Oracle（CDP）
156d-T7 子段」落地：使用者在動畫還沒播完時就又點了下一位女優（或清除／換人），
不管點得多快、點在動畫的哪個階段，settle 後看到的畫面都必須跟「直接設成最後一次
點擊的目標」一模一樣。這件事只被 156d-T3 實作者在開發當下用 CDP 手動驗過一次
（未留下可重跑的測試），本檔把它變成可重跑的自動化回歸。

驗證目標：`web/static/js/pages/insights/state.js::_handleActressFocusChange`
（CD-156d-2 步驟 4：每次新觸發前先對 top20El/costarEl/row7El 呼叫
`motion.killTweens(...)`，再永遠依當下最新 `this.isActressFocused` 從頭開始）。

**定稿輪數 2（review REQUEST_CHANGES 後修正，逐條對應）**：
  - F1：介入點擊改由「觀察條件驅動」（`page.wait_for_function` 輪詢目標元素的
    inline opacity，落在 (0,1) 開區間才判定為真的打在補間中途），並改用低開銷的
    `page.mouse.click(x, y)`（非 Playwright Locator `.click()`——定稿輪數 1 用
    Locator 時，其 actionability 檢查（可見＋穩定兩幀＋非遮擋）本身要花
    150–250ms，導致「淡出中中斷」實際落在首擊後 365.7ms（淡出 250ms 早已播完）、
    「淡入中中斷」落在 682.3ms（costar 已到終值 opacity 1）——兩次介入其實都打在
    settle 之後，不是打在補間中途，測試整段沒有驗到它宣稱在驗的東西）。
    點擊前那一刻的 opacity 現在會被**斷言**落在 (0.02, 0.98) 之間，量到的值也會
    印出來供人工核對；沒打中就是測試失敗（不是 skip），讓時序失誤可見。
    「1 秒內連點 3 人再清除」情境比照辦理：最後一次「清除」點擊斷言落在 row7
    進場淡入（0~0.5s）的中途（前面兩次「換人」對動畫是 no-op，不影響這個窗口）。
  - F2：新增 `test_switch_actress_mid_animation_matches_direct_set`——焦點 A 進場
    淡入中途（觀察 costarEl opacity 落在 (0,1)）點 B（不清除，直接換人）：讀
    `_handleActressFocusChange` 步驟 3 可證這是 `wasActress===isNowActress` 的
    no-op 分支（不觸發任何新的淡出淡入，A 遺留的 tween 会自然跑完），但 CD-156d-6
    的捲動判斷（`switchedActress`）仍然成立、且其餘 recompute 呼叫已經算好 B 的
    資料——settle 後應完全等同「直接進場點 B 一次（未經過 A）」的對照組，且
    `window.scrollTo` 確實被呼叫過。
  - F3：可見元素（`display !== 'none'`）除了既有 inline opacity 規則外，新增
    `getComputedStyle().opacity === '1'` 斷言（CD-156d-5「無殘留半透明」／
    T3 DoD「可見者 computed opacity===1」）。

**其餘設計決策（同定稿輪數 1，未變動）**：
  1. 「聚焦→清除」的介入動作優先於「切成另一位」——後者在 `_handleActressFocusChange`
     內 `wasActress === isNowActress` 時直接 `return`，是天生安全、不會被本卡
     mutation 點影響的路徑；F2 新增的切換測試專門驗這條 no-op 路徑本身的正確性
     （settle 後資料/捲動仍須正確），跟其餘四支測試驗的「isActressFocused 真正
     翻轉」是互補、不重疊的兩件事。
  2. 對照組＝「頁面剛載入、從未點擊過」的初始快照（四支「清除」情境）或「reload
     後直接點一次目標」（F2「切換」情境，因為目標不是清除）。
  3. 點擊目標一律用年表（`.gantt-table .gantt-row`，row5）——不在 row3/row7 的
     `is-hidden` 切換範圍內，點擊當下不會因為目標暫時 `display:none` 而落空。
     座標取 `.gantt-cell`（資料格，非頭像——頭像有 `@click.stop`，點下去不會
     冒泡到列本身的 `@click="toggleActressFocus(...)"`）。

執行：
    source venv/bin/activate && pytest tests/e2e/test_insights_focus_race_e2e.py -v -m e2e
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

DESKTOP = 1440
MOBILE = 390

ALPINE_ROOT_SELECTOR = '[x-data="libraryInsights"]'

# 1 秒內連續點擊 3 位不同女優的節奏（PRM 情境的點擊間隔；一般情境改用觀察式
# `_click_mid_tween` 驅動節奏，見 `test_rapid_triple_click_then_clear_matches_baseline`
# 定稿輪數 2 的說明——實測真滑鼠點擊本身的 CDP 往返就要約 250–300ms，固定間隔
# 疊加三次點擊會把短窗口的 tween 吃光）。
BURST_CLICK_INTERVAL_MS = 150

# settle：卡片給的 1.5 秒是「保守上限」；實際判定靠 _wait_settled 的輪詢式 oracle。
SETTLE_TIMEOUT_MS = 1_500
# T6 頒獎台進場動效（playRise）只在首次載入播一次，動的是子元素 transform，跟本檔
# 要驗證的 killTweens 目標（top20El/costarEl/row7El 的 opacity）並非同一組屬性，
# 但先讓它播完可以讓測試意圖單純、不與本檔無關的動畫時序糾纏。
PODIUM_ENTRANCE_SETTLE_MS = 900

REF_NAMES = ("top20Row3El", "costarEl", "row7El")

# F1：「打在補間中途」的判定窗口——嚴格排除兩端點（0/1/''），避免把「剛好取樣到
# 起點或終點那一幀」誤判成命中中途。
MID_TWEEN_LOW = 0.02
MID_TWEEN_HIGH = 0.98
MID_TWEEN_WAIT_TIMEOUT_MS = 2_000


# ── 共用 helper ───────────────────────────────────────────────────────────────

def _load_ready(page: Page, base_url: str, width: int = DESKTOP, height: int = 900) -> list:
    """導到 /insights、等 Alpine hydrate + 快照載完（ganttRows 非空）、
    等 T6 頒獎台進場動效播完，回傳目前 `ganttRows` 的女優名字清單（依渲染順序）。
    """
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/insights")
    page.wait_for_function(
        "window.Alpine && !!document.querySelector('%s')?._x_dataStack"
        % ALPINE_ROOT_SELECTOR,
        timeout=15_000,
    )
    page.wait_for_function(
        """() => {
            const root = document.querySelector('%s');
            const data = window.Alpine && Alpine.$data(root);
            return !!(data && data.ganttRows && data.ganttRows.length > 0);
        }"""
        % ALPINE_ROOT_SELECTOR,
        timeout=15_000,
    )
    page.wait_for_timeout(PODIUM_ENTRANCE_SETTLE_MS)
    return page.evaluate(
        """() => {
            const root = document.querySelector('%s');
            const data = window.Alpine && Alpine.$data(root);
            return data ? (data.ganttRows || []).map(r => r.name) : [];
        }"""
        % ALPINE_ROOT_SELECTOR
    )


_FIND_GANTT_CELL_JS = """(name) => {
    const rows = Array.from(
        document.querySelectorAll('.gantt-table .gantt-row:not(.gantt-head-row)')
    );
    for (const row of rows) {
        const nameEl = row.querySelector('.gantt-name');
        if (nameEl && nameEl.textContent.trim() === name) {
            const cell = row.querySelector('.gantt-cell') || row;
            cell.scrollIntoView({ block: 'center', inline: 'center' });
            const r = cell.getBoundingClientRect();
            return { x: r.left + r.width / 2, y: r.top + r.height / 2, found: true };
        }
    }
    return { found: false };
}"""


def _wait_scroll_settled(page: Page, timeout: int = 800) -> None:
    """CD-156d-6：聚焦（進場／換人）會觸發 `window.scrollTo({top:0, behavior:
    'smooth'})`——若在這個平滑捲動還沒播完時就去讀「下一個點擊目標」的座標，會
    撈到捲動途中某一幀的 viewport，算出來的座標對應到的其實是別的元素（定稿
    輪數 2 實測：切換到 b 後緊接著找 c 的座標，`elementFromPoint` 在那組座標
    量到的是 costarCard 的 `.list-rows`，不是年表列——因為畫面正在往頁面頂端
    捲動途中，年表原本的位置暫時被 row3 的內容佔據）。等 `window.scrollY`
    連續 3 次輪詢不再變動才視為捲動 settle。
    """
    page.evaluate("() => { window.__oaLastScrollY = -1; window.__oaScrollStableCount = 0; }")
    page.wait_for_function(
        """() => {
            const y = window.scrollY;
            if (Math.abs(y - window.__oaLastScrollY) < 0.5) {
                window.__oaScrollStableCount = (window.__oaScrollStableCount || 0) + 1;
            } else {
                window.__oaScrollStableCount = 0;
            }
            window.__oaLastScrollY = y;
            return window.__oaScrollStableCount >= 3;
        }""",
        timeout=timeout,
    )


def _click_gantt_actress_raw(page: Page, name: str) -> None:
    """低延遲版本：等捲動 settle 後，單一 evaluate 內完成「找列→捲入視窗→算
    座標」，接著立刻 `page.mouse.click(x, y)`——不經過 Playwright Locator 的
    actionability 檢查（可見＋穩定兩幀＋非遮擋，實測要花 150–250ms）。用於需要
    精準命中補間中途的介入點擊；年表列不在 row3/row7 的淡出淡入切換範圍內，
    `scrollIntoView` 後座標穩定，真滑鼠點擊（`page.mouse.click`）仍是 card
    允許的「真滑鼠」兩種方式之一。
    """
    _wait_scroll_settled(page)
    coords = page.evaluate(_FIND_GANTT_CELL_JS, name)
    assert coords.get("found"), f"年表找不到女優 {name!r} 那一列（可能已被 period 篩掉）"
    page.mouse.click(coords["x"], coords["y"])


def _click_mid_tween(page: Page, watch_ref: str, click_name: str,
                      timeout: int = MID_TWEEN_WAIT_TIMEOUT_MS) -> float:
    """F1：輪詢 `watch_ref` 的 inline opacity 直到落在 (MID_TWEEN_LOW,
    MID_TWEEN_HIGH) 之間（代表該元素真的在 GSAP 補間中途，非兩端點），一成立
    立刻讀值＋算座標＋用低開銷原生點擊觸發 `click_name` 那一列，回傳點擊當下
    量到的 opacity（供斷言與人工核對）。

    條件逾時或點擊當下的 opacity 不在範圍內 ⇒ AssertionError（測試失敗，不是
    skip——時序失誤要可見，不能被吞掉）。
    """
    page.wait_for_function(
        """(args) => {
            const [ref, low, high] = args;
            const el = document.querySelector(`[x-ref="${ref}"]`);
            if (!el) return false;
            const op = parseFloat(el.style.opacity);
            return !Number.isNaN(op) && op > low && op < high;
        }""",
        arg=[watch_ref, MID_TWEEN_LOW, MID_TWEEN_HIGH],
        timeout=timeout,
    )
    result = page.evaluate(
        """(args) => {
            const [ref, name] = args;
            const el = document.querySelector(`[x-ref="${ref}"]`);
            const op = el ? parseFloat(el.style.opacity) : NaN;
            const rows = Array.from(
                document.querySelectorAll('.gantt-table .gantt-row:not(.gantt-head-row)')
            );
            let coords = null;
            for (const row of rows) {
                const nameEl = row.querySelector('.gantt-name');
                if (nameEl && nameEl.textContent.trim() === name) {
                    const cell = row.querySelector('.gantt-cell') || row;
                    const r = cell.getBoundingClientRect();
                    coords = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                    break;
                }
            }
            return { opacity: op, coords };
        }""",
        [watch_ref, click_name],
    )
    assert result["coords"] is not None, f"年表找不到女優 {click_name!r} 那一列"
    op = result["opacity"]
    assert MID_TWEEN_LOW < op < MID_TWEEN_HIGH, (
        f"介入沒打在補間中途：觀察目標 {watch_ref} 點擊當下 opacity={op!r}，"
        f"預期落在 ({MID_TWEEN_LOW}, {MID_TWEEN_HIGH})（時序失誤，不是環境問題）"
    )
    page.mouse.click(result["coords"]["x"], result["coords"]["y"])
    return op


def _install_scroll_spy(page: Page) -> None:
    """monkey-patch `window.scrollTo` 計數呼叫次數（供 F2 驗證 CD-156d-6 的
    `switchedActress` 捲動判斷確實被觸發），不影響原本的捲動行為（仍呼叫
    原始函式）。"""
    page.evaluate(
        """() => {
            window.__oaScrollToCalls = 0;
            if (!window.__oaScrollToPatched) {
                window.__oaScrollToPatched = true;
                const orig = window.scrollTo.bind(window);
                window.scrollTo = function (...args) {
                    window.__oaScrollToCalls += 1;
                    return orig(...args);
                };
            }
        }"""
    )


def _scroll_call_count(page: Page) -> int:
    return page.evaluate("() => window.__oaScrollToCalls || 0")


def _snapshot(page: Page) -> dict:
    """讀 focus + 三個可切換顯示旗標 + 各列表渲染順序（名字清單）+ 三個動畫目標
    元素的 computed display / computed opacity / inline opacity / inline
    backgroundColor。
    """
    return page.evaluate(
        """() => {
            const root = document.querySelector('%s');
            const data = window.Alpine && Alpine.$data(root);
            if (!data) return null;
            const readEl = (ref) => {
                const el = document.querySelector(`[x-ref="${ref}"]`);
                if (!el) return null;
                const cs = getComputedStyle(el);
                return {
                    display: cs.display,
                    computedOpacity: cs.opacity,
                    inlineOpacity: el.style.opacity,
                    inlineBg: el.style.backgroundColor,
                };
            };
            return {
                focus: data.focus ? { type: data.focus.type, value: data.focus.value } : null,
                showTop20InRow3: !!data.showTop20InRow3,
                showCostar: !!data.showCostar,
                showTop20InRow7: !!data.showTop20InRow7,
                podiumNames: (data.podiumRows || []).map(r => r.rank + ':' + r.name),
                restNames: (data.restRows || []).map(r => r.name),
                ganttNames: (data.ganttRows || []).map(r => r.name),
                soloNames: (data.soloRows || []).map(r => r.name),
                costarNames: (data.costarRows || []).map(r => r.self + '×' + r.name),
                top20Row3El: readEl('top20Row3El'),
                costarEl: readEl('costarEl'),
                row7El: readEl('row7El'),
            };
        }"""
        % ALPINE_ROOT_SELECTOR
    )


def _sample_opacities(page: Page) -> dict:
    return page.evaluate(
        """() => {
            const out = {};
            %s.forEach((ref) => {
                const el = document.querySelector(`[x-ref="${ref}"]`);
                out[ref] = el ? el.style.opacity : '';
            });
            return out;
        }"""
        % list(REF_NAMES)
    )


def _geometry(page: Page) -> dict:
    """row4 起點 + 四個 chart-wrap 容器（treemap/age/director/series）的 rect——
    不變式 4（桌面完全相同）＋「圖表長寬比」DoD 用同一份快照（rect 相同蘊含長寬
    比相同，比只比長寬比更嚴格，兩條 DoD 一併滿足）。

    量測前強制捲回 (0,0)：不變式 4 要驗的是「連點導致的版面高度變動」（row3 兩個
    佔用者高度不同造成 row4/row5 位移），跟「視窗當下捲動到哪」是兩件事——本檔
    點擊年表列時會 `scrollIntoView`，若不歸零捲動位置，settle 後量到的
    `getBoundingClientRect()` 會把「測試自己造成的捲動位移」跟「產品真正的版面
    位移」混在一起，稀釋掉這條不變式的鑑別力。
    """
    page.evaluate("() => window.scrollTo(0, 0)")
    return page.evaluate(
        """() => {
            const rect = (el) => {
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return { x: r.x, y: r.y, width: r.width, height: r.height };
            };
            const wrapOf = (id) => {
                const el = document.getElementById(id);
                return rect(el ? el.parentElement : null);
            };
            return {
                row4: rect(document.querySelector('.row4')),
                treemap: wrapOf('tagsChart'),
                age: wrapOf('ageChart'),
                director: wrapOf('directorChart'),
                series: wrapOf('seriesChart'),
            };
        }"""
    )


def _wait_settled(page: Page, timeout: int = SETTLE_TIMEOUT_MS) -> None:
    """輪詢式 settle 判定：top20Row3El/costarEl/row7El 的 inline `style.opacity`
    連續 3 次輪詢（Playwright 預設用 requestAnimationFrame 輪詢）都落在
    `''`/`'0'`/`'1'`（非補間中間值）才判定為 settle——GSAP tween 進行中每一幀
    都會寫入非這三個值之一的 inline opacity，連續 3 幀都不是代表已無 tween 在跑。
    """
    page.evaluate("() => { window.__oaSettleStreak = 0; }")
    page.wait_for_function(
        """() => {
            const refs = %s;
            const settled = refs.every((ref) => {
                const el = document.querySelector(`[x-ref="${ref}"]`);
                if (!el) return true;
                const op = el.style.opacity;
                return op === '' || op === '0' || op === '1';
            });
            if (!settled) { window.__oaSettleStreak = 0; return false; }
            window.__oaSettleStreak = (window.__oaSettleStreak || 0) + 1;
            return window.__oaSettleStreak >= 3;
        }"""
        % list(REF_NAMES),
        timeout=timeout,
    )
    # 額外緩衝：onComplete 內的 `this.showXxx = ...` 與其 `$nextTick` 回呼理論上
    # 在 opacity 落定的同一輪已跑完，這裡留一點餘裕避免邊界時序誤判。
    page.wait_for_timeout(50)


def _assert_state_equal(actual: dict, expected: dict, label: str) -> None:
    assert actual is not None and expected is not None, f"{label}: 讀不到 Alpine 狀態"
    assert actual["focus"] == expected["focus"], (
        f"{label}: focus 不一致，實際 {actual['focus']!r}，預期 {expected['focus']!r}"
    )
    for key in ("showTop20InRow3", "showCostar", "showTop20InRow7"):
        assert actual[key] == expected[key], (
            f"{label}: {key} 不一致，實際 {actual[key]!r}，預期 {expected[key]!r}"
        )
    for key in ("podiumNames", "restNames", "ganttNames", "soloNames", "costarNames"):
        assert actual[key] == expected[key], (
            f"{label}: {key} 順序/內容不一致，實際 {actual[key]!r}，預期 {expected[key]!r}"
        )
    for ref in ("top20Row3El", "costarEl", "row7El"):
        a, e = actual[ref], expected[ref]
        assert a is not None and e is not None, f"{label}: {ref} 元素缺失"
        assert (a["display"] == "none") == (e["display"] == "none"), (
            f"{label}: {ref} 可見性不一致，實際 display={a['display']!r}，"
            f"預期 display={e['display']!r}"
        )
        if a["display"] == "none":
            # 隱藏路徑一律經過 `onComplete` 裡的 `motion.clearProps(el, 'opacity')`
            # 才會把 `is-hidden` 蓋上（見 `_handleActressFocusChange` 兩個
            # onComplete 分支）——真正清空是 `''`，不是「''/0/1 任一都算」。
            assert a["inlineOpacity"] == "", (
                f"{label}: {ref} 已隱藏（display:none）卻殘留 inline opacity="
                f"{a['inlineOpacity']!r}（不變式 2：隱藏路徑必須真正清空，非"
                "'0'/'1'——殘留代表有一條沒被 killTweens 清掉的舊 tween 在"
                "clearProps 之後又寫回了這個屬性）"
            )
        else:
            assert a["inlineOpacity"] in ("", "0", "1"), (
                f"{label}: {ref} 殘留補間中間態 opacity={a['inlineOpacity']!r}（不變式 2）"
            )
            # F3：可見元素 computed opacity 必須是 '1'（CD-156d-5「無殘留半透明」／
            # T3 DoD「可見者 computed opacity===1」），比 inline 值更貼近使用者
            # 實際看到的畫面（inline 值可能因瀏覽器四捨五入等因素與 computed 值
            # 有極小差異，computed 才是渲染管線真正採用的值）。
            assert a["computedOpacity"] == "1", (
                f"{label}: {ref} 可見（display={a['display']!r}）但 computed "
                f"opacity={a['computedOpacity']!r}（應為 '1'，殘留半透明）"
            )
        assert a["inlineBg"] in ("", "rgba(0, 0, 0, 0)"), (
            f"{label}: {ref} 殘留 backgroundColor={a['inlineBg']!r}（不變式 2）"
        )
    # 不變式 3：同一插槽（top20Row3El／costarEl）settle 後不得同時有排版。
    top20_visible = actual["top20Row3El"]["display"] != "none"
    costar_visible = actual["costarEl"]["display"] != "none"
    assert not (top20_visible and costar_visible), (
        f"{label}: top20Row3El 與 costarEl settle 後同時可見"
        f"（top20Row3El={actual['top20Row3El']}, costarEl={actual['costarEl']}）"
    )


def _assert_geometry_equal(actual: dict, expected: dict, tolerance: float = 1.0) -> None:
    for key in ("row4", "treemap", "age", "director", "series"):
        a, e = actual.get(key), expected.get(key)
        assert a is not None and e is not None, f"geometry 缺失：{key}（實際 {a}，基準 {e}）"
        for field in ("x", "y", "width", "height"):
            assert abs(a[field] - e[field]) <= tolerance, (
                f"{key}.{field} 連點後與基準不同：實際 {a[field]:.2f} vs 基準 {e[field]:.2f}"
                f"（容差 {tolerance}px，不變式 4／圖表長寬比 DoD）"
            )


def _skip_if_insufficient(names: list, need: int) -> None:
    if len(names) < need:
        pytest.skip(
            f"年表女優列數 {len(names)} 不足 {need} 位，無法湊出本情境所需的連點目標"
            "（片庫資料可能太少）"
        )


# ── 情境 1：淡出中中斷（卡片指定 mutation 目標測試） ──────────────────────────

def test_interrupt_during_fade_out_matches_direct_set(page: Page, base_url: str) -> None:
    """淡出中中斷：點擊聚焦後，觀察 top20Row3El 的 inline opacity 落回 (0,1)
    開區間（代表淡出 tween 正在跑、display 尚未切換）就立刻再點同一位（清除）。
    settle 後畫面應與「從未點擊過」的基準快照一致（不變式 1）。
    """
    names = _load_ready(page, base_url)
    _skip_if_insufficient(names, 1)
    baseline_state = _snapshot(page)
    baseline_geo = _geometry(page)

    target = names[0]
    _click_gantt_actress_raw(page, target)
    _click_mid_tween(page, "top20Row3El", target)  # 中途點同一位＝清除
    _wait_settled(page)

    settled_state = _snapshot(page)
    settled_geo = _geometry(page)
    _assert_state_equal(settled_state, baseline_state, "淡出中中斷")
    _assert_geometry_equal(settled_geo, baseline_geo)


# ── 情境 2：淡入中中斷 ─────────────────────────────────────────────────────────

def test_interrupt_during_fade_in_matches_direct_set(page: Page, base_url: str) -> None:
    """淡入中中斷：觀察 costarEl 的 inline opacity 落回 (0,1) 開區間（代表
    display 已切換、costarEl 正在淡入)才立刻再點同一位（清除）。settle 後畫面
    應與基準快照一致。
    """
    names = _load_ready(page, base_url)
    _skip_if_insufficient(names, 1)
    baseline_state = _snapshot(page)
    baseline_geo = _geometry(page)

    target = names[0]
    _click_gantt_actress_raw(page, target)
    _click_mid_tween(page, "costarEl", target)  # 中途點同一位＝清除
    _wait_settled(page)

    settled_state = _snapshot(page)
    settled_geo = _geometry(page)
    _assert_state_equal(settled_state, baseline_state, "淡入中中斷")
    _assert_geometry_equal(settled_geo, baseline_geo)


# ── 情境 3：1 秒內連點 3 位不同女優再清除 ──────────────────────────────────────

def test_rapid_triple_click_then_clear_matches_baseline(page: Page, base_url: str) -> None:
    """1 秒內連續點擊 3 個不同女優（年表任一皆可）再點清除：settle 後應回到
    「無焦點」的基準畫面，與清除狀態的靜態對照組（=頁面初始快照）相同。

    F1：第二次點擊（切成 b）斷言落在 costarEl 淡入中途——實測發現每次真滑鼠點擊
    本身（`evaluate` 找列＋`page.mouse.click` 的 CDP 往返）就要花約 250–300ms，
    3 次點擊疊加後如果把「打中補間中途」的斷言放在最後一次「清除」點擊、觀察
    row7（僅 0.5s 窗口），會在點擊 b／c 的路上就把窗口耗盡（實測 c 點下去時
    row7 opacity 已是 0.9994，下一輪就到 1，`_click_mid_tween` 直接 timeout——
    見定稿輪數 2 執行紀錄）。改把斷言放在**第二次**點擊（a→b，觀察 costarEl）：
    這是 a 自己的進場序列最先進入、視窗最寬裕的一段（top20 淡出 0.25s 播完後
    costarEl 才開始淡入，接在第一次點擊的 CDP 往返之後正好落入這段），滿足
    review「至少一次點擊要斷言落在 tween 中途」——後續切 c、清除兩次點擊不需要
    精準時序（`wasActress===isNowActress` 的換人本身對動畫是 no-op，只有這裡的
    b 需要真的打中還在跑的舊 tween 才算「連點打斷」）。
    """
    names = _load_ready(page, base_url)
    _skip_if_insufficient(names, 3)
    baseline_state = _snapshot(page)
    baseline_geo = _geometry(page)

    a, b, c = names[0], names[1], names[2]
    _click_gantt_actress_raw(page, a)
    _click_mid_tween(page, "costarEl", b)  # 中途切成 b（真正命中補間中途的那一擊）
    _click_gantt_actress_raw(page, c)  # 再切成 c（`_wait_scroll_settled` 已排除
    # 切到 b 觸發的 CD-156d-6 捲動與「找 c 座標」互撞的問題，見執行紀錄）
    _click_gantt_actress_raw(page, c)  # 此刻聚焦者是 c → 再點 c 才是清除
    _wait_settled(page)

    settled_state = _snapshot(page)
    settled_geo = _geometry(page)
    _assert_state_equal(settled_state, baseline_state, "1秒連點3人再清除")
    _assert_geometry_equal(settled_geo, baseline_geo)


# ── 情境 4（F2）：聚焦中途切成另一位（no-op 動畫路徑本身要正確） ──────────────

def test_switch_actress_mid_animation_matches_direct_set(page: Page, base_url: str) -> None:
    """焦點 A 進場、costarEl 淡入中途（觀察 opacity 落在 (0,1)）直接切成 B
    （不清除）：讀 `_handleActressFocusChange` 步驟 3，`wasActress ===
    isNowActress`（true===true）時函式直接 `return`——不觸發任何新的淡出淡入、
    不呼叫 `killTweens`，A 的 costarEl/row7El tween 會各自自然跑完；但 CD-156d-6
    的 `switchedActress` 捲動判斷仍會成立，且同一輪 `$watch('focus')` 的其餘
    recompute 呼叫（`recomputeCostar`/`recomputeGantt`/`recomputeSolo` 等）已經
    算好 B 的資料。

    settle 後應完全等同「reload 後直接進場點 B 一次（未經過 A）」的對照組
    （focus/顯示旗標/三個 ref 元素狀態/各列表渲染順序全部一致），且捲動被觸發過
    （`window.scrollTo` 呼叫次數 > 0）。
    """
    names = _load_ready(page, base_url)
    _skip_if_insufficient(names, 2)
    a, b = names[0], names[1]

    _install_scroll_spy(page)
    _click_gantt_actress_raw(page, a)
    _click_mid_tween(page, "costarEl", b)  # A 進場淡入中途，直接切成 B（非清除）
    scroll_calls = _scroll_call_count(page)
    _wait_settled(page)

    switched_state = _snapshot(page)
    switched_geo = _geometry(page)

    # 對照組：reload 後直接進場點 B 一次（未經過 A）。
    reference_names = _load_ready(page, base_url)
    assert b in reference_names, f"reload 後年表找不到目標 {b!r}（片庫資料應一致）"
    _click_gantt_actress_raw(page, b)
    _wait_settled(page)
    reference_state = _snapshot(page)
    reference_geo = _geometry(page)

    assert scroll_calls > 0, (
        "中途切換到不同女優（CD-156d-6 switchedActress）應觸發 window.scrollTo "
        f"捲回頂端，但監聽到的呼叫次數是 {scroll_calls}"
    )
    assert switched_state["focus"] == {"type": "actress", "value": b}, (
        f"settle 後 focus 應為切換目標 B（{b!r}），實際 {switched_state['focus']!r}"
    )
    _assert_state_equal(switched_state, reference_state, "聚焦中途切換女優")
    _assert_geometry_equal(switched_geo, reference_geo)


# ── 窄螢幕：settle 後位置與基準相同（不變式 4 窄螢幕子句） ─────────────────────

def test_narrow_width_settles_to_baseline_position(page: Page, base_url: str) -> None:
    """不變式 4 窄螢幕子句：<=1024px 只要求 settle 後位置與「該寬度下的靜態位置」
    相同（不要求逐幀不動）。本檔對照組＝基準快照本身就是同寬度下未聚焦的靜態
    位置，settle 後（=清除後）理當回到同一組數字。
    """
    names = _load_ready(page, base_url, width=MOBILE)
    _skip_if_insufficient(names, 1)
    baseline_state = _snapshot(page)
    baseline_geo = _geometry(page)

    target = names[0]
    _click_gantt_actress_raw(page, target)
    _click_mid_tween(page, "top20Row3El", target)
    _wait_settled(page)

    settled_state = _snapshot(page)
    settled_geo = _geometry(page)
    _assert_state_equal(settled_state, baseline_state, "窄螢幕連點")
    _assert_geometry_equal(settled_geo, baseline_geo, tolerance=2.0)


# ── PRM：reduced-motion 開啟時全動效瞬間完成 ──────────────────────────────────

def test_prm_rapid_clicks_settle_instantly_and_match_baseline(page: Page, base_url: str) -> None:
    """`page.emulate_media(reduced_motion="reduce")`（觸發 motion-prefs.js 的
    matchMedia listener，非手動塞旗標——見假綠陷阱 #4）開啟後跑「1 秒連點 3 人
    再清除」：settle 後畫面應與 PRM 關閉時的基準（=同一份「無焦點」初始快照，
    PRM 不影響任何非動畫的資料/排序邏輯）相同；且觸發後 0/50/100ms 三次抽樣都
    量不到 0~1 之間的中間 opacity（`playFadeTo`/`playPulse`/`playRise` 在
    `_shouldAnimate()===false` 時皆為同步 `gsap.set` 到終值，見
    motion-adapter.js:143-162/213-233/246-289）。
    """
    page.emulate_media(reduced_motion="reduce")
    names = _load_ready(page, base_url)
    _skip_if_insufficient(names, 3)
    baseline_state = _snapshot(page)
    baseline_geo = _geometry(page)

    a, b, c = names[0], names[1], names[2]
    _click_gantt_actress_raw(page, a)
    samples = [_sample_opacities(page)]
    page.wait_for_timeout(50)
    samples.append(_sample_opacities(page))
    page.wait_for_timeout(50)
    samples.append(_sample_opacities(page))
    for i, sample in enumerate(samples):
        for ref, val in sample.items():
            assert val in ("", "0", "1"), (
                f"PRM 開啟時抽樣 #{i}（觸發後 {i * 50}ms）觀察到中間態 opacity："
                f"{ref}={val!r}（PRM 應同步 gsap.set 到終值，不補間）"
            )

    page.wait_for_timeout(BURST_CLICK_INTERVAL_MS)
    _click_gantt_actress_raw(page, b)
    page.wait_for_timeout(BURST_CLICK_INTERVAL_MS)
    _click_gantt_actress_raw(page, c)
    page.wait_for_timeout(BURST_CLICK_INTERVAL_MS)
    _click_gantt_actress_raw(page, c)  # 清除
    _wait_settled(page)

    settled_state = _snapshot(page)
    settled_geo = _geometry(page)
    _assert_state_equal(settled_state, baseline_state, "PRM 連點")
    _assert_geometry_equal(settled_geo, baseline_geo)
