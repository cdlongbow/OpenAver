// TASK-156b-T5: computePreviewPosition 契約（浮層定位不變式）。
// 純函式；錨點貼近四緣各自一條。state.js 會連帶載入 charts.js，故先掛最小 window stub。

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;
globalThis.window.matchMedia = () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
});
globalThis.window.addEventListener = () => {};
globalThis.window.removeEventListener = () => {};
globalThis.document = globalThis.document || {
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return null; },
    getElementById() { return null; },
    createElement() {
        return {
            style: {},
            appendChild() {},
        };
    },
    body: {
        appendChild() {},
        classList: { add() {}, remove() {}, contains() { return false; } },
    },
};

const { computePreviewPosition, libraryInsightsState, shouldPlayPodiumEntrance, computeCostarVisible } = await import('../state.js');
const { setRecords } = await import('../aggregate.js');
const { refreshMakerColorSlots } = await import('../charts.js');

// 測試用手組 sel（三條件，預設全空）
function selOf(over) {
    return { period: { type: 'all' }, actress: null, maker: null, ...over };
}

function rec(opts) {
    return {
        year: opts.year === undefined ? 2020 : opts.year,
        month: opts.month === undefined ? null : opts.month,
        actresses: opts.actresses === undefined ? ['Alice'] : opts.actresses,
        maker: opts.maker === undefined ? 'SOD' : opts.maker,
        tags: opts.tags === undefined ? [] : opts.tags,
        date: opts.date === undefined ? null : opts.date,
        duration: opts.duration === undefined ? null : opts.duration,
    };
}

const POPUP = { width: 160, height: 224 };
const VIEWPORT = { width: 1440, height: 900 };
const GAP = 8;

function assertInside(pos, viewport, popup) {
    assert.ok(pos.left >= 0, 'left >= 0');
    assert.ok(pos.top >= 0, 'top >= 0');
    assert.ok(pos.left + popup.width <= viewport.width, 'right edge inside');
    assert.ok(pos.top + popup.height <= viewport.height, 'bottom edge inside');
}

test('computePreviewPosition: 錨點正常（右側空間足夠）時貼在錨點右側', () => {
    const anchor = { top: 100, left: 200, width: 32, height: 32 };
    const pos = computePreviewPosition(anchor, VIEWPORT, POPUP);
    assert.equal(pos.left, anchor.left + anchor.width + GAP);
    assert.equal(pos.top, anchor.top);
    assertInside(pos, VIEWPORT, POPUP);
});

test('computePreviewPosition: 錨點貼近視窗右緣時，改貼左側且仍完全落在視窗內', () => {
    const anchor = { top: 100, left: 1400, width: 32, height: 32 };
    const pos = computePreviewPosition(anchor, VIEWPORT, POPUP);
    assert.ok(pos.left < anchor.left, 'flips to left of anchor');
    assertInside(pos, VIEWPORT, POPUP);
});

test('computePreviewPosition: 錨點貼近視窗左緣時，left 不得為負', () => {
    const anchor = { top: 100, left: 4, width: 32, height: 32 };
    // 右側也放不下（窄視窗模擬）
    const narrow = { width: 180, height: 900 };
    const pos = computePreviewPosition(anchor, narrow, POPUP);
    assert.ok(pos.left >= 0);
    assertInside(pos, narrow, POPUP);
});

test('computePreviewPosition: 錨點貼近視窗下緣時，浮層仍完全落在視窗內', () => {
    const anchor = { top: 850, left: 200, width: 32, height: 32 };
    const pos = computePreviewPosition(anchor, VIEWPORT, POPUP);
    assert.ok(pos.top + POPUP.height <= VIEWPORT.height);
    assert.ok(pos.top >= 0);
    assertInside(pos, VIEWPORT, POPUP);
});

test('computePreviewPosition: 錨點貼近視窗上緣時，top 不得為負', () => {
    const anchor = { top: 2, left: 200, width: 32, height: 32 };
    const pos = computePreviewPosition(anchor, VIEWPORT, POPUP);
    assert.equal(pos.top, 2);
    assert.ok(pos.top >= 0);
    assertInside(pos, VIEWPORT, POPUP);
});

test('actressHasPhoto: 收藏存在但 hasPhoto=false（來源沒圖／下載失敗）→ 回 false', () => {
    // Finding 1：收藏落地不代表本機有照片檔，見 web/routers/insights.py
    // favorites_by_primary 的 hasPhoto 計算（get_local_photo_path）。
    const state = libraryInsightsState();
    state.snapshot = {
        actressFavorites: {
            '無圖女優': { photoName: '無圖女優', hasPhoto: false, auto_focal: '', crop_mode: 'auto' },
        },
    };
    assert.equal(state.actressHasPhoto('無圖女優'), false);
});

test('actressHasPhoto: hasPhoto=true → 回 true', () => {
    const state = libraryInsightsState();
    state.snapshot = {
        actressFavorites: {
            '有圖女優': { photoName: '有圖女優', hasPhoto: true, auto_focal: '', crop_mode: 'auto' },
        },
    };
    assert.equal(state.actressHasPhoto('有圖女優'), true);
});

test('openPreview: hasPhoto=false 時不開預覽（spec §3.4.1「不出現預覽」）', () => {
    const state = libraryInsightsState();
    state.snapshot = {
        actressFavorites: {
            '無圖女優': { photoName: '無圖女優', hasPhoto: false, auto_focal: '', crop_mode: 'auto' },
        },
    };
    state.openPreview('無圖女優', null);
    assert.equal(state.previewActress, null);
});

test('openPreview: hasPhoto=true 時正常開預覽', () => {
    const state = libraryInsightsState();
    state.snapshot = {
        actressFavorites: {
            '有圖女優': { photoName: '有圖女優', hasPhoto: true, auto_focal: '', crop_mode: 'auto' },
        },
    };
    state.openPreview('有圖女優', null);
    assert.equal(state.previewActress, '有圖女優');
});

