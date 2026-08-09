// TASK-115-T9: 搜尋框 Backspace 刪最後一枚 pill ＋ IME 安全閘。
// 覆蓋 onSearchBackspace 的 isComposing / empty / caret / zero-pills / removePill 委派，
// 以及 showcase.html 的 @keydown.backspace 綁定與 D6 focus 回歸鎖。
//
// state-videos.js 用瀏覽器 importmap 別名 `@/showcase/...` 與 `@/shared/...`，
// plain `node --test` 不認得。既有 search/__tests__/alias-loader.mjs 只做
// `@/` → `web/static/js/` 字首轉譯，對 `@/showcase/` 會解成錯誤路徑
// （importmap 實際指到 `pages/showcase/`）。比照 pill-state.test.mjs，
// 本檔自帶與 base.html importmap 對齊的 resolve hook（FE-GUARD-11）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import { readFileSync } from 'node:fs';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// 任務卡聲稱 open-local 的 window 存取皆在函式體內，實際並非如此。
// 比照 cover-fallback.test.mjs / pill-state.test.mjs 先 stub window。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;
// clearAllFilters / Alpine.store 路徑不在本檔主測，但 stateVideos 合併物可能被引用。
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

const { stateVideos } = await import('../state-videos.js');

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '../../../../../..');
const STATE_VIDEOS_SRC = readFileSync(
    path.join(REPO_ROOT, 'web/static/js/pages/showcase/state-videos.js'),
    'utf8',
);
const LIGHTBOX_SRC = readFileSync(
    path.join(REPO_ROOT, 'web/static/js/pages/showcase/state-lightbox.js'),
    'utf8',
);
const SHOWCASE_HTML = readFileSync(
    path.join(REPO_ROOT, 'web/templates/showcase.html'),
    'utf8',
);

/** 抽出 class="filter-pill-group" 起的那一個元素 markup（含內層，depth-aware）。 */
function extractFilterPillGroup(html) {
    const openRe = /<div\b[^>]*\bclass="filter-pill-group"[^>]*>/;
    const m = openRe.exec(html);
    assert.ok(m, 'showcase.html 應含 class="filter-pill-group" 的容器');
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
    throw new Error('filter-pill-group 未找到匹配的 </div>');
}

/** 抽出 searchFromMetadata 方法體（brace-matched），供 D6 focus 回歸鎖。 */
function extractFnBody(src, signatureNeedle, label) {
    const start = src.indexOf(signatureNeedle);
    assert.ok(start !== -1, `找不到 ${label} 定義：${signatureNeedle}`);
    const braceStart = src.indexOf('{', start);
    assert.ok(braceStart !== -1, `${label} 找不到開括號`);
    let depth = 0;
    for (let i = braceStart; i < src.length; i++) {
        const ch = src[i];
        if (ch === '{') depth++;
        else if (ch === '}') {
            depth--;
            if (depth === 0) return src.slice(braceStart + 1, i);
        }
    }
    throw new Error(`${label} 方法體未閉合`);
}

function makeComponent(overrides) {
    const c = Object.assign({}, stateVideos(), {
        pills: [],
        search: '',
        actressSearch: '',
        page: 3,
        sort: 'title',
        order: 'asc',
        animateCalls: 0,
        heroCalls: 0,
        removeCalls: [],
        _clearPreciseMatch() {},
        _checkPreciseActressMatch() {},
        applyActressFilterAndSort() {},
    }, overrides);
    c._animateFilter = function () { c.animateCalls++; };
    c._reconcileHeroCard = function () { c.heroCalls++; };
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

test('stateVideos() 定義 onSearchBackspace', () => {
    assert.equal(typeof stateVideos().onSearchBackspace, 'function');
});

// ===== IME 安全閘（硬性紅線）=====

test('isComposing: true（空值＋caret 0＋有 pill）→ pills 不變、不呼叫 removePill', () => {
    const c = makeComponent({
        pills: [
            { dim: 'maker', value: 'Moodyz' },
            { dim: 'series', value: 'Madonna' },
        ],
    });
    const realRemove = c.removePill.bind(c);
    c.removePill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    const before = c.pills.slice();
    c.onSearchBackspace(evt({ isComposing: true, value: '', selectionStart: 0, selectionEnd: 0 }));
    assert.equal(c.removeCalls.length, 0, 'IME 組字中不得呼叫 removePill');
    assert.equal(c.pills.length, 2);
    assert.deepEqual(c.pills, before);
});

// ===== 成功刪除最後一枚 =====

test('空值＋caret 0＋非組字＋有 pill → 刪最後一枚，第一枚存活', () => {
    const c = makeComponent({
        pills: [
            { dim: 'maker', value: 'Moodyz' },
            { dim: 'series', value: 'Madonna' },
        ],
    });
    c.onSearchBackspace(evt({ value: '', selectionStart: 0, selectionEnd: 0 }));
    assert.equal(c.pills.length, 1);
    assert.equal(c.pills[0].dim, 'maker');
    assert.equal(c.pills[0].value, 'Moodyz');
});

test('刪除委派 removePill(last.dim, last.value)', () => {
    const c = makeComponent({
        pills: [
            { dim: 'maker', value: 'Moodyz' },
            { dim: 'series', value: 'Madonna' },
        ],
    });
    const realRemove = c.removePill.bind(c);
    c.removePill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    c.onSearchBackspace(evt({ value: '', selectionStart: 0, selectionEnd: 0 }));
    assert.equal(c.removeCalls.length, 1);
    assert.deepEqual(c.removeCalls[0], ['series', 'Madonna']);
});

// ===== 有字 → 不動 pill（含 caret 0 組合，鎖空值擋板本身）=====

test('輸入框有字 → pills 不變、不呼叫 removePill', () => {
    const c = makeComponent({
        pills: [{ dim: 'maker', value: 'Moodyz' }],
    });
    const realRemove = c.removePill.bind(c);
    c.removePill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    c.onSearchBackspace(evt({ value: 'ab', selectionStart: 2, selectionEnd: 2 }));
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.pills.length, 1);
});

