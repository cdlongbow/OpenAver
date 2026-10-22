// TASK-116a-T4: 女優搜尋框 Backspace 刪最後一枚 actressPills ＋ IME 安全閘。
// 鏡射 pill-backspace.test.mjs（115 T9），改測 onActressSearchBackspace / removeActressPill。
// 不含 D6 focus 回歸（removeActressPill 路徑無 .focus( 副作用）。
//
// state-actress.js 用瀏覽器 importmap 別名；plain node --test 不認得。
// 比照 actress-pill-state.test.mjs，本檔自帶 resolve hook（FE-GUARD-11）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// state-base.js 模組頂層讀 localStorage（清壞值）。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;
globalThis.Alpine = globalThis.Alpine || {
    store: () => ({ toolbarOpen: false, showcaseHasSearch: false }),
};

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

const { stateActress } = await import('../state-actress.js');
const { stateBase, _setActresses } = await import('../state-base.js');


/**
 * 合併 stateBase + stateActress 的 harness（比照 actress-pill-state.test.mjs）。
 * Backspace 路徑走 removeActressPill → applyActressFilterAndSort，不經 _sortWithFlip。
 */
function makeComponent(overrides) {
    const base = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    const actress = stateActress();
    const c = Object.assign({}, base, actress, {
        actressSearch: '',
        actressSort: 'video_count',
        actressOrder: 'desc',
        removeCalls: [],
        sortFlipCalls: 0,
        _sortWithFlip(fn) {
            c.sortFlipCalls++;
            if (typeof fn === 'function') fn();
        },
    }, overrides);
    if (!Array.isArray(c.actressPills)) c.actressPills = [];
    _setActresses([
        { name: 'full', age: 37, height: '160cm', cup: 'B' },
        { name: 'tall', age: 25, height: '170cm', cup: 'C' },
    ]);
    return c;
}

/** 假 KeyboardEvent + 假 input target（node:test 無 DOM）。 */
function evt({ isComposing = false, value = '', selectionStart = 0, selectionEnd = 0 } = {}) {
    return {
        isComposing,
        target: { value, selectionStart, selectionEnd },
    };
}

// ===== 方法存在性 =====


// ===== IME 安全閘（硬性紅線）=====

test('isComposing: true（空值＋caret 0＋有 pill）→ actressPills 不變、不呼叫 removeActressPill', () => {
    const c = makeComponent({
        actressPills: [
            { dim: 'age', op: '=', value: '37', value2: null },
            { dim: 'cup', op: '=', value: 'B', value2: null },
        ],
    });
    const realRemove = c.removeActressPill.bind(c);
    c.removeActressPill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    const before = c.actressPills.slice();
    c.onActressSearchBackspace(evt({ isComposing: true, value: '', selectionStart: 0, selectionEnd: 0 }));
    assert.equal(c.removeCalls.length, 0, 'IME 組字中不得呼叫 removeActressPill');
    assert.equal(c.actressPills.length, 2);
    assert.deepEqual(c.actressPills, before);
});

// ===== 成功刪除最後一枚 =====

test('空值＋caret 0＋非組字＋有 pill → 刪最後一枚，第一枚存活', () => {
    const c = makeComponent({
        actressPills: [
            { dim: 'age', op: '=', value: '37', value2: null },
            { dim: 'cup', op: '=', value: 'B', value2: null },
        ],
    });
    c.onActressSearchBackspace(evt({ value: '', selectionStart: 0, selectionEnd: 0 }));
    assert.equal(c.actressPills.length, 1);
    assert.equal(c.actressPills[0].dim, 'age');
    assert.equal(c.actressPills[0].value, '37');
});


// ===== 有字 → 不動 pill（含 caret 0 組合，鎖空值擋板本身）=====


// ===== caret / selection =====


// 顯式鎖 caret 的非 collapsed 分支：空字串 + selectionStart/End 不同（合成 event）
// 若有人只判 selectionStart === 0 而漏 selectionEnd，這支會抓到。

// ===== 零 pill =====


// ===== 結構：handler 第一行必須是 isComposing 早退 =====