test('scheduleOpenPreview: touch 事件不排程預覽，mouse／pen／缺省照常排程', () => {
    const state = libraryInsightsState();
    state.snapshot = {
        actressFavorites: {
            '有圖女優': { photoName: '有圖女優', hasPhoto: true, auto_focal: '', crop_mode: 'auto' },
        },
    };
    const originalSetTimeout = globalThis.setTimeout;
    let scheduled = 0;
    globalThis.setTimeout = () => { scheduled += 1; return scheduled; };
    try {
        const counts = [];
        for (const pointerType of ['touch', 'mouse', 'pen', '']) {
            scheduled = 0;
            state.scheduleOpenPreview('有圖女優', null, { pointerType });
            counts.push(scheduled);
            state.cancelOpenPreview();
        }
        scheduled = 0;
        state.scheduleOpenPreview('有圖女優', null);
        counts.push(scheduled);
        assert.deepEqual(counts, [0, 1, 1, 1, 1]);
    } finally {
        globalThis.setTimeout = originalSetTimeout;
        state.cancelOpenPreview();
    }
});

test('flyAndFocusActress: 進入先收掉已開的預覽（hover 後直接點選人不殘留）', () => {
    const state = libraryInsightsState();
    state.previewActress = '某人';
    state.flyAndFocusActress('她', null);
    assert.equal(state.previewActress, null);
    assert.equal(state.sel.actress, '她');
});

test('_onPageShow: bfcache 還原時快照仍未載入完成（離頁前 fetch 被丟棄）→ 重新 fetch 並填入資料', async () => {
    // Finding 2：真實流程是 sidebar 點擊觸發 page-lifecycle.js 的 leavePage() →
    // 同步呼叫這裡註冊的 cleanup（_pageAlive=false），發生在快照 fetch 尚未回應時；
    // 之後瀏覽器把這頁存進 bfcache，使用者按上一頁回來只會收到 pageshow(persisted)，
    // 不會重跑 init()——若這裡不重新 fetch，畫面永遠停在空的。
    let cleanupFn = null;
    globalThis.window.__registerPage = (handlers) => {
        cleanupFn = handlers.cleanup;
    };

    let fetchCalls = 0;
    let resolveFirst;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = () => {
        fetchCalls += 1;
        if (fetchCalls === 1) {
            return new Promise((resolve) => {
                resolveFirst = resolve;
            });
        }
        return Promise.resolve({
            ok: true,
            json: async () => ({
                records: [],
                logicalTitles: 5,
                physicalRows: 5,
                years: [],
                actressFavorites: {},
            }),
        });
    };

    const state = libraryInsightsState();
    state.$watch = () => {};
    const initPromise = state.init(); // 發起 fetch #1（掛著不回）

    assert.equal(typeof cleanupFn, 'function', 'init() 應註冊 __registerPage cleanup');
    cleanupFn(); // 模擬使用者在快照載完前離頁

    // 離頁前的 fetch #1 這時才回來（fetch 不會因為 cleanup 被取消）
    resolveFirst({
        ok: true,
        json: async () => ({
            records: [{ maker: 'stale' }],
            logicalTitles: 999,
            physicalRows: 999,
            years: [],
            actressFavorites: {},
        }),
    });
    await initPromise;

    assert.equal(state.snapshot, null, '離頁後才回來的回應不該寫入 snapshot');
    assert.equal(state.snapshotError, null);

    // bfcache 還原：pageshow(persisted) 觸發，此時快照仍是 null 且非 snapshotError
    await state._onPageShow({ persisted: true });

    assert.equal(fetchCalls, 2, '應重新發起一次 fetch，不是停在空畫面等不到的舊回應');
    assert.ok(state.snapshot, 'bfcache 還原後應該有 snapshot 資料');
    assert.equal(state.snapshot.logicalTitles, 5);

    globalThis.fetch = originalFetch;
    delete globalThis.window.__registerPage;
});

test('totalCountLabel: 用 logicalTitles（全庫片數）而非 scopedCount（目前範圍片數）', () => {
    // Finding 3：spec §3.1 片數格下方小字固定顯示「全庫 N 部」，不隨期間／焦點縮。
    const state = libraryInsightsState();
    state.snapshot = { logicalTitles: 2103 };
    state.scopedCount = 12; // 目前範圍（期間 ∩ 焦點）片數，不應影響這個小字
    globalThis.window.t = (key, params) => {
        assert.equal(key, 'insights.total_count');
        return '全庫 ' + params.n + ' 部';
    };
    assert.equal(state.totalCountLabel(), '全庫 2,103 部');
    globalThis.window.t = (key) => key;
});

test('totalCountLabel: snapshot 未載入時回 0（不拋錯）', () => {
    const state = libraryInsightsState();
    state.snapshot = null;
    globalThis.window.t = (key, params) => '全庫 ' + params.n + ' 部';
    assert.equal(state.totalCountLabel(), '全庫 0 部');
    globalThis.window.t = (key) => key;
});

test('previewPositionStyle: viewport 以 clientWidth 為準（不含捲軸）', () => {
    // 模擬 390 視窗、捲軸佔 15px：innerWidth=390、clientWidth=375（CDP #19 實況）
    globalThis.window.innerWidth = 390;
    globalThis.window.innerHeight = 844;
    globalThis.document.documentElement = {
        clientWidth: 375,
        clientHeight: 844,
    };
    const state = libraryInsightsState();
    // 錨點靠右：若誤用 innerWidth=390，會貼右側 left=225、right=385 > clientWidth=375
    state.previewAnchorRect = { top: 600, left: 193, width: 32, height: 32 };
    const style = state.previewPositionStyle();
    const left = parseFloat(style.left);
    assert.ok(Number.isFinite(left), 'left is a number');
    assert.ok(left + POPUP.width <= 375, `right edge within clientWidth; left=${left}`);
    // 證明不是誤用 innerWidth：若用 390 夾限，此錨點會得到 left=225
    assert.notEqual(left, 225);
});

// ── cardEmptyKey（TASK-156c-T6／161a-T5a：舊版型別白名單寫法已刪）──────────

test('cardEmptyKey: 該卡範圍內有片時回傳 no_data（不是 period_empty）', () => {
    setRecords([rec({ maker: 'SOD' })]);
    try {
        const state = libraryInsightsState();
        state.snapshot = { logicalTitles: 100 };
        state.snapshotError = null;
        state.sel = selOf({ maker: 'SOD' });
        assert.equal(state.cardEmptyKey('actress'), 'insights.no_data');
    } finally {
        setRecords([]);
    }
});

