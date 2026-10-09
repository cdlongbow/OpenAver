// TASK-119-T5: UI 接線（選單四條、tooltip、A 鍵、_posterModeActive()）。
// 覆蓋反向鎖（桌面 + poster 仍四條／四段）、A 鍵三／四段循環、窄螢幕不得洗掉
// cardShape（技術要點 ①）、女優牆早退、選單源碼契約。
//
// harness 照抄 select-presentation.test.mjs（importmap hook、readFileSync 讀源碼、
// Object.assign({}, stateVideos(), …)），並把 stateLightbox() 併進元件以測 A 鍵。
//
// TASK-133b-T2：選單／序列／A 鍵三組各拆旗標開／關兩態；新鈕 x-show／@click 源碼鎖。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import { readFileSync } from 'node:fs';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
// 本檔：web/static/js/pages/showcase/__tests__/ → 上三層 = web/static/js/
const STATIC_JS_ROOT = pathToFileURL(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../') + '/',
).href;

const loaderCode = `
const IMPORTMAP = ${JSON.stringify(IMPORTMAP)};
const STATIC_JS_ROOT = ${JSON.stringify(STATIC_JS_ROOT)};
export async function resolve(specifier, context, nextResolve) {
    for (const [prefix, rel] of Object.entries(IMPORTMAP)) {
        if (specifier.startsWith(prefix)) {
            return nextResolve(STATIC_JS_ROOT + rel + specifier.slice(prefix.length), context);
        }
    }
    if (specifier.startsWith('@/')) {
        return nextResolve(STATIC_JS_ROOT + specifier.slice(2), context);
    }
    return nextResolve(specifier, context);
}
`;
register(`data:text/javascript,${encodeURIComponent(loaderCode)}`, import.meta.url);

const { stateVideos } = await import('../state-videos.js');
const { stateLightbox } = await import('../state-lightbox.js');

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '../../../../../..');
const SHOWCASE_HTML = readFileSync(
    path.join(REPO_ROOT, 'web/templates/showcase.html'),
    'utf8',
);

const FAKE_GRID = { id: 'fake-grid' };

function makeComponent(overrides) {
    const c = Object.assign({}, stateVideos(), stateLightbox(), {
        mode: 'grid',
        cardShape: 'cover',
        perPage: 60,
        page: 1,
        totalPages: 1,
        _isNarrow: false,
        showFavoriteActresses: false,
        // handleKeydown 在 A 鍵之前的 guard 全部關死，讓按鍵落到第 6 段
        _pillEditor: null,
        similarModeOpen: false,
        similarModeMobileOpen: false,
        removeActressModalOpen: false,
        actressAddPanelOpen: false,
        _pickerOpen: false,
        rescrapeOpen: false,
        deleteVideoModalOpen: false,
        sampleGalleryOpen: false,
        lightboxOpen: false,
        saveCalls: 0,
        saveState() { c.saveCalls++; },
        $nextTick(fn) { fn(); },
        _getActiveGrid() { return FAKE_GRID; },
    }, overrides);
    return c;
}

function pressA(c) {
    c.handleKeydown({
        key: 'A',
        target: { tagName: 'BODY' },
        preventDefault() {},
        stopPropagation() {},
        ctrlKey: false,
        altKey: false,
        shiftKey: false,
        metaKey: false,
    });
}

function extractModeMenu(html) {
    const start = html.indexOf('<!-- 顯示模式 -->');
    assert.ok(start >= 0, 'showcase.html 必須有「顯示模式」註解錨點');
    const end = html.indexOf('<!-- 資訊顯示開關', start);
    assert.ok(end > start, '顯示模式區塊必須在資訊顯示開關之前結束');
    return html.slice(start, end);
}

function evalMenuXShow(expr, c) {
    const fn = new Function(
        '_isNarrow',
        '_posterModeActive',
        'cardShape',
        'mode',
        'showTableList',
        `return (${expr});`,
    );
    return Boolean(fn(
        c._isNarrow,
        () => c._posterModeActive(),
        c.cardShape,
        c.mode,
        c.showTableList,
    ));
}

function visibleMenuCount(c) {
    const menu = extractModeMenu(SHOWCASE_HTML);
    const tags = menu.match(/<a\b[^>]*>/g) || [];
    assert.ok(tags.length > 0, '模式選單必須有 <a> 項目');
    return tags.filter((tag) => {
        const m = tag.match(/\bx-show="([^"]*)"/);
        if (!m) return true;
        return evalMenuXShow(m[1], c);
    }).length;
}

/** 新鈕：x-show 含 showTableList 的 <button>（下拉觸發鈕沒有這個 gate）。 */
function extractShapeToggleButton(menu) {
    const re = /<button\b([^>]*)>/g;
    let m;
    while ((m = re.exec(menu)) !== null) {
        const attrs = m[1];
        const xs = attrs.match(/\bx-show="([^"]*)"/);
        if (xs && xs[1].includes('showTableList')) {
            return { attrs, xShow: xs[1] };
        }
    }
    return null;
}

// =====================================================================
// 反向鎖（§0.1 / P2-1）：桌面 + poster 仍是四條／四段（旗標開）
// =====================================================================

