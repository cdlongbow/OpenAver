// TASK-116b-T4: handleKeydown 兩段式浮層分支（CD-116b-6）——零-DOM 餵假 event。
//
// state-lightbox.js 用瀏覽器 importmap 別名；plain node --test 不認得。
// 比照 actress-pill-state.test.mjs / pill-entry.test.mjs，本檔自帶 resolve hook（FE-GUARD-11）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// state-base.js 模組頂層讀 localStorage（清壞值）。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;
const _uiStore = { toolbarOpen: false, showcaseHasSearch: false };
globalThis.Alpine = {
    store: () => _uiStore,
};
if (typeof globalThis.localStorage === 'undefined') {
    const _store = Object.create(null);
    globalThis.localStorage = {
        getItem: (k) => (k in _store ? _store[k] : null),
        setItem: (k, v) => { _store[k] = String(v); },
        removeItem: (k) => { delete _store[k]; },
    };
}
if (typeof globalThis.requestAnimationFrame !== 'function') {
    globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
}
if (typeof globalThis.window.addEventListener !== 'function') {
    globalThis.window.addEventListener = () => {};
    globalThis.window.removeEventListener = () => {};
}
if (typeof globalThis.document === 'undefined') {
    globalThis.document = {
        querySelector: () => null,
        body: { classList: { add() {}, remove() {} } },
    };
}
if (typeof globalThis.window.scrollY === 'undefined') {
    globalThis.window.scrollY = 0;
}
globalThis.window.location = { pathname: '/showcase', search: '' };
globalThis.window.history = { replaceState() {} };

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

const { stateLightbox } = await import('../state-lightbox.js');
const { stateBase } = await import('../state-base.js');

/**
 * 餵假 keydown event。tagName 預設 'BODY'（非 INPUT）。
 */
function makeKeyEvent(key, { tagName = 'BODY', preventDefault = null } = {}) {
    let prevented = false;
    const e = {
        key,
        target: { tagName },
        preventDefault() {
            prevented = true;
            if (typeof preventDefault === 'function') preventDefault();
        },
        stopPropagation() {},
        get defaultPrevented() { return prevented; },
    };
    return e;
}

/**
 * harness：stateBase + stateLightbox，外加 spy 的 nextPage / prevPage / _cancelPillEditor。
 * page/totalPages 設成可換頁，才能測「鎖鍵」有沒有擋到 nextPage。
 */
function makeComponent(overrides) {
    const base = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    const lightbox = stateLightbox();
    const calls = [];
    const c = Object.assign({}, base, lightbox, {
        page: 2,
        totalPages: 5,
        mode: 'table',
        lightboxOpen: false,
        similarModeOpen: false,
        similarModeMobileOpen: false,
        removeActressModalOpen: false,
        _pickerOpen: false,
        rescrapeOpen: false,
        deleteVideoModalOpen: false,
        sampleGalleryOpen: false,
        _pillEditor: null,
        nextPage() { calls.push(['nextPage']); },
        prevPage() { calls.push(['prevPage']); },
        _cancelPillEditor() {
            calls.push(['_cancelPillEditor']);
            this._pillEditor = null;
        },
    }, overrides);
    c.__calls = calls;
    return c;
}

// ── CD-116b-6：浮層開著 + Escape ──────────────────────────────────────────

test('_pillEditor 非 null + Escape → _cancelPillEditor 被呼叫、preventDefault 被呼叫', () => {
    const c = makeComponent({
        _pillEditor: { dim: 'age', op: '=', value: '37', rangeLo: null, rangeHi: null },
    });
    const e = makeKeyEvent('Escape');
    c.handleKeydown(e);
    assert.ok(c.__calls.some((x) => x[0] === '_cancelPillEditor'), '應呼叫 _cancelPillEditor');
    assert.equal(e.defaultPrevented, true, 'Escape 必須 preventDefault');
    assert.equal(c._pillEditor, null);
});

// ── 承重：分支必須在 INPUT 擋板之前 ──────────────────────────────────────

test('_pillEditor 非 null + e.target.tagName===INPUT + Escape → 一樣關浮層', () => {
    const c = makeComponent({
        _pillEditor: { dim: 'height', op: 'range', value: '160', rangeLo: '155', rangeHi: '165' },
    });
    const e = makeKeyEvent('Escape', { tagName: 'INPUT' });
    c.handleKeydown(e);
    assert.ok(
        c.__calls.some((x) => x[0] === '_cancelPillEditor'),
        '區間 input 聚焦時 ESC 仍必須關浮層（分支若誤放在 INPUT return 之後，本條會靜默失效）',
    );
    assert.equal(e.defaultPrevented, true);
    assert.equal(c._pillEditor, null);
});

// ── 第二段：鎖其餘鍵，但不得 preventDefault ─────────────────────────────

test('_pillEditor 非 null + ArrowRight → 不得 preventDefault、不得 nextPage', () => {
    const c = makeComponent({
        _pillEditor: { dim: 'age', op: '=', value: '37', rangeLo: null, rangeHi: null },
    });
    const e = makeKeyEvent('ArrowRight');
    c.handleKeydown(e);
    assert.equal(e.defaultPrevented, false, '第二段鎖鍵不得 preventDefault（否則區間 input 打不進字）');
    assert.ok(!c.__calls.some((x) => x[0] === 'nextPage'), '不得觸發換頁');
    assert.ok(!c.__calls.some((x) => x[0] === 'prevPage'), '不得觸發換頁');
    assert.ok(c._pillEditor, '非 Escape 不得關浮層');
});

// ── 浮層關閉時既有行為不變 ──────────────────────────────────────────────

test('_pillEditor 為 null + ArrowRight → 仍會 nextPage（既有行為）', () => {
    const c = makeComponent({ _pillEditor: null, page: 2, totalPages: 5 });
    const e = makeKeyEvent('ArrowRight');
    c.handleKeydown(e);
    assert.ok(c.__calls.some((x) => x[0] === 'nextPage'), '浮層未開時 ArrowRight 應 nextPage');
    assert.equal(e.defaultPrevented, false);
});

test('_pillEditor 為 null + Escape on INPUT → 早 return，不副作用', () => {
    const c = makeComponent({ _pillEditor: null });
    const e = makeKeyEvent('Escape', { tagName: 'INPUT' });
    c.handleKeydown(e);
    assert.equal(c.__calls.length, 0, '浮層未開 + INPUT 應完全不處理');
    assert.equal(e.defaultPrevented, false);
});