test('cardEmptyKey: snapshotError 為真時回傳 no_data', () => {
    setRecords([]);
    const state = libraryInsightsState();
    state.snapshot = { logicalTitles: 100 };
    state.snapshotError = 'error';
    state.sel = selOf({ maker: 'SOD' });
    assert.equal(state.cardEmptyKey('actress'), 'insights.no_data');
});

test('cardEmptyKey: snapshot.logicalTitles===0（空片庫）時回傳 no_data', () => {
    setRecords([]);
    const state = libraryInsightsState();
    state.snapshot = { logicalTitles: 0 };
    state.snapshotError = null;
    state.sel = selOf({ maker: 'SOD' });
    assert.equal(state.cardEmptyKey('actress'), 'insights.no_data');
});

test('cardEmptyKey: 條件滿足時回傳 period_empty', () => {
    setRecords([rec({ maker: 'Moodyz' })]);
    try {
        const state = libraryInsightsState();
        state.snapshot = { logicalTitles: 100 };
        state.snapshotError = null;
        state.sel = selOf({ maker: 'SOD' });
        assert.equal(state.cardEmptyKey('actress'), 'insights.period_empty');
    } finally {
        setRecords([]);
    }
});

// ── podiumRows / restRows（TASK-156d-T2）─────────────────────────────

test('podiumRows/restRows: top20Rows 只有 2 筆（女優總數 <3）→ podiumRows 回傳 2 筆，restRows 為空', () => {
    const state = libraryInsightsState();
    state.top20Rows = [
        { rank: 1, name: 'A', count: 10 },
        { rank: 2, name: 'B', count: 8 },
    ];
    assert.deepEqual(state.podiumRows.map((r) => r.name), ['A', 'B']);
    assert.deepEqual(state.restRows, []);
});

test('podiumRows/restRows: top20Rows 為空（0 位女優）→ 兩者皆為空陣列', () => {
    const state = libraryInsightsState();
    state.top20Rows = [];
    assert.deepEqual(state.podiumRows, []);
    assert.deepEqual(state.restRows, []);
});

test('podiumRows/restRows: 焦點女優 rank>25 附加列（真實名次 37）→ 落在 restRows，podiumRows 不受影響', () => {
    const state = libraryInsightsState();
    state.top20Rows = [...rankingRows(), { rank: 37, name: '焦點女優', count: 1 }];
    assert.equal(state.podiumRows.length, 3);
    assert.ok(!state.podiumRows.some((r) => r.name === '焦點女優'));
    const focusRow = state.restRows.find((r) => r.name === '焦點女優');
    assert.ok(focusRow, '焦點女優應出現在 restRows');
    assert.equal(focusRow.rank, 37, '名次要顯示真實名次，不是 26');
});

test('podiumRows/restRows: 焦點女優 rank<=3（本來就在頒獎台上）→ podiumRows 含她、restRows 不含她', () => {
    const state = libraryInsightsState();
    state.top20Rows = [
        { rank: 1, name: 'A', count: 10 },
        { rank: 2, name: '焦點女優', count: 9 },
        { rank: 3, name: 'C', count: 8 },
    ];
    assert.ok(state.podiumRows.some((r) => r.name === '焦點女優'));
    assert.ok(!state.restRows.some((r) => r.name === '焦點女優'));
});

test('podiumRows/restRows: top20Rows 剛好 25 筆滿額且焦點女優 rank===25 → 落在 restRows', () => {
    const state = libraryInsightsState();
    const rows = [];
    for (let i = 1; i <= 25; i += 1) {
        rows.push({ rank: i, name: 'name' + i, count: 26 - i });
    }
    state.top20Rows = rows;
    assert.equal(state.podiumRows.length, 3);
    assert.equal(state.restRows.length, 22);
    const row25 = state.restRows.find((r) => r.rank === 25);
    assert.ok(row25, 'rank===25 應落在 restRows');
});

// ── isActressFocused（TASK-156d-T3）───────────────────────────────────

test('isActressFocused: true only when focus.type is actress', () => {
    const state = libraryInsightsState();
    state.sel = selOf({ actress: '明里つむぎ' });
    assert.equal(state.isActressFocused, true);
});

test('isActressFocused: focus.type === "maker" 時回傳 false', () => {
    const state = libraryInsightsState();
    state.sel = selOf({ maker: 'SOD' });
    assert.equal(state.isActressFocused, false);
});

test('isActressFocused: 無焦點（focus === null）時回傳 false', () => {
    const state = libraryInsightsState();
    state.sel = selOf();
    assert.equal(state.isActressFocused, false);
});

// ── _maybePlayPinPulse（TASK-156d-T4／review P2，定稿輪數 2）───────────
// review 發現：年表切到「年齡」軸時，ganttView('age') 會用 ganttAgeEligibility
// 濾掉沒生日的女優；她若無生日，this.ganttRows[0] 仍是她（資料層置頂沒問題），
// 但 DOM 實際渲染的年表列裡完全沒有她，原本的邏輯會盲抓 DOM 第一列（那是別人）
// 播放強調亮起。修法：`ganttAxis` 是 `.gantt-card` 巢狀 x-data 的子層狀態，父層
// 元件讀不到（`this.ganttAxis` 恆 undefined），改成直接讀 DOM 實際渲染出來的
// 第一列名字（`.gantt-name` 文字），核對是否等於這次要置頂的名字。

function makeGanttRowEl(name) {
    return {
        querySelector(sel) {
            if (sel === '.gantt-name') return { textContent: name };
            return null;
        },
    };
}

