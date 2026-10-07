import { test } from 'node:test';
import assert from 'node:assert/strict';

const selMod = await import('../selection.js');
const {
    emptySel,
    normalizePeriod,
    periodContainsYear,
    toggleYear,
    toggleActress,
    toggleMaker,
    scopeRecords,
    emptyKey,
    periodLabel,
    suffixLabel,
} = selMod;

function rec(opts = {}) {
    return {
        year: opts.year === undefined ? 2020 : opts.year,
        month: opts.month === undefined ? null : opts.month,
        actresses: opts.actresses === undefined ? ['Alice'] : opts.actresses,
        maker: opts.maker === undefined ? 'SOD' : opts.maker,
        tags: opts.tags === undefined ? [] : opts.tags,
        date: opts.date === undefined ? null : opts.date,
        duration: opts.duration === undefined ? null : opts.duration,
    };
}

function deepProxy(obj) {
    if (obj === null || typeof obj !== 'object') return obj;
    return new Proxy(obj, {
        get(target, prop, receiver) {
            const val = Reflect.get(target, prop, receiver);
            return deepProxy(val);
        },
    });
}

// ── 1. selection: range 含兩端 ─────────────────────────────────────────

test('selection: range 含兩端', () => {
    const p = { type: 'range', from: 2019, to: 2023 };
    assert.equal(periodContainsYear(p, 2019), true);
    assert.equal(periodContainsYear(p, 2023), true);
    assert.equal(periodContainsYear(p, 2021), true);
    assert.equal(periodContainsYear(p, 2018), false);
    assert.equal(periodContainsYear(p, 2024), false);

    const r2018 = rec({ year: 2018 });
    const r2019 = rec({ year: 2019 });
    const r2023 = rec({ year: 2023 });
    const r2024 = rec({ year: 2024 });
    const sel = { period: p, actress: null, maker: null };
    const out = scopeRecords([r2018, r2019, r2023, r2024], sel, null);
    assert.equal(out.length, 2);
    assert.deepEqual(out, [r2019, r2023]);
});

// ── 2. selection: year==null 只在 all 入範圍 ───────────────────────────

test('selection: year==null 只在 all 入範圍', () => {
    const allPeriod = { type: 'all' };
    const yearPeriod = { type: 'year', year: 2020 };
    const rangePeriod = { type: 'range', from: 2019, to: 2023 };

    assert.equal(periodContainsYear(allPeriod, null), true);
    assert.equal(periodContainsYear(yearPeriod, null), false);
    assert.equal(periodContainsYear(rangePeriod, null), false);

    const rNull = rec({ year: null });
    const r2020 = rec({ year: 2020 });
    const records = [rNull, r2020];

    const outAll = scopeRecords(records, { period: allPeriod, actress: null, maker: null }, null);
    assert.equal(outAll.length, 2);

    const outYear = scopeRecords(records, { period: yearPeriod, actress: null, maker: null }, null);
    assert.equal(outYear.length, 1);
    assert.equal(outYear[0], r2020);

    const outRange = scopeRecords(records, { period: rangePeriod, actress: null, maker: null }, null);
    assert.equal(outRange.length, 1);
    assert.equal(outRange[0], r2020);
});

// ── 3. selection: normalizePeriod from==to 變單年 ──────────────────────

test('selection: normalizePeriod from==to 變單年', () => {
    const p = { type: 'range', from: 2020, to: 2020 };
    const norm = normalizePeriod(p);
    assert.deepEqual(norm, { type: 'year', year: 2020 });
});

// ── 4. selection: scopeRecords skipDim=actress 不套女優條件 ────────────

test('selection: scopeRecords skipDim=actress 不套女優條件', () => {
    const rAlice = rec({ actresses: ['Alice'] });
    const rBob = rec({ actresses: ['Bob'] });
    const sel = { period: { type: 'all' }, actress: 'Alice', maker: null };

    const skipped = scopeRecords([rAlice, rBob], sel, 'actress');
    assert.equal(skipped.length, 2);
    assert.deepEqual(skipped, [rAlice, rBob]);

    const notSkipped = scopeRecords([rAlice, rBob], sel, null);
    assert.equal(notSkipped.length, 1);
    assert.equal(notSkipped[0], rAlice);
});

