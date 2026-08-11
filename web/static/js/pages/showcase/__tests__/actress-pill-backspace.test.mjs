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
import { readFileSync } from 'node:fs';

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

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '../../../../../..');
const STATE_ACTRESS_SRC = readFileSync(
    path.join(REPO_ROOT, 'web/static/js/pages/showcase/state-actress.js'),
    'utf8',
);
const SHOWCASE_HTML = readFileSync(
    path.join(REPO_ROOT, 'web/templates/showcase.html'),
    'utf8',
);

/**
 * 抽出 class="filter-pill-group actress-filter-pill-group" 起的那一個元素 markup
 * （含內層，depth-aware）。比照 actress-pill-shell.test.mjs。
 */
function extractActressFilterPillGroup(html) {
    const openRe = /<div\b[^>]*\bclass="filter-pill-group actress-filter-pill-group"[^>]*>/;
    const m = openRe.exec(html);
    assert.ok(m, 'showcase.html 應含 class="filter-pill-group actress-filter-pill-group" 的容器');
    const start = m.index;
    let i = start + m[0].length;
    let depth = 1;
    while (i < html.length && depth > 0) {
        const nextOpen = html.indexOf('<div', i);
        const nextClose = html.indexOf('</div>', i);
        if (nextClose === -1) break;
        if (nextOpen !== -1 && nextOpen < nextClose) {
            depth++;
            i = nextOpen + 4;
        } else {
            depth--;
            i = nextClose + 6;
            if (depth === 0) {
                return html.slice(start, i);
            }
        }
    }
    throw new Error('actress-filter-pill-group 未找到匹配的 </div>');
}

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

test('stateActress() 定義 onActressSearchBackspace', () => {
    assert.equal(typeof stateActress().onActressSearchBackspace, 'function');
});

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

test('刪除委派 removeActressPill(last.dim, last.value)', () => {
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
    c.onActressSearchBackspace(evt({ value: '', selectionStart: 0, selectionEnd: 0 }));
    assert.equal(c.removeCalls.length, 1);
    assert.deepEqual(c.removeCalls[0], ['cup', 'B']);
});

// ===== 有字 → 不動 pill（含 caret 0 組合，鎖空值擋板本身）=====

test('輸入框有字 → actressPills 不變、不呼叫 removeActressPill', () => {
    const c = makeComponent({
        actressPills: [{ dim: 'age', op: '=', value: '37', value2: null }],
    });
    const realRemove = c.removeActressPill.bind(c);
    c.removeActressPill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    c.onActressSearchBackspace(evt({ value: 'ab', selectionStart: 2, selectionEnd: 2 }));
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.actressPills.length, 1);
});

test('輸入框有字且 caret 在最左 → 仍不刪 pill（空值判斷先擋）', () => {
    const c = makeComponent({
        actressPills: [{ dim: 'age', op: '=', value: '37', value2: null }],
    });
    const realRemove = c.removeActressPill.bind(c);
    c.removeActressPill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    c.onActressSearchBackspace(evt({ value: 'ab', selectionStart: 0, selectionEnd: 0 }));
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.actressPills.length, 1);
});

// ===== caret / selection =====

test('空值但 caret 不在 0 → actressPills 不變、不呼叫 removeActressPill', () => {
    const c = makeComponent({
        actressPills: [{ dim: 'age', op: '=', value: '37', value2: null }],
    });
    const realRemove = c.removeActressPill.bind(c);
    c.removeActressPill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    // 理論上空字串 caret 不會在中間，但仍須顯式覆蓋 caret 判斷分支本身
    c.onActressSearchBackspace(evt({ value: '', selectionStart: 1, selectionEnd: 1 }));
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.actressPills.length, 1);
});

test('非 collapsed 選取（selectionStart !== selectionEnd）→ 不刪 pill', () => {
    const c = makeComponent({
        actressPills: [{ dim: 'age', op: '=', value: '37', value2: null }],
    });
    const realRemove = c.removeActressPill.bind(c);
    c.removeActressPill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    // value 非空才能有真實非 collapsed 選取；空值判斷也會擋，但選取條件必須仍顯式成立
    c.onActressSearchBackspace(evt({ value: 'ab', selectionStart: 0, selectionEnd: 2 }));
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.actressPills.length, 1);
});

// 顯式鎖 caret 的非 collapsed 分支：空字串 + selectionStart/End 不同（合成 event）
// 若有人只判 selectionStart === 0 而漏 selectionEnd，這支會抓到。
test('空值但 selection 非 collapsed → 不刪 pill（caret 判斷式必須同時比對 End）', () => {
    const c = makeComponent({
        actressPills: [{ dim: 'age', op: '=', value: '37', value2: null }],
    });
    const realRemove = c.removeActressPill.bind(c);
    c.removeActressPill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    c.onActressSearchBackspace(evt({ value: '', selectionStart: 0, selectionEnd: 1 }));
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.actressPills.length, 1);
});

// ===== 零 pill =====

test('actressPills.length === 0（空值＋caret 0＋非組字）→ 不丟例外、不呼叫 removeActressPill', () => {
    const c = makeComponent({ actressPills: [] });
    const realRemove = c.removeActressPill.bind(c);
    c.removeActressPill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    assert.doesNotThrow(() => {
        c.onActressSearchBackspace(evt({ value: '', selectionStart: 0, selectionEnd: 0 }));
    });
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.actressPills.length, 0);
});

// ===== 結構：handler 第一行必須是 isComposing 早退 =====

test('onActressSearchBackspace 函式體第一行即 if (event.isComposing) return', () => {
    // 鎖順序：IME 閘必須是第一個 early-return，不得被 empty/caret 判斷擠到後面
    const m = STATE_ACTRESS_SRC.match(
        /onActressSearchBackspace\s*\(\s*event\s*\)\s*\{([\s\S]*?)\n\s{4,8}\},/,
    );
    assert.ok(m, '應能抽出 onActressSearchBackspace 方法體');
    const body = m[1].replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
    const firstStmt = body.trim().split(/\n/).map((l) => l.trim()).filter(Boolean)[0];
    assert.equal(
        firstStmt,
        'if (event.isComposing) return;',
        `函式體第一句必須是 isComposing 早退，實際：${firstStmt}`,
    );
});

// ===== 結構：showcase.html 綁定 =====

test('showcase.html 女優搜尋 input 帶 @keydown.backspace="onActressSearchBackspace($event)"', () => {
    const GROUP = extractActressFilterPillGroup(SHOWCASE_HTML);
    assert.ok(
        /@keydown\.backspace="onActressSearchBackspace\(\$event\)"/.test(GROUP),
        'actress-filter-pill-group 內搜尋 input 應綁 @keydown.backspace="onActressSearchBackspace($event)"',
    );
});