test('_maybePlayPinPulse: 年齡軸下她的列被濾掉（無生日）→ DOM 第一列渲染的是別人 → 不對年表動手，分布表仍照常播放', () => {
    globalThis.window.OpenAver = globalThis.window.OpenAver || {};
    const pulsed = [];
    globalThis.window.OpenAver.motion = { playPulse: (el) => pulsed.push(el) };
    // 模擬年齡軸把她濾掉：DOM 實際渲染出來的第一列是「別人」，不是她。
    const ganttEl = makeGanttRowEl('別人');
    const soloEl = { tag: 'solo-row-dom-1' };
    const origQuerySelector = globalThis.document.querySelector;
    globalThis.document.querySelector = (sel) => {
        if (sel.indexOf('gantt-row') !== -1) return ganttEl;
        if (sel.indexOf('solo-row') !== -1) return soloEl;
        return null;
    };

    const state = libraryInsightsState();
    state.$nextTick = (fn) => fn();
    state.sel = selOf({ actress: '無生日女優' });
    state.ganttRows = [{ name: '無生日女優', pinned: true }];
    state.soloRows = [{ name: '無生日女優', pinned: true }];

    state._maybePlayPinPulse();

    assert.deepEqual(
        pulsed,
        [soloEl],
        '年表渲染第一列不是她時只有分布表播放，不得對年表 DOM 第一列（別人）動手',
    );

    globalThis.document.querySelector = origQuerySelector;
});

test('_maybePlayPinPulse: DOM 渲染第一列確實是她（年份軸／年齡軸但她有生日皆同理）→ 年表與分布表都照常播放', () => {
    globalThis.window.OpenAver = globalThis.window.OpenAver || {};
    const pulsed = [];
    globalThis.window.OpenAver.motion = { playPulse: (el) => pulsed.push(el) };
    const ganttEl = makeGanttRowEl('有生日女優');
    const soloEl = { tag: 'solo-row-dom-2' };
    const origQuerySelector = globalThis.document.querySelector;
    globalThis.document.querySelector = (sel) => {
        if (sel.indexOf('gantt-row') !== -1) return ganttEl;
        if (sel.indexOf('solo-row') !== -1) return soloEl;
        return null;
    };

    const state = libraryInsightsState();
    state.$nextTick = (fn) => fn();
    state.sel = selOf({ actress: '有生日女優' });
    state.ganttRows = [{ name: '有生日女優', pinned: true }];
    state.soloRows = [{ name: '有生日女優', pinned: true }];

    state._maybePlayPinPulse();

    assert.deepEqual(pulsed, [ganttEl, soloEl], '渲染第一列吻合時，年表與分布表都應播放一次');

    globalThis.document.querySelector = origQuerySelector;
});


// ── ganttGridStyle（TASK-156d-T5：年表撐滿卡寬）─────────────────────────

test('ganttGridStyle: 年份軸用 minmax(floor,1fr) 分配剩餘寬度而非固定寬度', () => {
    setRecords([
        rec({ year: 2020 }),
        rec({ year: 2021 }),
        rec({ year: 2022 }),
    ]);
    const state = libraryInsightsState();
    const style = state.ganttGridStyle('year');
    assert.match(
        style,
        /minmax\(var\(--gantt-cell-min-w\), 1fr\)/,
        `should use minmax(var(--gantt-cell-min-w), 1fr) to stretch columns; got: ${style}`,
    );
    assert.ok(
        style.indexOf('var(--gantt-cell-w))') === -1,
        `should not fall back to fixed var(--gantt-cell-w) column width; got: ${style}`,
    );
});


// ── shouldPlayPodiumEntrance（TASK-156d-T6：頒獎台一次性進場動效）──────────

test('shouldPlayPodiumEntrance: 尚未播放且頒獎台有資料 → 播放', () => {
    assert.equal(shouldPlayPodiumEntrance(false, 3), true);
});

test('shouldPlayPodiumEntrance: 已播放過 → 不重播', () => {
    assert.equal(shouldPlayPodiumEntrance(true, 3), false);
});

test('shouldPlayPodiumEntrance: podiumRows 為空（尚未算出頒獎台名單）時不播放', () => {
    assert.equal(shouldPlayPodiumEntrance(false, 0), false);
});


// ── computeCostarVisible（TASK-156d-T9／CD-156d-10a：沒有共演不顯示空卡）──

test('computeCostarVisible: 無焦點 → false', () => {
    assert.equal(computeCostarVisible(false, 5), false);
});

test('computeCostarVisible: 女優焦點且有共演 → true', () => {
    assert.equal(computeCostarVisible(true, 3), true);
});

test('computeCostarVisible: 女優焦點但零共演 → false', () => {
    assert.equal(computeCostarVisible(true, 0), false);
});

test('costarVisible getter: 反映 isActressFocused 與 costarRows.length', () => {
    const state = libraryInsightsState();
    state.sel = selOf({ actress: '明里つむぎ' });
    state.costarRows = [];
    assert.equal(state.costarVisible, false, '零共演時應為 false');

    state.costarRows = [{ name: 'B', count: 1, self: '明里つむぎ' }];
    assert.equal(state.costarVisible, true, '有共演時應為 true');

    state.sel = selOf({ maker: 'SOD' });
    assert.equal(state.costarVisible, false, '片商焦點時應為 false');
});

// ── TASK-161a-T5a：單一 sel 狀態 ─────────────────────────────────────

test('_handleActressFocusChange: 只在女優格換人時捲回頂端（換期間／換片商／清除都不捲）', () => {
    const scrolls = [];
    const origScrollTo = globalThis.window.scrollTo;
    const origOpenAver = globalThis.window.OpenAver;
    globalThis.window.scrollTo = (opt) => scrolls.push(opt);
    globalThis.window.OpenAver = { prefersReducedMotion: true };
    try {
        const run = (oldSel, newSel) => {
            const state = libraryInsightsState();
            state._syncCostarVisibility = () => {};
            state.sel = newSel;
            scrolls.length = 0;
            state._handleActressFocusChange(oldSel, 0);
            return scrolls.length;
        };
        // 沒女優 → 有女優、換成另一位：捲
        assert.equal(run(selOf(), selOf({ actress: 'A' })), 1);
        assert.equal(run(selOf({ actress: 'A' }), selOf({ actress: 'B' })), 1);
        // 同一位女優只換期間、只加片商、清掉女優：不捲
        assert.equal(
            run(selOf({ actress: 'A' }), selOf({ actress: 'A', period: { type: 'year', year: 2020 } })),
            0,
        );
        assert.equal(run(selOf({ actress: 'A' }), selOf({ actress: 'A', maker: 'S1' })), 0);
        assert.equal(run(selOf({ actress: 'A' }), selOf()), 0);
        // 只選片商、換片商：不捲
        assert.equal(run(selOf({ maker: 'S1' }), selOf({ maker: 'S2' })), 0);
    } finally {
        globalThis.window.scrollTo = origScrollTo;
        globalThis.window.OpenAver = origOpenAver;
    }
});