// ── 5. selection: toggleYear 同單年再點清除 ─────────────────────────────

test('selection: toggleYear 同單年再點清除', () => {
    const sel = { period: { type: 'year', year: 2021 }, actress: 'Alice', maker: 'SOD' };
    const toggled = toggleYear(sel, 2021);
    assert.deepEqual(toggled.period, { type: 'all' });
    assert.equal(toggled.actress, 'Alice');
    assert.equal(toggled.maker, 'SOD');
});

// ── 6. selection: toggleMaker 同片商再點清格 ────────────────────────────

test('selection: toggleMaker 同片商再點清格', () => {
    const sel = { period: { type: 'all' }, actress: null, maker: 'SOD' };
    const toggled = toggleMaker(sel, 'SOD');
    assert.equal(toggled.maker, null);
});

// ── 7. selection: periodLabel 輸出全庫／單年／範圍 en dash ─────────────

test('selection: periodLabel 輸出全庫／單年／範圍 en dash', () => {
    assert.equal(periodLabel({ type: 'all' }, '全庫'), '全庫');
    assert.equal(periodLabel({ type: 'year', year: 2023 }, '全庫'), '2023');
    assert.equal(periodLabel({ type: 'range', from: 2019, to: 2023 }, '全庫'), '2019–2023');
    assert.equal(periodLabel({ type: 'range', from: 2019, to: 2023 }, '全庫').charCodeAt(4), 0x2013);
});

// ── 8. selection: scopeRecords 三條件取交集 ────────────────────────────

test('selection: scopeRecords 三條件取交集', () => {
    // 假綠陷阱：fixture 包含「同片商不同寫法」MOODYZ vs Moodyz，且 year、actresses 相同只差 maker；
    // 包含「年份-only」片：year: 2015, month: null, date: null。
    const rTarget = rec({ year: 2021, actresses: ['Alice'], maker: 'Moodyz' });
    const rDiffMakerCase = rec({ year: 2021, actresses: ['Alice'], maker: 'MOODYZ' });
    const rDiffYear = rec({ year: 2020, actresses: ['Alice'], maker: 'Moodyz' });
    const rDiffActress = rec({ year: 2021, actresses: ['Bob'], maker: 'Moodyz' });
    const rYearOnly = rec({ year: 2015, month: null, date: null, actresses: ['Alice'], maker: 'Moodyz' });

    const records = [rTarget, rDiffMakerCase, rDiffYear, rDiffActress, rYearOnly];
    const sel = { period: { type: 'year', year: 2021 }, actress: 'Alice', maker: 'Moodyz' };

    const out = scopeRecords(records, sel, null);
    assert.equal(out.length, 1);
    assert.equal(out[0], rTarget);

    // 假綠陷阱：空條件與 skipDim 時回新陣列，非原參照
    const emptyOut = scopeRecords(records, emptySel(), null);
    assert.notEqual(emptyOut, records);
    assert.deepEqual(emptyOut, records);

    // 年份-only 落在單年 2015 與範圍 2015–2018 時皆可命中
    const selYearOnly = { period: { type: 'year', year: 2015 }, actress: 'Alice', maker: 'Moodyz' };
    const outYearOnly = scopeRecords(records, selYearOnly, null);
    assert.equal(outYearOnly.length, 1);
    assert.equal(outYearOnly[0], rYearOnly);

    const selRange = { period: { type: 'range', from: 2015, to: 2018 }, actress: 'Alice', maker: 'Moodyz' };
    const outRange = scopeRecords(records, selRange, null);
    assert.equal(outRange.length, 1);
    assert.equal(outRange[0], rYearOnly);
});

// ── 9. selection: scopeRecords skipDim=period 不套期間 ─────────────────

