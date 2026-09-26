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

const { computePreviewPosition, libraryInsightsState } = await import('../state.js');

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

// ── isPeriodEmpty（TASK-156c-T6）─────────────────────────────────────

test('isPeriodEmpty: scopedCount>0 時回傳 false', () => {
    const state = libraryInsightsState();
    state.snapshot = { logicalTitles: 100 };
    state.snapshotError = null;
    state.focus = { type: 'maker', value: 'SOD' };
    state.scopedCount = 5;
    assert.equal(state.isPeriodEmpty(['maker']), false);
});

test('isPeriodEmpty: snapshotError 為真時回傳 false', () => {
    const state = libraryInsightsState();
    state.snapshot = { logicalTitles: 100 };
    state.snapshotError = 'error';
    state.focus = { type: 'maker', value: 'SOD' };
    state.scopedCount = 0;
    assert.equal(state.isPeriodEmpty(['maker']), false);
});

test('isPeriodEmpty: snapshot.logicalTitles===0（空片庫）時回傳 false', () => {
    const state = libraryInsightsState();
    state.snapshot = { logicalTitles: 0 };
    state.snapshotError = null;
    state.focus = { type: 'maker', value: 'SOD' };
    state.scopedCount = 0;
    assert.equal(state.isPeriodEmpty(['maker']), false);
});

test('isPeriodEmpty: 條件滿足時回傳 true', () => {
    const state = libraryInsightsState();
    state.snapshot = { logicalTitles: 100 };
    state.snapshotError = null;
    state.focus = { type: 'maker', value: 'SOD' };
    state.scopedCount = 0;
    assert.equal(state.isPeriodEmpty(['maker']), true);
});