test('ganttView: 快取鍵認整個 sel，只換片商或只換期間也必須重算', () => {
    setRecords([rec({ year: 2020, actresses: ['Alice'] }), rec({ year: 2021, actresses: ['Alice'] })]);
    try {
        const state = libraryInsightsState();
        state.snapshot = { actressFavorites: {} };
        state.ganttRows = [{ name: 'Alice' }];
        state.sel = selOf({ actress: 'Alice' });
        const first = state.ganttView('year');
        assert.equal(state.ganttView('year'), first, 'sel 沒變時命中快取');
        state.sel = { ...state.sel, maker: 'SOD' };
        const afterMaker = state.ganttView('year');
        assert.notEqual(afterMaker, first, '只換片商必須重算');
        state.sel = { ...state.sel, period: { type: 'year', year: 2020 } };
        const afterPeriod = state.ganttView('year');
        assert.notEqual(afterPeriod, afterMaker, '只換期間必須重算');
    } finally {
        setRecords([]);
    }
});

test('toggleMakerFocus／toggleActressFocus: 疊加不互斥，期間與另一條件保留', () => {
    const state = libraryInsightsState();
    const period = { type: 'range', from: 2019, to: 2023 };
    state.sel = selOf({ period, actress: 'A' });
    state.toggleMakerFocus('S1');
    assert.deepEqual(state.sel, { period, actress: 'A', maker: 'S1' });
    state.toggleActressFocus('A');
    assert.deepEqual(state.sel, { period, actress: null, maker: 'S1' });
    state.toggleActressFocus('B');
    assert.deepEqual(state.sel, { period, actress: 'B', maker: 'S1' });
    state.toggleActressFocus('B');
    state.toggleMakerFocus('S1');
    assert.deepEqual(state.sel, { period, actress: null, maker: null });
});

test('clearActress／clearMaker: 各自只清自己那一條件，期間保留', () => {
    const state = libraryInsightsState();
    const period = { type: 'year', year: 2021 };
    state.sel = selOf({ period, actress: 'A', maker: 'S1' });
    state.clearActress();
    assert.deepEqual(state.sel, { period, actress: null, maker: 'S1' });
    state.sel = selOf({ period, actress: 'A', maker: 'S1' });
    state.clearMaker();
    assert.deepEqual(state.sel, { period, actress: 'A', maker: null });
});

test('costarVisible getter: 加選片商使與她同片 0 筆時為 false，清掉片商後恢復', () => {
    setRecords([
        rec({ actresses: ['A', 'B'], maker: 'X' }),
        rec({ actresses: ['A'], maker: 'Y' }),
    ]);
    try {
        const state = libraryInsightsState();
        state.sel = selOf({ actress: 'A' });
        state.recomputeCostar();
        assert.equal(state.costarRows.length, 1, '只選 A：與 B 同片');
        assert.equal(state.costarVisible, true);
        state.toggleMakerFocus('Y');
        state.recomputeCostar();
        assert.equal(state.costarRows.length, 0, '加選 Y：A 在 Y 沒有同片');
        assert.equal(state.costarVisible, false);
        state.clearMaker();
        state.recomputeCostar();
        assert.equal(state.costarVisible, true, '清掉片商後恢復');
        state.sel = selOf({ maker: 'X' });
        state.recomputeCostar();
        assert.equal(state.costarVisible, false, '只有片商恆 false');
    } finally {
        setRecords([]);
    }
});

test('focusMakerColor／focusInitial: 片商色點不受女優條件影響，頭像字母只取女優', () => {
    setRecords([rec({ actresses: ['Alice'], maker: 'SOD' })]);
    const hadGcs = Object.prototype.hasOwnProperty.call(globalThis, 'getComputedStyle');
    const oldGcs = globalThis.getComputedStyle;
    // node 無 DOM：色票解析要 getComputedStyle，給固定回傳讓「有值／空」可斷言
    globalThis.getComputedStyle = () => ({ color: 'rgb(10, 20, 30)' });
    const oldCreate = document.createElement;
    document.createElement = () => ({
        style: {},
        appendChild() {},
        getContext: () => ({
            fillRect() {},
            getImageData: () => ({ data: [10, 20, 30, 255] }),
        }),
    });
    try {
        refreshMakerColorSlots();
        const state = libraryInsightsState();
        state.sel = selOf({ maker: 'SOD' });
        const solo = state.focusMakerColor();
        assert.ok(solo, '只選片商：色票非空');
        state.sel = selOf({ actress: 'Alice', maker: 'SOD' });
        assert.equal(state.focusMakerColor(), solo, '疊加女優後色點不變');
        assert.equal(state.focusInitial(), 'A', '字母取女優首字');
        state.sel = selOf({ maker: 'SOD' });
        assert.equal(state.focusInitial(), '', '只有片商時不取字母');
        state.sel = selOf({ actress: 'Alice' });
        assert.equal(state.focusMakerColor(), '', '無片商回空');
    } finally {
        document.createElement = oldCreate;
        if (hadGcs) globalThis.getComputedStyle = oldGcs; else delete globalThis.getComputedStyle;
        setRecords([]);
    }
});

test('periodTileLabel: range 顯示 2019–2023、單年顯示年份、all 為空字串', () => {
    const state = libraryInsightsState();
    state.sel = selOf({ period: { type: 'range', from: 2019, to: 2023 } });
    assert.equal(state.periodTileLabel(), '2019–2023');
    state.sel = selOf({ period: { type: 'year', year: 2023 } });
    assert.equal(state.periodTileLabel(), '2023');
    state.sel = selOf();
    assert.equal(state.periodTileLabel(), '');
});

test('isYearInSel: 單年與範圍含兩端、範圍外為 false、all 為 true', () => {
    const state = libraryInsightsState();
    state.sel = selOf();
    assert.equal(state.isYearInSel(2021), true);
    state.sel = selOf({ period: { type: 'year', year: 2021 } });
    assert.equal(state.isYearInSel(2021), true);
    assert.equal(state.isYearInSel(2020), false);
    assert.equal(state.isYearInSel('2021'), true);
    state.sel = selOf({ period: { type: 'range', from: 2019, to: 2023 } });
    assert.equal(state.isYearInSel(2019), true);
    assert.equal(state.isYearInSel(2023), true);
    assert.equal(state.isYearInSel(2018), false);
    assert.equal(state.isYearInSel(2024), false);
    assert.equal(state.isYearInSel('2021'), true);
});

