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
    beginYearsDrag,
    cancelYearsDrag,
    getYearsDragState,
    disposeAll,
} = await import('../charts.js');
const { UNKNOWN_KEY } = await import('../aggregate.js');

// ── escapeHtml（P3-1：tooltip renderMode:'html' 自訂 formatter XSS 修正）───

test('escapeHtml: <img onerror> payload 被拆解，不再是可執行的標籤', () => {
    const out = escapeHtml('<img src=x onerror="window.__xss=1">');
    assert.equal(out, '&lt;img src=x onerror=&quot;window.__xss=1&quot;&gt;');
    assert.ok(!out.includes('<img'));
});

// ── shouldAnimate ────────────────────────────────────────────────────

test('shouldAnimate: 系統未開「減少動態效果」時回傳 true（播放動畫）', () => {
    // 表驅動：使用者的「減少動態」偏好關／開各一列
    const cases = [
        { prefersReducedMotion: false, exp: true },
        { prefersReducedMotion: true, exp: false },
    ];
    for (const c of cases) {
        assert.equal(shouldAnimate(c.prefersReducedMotion), c.exp);
    }
});

// ── emptyKeyForCard（TASK-156c-T6／161a-T5a：舊版型別白名單寫法已刪）────────

const ALL_PERIOD = { type: 'all' };
const cRec = (year, actresses, maker) => ({ year, actresses, maker });
const cSel = (over) => ({ period: ALL_PERIOD, actress: null, maker: null, ...over });

test('emptyKeyForCard: count 取該卡範圍內的片數，不是整體範圍', () => {
    // A 沒有 S1 的片、S1 有別人（B）的片；2020 年有片
    const records = [
        cRec(2020, ['A'], 'M1'),
        cRec(2021, ['B'], 'S1'),
    ];
    const both = cSel({ actress: 'A', maker: 'S1' });
    // 女優榜類（skip actress）：範圍＝期間∩片商，B 的片在 → 有東西，不是 period_empty
    assert.equal(emptyKeyForCard(records, both, 'actress'), 'insights.no_data');
    // 看自己那一維全貌之外的卡（不跳維度）：A∩S1 = 0 → period_empty
    assert.equal(emptyKeyForCard(records, both, null), 'insights.period_empty');
    // 圓餅（skip maker）：期間∩女優 A 有 M1 的片 → 不是 period_empty
    assert.equal(emptyKeyForCard(records, both, 'maker'), 'insights.no_data');
    // 只選一年、該年有片：任一卡都不是 period_empty
    const year2020 = cSel({ period: { type: 'year', year: 2020 } });
    assert.equal(emptyKeyForCard(records, year2020, null), 'insights.no_data');
    assert.equal(emptyKeyForCard(records, year2020, 'maker'), 'insights.no_data');
});

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

test('resolveDragResult: 起於未知欄（或無效起點）不產生任何結果', () => {
    for (const start of [6, null, -1, 99, 1.5]) {
        assert.equal(resolveDragResult(start, 2, dragCats), null, 'start=' + start);
    }
});

test('resolveDragResult: 終點在未知欄或畫布外時夾在最後一個真實年份欄', () => {
    // 表驅動：夾限、夾限後兩端同欄正規化成單點（不產生 from===to 的範圍）、終點算不出視為沒移動
    const cases = [
        { start: 2, end: 6, exp: { kind: 'range', from: 2020, to: 2023 } },
        { start: 2, end: 99, exp: { kind: 'range', from: 2020, to: 2023 } },
        { start: 2, end: -5, exp: { kind: 'range', from: 2018, to: 2020 } },
        { start: 5, end: 6, exp: { kind: 'point', year: 2023 } },
        { start: 5, end: 99, exp: { kind: 'point', year: 2023 } },
        { start: 3, end: NaN, exp: { kind: 'point', year: 2021 } },
        { start: 3, end: null, exp: { kind: 'point', year: 2021 } },
    ];
    for (const c of cases) {
        assert.deepEqual(resolveDragResult(c.start, c.end, dragCats), c.exp, 'start=' + c.start + ' end=' + c.end);
    }
});

test('resolveGestureResult: 觸控拖過多欄不產生範圍，同欄 tap 仍是單點，滑鼠不受影響', () => {
    assert.equal(resolveGestureResult(1, 4, dragCats, true), null);
    assert.deepEqual(resolveGestureResult(2, 2, dragCats, true), { kind: 'point', year: 2020 });
    assert.deepEqual(resolveGestureResult(1, 4, dragCats, false), {
        kind: 'range',
        from: 2019,
        to: 2022,
    });
});

test('cancelYearsDrag／disposeAll: dispose 後 document mouseup 監聽被移除且手勢狀態清空', () => {
    const doc = globalThis.document;
    const oldAdd = doc.addEventListener;
    const oldRemove = doc.removeEventListener;
    const adds = [];
    const removes = [];
    doc.addEventListener = (...a) => adds.push(a);
    doc.removeEventListener = (...a) => removes.push(a);
    try {
        const fn = () => {};
        beginYearsDrag(2, false, fn);
        assert.deepEqual(adds, [['mouseup', fn]]);
        assert.deepEqual(getYearsDragState(), { startIdx: 2, curIdx: 2, byTouch: false });
        disposeAll();
        assert.deepEqual(removes, [['mouseup', fn]]);
        assert.equal(getYearsDragState(), null);
        cancelYearsDrag();
        assert.equal(removes.length, 1);
    } finally {
        doc.addEventListener = oldAdd;
        doc.removeEventListener = oldRemove;
    }
});
