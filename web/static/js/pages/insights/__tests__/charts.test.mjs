// charts.js 純函式分支（escapeHtml / shouldAnimate / emptyKeyForCard / 年份拖曳判定 / dispose 清理）。
// 不碰 DOM／ECharts 實例。

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

const {
    shouldAnimate,
    escapeHtml,
    emptyKeyForCard,
    resolveDragResult,
    resolveGestureResult,
    isTouchZrEvent,
    beginYearsDrag,
    cancelYearsDrag,
    getYearsDragState,
    disposeAll,
} = await import('../charts.js');
const { UNKNOWN_KEY } = await import('../aggregate.js');

// ── escapeHtml（P3-1：tooltip renderMode:'html' 自訂 formatter XSS 修正）───

test('escapeHtml: <img onerror> payload 被拆解，不再是可執行的標籤', () => {
    // 表驅動：每個轉義字元類別一列（標籤、&、雙／單引號、null／undefined）
    const cases = [
        { input: '<img src=x onerror="window.__xss=1">', exp: '&lt;img src=x onerror=&quot;window.__xss=1&quot;&gt;' },
        { input: 'A & B', exp: 'A &amp; B' },
        { input: `"quoted" 'single'`, exp: '&quot;quoted&quot; &#39;single&#39;' },
        { input: null, exp: '' },
        { input: undefined, exp: '' },
    ];
    for (const c of cases) {
        assert.equal(escapeHtml(c.input), c.exp, String(c.input));
    }
    assert.ok(!escapeHtml(cases[0].input).includes('<img'));
});

// ── shouldAnimate ────────────────────────────────────────────────────


// ── emptyKeyForCard（TASK-156c-T6／161a-T5a：舊版型別白名單寫法已刪）────────

const ALL_PERIOD = { type: 'all' };
const cRec = (year, actresses, maker) => ({ year, actresses, maker });
const cSel = (over) => ({ period: ALL_PERIOD, actress: null, maker: null, ...over });


// ── resolveDragResult（TASK-161a-T6a：年份拖曳手勢的純判定）──────────────

const dragCats = ['2018', '2019', '2020', '2021', '2022', '2023', UNKNOWN_KEY];

test('resolveDragResult: 同欄放開視為單點，不論中途拖去哪裡', () => {
    assert.deepEqual(resolveDragResult(2, 2, dragCats), { kind: 'point', year: 2020 });
});

test('resolveDragResult: 反向拖與正向拖結果相同', () => {
    const fwd = resolveDragResult(1, 4, dragCats);
    const rev = resolveDragResult(4, 1, dragCats);
    assert.deepEqual(fwd, { kind: 'range', from: 2019, to: 2022 });
    assert.deepEqual(rev, fwd);
});


// ── 177-T2：三種圖可點（點擊→extra、chip 組裝、長條 tooltip）───────────────

const {
    extraFromTreemapClick,
    extraFromBarClick,
    renderPulledChips,
    fieldBarTooltip,
} = await import('../charts.js');

function _fakeNode(tag) {
    const n = {
        tagName: String(tag).toUpperCase(),
        children: [],
        handlers: {},
        attrs: {},
        title: '',
        className: '',
        type: '',
        setAttribute(k, v) { n.attrs[k] = v; },
        addEventListener(ev, fn) { n.handlers[ev] = fn; },
        replaceChildren(...nodes) { n.children = nodes; },
        append(...nodes) { n.children.push(...nodes); },
        appendChild(x) { n.children.push(x); return x; },
    };
    Object.defineProperty(n, 'textContent', {
        set(v) { n.children = [{ nodeType: 3, data: String(v) }]; },
        get() { return n.children.map((c) => c.data || '').join(''); },
    });
    Object.defineProperty(n, 'innerHTML', {
        set(v) { n.children = /<img/i.test(v) ? [{ tagName: 'IMG' }] : [{ nodeType: 3, data: String(v) }]; },
    });
    return n;
}

function _walkTags(n, out) {
    for (const c of n.children) {
        if (c && c.tagName) { out.push(c.tagName); _walkTags(c, out); }
    }
    return out;
}

test('圖點擊: 各圖點到的項目帶對的維度與原字面', () => {
    const tree = (data) => ({ componentType: 'series', seriesType: 'treemap', data });
    const cases = [
        { got: extraFromTreemapClick(tree({ name: 'ＡＢＣ def' })), exp: { dim: 'tag', value: 'ＡＢＣ def' } },
        { got: extraFromBarClick('director', { name: ' 山田 太郎 ' }), exp: { dim: 'director', value: ' 山田 太郎 ' } },
        { got: extraFromBarClick('series', { name: 'Ｓ 系列 x' }), exp: { dim: 'series', value: 'Ｓ 系列 x' } },
        { got: extraFromTreemapClick(tree({ name: '' })), exp: null },
        { got: extraFromTreemapClick({ componentType: 'xAxis', seriesType: 'treemap', data: { name: 'a' } }), exp: null },
        { got: extraFromTreemapClick({ componentType: 'series', seriesType: 'pie', data: { name: 'a' } }), exp: null },
        { got: extraFromTreemapClick({ componentType: 'series', seriesType: 'treemap' }), exp: null },
        { got: extraFromBarClick('director', { name: '' }), exp: null },
        { got: extraFromBarClick('maker', { name: 'x' }), exp: null },
    ];
    cases.forEach((c, i) => assert.deepEqual(c.got, c.exp, 'row ' + i));
});

test('拉出標籤按鈕: 惡意名稱只成為文字、點擊帶原字串', () => {
    const evil = '<img src=x onerror=1>';
    const oldDoc = globalThis.document;
    globalThis.document = {
        ...oldDoc,
        createElement: _fakeNode,
        createTextNode: (s) => ({ nodeType: 3, data: String(s) }),
    };
    try {
        const el = _fakeNode('div');
        const picked = [];
        renderPulledChips(el, [[evil, 9]], 10, '前綴：', (x) => picked.push(x));
        const tags = _walkTags(el, []);
        assert.ok(tags.length >= 1);
        assert.ok(tags.every((t) => t === 'BUTTON'), tags.join(','));
        const btn = el.children.find((c) => c.tagName === 'BUTTON');
        assert.equal(btn.type === 'button' || btn.attrs.type === 'button', true);
        assert.ok(btn.className.includes('tags-pulled-chip'));
        assert.ok(btn.textContent.includes(evil));
        btn.handlers.click();
        assert.deepEqual(picked, [{ dim: 'tag', value: evil }]);
        renderPulledChips(el, [], 0, '前綴：', () => {});
        assert.equal(el.children.length, 0);
    } finally {
        globalThis.document = oldDoc;
    }
});

test('長條 tooltip: 導演／系列名稱被轉義', () => {
    const out = fieldBarTooltip([{ name: '<img src=x onerror=1>', value: 3 }]);
    assert.ok(!out.includes('<img'));
    assert.ok(out.includes('&lt;img'));
});