test('selection: scopeRecords skipDim=period 不套期間', () => {
    const r2020 = rec({ year: 2020, actresses: ['Alice'] });
    const r2021 = rec({ year: 2021, actresses: ['Alice'] });
    const rBob = rec({ year: 2021, actresses: ['Bob'] });
    const records = [r2020, r2021, rBob];

    const sel = { period: { type: 'year', year: 2021 }, actress: 'Alice', maker: null };
    const skipped = scopeRecords(records, sel, 'period');
    assert.equal(skipped.length, 2);
    assert.deepEqual(skipped, [r2020, r2021]);

    const scoped = scopeRecords(records, sel, null);
    assert.equal(scoped.length, 1);
    assert.equal(scoped[0], r2021);
});

// ── 10. selection: scopeRecords skipDim=maker 不套片商 ──────────────────

test('selection: scopeRecords skipDim=maker 不套片商', () => {
    const rSOD = rec({ actresses: ['Alice'], maker: 'SOD' });
    const rMoodyz = rec({ actresses: ['Alice'], maker: 'Moodyz' });
    const rBobSOD = rec({ actresses: ['Bob'], maker: 'SOD' });
    const records = [rSOD, rMoodyz, rBobSOD];

    const sel = { period: { type: 'all' }, actress: 'Alice', maker: 'SOD' };
    const skipped = scopeRecords(records, sel, 'maker');
    assert.equal(skipped.length, 2);
    assert.deepEqual(skipped, [rSOD, rMoodyz]);

    const scoped = scopeRecords(records, sel, null);
    assert.equal(scoped.length, 1);
    assert.equal(scoped[0], rSOD);
});

// ── 11. selection: toggleYear 範圍換成單年 ──────────────────────────────

test('selection: toggleYear 範圍換成單年', () => {
    const selRange = { period: { type: 'range', from: 2019, to: 2023 }, actress: null, maker: null };
    const t2021 = toggleYear(selRange, 2021);
    assert.deepEqual(t2021.period, { type: 'year', year: 2021 });

    const t2019 = toggleYear(selRange, 2019);
    assert.deepEqual(t2019.period, { type: 'year', year: 2019 });

    const selAll = { period: { type: 'all' }, actress: null, maker: null };
    const tFromAll = toggleYear(selAll, 2020);
    assert.deepEqual(tFromAll.period, { type: 'year', year: 2020 });

    const frozen = Object.freeze({ period: Object.freeze({ type: 'range', from: 2019, to: 2023 }), actress: null, maker: null });
    assert.doesNotThrow(() => {
        const out = toggleYear(frozen, 2020);
        assert.notEqual(out, frozen);
        assert.deepEqual(out.period, { type: 'year', year: 2020 });
    });
});

// ── 12. selection: toggleActress 同女優再點清格 ─────────────────────────

test('selection: toggleActress 同女優再點清格', () => {
    const sel = { period: { type: 'all' }, actress: 'Alice', maker: null };
    const cleared = toggleActress(sel, 'Alice');
    assert.equal(cleared.actress, null);

    const switched = toggleActress(sel, 'Bob');
    assert.equal(switched.actress, 'Bob');

    const frozen = Object.freeze({ period: { type: 'all' }, actress: 'Alice', maker: null });
    assert.doesNotThrow(() => {
        const out = toggleActress(frozen, 'Alice');
        assert.notEqual(out, frozen);
        assert.equal(out.actress, null);
    });
});

// ── 13. selection: normalizePeriod from>to 對調 ─────────────────────────

test('selection: normalizePeriod from>to 對調', () => {
    const norm = normalizePeriod({ type: 'range', from: 2023, to: 2019 });
    assert.deepEqual(norm, { type: 'range', from: 2019, to: 2023 });

    assert.deepEqual(normalizePeriod(null), { type: 'all' });
    assert.deepEqual(normalizePeriod(undefined), { type: 'all' });
    assert.deepEqual(normalizePeriod({ type: 'unknown' }), { type: 'all' });
    assert.deepEqual(normalizePeriod({ type: 'range', from: 2020 }), { type: 'all' });
    assert.deepEqual(normalizePeriod({ type: 'year' }), { type: 'all' });
});

