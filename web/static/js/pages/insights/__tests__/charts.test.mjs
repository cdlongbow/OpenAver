// TASK-156b-T3: charts.js 純函式分支（resolveYearBarColorMode / shouldAnimate）。
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
    resolveYearBarColorMode,
    shouldAnimate,
    formatRgbaChannels,
    computeDonutStartAngle,
    escapeHtml,
    emptyKeyForCard,
    resolveDragResult,
} = await import('../charts.js');
const { UNKNOWN_KEY } = await import('../aggregate.js');

// ── escapeHtml（P3-1：tooltip renderMode:'html' 自訂 formatter XSS 修正）───

test('escapeHtml: <img onerror> payload 被拆解，不再是可執行的標籤', () => {
    const out = escapeHtml('<img src=x onerror="window.__xss=1">');
    assert.equal(out, '&lt;img src=x onerror=&quot;window.__xss=1&quot;&gt;');
    assert.ok(!out.includes('<img'));
});

test('escapeHtml: & 被 escape 成 &amp;（且不二次 escape 既有 entity 以外的字元）', () => {
    assert.equal(escapeHtml('A & B'), 'A &amp; B');
});

test('escapeHtml: 雙引號與單引號分別 escape 成 &quot; / &#39;', () => {
    assert.equal(escapeHtml(`"quoted" 'single'`), '&quot;quoted&quot; &#39;single&#39;');
});

test('escapeHtml: null/undefined 回傳空字串，不丟例外', () => {
    assert.equal(escapeHtml(null), '');
    assert.equal(escapeHtml(undefined), '');
});

// ── resolveYearBarColorMode ──────────────────────────────────────────

test('resolveYearBarColorMode: 無焦點 → neutral', () => {
    assert.equal(resolveYearBarColorMode(null), 'neutral');
    assert.equal(resolveYearBarColorMode(undefined), 'neutral');
});

test('resolveYearBarColorMode: 片商焦點仍是中性計數色（不得誤判為女優焦點才有的分類色）', () => {
    assert.equal(
        resolveYearBarColorMode({ period: { type: 'all' }, actress: null, maker: 'SOD' }),
        'neutral',
    );
});

test('resolveYearBarColorMode: 女優焦點 → byMaker', () => {
    assert.equal(
        resolveYearBarColorMode({ period: { type: 'all' }, actress: 'Alice', maker: null }),
        'byMaker',
    );
});

// ── shouldAnimate ────────────────────────────────────────────────────

test('shouldAnimate: 系統未開「減少動態效果」時回傳 true（播放動畫）', () => {
    assert.equal(shouldAnimate(false), true);
});

test('shouldAnimate: 系統開啟「減少動態效果」時回傳 false（不播放動畫）', () => {
    assert.equal(shouldAnimate(true), false);
});

// ── formatRgbaChannels ───────────────────────────────────────────────

test('formatRgbaChannels: a===255 時回傳 rgb()（不帶 alpha）', () => {
    assert.equal(formatRgbaChannels(128, 149, 170, 255), 'rgb(128, 149, 170)');
});

test('formatRgbaChannels: a<255 時回傳 rgba()，alpha 為 a/255', () => {
    assert.equal(
        formatRgbaChannels(10, 20, 30, 128),
        'rgba(10, 20, 30, ' + (128 / 255) + ')',
    );
});

// ── computeDonutStartAngle（TASK-156b-T4）────────────────────────────

test('computeDonutStartAngle: 目標片商存在 → 該扇形中點置於正上方（90°）', () => {
    // values 25+25+50；目標第二塊：sum_before=25, half=12.5 → offset=37.5°
    // startAngle = 90 + 360 * 37.5/100 = 90 + 135 = 225
    const inner = [
        { name: 'A', value: 25 },
        { name: 'B', value: 25 },
        { name: 'C', value: 50 },
    ];
    assert.equal(computeDonutStartAngle(inner, 'B'), 225);
});

test('computeDonutStartAngle: 目標為 null → 回傳預設 90（原位）', () => {
    const inner = [
        { name: 'A', value: 10 },
        { name: 'B', value: 20 },
    ];
    assert.equal(computeDonutStartAngle(inner, null), 90);
});

test('computeDonutStartAngle: 目標不在 inner／total===0 → 回傳預設 90', () => {
    const inner = [
        { name: 'A', value: 10 },
        { name: 'B', value: 20 },
    ];
    assert.equal(computeDonutStartAngle(inner, 'Z'), 90);
    assert.equal(computeDonutStartAngle([], 'A'), 90);
    assert.equal(
        computeDonutStartAngle([{ name: 'A', value: 0 }, { name: 'B', value: 0 }], 'A'),
        90,
    );
});

// ── emptyKeyForCard（TASK-156c-T6／161a-T5a：舊版型別白名單寫法已刪）────────

const ALL_PERIOD = { type: 'all' };
const cRec = (year, actresses, maker) => ({ year, actresses, maker });
const cSel = (over) => ({ period: ALL_PERIOD, actress: null, maker: null, ...over });

test('emptyKeyForCard: count>0 時一律不是 period_empty，即使有女優條件', () => {
    const records = [cRec(2020, ['Alice'], 'SOD')];
    assert.equal(
        emptyKeyForCard(records, cSel({ actress: 'Alice' }), 'maker'),
        'insights.no_data',
    );
});

test('emptyKeyForCard: 無條件時回傳 no_data（沿用既有沒有資料文字）', () => {
    assert.equal(emptyKeyForCard([], cSel(), null), 'insights.no_data');
});

test('emptyKeyForCard: 圓餅在只選片商下不算範圍縮小，回傳 no_data', () => {
    assert.equal(
        emptyKeyForCard([], cSel({ maker: 'SOD' }), 'maker'),
        'insights.no_data',
    );
});

test('emptyKeyForCard: 女優條件且 count===0 時回傳 period_empty', () => {
    const records = [cRec(2020, ['Bob'], 'SOD')];
    assert.equal(
        emptyKeyForCard(records, cSel({ actress: 'Alice' }), 'maker'),
        'insights.period_empty',
    );
});

test('emptyKeyForCard: count 取該卡範圍內的片數，不是整體範圍', () => {
    // A 沒有 S1 的片、S1 有別人（B）的片；2020 年有片
    const records = [
        cRec(2020, ['A'], 'M1'),
        cRec(2021, ['B'], 'S1'),
    ];
    const both = cSel({ actress: 'A', maker: 'S1' });
    // Top 20 類（skip actress）：範圍＝期間∩片商，B 的片在 → 有東西，不是 period_empty
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
    assert.deepEqual(resolveDragResult(2, 6, dragCats), { kind: 'range', from: 2020, to: 2023 });
    assert.deepEqual(resolveDragResult(2, 99, dragCats), { kind: 'range', from: 2020, to: 2023 });
    assert.deepEqual(resolveDragResult(2, -5, dragCats), { kind: 'range', from: 2018, to: 2020 });
});

test('resolveDragResult: 夾限後兩端同欄正規化成單點，不產生 from===to 的範圍', () => {
    assert.deepEqual(resolveDragResult(5, 6, dragCats), { kind: 'point', year: 2023 });
    assert.deepEqual(resolveDragResult(5, 99, dragCats), { kind: 'point', year: 2023 });
});

test('resolveDragResult: 終點算不出來（NaN／null）視為沒移動', () => {
    assert.deepEqual(resolveDragResult(3, NaN, dragCats), { kind: 'point', year: 2021 });
    assert.deepEqual(resolveDragResult(3, null, dragCats), { kind: 'point', year: 2021 });
});