test('輸入框有字且 caret 在最左 → 仍不刪 pill（空值判斷先擋）', () => {
    const c = makeComponent({
        pills: [{ dim: 'maker', value: 'Moodyz' }],
    });
    const realRemove = c.removePill.bind(c);
    c.removePill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    c.onSearchBackspace(evt({ value: 'ab', selectionStart: 0, selectionEnd: 0 }));
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.pills.length, 1);
});

// ===== caret / selection =====

test('空值但 caret 不在 0 → pills 不變、不呼叫 removePill', () => {
    const c = makeComponent({
        pills: [{ dim: 'maker', value: 'Moodyz' }],
    });
    const realRemove = c.removePill.bind(c);
    c.removePill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    // 理論上空字串 caret 不會在中間，但仍須顯式覆蓋 caret 判斷分支本身
    c.onSearchBackspace(evt({ value: '', selectionStart: 1, selectionEnd: 1 }));
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.pills.length, 1);
});

test('非 collapsed 選取（selectionStart !== selectionEnd）→ 不刪 pill', () => {
    const c = makeComponent({
        pills: [{ dim: 'maker', value: 'Moodyz' }],
    });
    const realRemove = c.removePill.bind(c);
    c.removePill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    // value 非空才能有真實非 collapsed 選取；空值判斷也會擋，但選取條件必須仍顯式成立
    c.onSearchBackspace(evt({ value: 'ab', selectionStart: 0, selectionEnd: 2 }));
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.pills.length, 1);
});

// 顯式鎖 caret 的非 collapsed 分支：空字串 + selectionStart/End 不同（合成 event）
// 若有人只判 selectionStart === 0 而漏 selectionEnd，這支會抓到。
test('空值但 selection 非 collapsed → 不刪 pill（caret 判斷式必須同時比對 End）', () => {
    const c = makeComponent({
        pills: [{ dim: 'maker', value: 'Moodyz' }],
    });
    const realRemove = c.removePill.bind(c);
    c.removePill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    c.onSearchBackspace(evt({ value: '', selectionStart: 0, selectionEnd: 1 }));
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.pills.length, 1);
});

// ===== 零 pill =====

test('pills.length === 0（空值＋caret 0＋非組字）→ 不丟例外、不呼叫 removePill', () => {
    const c = makeComponent({ pills: [] });
    const realRemove = c.removePill.bind(c);
    c.removePill = function (dim, value) {
        c.removeCalls.push([dim, value]);
        return realRemove(dim, value);
    };
    assert.doesNotThrow(() => {
        c.onSearchBackspace(evt({ value: '', selectionStart: 0, selectionEnd: 0 }));
    });
    assert.equal(c.removeCalls.length, 0);
    assert.equal(c.pills.length, 0);
});

// ===== 結構：handler 第一行必須是 isComposing 早退 =====

test('onSearchBackspace 函式體第一行即 if (event.isComposing) return', () => {
    // 鎖順序：IME 閘必須是第一個 early-return，不得被 empty/caret 判斷擠到後面
    const m = STATE_VIDEOS_SRC.match(
        /onSearchBackspace\s*\(\s*event\s*\)\s*\{([\s\S]*?)\n\s{4,8}\},/,
    );
    assert.ok(m, '應能抽出 onSearchBackspace 方法體');
    const body = m[1].replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
    const firstStmt = body.trim().split(/\n/).map((l) => l.trim()).filter(Boolean)[0];
    assert.equal(
        firstStmt,
        'if (event.isComposing) return;',
        `函式體第一句必須是 isComposing 早退，實際：${firstStmt}`,
    );
});

// ===== 結構：showcase.html 綁定 =====

test('showcase.html 搜尋 input 帶 @keydown.backspace="onSearchBackspace($event)"', () => {
    const GROUP = extractFilterPillGroup(SHOWCASE_HTML);
    assert.ok(
        /@keydown\.backspace="onSearchBackspace\(\$event\)"/.test(GROUP),
        'filter-pill-group 內搜尋 input 應綁 @keydown.backspace="onSearchBackspace($event)"',
    );
});

// ===== D6：不自動 focus =====

test('D6：filter-pill-group 搜尋區塊不含 .focus( 字面', () => {
    const GROUP = extractFilterPillGroup(SHOWCASE_HTML);
    assert.ok(!GROUP.includes('.focus('), '搜尋 pill 區塊不得含 .focus(');
});

test('D6：searchFromMetadata body 不含 .focus( 字面', () => {
    const body = extractFnBody(LIGHTBOX_SRC, 'searchFromMetadata(value, dim) {', 'searchFromMetadata');
    assert.ok(!body.includes('.focus('), 'searchFromMetadata 不得自動 focus 搜尋框');
});