// ── 14. selection: 比對用業務鍵，Proxy 包的 sel 仍正確 ──────────────────

test('selection: 比對用業務鍵，Proxy 包的 sel 仍正確', () => {
    const rawSel = {
        period: { type: 'year', year: 2021 },
        actress: 'Alice',
        maker: 'Moodyz',
    };
    const proxySel = deepProxy(rawSel);

    // 確認巢狀 Proxy 確實生效
    assert.notEqual(proxySel.period, rawSel.period);

    const records = [
        rec({ year: 2021, actresses: ['Alice'], maker: 'Moodyz' }),
        rec({ year: 2020, actresses: ['Alice'], maker: 'Moodyz' }),
    ];

    const outRaw = scopeRecords(records, rawSel, null);
    assert.equal(outRaw.length, 1);
    const outProxy = scopeRecords(records, proxySel, null);
    assert.deepEqual(outProxy, outRaw);

    assert.deepEqual(toggleYear(proxySel, 2021), toggleYear(rawSel, 2021));
    assert.deepEqual(toggleActress(proxySel, 'Alice'), toggleActress(rawSel, 'Alice'));
    assert.deepEqual(toggleMaker(proxySel, 'Moodyz'), toggleMaker(rawSel, 'Moodyz'));
});

// ── 15. selection: emptyKey 依該卡範圍內是否有條件在縮 ─────────────────

test('selection: emptyKey 依該卡範圍內是否有條件在縮', () => {
    assert.equal(emptyKey(emptySel(), null, 5), null);
    assert.equal(emptyKey(emptySel(), 'period', 1), null);

    // count === 0
    assert.equal(emptyKey(emptySel(), null, 0), 'insights.no_data');
    assert.equal(emptyKey(emptySel(), 'period', 0), 'insights.no_data');

    // period 縮
    const selYear = { period: { type: 'year', year: 2021 }, actress: null, maker: null };
    assert.equal(emptyKey(selYear, null, 0), 'insights.period_empty');
    assert.equal(emptyKey(selYear, 'period', 0), 'insights.no_data');
    assert.equal(emptyKey(selYear, 'actress', 0), 'insights.period_empty');

    // actress 縮
    const selActress = { period: { type: 'all' }, actress: 'Alice', maker: null };
    assert.equal(emptyKey(selActress, null, 0), 'insights.period_empty');
    assert.equal(emptyKey(selActress, 'actress', 0), 'insights.no_data');
    assert.equal(emptyKey(selActress, 'period', 0), 'insights.period_empty');

    // maker 縮
    const selMaker = { period: { type: 'all' }, actress: null, maker: 'SOD' };
    assert.equal(emptyKey(selMaker, null, 0), 'insights.period_empty');
    assert.equal(emptyKey(selMaker, 'maker', 0), 'insights.no_data');
    assert.equal(emptyKey(selMaker, 'period', 0), 'insights.period_empty');
});

// ── 16. selection: suffixLabel 只在 suffixDims 有值時加期間 ─────────────

test('selection: suffixLabel 只在 suffixDims 有值時加期間', () => {
    const sel1 = { period: { type: 'year', year: 2021 }, actress: 'Alice', maker: null };
    assert.equal(suffixLabel(sel1, ['actress', 'maker'], '全庫'), ' · 2021');
    assert.equal(suffixLabel(sel1, ['maker'], '全庫'), '');

    const sel2 = { period: { type: 'all' }, actress: 'Alice', maker: null };
    assert.equal(suffixLabel(sel2, ['actress'], '全庫'), ' · 全庫');

    const sel3 = { period: { type: 'range', from: 2019, to: 2023 }, actress: null, maker: 'SOD' };
    assert.equal(suffixLabel(sel3, ['actress', 'maker'], '全庫'), ' · 2019–2023');
    assert.equal(suffixLabel(sel3, ['actress'], '全庫'), '');

    const selNone = { period: { type: 'year', year: 2021 }, actress: null, maker: null };
    assert.equal(suffixLabel(selNone, ['actress', 'maker'], '全庫'), '');
});
