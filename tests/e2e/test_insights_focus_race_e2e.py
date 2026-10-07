"""
E2E 安全網：TASK-156d-T7 — 快速連點最終一致性＋PRM 全域整合驗收（片庫分析頁）

依 `feature/156-library-insights2/TASK-156d-T7.md` ＋ plan CD-156d-5「Oracle（CDP）
156d-T7 子段」落地：使用者在動畫還沒播完時就又點了下一位女優（或清除／換人），
不管點得多快、點在動畫的哪個階段，settle 後看到的畫面都必須跟「直接設成最後一次
點擊的目標」一模一樣。這件事只被 156d-T3 實作者在開發當下用 CDP 手動驗過一次
（未留下可重跑的測試），本檔把它變成可重跑的自動化回歸。

驗證目標：`web/static/js/pages/insights/state.js::_handleActressFocusChange`
（CD-156d-2 步驟 4：每次新觸發前先對 boardEl/costarEl/row7El 呼叫
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
     座標取 `.gantt-name`（名字 hover 可預覽，click 冒泡到列切換女優；
     頭像 click 選女優，資料格 click 會同時提交年份）。

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
# 要驗證的 killTweens 目標（boardEl/costarEl/row7El 的 opacity）並非同一組屬性，
# 但先讓它播完可以讓測試意圖單純、不與本檔無關的動畫時序糾纏。
PODIUM_ENTRANCE_SETTLE_MS = 900

REF_NAMES = ("boardRow3El", "costarEl", "row7El")

# F1：「打在補間中途」的判定窗口——嚴格排除兩端點（0/1/''），避免把「剛好取樣到
# 起點或終點那一幀」誤判成命中中途。
# 161a-T5a：分析頁改單一 sel 後，點擊到補間開始約晚 30ms、補間開始後主執行緒又被
# 卡更久，ease-out 的可見段只剩收尾 1~2 幀（opacity 0.1 以下），真實時間下的取樣窗口
# 不穩（基準版 3/3 過、本分支 0/5 過）。判定窗口 (0.02, 0.98) 不動，改成把 GSAP 全域
# 時間軸放慢（MID_TWEEN_TIME_SCALE），讓同一段補間的中途停留時間拉長到好取樣。
# 只影響「補間跑多快」，不改任何終態斷言（settle 後與直設基準的比對、位置容差）。
MID_TWEEN_LOW = 0.02
MID_TWEEN_HIGH = 0.98
MID_TWEEN_TIME_SCALE = 0.5
MID_TWEEN_WAIT_TIMEOUT_MS = 2_000


# ── 共用 helper ───────────────────────────────────────────────────────────────

def _load_ready(
    page: Page, base_url: str, width: int = DESKTOP, height: int = 900, slow: bool = False
) -> list:
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
    if slow:
        # 只有「抓補間中途」的測試才放慢（頒獎台進場播完之後）：淡出淡入補間變長，
        # 中途窗口才抓得穩（見 MID_TWEEN_TIME_SCALE）。其餘測試維持真實速度。
        page.evaluate(
            "(k) => { if (window.gsap) window.gsap.globalTimeline.timeScale(k); }",
            MID_TWEEN_TIME_SCALE,
        )
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
            const cell = row.querySelector('.gantt-name') || row;
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

    TASK-156d-T9 修正既有假綠陷阱：先前這裡沒有 `scrollIntoView`（不像
    `_FIND_GANTT_CELL_JS`），但第一次點擊已觸發 CD-156d-6 的
    `window.scrollTo({top:0})`——在窄螢幕（單欄版面，row5 年表常落在文件
    Y>900px，超過一個視窗高度）下，頁面捲回頂端後目標列會被推出視窗外，
    這裡量到的 `getBoundingClientRect()` y 座標會大於 `innerHeight`，
    `page.mouse.click` 點在視窗外等於沒點到，導致 focus 沒有如預期切換
    （`test_narrow_width_settles_to_baseline_position` 實測 100% 重現，CDP
    量測見執行紀錄：390×900 視窗下 row5.top≈3294px）。`scrollIntoView`
    預設是瞬間捲動（頁面沒有全域 `scroll-behavior:smooth`），不佔用補間
    觀察窗口的時間預算，比照 `_FIND_GANTT_CELL_JS` 補回這一步即可。
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
                    const cell = row.querySelector('.gantt-name') || row;
                    cell.scrollIntoView({ block: 'center', inline: 'center' });
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
    backgroundColor / rectArea。
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
                const r = el.getBoundingClientRect();
                return {
                    display: cs.display,
                    computedOpacity: cs.opacity,
                    inlineOpacity: el.style.opacity,
                    inlineBg: el.style.backgroundColor,
                    rectArea: r.width * r.height,
                };
            };
            return {
                focus: data.sel.actress != null ? { type: 'actress', value: data.sel.actress } : (data.sel.maker != null ? { type: 'maker', value: data.sel.maker } : null),
                showBoardInRow3: !!data.showBoardInRow3,
                showCostar: !!data.showCostar,
                showBoardInRow7: !!data.showBoardInRow7,
                podiumNames: (data.podiumRows || []).map(r => r.rank + ':' + r.name),
                restNames: (data.restRows || []).map(r => r.name),
                ganttNames: (data.ganttRows || []).map(r => r.name),
                soloNames: (data.soloRows || []).map(r => r.name),
                costarNames: (data.costarRows || []).map(r => r.self + '×' + r.name),
                boardRow3El: readEl('boardRow3El'),
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
    """輪詢式 settle 判定：boardRow3El/costarEl/row7El 的 inline `style.opacity`
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
    for key in ("showBoardInRow3", "showCostar", "showBoardInRow7"):
        assert actual[key] == expected[key], (
            f"{label}: {key} 不一致，實際 {actual[key]!r}，預期 {expected[key]!r}"
        )
    for key in ("podiumNames", "restNames", "ganttNames", "soloNames", "costarNames"):
        assert actual[key] == expected[key], (
            f"{label}: {key} 順序/內容不一致，實際 {actual[key]!r}，預期 {expected[key]!r}"
        )
    for ref in ("boardRow3El", "costarEl", "row7El"):
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
            # P3 修正回歸守衛（Codex review）：可見元素必須有實際渲染盒子，
            # 否則 `_handleActressFocusChange` 對它 playFadeTo(opacity) 補間會是
            # 沒有視覺效果的假動畫（display:contents 曾經就是這樣，見
            # insights.css `.board-row3-wrap` 註解）——這條斷言不依賴修法內部
            # 實作細節，只要求「淡出淡入動畫作用的目標必須是有真實渲染盒子的
            # 元素」。
            assert a["rectArea"] > 0, (
                f"{label}: {ref} 可見（display={a['display']!r}）但沒有實際渲染"
                "盒子（rect area=0）——opacity 補間會作用在一個沒有畫面的元素"
                "上，不是真的視覺淡出淡入（display:contents 之類會有這個問題）"
            )
        assert a["inlineBg"] in ("", "rgba(0, 0, 0, 0)"), (
            f"{label}: {ref} 殘留 backgroundColor={a['inlineBg']!r}（不變式 2）"
        )
    # 不變式 3：同一插槽（boardRow3El／costarEl）settle 後不得同時有排版。
    board_visible = actual["boardRow3El"]["display"] != "none"
    costar_visible = actual["costarEl"]["display"] != "none"
    assert not (board_visible and costar_visible), (
        f"{label}: boardRow3El 與 costarEl settle 後同時可見"
        f"（boardRow3El={actual['boardRow3El']}, costarEl={actual['costarEl']}）"
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


def _costar_rows_length(page: Page) -> int:
    return page.evaluate(
        """() => {
            const root = document.querySelector('%s');
            const data = window.Alpine && Alpine.$data(root);
            return data ? (data.costarRows || []).length : 0;
        }"""
        % ALPINE_ROOT_SELECTOR
    )


def _read_period(page: Page) -> dict:
    """讀 `this.sel.period`（`_snapshot()` 沒有這個欄位——它是既有共用 helper，
    本卡 round 3 新測試才需要直接讀 period，不擴大共用 helper 的形狀）。"""
    return page.evaluate(
        """() => {
            const root = document.querySelector('%s');
            const data = window.Alpine && Alpine.$data(root);
            return data ? data.sel.period : null;
        }"""
        % ALPINE_ROOT_SELECTOR
    )


def _classify_by_costar(
    page: Page, names: list, need_with: int = 0, need_without: int = 0
) -> tuple:
    """TASK-156d-T9：`costarVisible`（CD-156d-10a）只在女優焦點且
    `costarRows.length>0` 時為 true——本檔既有測試靠「中途攔截補間」驗證
    `_handleActressFocusChange`，若挑到零共演的女優，`costarVisible` 不會翻轉、
    根本不會播放任何淡出淡入，`_click_mid_tween` 會等不到補間中途（見卡片
    「繼承的陷阱」段）。單一輪依序探測每位候選女優（聚焦→讀 `costarRows.length`
    →清除焦點）、同時收集「有共演」與「零共演」兩個桶，找齊兩邊 need 就提早
    停止；每次探測完都清除焦點並等待 settle，讓頁面回到探測前的無焦點狀態，
    不污染呼叫方接下來的測試流程（呼叫方接手時頁面必為 idle／無焦點）。
    """
    with_costar: list = []
    without_costar: list = []
    for name in names:
        if len(with_costar) >= need_with and len(without_costar) >= need_without:
            break
        _click_gantt_actress_raw(page, name)
        _wait_settled(page)
        length = _costar_rows_length(page)
        if length > 0:
            with_costar.append(name)
        else:
            without_costar.append(name)
        _click_gantt_actress_raw(page, name)  # 清除焦點，恢復無焦點狀態。
        _wait_settled(page)
    return with_costar, without_costar


# ── 情境 1：淡出中中斷（卡片指定 mutation 目標測試） ──────────────────────────

def test_interrupt_during_fade_out_matches_direct_set(page: Page, base_url: str) -> None:
    """淡出中中斷：點擊聚焦後，觀察 boardRow3El 的 inline opacity 落回 (0,1)
    開區間（代表淡出 tween 正在跑、display 尚未切換）就立刻再點同一位（清除）。
    settle 後畫面應與「從未點擊過」的基準快照一致（不變式 1）。

    TASK-156d-T9：淡出淡入現在由 `costarVisible`（非 `isActressFocused`）翻轉
    觸發，零共演女優不會播放任何動畫——目標必須先過濾成「有共演」的女優，
    否則 `_click_mid_tween` 會等不到補間中途（見卡片「繼承的陷阱」段）。
    """
    names = _load_ready(page, base_url, slow=True)
    with_costar, _ = _classify_by_costar(page, names, need_with=1)
    _skip_if_insufficient(with_costar, 1)
    baseline_state = _snapshot(page)
    baseline_geo = _geometry(page)

    target = with_costar[0]
    _click_gantt_actress_raw(page, target)
    _click_mid_tween(page, "boardRow3El", target)  # 中途點同一位＝清除
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

    TASK-156d-T9：同上——目標必須先過濾成「有共演」的女優。
    """
    names = _load_ready(page, base_url, slow=True)
    with_costar, _ = _classify_by_costar(page, names, need_with=1)
    _skip_if_insufficient(with_costar, 1)
    baseline_state = _snapshot(page)
    baseline_geo = _geometry(page)

    target = with_costar[0]
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
    這是 a 自己的進場序列最先進入、視窗最寬裕的一段（女優榜淡出 0.25s 播完後
    costarEl 才開始淡入，接在第一次點擊的 CDP 往返之後正好落入這段），滿足
    review「至少一次點擊要斷言落在 tween 中途」——後續切 c、清除兩次點擊不需要
    精準時序（`wasActress===isNowActress` 的換人本身對動畫是 no-op，只有這裡的
    b 需要真的打中還在跑的舊 tween 才算「連點打斷」）。

    TASK-156d-T9：a/b/c 三位都必須「有共演」——a 自己的進場需要真的觸發
    `costarVisible` 翻轉（否則沒有 tween 可觀察）；切到 b／c 時若對方零共演，
    `costarVisible` 會從 true 翻轉成 false，觸發全新的「離開」動畫（殺掉 a
    還在跑的 tween），跟本測試原本設計的「換人對動畫是 no-op」語意不符。
    """
    names = _load_ready(page, base_url, slow=True)
    with_costar, _ = _classify_by_costar(page, names, need_with=3)
    _skip_if_insufficient(with_costar, 3)
    baseline_state = _snapshot(page)
    baseline_geo = _geometry(page)

    a, b, c = with_costar[0], with_costar[1], with_costar[2]
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

    TASK-156d-T9：a／b 都必須「有共演」，理由同上——若 b 零共演，切換到 b
    會觸發 `costarVisible` 真正翻轉（離開動畫），不再是本測試要驗的
    `wasActress===isNowActress` no-op 分支。
    """
    names = _load_ready(page, base_url, slow=True)
    with_costar, _ = _classify_by_costar(page, names, need_with=2)
    _skip_if_insufficient(with_costar, 2)
    a, b = with_costar[0], with_costar[1]

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

    TASK-156d-T9：目標必須先過濾成「有共演」的女優（理由同淡出/淡入中斷）。
    """
    names = _load_ready(page, base_url, slow=True, width=MOBILE)
    with_costar, _ = _classify_by_costar(page, names, need_with=1)
    _skip_if_insufficient(with_costar, 1)
    baseline_state = _snapshot(page)
    baseline_geo = _geometry(page)

    target = with_costar[0]
    _click_gantt_actress_raw(page, target)
    _click_mid_tween(page, "boardRow3El", target)
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


# ── TASK-156d-T9：沒有共演時顯示女優榜而非空卡 ──────────────────────────────
# CD-156d-10a／10b：`costarVisible = isActressFocused && costarRows.length > 0`；
# 零共演女優 settle 後應顯示女優榜（`showBoardInRow3=true`），`costarEl`
# 不顯示，也不播放任何淡出淡入（`costarVisible` 從 false 到 false，沒有翻轉）。


def test_no_costar_actress_shows_board_not_empty_costar_card(
    page: Page, base_url: str
) -> None:
    """邊界條件 1：焦點一位 `costarRows.length===0` 的女優——row3 左半格顯示
    女優榜（`showBoardInRow3=true`），`costarEl` 不顯示（`showCostar=false`，
    computed `display==='none'`），row7 不顯示（`showBoardInRow7=false`），
    畫面上沒有空白的「與她同片」卡片。
    """
    names = _load_ready(page, base_url)
    _, without_costar = _classify_by_costar(page, names, need_without=1)
    _skip_if_insufficient(without_costar, 1)
    target = without_costar[0]

    _click_gantt_actress_raw(page, target)
    _wait_settled(page)

    state = _snapshot(page)
    assert state["focus"] == {"type": "actress", "value": target}, (
        f"focus 應為 {target!r}，實際 {state['focus']!r}"
    )
    assert state["showBoardInRow3"] is True, "零共演女優應顯示女優榜，不是空的與她同片卡"
    assert state["showCostar"] is False, "零共演女優不應顯示與她同片卡"
    assert state["showBoardInRow7"] is False, "零共演女優不應觸發 row7 顯示"
    assert state["costarEl"]["display"] == "none", (
        f"costarEl computed display 應為 none，實際 {state['costarEl']['display']!r}"
        "（畫面上不該出現空白的『與她同片』卡片）"
    )
    assert state["boardRow3El"]["display"] != "none", "row3 左半格應顯示女優榜"


# ── TASK-156d-T9 round 3：period 改變也要同步 costarVisible ────────────────────
# review 抓到的回歸：`$watch('period')` 只呼叫了 `recomputeCostar()`，沒有跑
# CD-156d-10b 的翻轉判斷——同一位有共演的女優，選到一個她零共演的年份時，
# 「與她同片」空卡會卡在畫面上不會換回女優榜；反方向（零共演年份→有共演年份）
# 也不會換回來。修法把翻轉判斷抽成 `_syncCostarVisibility()`，`period` watcher
# 也呼叫（不捲動，CD-156d-6 明確只認 focus 翻轉）。


def _click_year_bar(page: Page, year: int) -> bool:
    """在 `#yearsChart` 上用真滑鼠點擊該年份的長條，觸發 `charts.js` 既有的點擊
    handler（`_yearsCallbacks.setPeriod(...)`）。該 handler 只檢查點擊像素是否
    落在 grid 座標系內、再用 `convertFromPixel` 反算類別軸 index——不檢查是否
    真的點在長條本身的可見高度內，所以這裡的 y 座標取 grid 垂直置中即可，
    filmCount===0（那一年沒有任何片，長條高度為 0）的年份一樣點得到。若當前
    `period` 已經是這個年份，點擊會照 `charts.js` 既有邏輯切回 `{type:'all'}`
    （跟真人使用者「再點一次同一根長條＝取消篩選」的既有行為一致）。
    找不到該年份的類別軸 index（不在 x 軸範圍內）回傳 False。
    """
    coords = page.evaluate(
        """(year) => {
            const el = document.getElementById('yearsChart');
            const chart = window.echarts && window.echarts.getInstanceByDom(el);
            if (!chart) return null;
            const opt = chart.getOption();
            const cats = opt.xAxis[0].data;
            const idx = cats.indexOf(String(year));
            if (idx < 0) return null;
            const px = chart.convertToPixel({ xAxisIndex: 0 }, idx);
            const gridRect = chart.getModel().getComponent('grid').coordinateSystem.getRect();
            const py = gridRect.y + gridRect.height / 2;
            const rect = el.getBoundingClientRect();
            return { x: rect.left + px, y: rect.top + py };
        }""",
        year,
    )
    if not coords:
        return False
    page.mouse.click(coords["x"], coords["y"])
    return True


def _find_actress_year_costar_flip(page: Page, names: list):
    """依序聚焦候選女優，讀她在「全部年份」下的 `costarRows.length`（>0 才繼續
    往下找）；再用既有的 `ganttView('year')`（`state.js` 年表視圖，逐格
    `filmCount`）取出她「有片」的年份清單，逐一點年份長條讀
    `costarRows.length`，找到一個 `===0`（她那年有片但沒有共演）即回傳
    `(name, zero_year)`。每個候選試完都清回全部年份／清除焦點，讓頁面回到
    探測前的狀態，不污染呼叫方接下來的測試流程。全部候選都試過仍找不到就回
    傳 `None`（呼叫方 `pytest.skip()`，不可假 PASS）。
    """
    for name in names:
        _click_gantt_actress_raw(page, name)
        _wait_settled(page)
        all_costar_len = _costar_rows_length(page)
        if all_costar_len == 0:
            _click_gantt_actress_raw(page, name)  # 清除焦點
            _wait_settled(page)
            continue

        years = page.evaluate(
            """(name) => {
                const root = document.querySelector('%s');
                const data = window.Alpine && Alpine.$data(root);
                const v = data.ganttView('year');
                const row = (v.rows || []).find((r) => r.name === name);
                if (!row) return [];
                return row.cells.filter((c) => c.filmCount > 0).map((c) => c.year);
            }"""
            % ALPINE_ROOT_SELECTOR,
            name,
        )
        zero_year = None
        for y in years:
            if not _click_year_bar(page, y):
                continue
            _wait_settled(page)
            if _costar_rows_length(page) == 0:
                zero_year = y
                break

        # 恢復探測前狀態：回全部年份（若目前卡在某個年份）、清除焦點。
        if page.evaluate(
            """() => {
                const root = document.querySelector('%s');
                const data = window.Alpine && Alpine.$data(root);
                return data.sel.period && data.sel.period.type === 'year';
            }"""
            % ALPINE_ROOT_SELECTOR
        ):
            page.click("#tileYear .insights-x-btn")
            _wait_settled(page)
        _click_gantt_actress_raw(page, name)  # 清除焦點
        _wait_settled(page)

        if zero_year is not None:
            return name, zero_year
    return None


def test_period_change_syncs_costar_card_for_focused_actress(
    page: Page, base_url: str
) -> None:
    """round 3 回歸守衛：女優焦點且當下有共演 → 選一個她零共演的年份，settle
    後必須換成女優榜（`showBoardInRow3=true`、`showCostar=false`、
    `showBoardInRow7=false`），不能卡在空白的「與她同片」卡；接著清除年份篩選
    （回全部年份），「與她同片」卡必須換回來（`showCostar=true`）。

    動態挑選女優與年份（見 `_find_actress_year_costar_flip`）；片庫資料湊不出
    這種組合就 `pytest.skip()`，不可假 PASS。
    """
    names = _load_ready(page, base_url)
    found = _find_actress_year_costar_flip(page, names)
    if found is None:
        pytest.skip(
            "片庫資料湊不出『同一位女優在某年有共演、另一年有片但零共演』的組合"
        )
    name, zero_year = found

    _click_gantt_actress_raw(page, name)
    _wait_settled(page)
    focused_state = _snapshot(page)
    assert focused_state["showCostar"] is True, (
        f"{name!r} 全部年份下應已顯示與她同片卡（前置條件：探測階段已確認 "
        "costarRows.length>0）"
    )

    assert _click_year_bar(page, zero_year), f"yearsChart 找不到年份 {zero_year} 的類別軸座標"
    _wait_settled(page)
    zero_year_period = _read_period(page)
    zero_year_state = _snapshot(page)
    assert zero_year_period == {"type": "year", "year": zero_year}, (
        f"period 應切到 {{'type': 'year', 'year': {zero_year}}}，"
        f"實際 {zero_year_period!r}"
    )
    assert zero_year_state["showBoardInRow3"] is True, (
        f"{name!r} 在 {zero_year} 年零共演，row3 左半格應換回女優榜"
    )
    assert zero_year_state["showCostar"] is False, (
        f"{name!r} 在 {zero_year} 年零共演，不應繼續顯示與她同片卡（空卡）"
    )
    assert zero_year_state["showBoardInRow7"] is False, (
        f"{name!r} 在 {zero_year} 年零共演，row7 不應顯示"
    )
    assert zero_year_state["costarEl"]["display"] == "none", (
        f"costarEl computed display 應為 none，實際 "
        f"{zero_year_state['costarEl']['display']!r}"
    )

    # 回全部年份：與她同片卡必須換回來。
    page.click("#tileYear .insights-x-btn")
    _wait_settled(page)
    back_period = _read_period(page)
    back_state = _snapshot(page)
    assert back_period == {"type": "all"}, (
        f"清除年份篩選後 period 應回到 {{'type': 'all'}}，實際 {back_period!r}"
    )
    assert back_state["showCostar"] is True, (
        f"{name!r} 清除年份篩選回全部年份（有共演）後，與她同片卡應換回來"
    )
    assert back_state["showBoardInRow3"] is False, "與她同片卡顯示時 row3 左半格不應同時顯示女優榜"
    assert back_state["costarEl"]["display"] != "none", "與她同片卡應可見"


def test_switch_between_costar_and_no_costar_actress_matches_direct_set(
    page: Page, base_url: str
) -> None:
    """邊界條件 2：A（有共演）→B（沒共演）在動畫中途切換，settle 後必須與
    『reload 後直接點 B 一次』的對照組一致（不能因為在補間中途攔截，讓
    costarEl 卡在半途或顯示空白的『與她同片』卡——CD-156d-10b
    `wasCostarVisible`/`isNowCostarVisible` 判斷）；B→A 相反方向同理，沿用
    T7 的『直接設定終值』對照組手法（`_assert_state_equal`／
    `_assert_geometry_equal`）。
    """
    names = _load_ready(page, base_url, slow=True)
    with_costar, without_costar = _classify_by_costar(
        page, names, need_with=1, need_without=1
    )
    _skip_if_insufficient(with_costar, 1)
    _skip_if_insufficient(without_costar, 1)
    a, b = with_costar[0], without_costar[0]

    # 第一段：A 進場（costarEl 淡入中途）切成零共演的 B（觸發真正的離開動畫）。
    _click_gantt_actress_raw(page, a)
    _click_mid_tween(page, "costarEl", b)
    _wait_settled(page)
    switched_to_b_state = _snapshot(page)
    switched_to_b_geo = _geometry(page)

    # 對照組：reload 後直接點 B 一次。
    reference_names = _load_ready(page, base_url)
    assert b in reference_names, f"reload 後年表找不到目標 {b!r}（片庫資料應一致）"
    _click_gantt_actress_raw(page, b)
    _wait_settled(page)
    reference_b_state = _snapshot(page)
    reference_b_geo = _geometry(page)

    assert switched_to_b_state["focus"] == {"type": "actress", "value": b}, (
        f"settle 後 focus 應為 B（{b!r}），實際 {switched_to_b_state['focus']!r}"
    )
    assert switched_to_b_state["showCostar"] is False, (
        "零共演女優 settle 後不應顯示與她同片卡（空卡）"
    )
    _assert_state_equal(switched_to_b_state, reference_b_state, "A進場中途切成零共演B")
    _assert_geometry_equal(switched_to_b_geo, reference_b_geo)

    # 第二段：從 B（此刻頁面已聚焦 B、無殘留動畫）切回有共演的 A。
    _click_gantt_actress_raw(page, a)
    _wait_settled(page)
    switched_to_a_state = _snapshot(page)
    switched_to_a_geo = _geometry(page)

    # 對照組：reload 後直接點 A 一次。
    reference_names_a = _load_ready(page, base_url)
    assert a in reference_names_a, f"reload 後年表找不到目標 {a!r}（片庫資料應一致）"
    _click_gantt_actress_raw(page, a)
    _wait_settled(page)
    reference_a_state = _snapshot(page)
    reference_a_geo = _geometry(page)

    assert switched_to_a_state["focus"] == {"type": "actress", "value": a}, (
        f"settle 後 focus 應為 A（{a!r}），實際 {switched_to_a_state['focus']!r}"
    )
    _assert_state_equal(switched_to_a_state, reference_a_state, "B切回有共演A")
    _assert_geometry_equal(switched_to_a_geo, reference_a_geo)


# ── TASK-156d-T9：CD-156d-10c——女優焦點時 row4 移到 row3 之前 ────────────────


def _row_order_geometry(page: Page) -> dict:
    """row3／row4 的文件座標 top（`getBoundingClientRect().top + scrollY`），
    先強制捲回頂端避免當下捲動位置汙染量測（比照 `_geometry` 的做法）。
    """
    page.evaluate("() => window.scrollTo(0, 0)")
    return page.evaluate(
        """() => {
            const top = (sel) => {
                const el = document.querySelector(sel);
                return el ? el.getBoundingClientRect().top + window.scrollY : null;
            };
            return { row3_top: top('.row3'), row4_top: top('.row4') };
        }"""
    )


def _visible_direct_children_order(page: Page) -> list:
    """回傳 `.insights-container` 目前「可見」（computed `display !== 'none'`）
    的直接子元素，依渲染文件座標 top 由小到大排序後的 class 名稱清單（取
    `className` 第一個 token 當識別碼）。

    TASK-156d-T9 round 2 review 抓到的假綠陷阱：只驗 `row3.top`／`row4.top`
    兩者的相對關係，量不到「容器其他直接子元素沒有明確 `order` 基準值、
    預設 order:0 飄到最前面」這類問題——`.section-divider`（純文字分隔列，
    DOM 位置在 row4 與 row5 之間）就是實例：它一開始沒有 order 宣告，實際
    渲染跑到最頂端、蓋過 row1（CDP 實測 section-divider.top=32 < row1.top=60）。
    這支 helper 窮舉全部可見直接子元素（不只 row3/row4），讓測試斷言「完整
    渲染順序」而非「兩個點的相對關係」，才擋得住這類遺漏。
    `.insights-preview`（照片預覽浮層）是 `position:fixed`，不參與 flex
    排版；正常測試流程從未觸發預覽，應維持 `display:none`，不特別排除——
    若它意外可見，讓斷言直接失敗比默默過濾掉更安全。
    """
    page.evaluate("() => window.scrollTo(0, 0)")
    return page.evaluate(
        """() => {
            const root = document.querySelector('%s');
            const kids = Array.from(root.children).filter(
                (el) => getComputedStyle(el).display !== 'none'
            );
            const withTop = kids.map((el) => ({
                cls: (el.className || '').split(' ')[0],
                top: el.getBoundingClientRect().top + window.scrollY,
            }));
            withTop.sort((a, b) => a.top - b.top);
            return withTop.map((k) => k.cls);
        }"""
        % ALPINE_ROOT_SELECTOR
    )


# CD-156d-10c：無焦點（片商焦點視覺上相同）時 `.insights-container` 可見直接
# 子元素的完整渲染順序＝DOM 順序；女優焦點時 row3/row4 對調、多出 row7，其餘
# （含 `.section-divider` 夾在 row3/row4 那組之後、row5 之前）不變。
NO_FOCUS_VISIBLE_ORDER = [
    "row1", "row2", "row3", "row4", "section-divider", "row5", "row6",
]
ACTRESS_FOCUS_VISIBLE_ORDER = [
    "row1", "row2", "row4", "row3", "section-divider", "row5", "row6", "row7",
]


def test_row4_reorders_with_actress_focus(page: Page, base_url: str) -> None:
    """CD-156d-10c／10d：女優焦點時 row4（年齡/導演/系列）應排在 row3（標籤
    樹圖）之前（`row4.top < row3.top`）；無焦點（片商焦點視覺上相同——兩者
    皆不套用 `is-actress-focused`）時維持 row4 在 row3 之後
    （`row4.top > row3.top`）。1440／390 兩個寬度都要驗證（純 CSS `order`，
    不分寬度）。同時驗證 row4 移動後 age/director/series 三個圖表 canvas
    仍正常渲染（非空白）。

    round 2 review 追加：`.insights-container` 全部可見直接子元素（不只
    row3/row4）的完整渲染順序都要符合預期——擋住「某個直接子元素沒有明確
    `order` 基準值、飄到最前面」這類回歸（`.section-divider` 實例）。

    契約測試名稱（mutation 區塊指定，不得改名）。
    """
    for width in (DESKTOP, MOBILE):
        names = _load_ready(page, base_url, width=width)
        _skip_if_insufficient(names, 1)

        no_focus_geo = _row_order_geometry(page)
        assert no_focus_geo["row4_top"] > no_focus_geo["row3_top"], (
            f"寬度 {width}px 無焦點時 row4.top 應大於 row3.top，"
            f"實際 row4={no_focus_geo['row4_top']}, row3={no_focus_geo['row3_top']}"
        )
        no_focus_order = _visible_direct_children_order(page)
        assert no_focus_order == NO_FOCUS_VISIBLE_ORDER, (
            f"寬度 {width}px 無焦點時 .insights-container 可見直接子元素渲染順序"
            f"不符預期，實際 {no_focus_order!r}，預期 {NO_FOCUS_VISIBLE_ORDER!r}"
        )

        target = names[0]
        _click_gantt_actress_raw(page, target)
        _wait_settled(page)
        actress_geo = _row_order_geometry(page)
        assert actress_geo["row4_top"] < actress_geo["row3_top"], (
            f"寬度 {width}px 女優焦點時 row4.top 應小於 row3.top，"
            f"實際 row4={actress_geo['row4_top']}, row3={actress_geo['row3_top']}"
        )
        actress_order = _visible_direct_children_order(page)
        assert actress_order == ACTRESS_FOCUS_VISIBLE_ORDER, (
            f"寬度 {width}px 女優焦點時 .insights-container 可見直接子元素渲染"
            f"順序不符預期，實際 {actress_order!r}，"
            f"預期 {ACTRESS_FOCUS_VISIBLE_ORDER!r}"
        )

        canvases_ok = page.evaluate(
            """() => {
                return ['ageChart', 'directorChart', 'seriesChart'].every((id) => {
                    const el = document.getElementById(id);
                    const canvas = el && el.querySelector('canvas');
                    return !!(canvas && canvas.width > 0 && canvas.height > 0);
                });
            }"""
        )
        assert canvases_ok, (
            f"寬度 {width}px：row4 移動後 age/director/series 三個圖表 canvas "
            "應存在且非空白"
        )

        # 清除焦點，下一輪寬度重新載入前歸零。
        _click_gantt_actress_raw(page, target)
        _wait_settled(page)