// [lint-guard: node-justified] 162e 暫留：求值型行為測試（lint 無 JS 求值能力）；R1：旗標開、桌面、直式海報時模式下拉選項不得少掉，少了的顯示方式選不到
test('反向鎖（旗標開）：桌面 + cardShape=poster → 選單條數判斷仍是四條', () => {
    const c = makeComponent({
        _isNarrow: false,
        cardShape: 'poster',
        mode: 'grid',
        showTableList: true,
    });
    assert.equal(visibleMenuCount(c), 4, 'x-show 必須讀 _isNarrow，不得讀 _posterModeActive()');
});

// =====================================================================
// A 鍵循環
// =====================================================================

test('A 鍵（旗標開）：桌面四段循環 cover → poster → list → table → cover', () => {
    const c = makeComponent({
        _isNarrow: false,
        mode: 'grid',
        cardShape: 'cover',
        showTableList: true,
    });
    pressA(c);
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'poster');
    pressA(c);
    assert.equal(c.mode, 'list');
    assert.equal(c.cardShape, 'poster');
    pressA(c);
    assert.equal(c.mode, 'table');
    assert.equal(c.cardShape, 'poster');
    pressA(c);
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'cover');
});

test('A 鍵（旗標關）：桌面兩段循環 cover → poster → cover', () => {
    const c = makeComponent({
        _isNarrow: false,
        mode: 'grid',
        cardShape: 'cover',
        showTableList: false,
    });
    pressA(c);
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'poster');
    pressA(c);
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'cover');
});

test('A 鍵：窄螢幕三段循環 cover → list → table → cover', () => {
    const c = makeComponent({
        _isNarrow: true,
        mode: 'grid',
        cardShape: 'cover',
        showTableList: true,
    });
    pressA(c);
    assert.equal(c.mode, 'list');
    assert.equal(c.cardShape, 'cover');
    pressA(c);
    assert.equal(c.mode, 'table');
    assert.equal(c.cardShape, 'cover');
    pressA(c);
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'cover');
});

test('A 鍵：窄螢幕 + cardShape=poster 循環一整圈後 cardShape 仍是 poster', () => {
    const c = makeComponent({
        _isNarrow: true,
        mode: 'grid',
        cardShape: 'poster',
        showTableList: true,
    });
    pressA(c);
    assert.equal(c.mode, 'list');
    assert.equal(c.cardShape, 'poster');
    pressA(c);
    assert.equal(c.mode, 'table');
    assert.equal(c.cardShape, 'poster');
    pressA(c);
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'poster', '窄螢幕「圖片」必須送 _gridTarget()，不得寫死 cover');
});

test('A 鍵（旗標關）：窄螢幕按 A → mode 與 cardShape 都不變（單元素序列早退）', () => {
    const c = makeComponent({
        _isNarrow: true,
        mode: 'grid',
        cardShape: 'poster',
        showTableList: false,
    });
    pressA(c);
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'poster', '窄＋旗標關不得靜默洗掉桌機卡型');
    pressA(c);
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'poster');
});

test('A 鍵：女優牆（showFavoriteActresses=true）mode 與 cardShape 都不變', () => {
    const c = makeComponent({
        showFavoriteActresses: true,
        mode: 'grid',
        cardShape: 'cover',
        _isNarrow: false,
    });
    pressA(c);
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'cover');
});

// =====================================================================
// 源碼斷言（showcase.html 模式選單）
// =====================================================================

// [lint-guard: node-justified] 162e 暫留：缺「到結尾錨點」的 scope 欄位（只有 {anchor,window:N}），且 _posterModeActive 全檔有合法使用不能全檔 forbidden
test('源碼：模式選單區塊內零 switchMode(、零 _posterModeActive', () => {
    const menu = extractModeMenu(SHOWCASE_HTML);
    assert.equal(menu.includes('switchMode('), false, `選單不得再呼叫 switchMode(：${menu}`);
    assert.equal(menu.includes('_posterModeActive'), false, '選單區塊不得出現 _posterModeActive');
});

// [lint-guard: node-justified] 162e 暫留：求值型行為測試（lint 無 JS 求值能力）；R1：旗標關桌面要看得到卡型切換鈕，窄螢幕／旗標開不得多一顆重複鈕
test('源碼：新鈕 x-show 同時含 !showTableList 與 !_isNarrow，四態可見性正確', () => {
    const menu = extractModeMenu(SHOWCASE_HTML);
    const btn = extractShapeToggleButton(menu);
    assert.ok(btn, '必須有旗標關時的卡型切換新鈕');
    assert.ok(btn.xShow.includes('!showTableList'), '新鈕 x-show 必須含 !showTableList');
    assert.ok(btn.xShow.includes('!_isNarrow'), '新鈕 x-show 必須含 !_isNarrow');
    // 寬/窄 × 旗標開/關
    assert.equal(
        evalMenuXShow(btn.xShow, makeComponent({ _isNarrow: false, showTableList: false })),
        true,
        '寬＋旗標關 → 新鈕可見',
    );
    assert.equal(
        evalMenuXShow(btn.xShow, makeComponent({ _isNarrow: false, showTableList: true })),
        false,
        '寬＋旗標開 → 新鈕不可見',
    );
    assert.equal(
        evalMenuXShow(btn.xShow, makeComponent({ _isNarrow: true, showTableList: false })),
        false,
        '窄＋旗標關 → 新鈕不可見',
    );
    assert.equal(
        evalMenuXShow(btn.xShow, makeComponent({ _isNarrow: true, showTableList: true })),
        false,
        '窄＋旗標開 → 新鈕不可見',
    );
});