// ── topDisplayCount (TASK-156e-T3) ───────────────────────────────────

test('topDisplayCount: displayMap 有對應 key → 回傳該值', () => {
    const state = libraryInsightsState();
    state.top20DisplayCounts = { Alice: 7 };
    assert.equal(state.topDisplayCount({ name: 'Alice', count: 12 }), 7);
});

test('topDisplayCount: 沒有 key → fallback row.count', () => {
    const state = libraryInsightsState();
    state.top20DisplayCounts = {};
    assert.equal(state.topDisplayCount({ name: 'Alice', count: 12 }), 12);
});

test('topDisplayCount: row 為 null/undefined → 回傳空字串', () => {
    const state = libraryInsightsState();
    state.top20DisplayCounts = { Alice: 7 };
    assert.equal(state.topDisplayCount(null), '');
    assert.equal(state.topDisplayCount(undefined), '');
});

// ── canGoBrowse / goBrowse (TASK-161a-T7) ────────────────────────────

// 安裝 localStorage／location／console.warn 的記錄器，回傳 { calls, warns, restore }
function installBrowseStubs({ stored = null, setItemThrows = false } = {}) {
    const calls = [];
    const warns = [];
    const lsDesc = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
    const locDesc = Object.getOwnPropertyDescriptor(globalThis, 'location');
    const origWarn = console.warn;
    const fake = {
        getItem(k) { calls.push(['getItem', k]); return stored; },
        setItem(k, v) {
            if (setItemThrows) throw new Error('quota');
            calls.push(['setItem', k, v]);
        },
    };
    Object.defineProperty(globalThis, 'localStorage', { value: fake, configurable: true, writable: true });
    Object.defineProperty(globalThis, 'location', {
        value: { assign(url) { calls.push(['assign', url]); } },
        configurable: true,
        writable: true,
    });
    console.warn = (...args) => { warns.push(args); };
    const restore = () => {
        console.warn = origWarn;
        if (lsDesc) Object.defineProperty(globalThis, 'localStorage', lsDesc);
        else delete globalThis.localStorage;
        if (locDesc) Object.defineProperty(globalThis, 'location', locDesc);
        else delete globalThis.location;
    };
    return { calls, warns, restore };
}

test('canGoBrowse: 片數為 0、快照失敗、尚未載入時為 false，有片時為 true', () => {
    const fresh = libraryInsightsState();
    assert.equal(fresh.canGoBrowse, false);

    const state = libraryInsightsState();
    state.snapshotError = null;
    state.scopedCount = 5;
    assert.equal(state.canGoBrowse, true);
    state.scopedCount = 0;
    assert.equal(state.canGoBrowse, false);
    state.snapshotError = true;
    state.scopedCount = 5;
    assert.equal(state.canGoBrowse, false);
});

test('goBrowse: 片數為 0 或快照失敗時不寫入也不導航', () => {
    const stub = installBrowseStubs();
    try {
        const state = libraryInsightsState();
        state.snapshotError = null;
        state.scopedCount = 0;
        state.goBrowse();
        assert.deepEqual(stub.calls, []);
        state.snapshotError = true;
        state.scopedCount = 5;
        state.goBrowse();
        assert.deepEqual(stub.calls, []);
    } finally {
        stub.restore();
    }
});

test('goBrowse: 寫入失敗時不導航', () => {
    const stub = installBrowseStubs({ setItemThrows: true });
    try {
        const state = libraryInsightsState();
        state.snapshotError = null;
        state.scopedCount = 5;
        assert.doesNotThrow(() => state.goBrowse());
        assert.equal(stub.calls.filter((c) => c[0] === 'assign').length, 0);
        assert.equal(stub.warns.length, 1);
    } finally {
        stub.restore();
    }
});

test('goBrowse: 先寫入 showcase_state 再導向 /showcase，保留既有排序與卡型、整組換成目前條件', () => {
    const old = JSON.stringify({
        sort: 'x', cardShape: 'poster', infoVisible: true, search: 'abc',
        pills: [{ dim: 'actress', value: '舊' }],
    });
    const stub = installBrowseStubs({ stored: old });
    try {
        const state = libraryInsightsState();
        state.snapshotError = null;
        state.scopedCount = 12;
        state.sel = { period: { type: 'year', year: 2023 }, actress: 'A', maker: 'M' };
        state.goBrowse();
        const writes = stub.calls.filter((c) => c[0] === 'setItem' || c[0] === 'assign');
        assert.equal(writes.length, 2);
        assert.equal(writes[0][0], 'setItem');
        assert.equal(writes[0][1], 'showcase_state');
        assert.deepEqual(writes[1], ['assign', '/showcase']);
        const saved = JSON.parse(writes[0][2]);
        assert.equal(saved.pills.length, 3);
        const dims = saved.pills.map((p) => p.dim).sort();
        assert.deepEqual(dims, ['actress', 'maker', 'release']);
        const rel = saved.pills.find((p) => p.dim === 'release');
        assert.equal(rel.op, '=');
        assert.equal(rel.value, '2023');
        assert.equal(saved.search, '');
        assert.equal(saved.page, 1);
        assert.equal(saved.showFavoriteActresses, false);
        assert.equal(saved.sort, 'x');
        assert.equal(saved.cardShape, 'poster');
        assert.equal(saved.infoVisible, true);
    } finally {
        stub.restore();
    }

    // 無條件也能跳
    const stub2 = installBrowseStubs({ stored: old });
    try {
        const state = libraryInsightsState();
        state.snapshotError = null;
        state.scopedCount = 2103;
        state.sel = selOf({});
        state.goBrowse();
        const set = stub2.calls.find((c) => c[0] === 'setItem');
        assert.deepEqual(JSON.parse(set[2]).pills, []);
        assert.equal(stub2.calls.filter((c) => c[0] === 'assign').length, 1);
    } finally {
        stub2.restore();
    }
});

