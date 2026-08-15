// TASK-119-T5: UI 接線（選單四條、tooltip、A 鍵、_posterModeActive()）。
// 覆蓋反向鎖（桌面 + poster 仍四條／四段）、A 鍵三／四段循環、窄螢幕不得洗掉
// cardShape（技術要點 ①）、女優牆早退、三支 helper 邊界、_posterModeActive 三態、
// 選單源碼契約。
//
// harness 照抄 select-presentation.test.mjs（importmap hook、readFileSync 讀源碼、
// Object.assign({}, stateVideos(), …)），並把 stateLightbox() 併進元件以測 A 鍵。

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
        `return (${expr});`,
    );
    return Boolean(fn(
        c._isNarrow,
        () => c._posterModeActive(),
        c.cardShape,
        c.mode,
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

// =====================================================================
// 反向鎖（§0.1 / P2-1）：桌面 + poster 仍是四條／四段
// =====================================================================

test('反向鎖：桌面 + cardShape=poster → 選單條數判斷仍是四條', () => {
    const c = makeComponent({ _isNarrow: false, cardShape: 'poster', mode: 'grid' });
    assert.equal(visibleMenuCount(c), 4, 'x-show 必須讀 _isNarrow，不得讀 _posterModeActive()');
});

test('反向鎖：桌面 + cardShape=poster → A 仍四段', () => {
    const c = makeComponent({ _isNarrow: false, cardShape: 'poster', mode: 'grid' });
    assert.deepEqual(
        c._presentationOrder(),
        ['cover', 'poster', 'list', 'table'],
    );
    assert.equal(c._presentationOrder().length, 4);
});

// =====================================================================
// A 鍵循環
// =====================================================================

test('A 鍵：桌面四段循環 cover → poster → list → table → cover', () => {
    const c = makeComponent({
        _isNarrow: false,
        mode: 'grid',
        cardShape: 'cover',
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

test('A 鍵：窄螢幕三段循環 cover → list → table → cover', () => {
    const c = makeComponent({
        _isNarrow: true,
        mode: 'grid',
        cardShape: 'cover',
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
// _posterModeActive() 三態
// =====================================================================

test('_posterModeActive()：桌面 cover → false', () => {
    const c = makeComponent({ _isNarrow: false, cardShape: 'cover' });
    assert.equal(c._posterModeActive(), false);
});

test('_posterModeActive()：桌面 poster → true', () => {
    const c = makeComponent({ _isNarrow: false, cardShape: 'poster' });
    assert.equal(c._posterModeActive(), true);
});

test('_posterModeActive()：_isNarrow → true（不論卡型）', () => {
    const cover = makeComponent({ _isNarrow: true, cardShape: 'cover' });
    const poster = makeComponent({ _isNarrow: true, cardShape: 'poster' });
    assert.equal(cover._posterModeActive(), true);
    assert.equal(poster._posterModeActive(), true);
});

// =====================================================================
// helper 邊界
// =====================================================================

test('_gridTarget()：poster → poster，其餘 → cover', () => {
    assert.equal(makeComponent({ cardShape: 'poster' })._gridTarget(), 'poster');
    assert.equal(makeComponent({ cardShape: 'cover' })._gridTarget(), 'cover');
    assert.equal(makeComponent({ cardShape: 'other' })._gridTarget(), 'cover');
});

test('_currentPresentation()：grid 走卡型，list 走 list，其餘 fail-safe 落到 table', () => {
    assert.equal(
        makeComponent({ mode: 'grid', cardShape: 'cover' })._currentPresentation(),
        'cover',
    );
    assert.equal(
        makeComponent({ mode: 'grid', cardShape: 'poster' })._currentPresentation(),
        'poster',
    );
    assert.equal(
        makeComponent({ mode: 'list', cardShape: 'poster' })._currentPresentation(),
        'list',
    );
    assert.equal(
        makeComponent({ mode: 'table', cardShape: 'poster' })._currentPresentation(),
        'table',
    );
    assert.equal(
        makeComponent({ mode: 'unexpected', cardShape: 'cover' })._currentPresentation(),
        'table',
    );
});

test('_presentationOrder()：桌面四段字面、窄螢幕三段且第一格是 _gridTarget()', () => {
    assert.deepEqual(
        makeComponent({ _isNarrow: false, cardShape: 'poster' })._presentationOrder(),
        ['cover', 'poster', 'list', 'table'],
    );
    assert.deepEqual(
        makeComponent({ _isNarrow: true, cardShape: 'cover' })._presentationOrder(),
        ['cover', 'list', 'table'],
    );
    assert.deepEqual(
        makeComponent({ _isNarrow: true, cardShape: 'poster' })._presentationOrder(),
        ['poster', 'list', 'table'],
    );
});

// =====================================================================
// 源碼斷言（showcase.html 模式選單）
// =====================================================================

test('源碼：模式選單區塊內零 switchMode(、零 _posterModeActive', () => {
    const menu = extractModeMenu(SHOWCASE_HTML);
    assert.equal(menu.includes('switchMode('), false, `選單不得再呼叫 switchMode(：${menu}`);
    assert.equal(menu.includes('_posterModeActive'), false, '選單區塊不得出現 _posterModeActive');
});

test('源碼：觸發鈕 <i> class 運算式逐字未變', () => {
    const menu = extractModeMenu(SHOWCASE_HTML);
    assert.ok(
        menu.includes(":class=\"mode === 'grid' ? 'bi-grid-3x3' : mode === 'table' ? 'bi-table' : 'bi-list-ul'\""),
        '觸發鈕圖示運算式必須逐字不變（AC-1.2）',
    );
});

test('源碼：「完整封面」那條含 icon-mirror-x', () => {
    const menu = extractModeMenu(SHOWCASE_HTML);
    assert.ok(
        menu.includes('icon-mirror-x'),
        '完整封面 <i> 必須含 icon-mirror-x',
    );
    assert.ok(
        /bi-person-vcard[^"']*icon-mirror-x|icon-mirror-x[^"']*bi-person-vcard/.test(menu),
        'icon-mirror-x 必須掛在完整封面的 person-vcard 圖示上',
    );
});