// TASK-161b-T3：以可觀察分流驗證 podiumSize 接線。
function rankingRows() {
    return Array.from({ length: 25 }, (_, i) => ({ rank: i + 1, name: 'name' + (i + 1), count: 25 - i }));
}

function observeReorder(podiumSize, oldRank, newRank) {
    const saved = { OpenAver: window.OpenAver, document: globalThis.document, CSS: globalThis.CSS };
    const captures = [];
    const selectors = [];
    const fades = [];
    const elements = new Map();
    const wrap = {
        querySelector(selector) {
            selectors.push(selector);
            if (!elements.has(selector)) elements.set(selector, {
                selector,
                getBoundingClientRect: () => ({ left: 0, top: 0, width: 10, height: 10 }),
                cloneNode: () => ({}),
                querySelectorAll: (childSelector) => [{ selector, childSelector }],
            });
            return elements.get(selector);
        },
        querySelectorAll(selector) { selectors.push(selector); return []; },
    };
    try {
        globalThis.CSS = { escape: (value) => value };
        globalThis.document = { querySelector: () => ({ getBoundingClientRect: () => ({}) }) };
        window.OpenAver = { prefersReducedMotion: true, motion: {
            flipCapture: (els) => { captures.push(els); return {}; },
            flipFrom() {}, playEnter() {}, clearProps() {},
            playFadeTo: (els) => { fades.push(els); }, DURATION: { fast: 0 },
        } };
        const state = libraryInsightsState();
        state.podiumSize = podiumSize;
        state.top20Rows = [{ name: 'A', rank: oldRank, count: 1 }];
        state._computeTop20Rows = () => [{ name: 'A', rank: newRank, count: 1 }];
        state.$nextTick = (fn) => fn();
        state._settleTop20NonFlipAnims = () => {};
        state._playTop20Reorder(wrap);
        return { captures, selectors, fades };
    } finally {
        window.OpenAver = saved.OpenAver;
        globalThis.document = saved.document;
        globalThis.CSS = saved.CSS;
    }
}

test('podiumRows/restRows: podiumSize=5 時頒獎台 5 人、名單從第 6 名起，榜外附加列落在名單', () => {
    const state = libraryInsightsState();
    assert.equal(state.podiumSize, 3);
    state.podiumSize = 5;
    state.top20Rows = [...rankingRows(), { rank: 37, name: 'focus', count: 1 }];
    assert.deepEqual(state.podiumRows.map((r) => r.rank), Array.from({ length: 5 }, (_, i) => i + 1));
    assert.equal(state.restRows[0].rank, 6);
    assert.equal(state.restRows.length, 21);
    assert.equal(state.restRows.at(-1).rank, 37);
});

test('podiumRows/restRows: podiumSize=3 時頒獎台 3 人、名單從第 4 名起，榜外附加列落在名單', () => {
    const state = libraryInsightsState();
    assert.equal(state.podiumSize, 3);
    state.podiumSize = 3;
    state.top20Rows = [...rankingRows(), { rank: 37, name: 'focus', count: 1 }];
    assert.deepEqual(state.podiumRows.map((r) => r.rank), Array.from({ length: 3 }, (_, i) => i + 1));
    assert.equal(state.restRows[0].rank, 4);
    assert.equal(state.restRows.length, 23);
    assert.equal(state.restRows.at(-1).rank, 37);
});

test('_playTop20Reorder: podiumSize 傳給分類（5 人版 4→5 名走頒獎台換位、3 人版同輸入走名單換位）', () => {
    const wide = observeReorder(5, 4, 5);
    const narrow = observeReorder(3, 4, 5);
    assert.equal(wide.captures[1][0]?.selector, '[data-flip-id="podium-A"]');
    assert.equal(wide.captures[0].length, 0);
    assert.equal(narrow.captures[0][0]?.selector, '[data-flip-id="rest-A"]');
    assert.equal(narrow.captures[1].length, 0);
});

test('_playTop20Reorder: podiumSize=5 時名單第 6 名升到第 4 名，淡入走頒獎台名字區', () => {
    const wide = observeReorder(5, 6, 4);
    const narrow = observeReorder(3, 6, 4);
    assert.equal(wide.fades[0]?.[0].selector, '[data-flip-id="podium-A"]');
    assert.equal(wide.fades[0]?.[0].childSelector, '.podium-name, .podium-count');
    assert.equal(narrow.fades.length, 0);
    assert.equal(narrow.captures[0][0]?.selector, '[data-flip-id="rest-A"]');
});

test('_playPodiumEntrance: podiumSize=5 時台座依 4／2／1／3／5 順序進場，3 人版為 2／1／3', () => {
    const saved = window.OpenAver;
    try {
        const groups = [];
        window.OpenAver = { motion: { playRise: (value) => groups.push(value) } };
        const state = libraryInsightsState();
        state.$refs = { top20Row3El: { querySelector: (selector) => selector, querySelectorAll: () => [] } };
        state.top20Rows = rankingRows();
        state.podiumSize = 5;
        state._playPodiumEntrance();
        state.podiumSize = 3;
        state._playPodiumEntrance();
        assert.deepEqual(groups.map((g) => g.map((v) => v.stand)), [
            [4, 2, 1, 3, 5].map((r) => '.podium-stand--' + r),
            [2, 1, 3].map((r) => '.podium-stand--' + r),
        ]);
    } finally { window.OpenAver = saved; }
});

test('top20Title／top20RestTitle: 新 key 帶 {n}／{from,to} 參數，起訖隨 podiumSize', () => {
    const saved = window.t;
    try {
        const calls = [];
        window.t = (key, params) => { calls.push([key, params]); return key; };
        const state = libraryInsightsState();
        assert.equal(state.top20Title, 'insights.row.actress_top');
        assert.deepEqual(calls[0], ['insights.row.actress_top', { n: 25 }]);
        state.podiumSize = 5;
        assert.equal(state.top20RestTitle, 'insights.row.actress_top_rest');
        assert.deepEqual(calls.at(-1), ['insights.row.actress_top_rest', { from: 6, to: 25 }]);
        state.podiumSize = 3;
        assert.equal(state.top20RestTitle, 'insights.row.actress_top_rest');
        assert.deepEqual(calls.at(-1), ['insights.row.actress_top_rest', { from: 4, to: 25 }]);
    } finally { window.t = saved; }
});

test('podiumSize: 初值依視窗寬、resize 跨門檻才寫入、cleanup 拆監聽', async () => {
    const keys = ['innerWidth', 'addEventListener', 'removeEventListener', 'requestAnimationFrame', 'cancelAnimationFrame', '__registerPage'];
    const saved = Object.fromEntries(keys.map((key) => [key, Object.getOwnPropertyDescriptor(window, key)]));
    try {
        delete window.innerWidth;
        assert.equal(libraryInsightsState().podiumSize, 3);
        for (const [width, expected] of [[390, 3], [559, 3], [560, 5], [1024, 5], [1025, 3], [1159, 3], [1160, 5], [1440, 5]]) {
            window.innerWidth = width;
            assert.equal(libraryInsightsState().podiumSize, expected);
        }
        let handler, cleanup, frame;
        const removed = [];
        window.addEventListener = (type, fn, options) => {
            if (type === 'resize') { handler = fn; assert.equal(options.passive, true); }
        };
        window.removeEventListener = (type, fn) => removed.push([type, fn]);
        window.__registerPage = (entry) => { cleanup = entry.cleanup; };
        window.requestAnimationFrame = (fn) => { assert.equal(frame, undefined); frame = fn; return 1; };
        const flushFrame = () => {
            const fn = frame;
            frame = undefined;
            fn();
        };
        window.cancelAnimationFrame = () => { frame = null; };
        const state = libraryInsightsState();
        const rows = rankingRows();
        state.top20Rows = rows;
        state.$watch = () => {};
        state._loadSnapshot = async () => {};
        state._playTop20Reorder = () => assert.fail('resize 不應播換位');
        state.recomputeTop20 = () => assert.fail('resize 不應重算榜');
        let value = state.podiumSize, writes = 0;
        Object.defineProperty(state, 'podiumSize', { get: () => value, set: (v) => { value = v; writes++; } });
        await state.init();
        handler(); flushFrame();
        assert.equal(writes, 0);
        window.innerWidth = 1159; handler(); flushFrame();
        assert.equal(value, 3); assert.equal(writes, 1);
        handler(); flushFrame(); assert.equal(writes, 1);
        window.innerWidth = 1160; handler(); flushFrame();
        assert.equal(value, 5); assert.equal(writes, 2);
        window.innerWidth = 559; handler(); flushFrame();
        assert.equal(value, 3);
        window.innerWidth = 560; handler(); flushFrame();
        assert.equal(value, 5);
        assert.equal(state.top20Rows, rows);
        assert.equal(state.podiumRows.length, 5);
        window.requestAnimationFrame = (fn) => { assert.equal(frame, undefined); frame = fn; return 2; };
        handler(); handler();
        assert.equal(typeof frame, 'function');
        cleanup();
        assert.ok(removed.some(([type, fn]) => type === 'resize' && fn === handler));
        assert.equal(frame, null);
    } finally {
        for (const key of keys) {
            if (saved[key]) Object.defineProperty(window, key, saved[key]);
            else delete window[key];
        }
    }
});


test('cleanup 後經 pageshow 還原，resize 監聽重新生效且 podiumSize 依當下寬度重算；重複還原不會重複掛監聽', async () => {
    const keys = ['innerWidth', 'addEventListener', 'removeEventListener', 'requestAnimationFrame', 'cancelAnimationFrame', '__registerPage'];
    const saved = Object.fromEntries(keys.map((key) => [key, Object.getOwnPropertyDescriptor(window, key)]));
    const listeners = new Set();
    let cleanup, frame, registrations = 0, bindings = 0;
    let state;
    try {
        window.innerWidth = 1440;
        window.addEventListener = (type, fn) => {
            if (type === 'resize') { listeners.add(fn); bindings++; }
        };
        window.removeEventListener = (type, fn) => { if (type === 'resize') listeners.delete(fn); };
        window.requestAnimationFrame = (fn) => { assert.equal(frame, undefined); frame = fn; return 1; };
        window.cancelAnimationFrame = () => { frame = undefined; };
        window.__registerPage = (entry) => { cleanup = entry.cleanup; registrations++; };
        state = libraryInsightsState();
        state.$watch = () => {};
        state._loadSnapshot = async () => {};
        state._playTop20Reorder = () => assert.fail('還原不應播換位');
        state.recomputeTop20 = () => assert.fail('還原不應重算榜');
        await state.init();
        const leave = () => {
            const fn = cleanup;
            cleanup = undefined; // 真實 lifecycle cleanup 後清空 hooks。
            fn();
        };
        assert.equal(listeners.size, 1);
        leave();
        assert.equal(listeners.size, 0);
        window.innerWidth = 390;
        await state._onPageShow({ persisted: false });
        assert.equal(listeners.size, 0);
        await state._onPageShow({ persisted: true });
        assert.equal(listeners.size, 1, 'pageshow 必須重掛 resize');
        assert.equal(state.podiumSize, 3);
        assert.equal(registrations, 2, '還原必須重新註冊下次離頁的 cleanup');
        let value = state.podiumSize, writes = 0;
        Object.defineProperty(state, 'podiumSize', { get: () => value, set: (v) => { value = v; writes++; } });
        await state._onPageShow({ persisted: true });
        assert.equal(bindings, 2, '重複還原不得重複掛 resize');
        assert.equal(writes, 0, '相同寬度不得重寫人數');
        window.innerWidth = 1160;
        for (const fn of listeners) fn();
        const pending = frame;
        frame = undefined;
        pending();
        assert.equal(state.podiumSize, 5);
        assert.equal(writes, 1);
        leave();
        assert.equal(listeners.size, 0, '再次離頁仍須解除監聽');
        state.snapshotError = true;
        window.innerWidth = 559;
        await state._onPageShow({ persisted: true });
        assert.equal(listeners.size, 1, '快照錯誤不應阻止 resize 還原');
        assert.equal(state.podiumSize, 3);
        leave();
    } finally {
        if (cleanup) cleanup();
        for (const key of keys) {
            if (saved[key]) Object.defineProperty(window, key, saved[key]);
            else delete window[key];
        }
    }
});
