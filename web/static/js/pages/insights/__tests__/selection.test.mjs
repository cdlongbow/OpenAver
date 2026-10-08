import { test } from 'node:test';
import assert from 'node:assert/strict';

const selMod = await import('../selection.js');
const {
    emptySel,
    periodContainsYear,
    toggleYear,
    toggleActress,
    toggleMaker,
    toggleGanttCell,
    scopeRecords,
    emptyKey,
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

// ── 4. selection: scopeRecords skipDim=actress 不套女優條件 ────────────

test('selection: scopeRecords skipDim=actress 不套女優條件', () => {
    // 表驅動：skipDim 跳過該維條件（三維各一列），不跳過時三條件照套
    const rAlice = rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' });
    const rAlice21 = rec({ year: 2021, actresses: ['Alice'], maker: 'SOD' });
    const rBob21 = rec({ year: 2021, actresses: ['Bob'], maker: 'SOD' });
    const rAliceMoodyz = rec({ year: 2021, actresses: ['Alice'], maker: 'Moodyz' });
    const records = [rAlice, rAlice21, rBob21, rAliceMoodyz];
    const sel = { period: { type: 'year', year: 2021 }, actress: 'Alice', maker: 'SOD' };

    const cases = [
        { skip: 'actress', exp: [rAlice21, rBob21] },
        { skip: 'period', exp: [rAlice, rAlice21] },
        { skip: 'maker', exp: [rAlice21, rAliceMoodyz] },
        { skip: null, exp: [rAlice21] },
    ];
    for (const c of cases) {
        const out = scopeRecords(records, sel, c.skip);
        assert.equal(out.length, c.exp.length, String(c.skip));
        assert.deepEqual(out, c.exp, String(c.skip));
    }
});

// ── 5. selection: toggleYear 同單年再點清除 ─────────────────────────────

test('selection: toggleYear 同單年再點清除', () => {
    // 再點同一個值＝取消，其他條件保留（年／片商／女優各一列）
    const retap = [
        { fn: toggleYear, arg: 2021, sel: { period: { type: 'year', year: 2021 }, actress: 'Alice', maker: 'SOD' },
          exp: { period: { type: 'all' }, actress: 'Alice', maker: 'SOD' } },
        { fn: toggleMaker, arg: 'SOD', sel: { period: { type: 'all' }, actress: null, maker: 'SOD' },
          exp: { period: { type: 'all' }, actress: null, maker: null } },
        { fn: toggleActress, arg: 'Alice', sel: { period: { type: 'all' }, actress: 'Alice', maker: null },
          exp: { period: { type: 'all' }, actress: null, maker: null } },
    ];
    for (const c of retap) {
        assert.deepEqual(c.fn(c.sel, c.arg), c.exp);
    }

    // 範圍換成單年（兩端與中間）、全庫選年
    const selRange = { period: { type: 'range', from: 2019, to: 2023 }, actress: null, maker: null };
    assert.deepEqual(toggleYear(selRange, 2021).period, { type: 'year', year: 2021 });
    assert.deepEqual(toggleYear(selRange, 2019).period, { type: 'year', year: 2019 });
    const selAll = { period: { type: 'all' }, actress: null, maker: null };
    assert.deepEqual(toggleYear(selAll, 2020).period, { type: 'year', year: 2020 });

    // 點別的女優＝換人
    const selAlice = { period: { type: 'all' }, actress: 'Alice', maker: null };
    assert.equal(toggleActress(selAlice, 'Bob').actress, 'Bob');

    // 凍結的輸入不 throw、回傳新物件
    const frozenRange = Object.freeze({ period: Object.freeze({ type: 'range', from: 2019, to: 2023 }), actress: null, maker: null });
    assert.doesNotThrow(() => {
        const out = toggleYear(frozenRange, 2020);
        assert.notEqual(out, frozenRange);
        assert.deepEqual(out.period, { type: 'year', year: 2020 });
    });
    const frozenAlice = Object.freeze({ period: { type: 'all' }, actress: 'Alice', maker: null });
    assert.doesNotThrow(() => {
        const out = toggleActress(frozenAlice, 'Alice');
        assert.notEqual(out, frozenAlice);
        assert.equal(out.actress, null);
    });
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

// ── 17. selection: toggleGanttCell 有片格把女優與年份一起設成單一年（表第 1–5、7 列） ──

test('selection: toggleGanttCell 有片格把女優與年份一起設成單一年（表第 1–5、7 列）', () => {
    const cases = [
        // 1: null／all
        { sel: { actress: null, period: { type: 'all' } }, name: 'A', year: 2021, expActress: 'A', expPeriod: { type: 'year', year: 2021 } },
        // 2: B／all
        { sel: { actress: 'B', period: { type: 'all' } }, name: 'A', year: 2021, expActress: 'A', expPeriod: { type: 'year', year: 2021 } },
        // 3: A／all
        { sel: { actress: 'A', period: { type: 'all' } }, name: 'A', year: 2021, expActress: 'A', expPeriod: { type: 'year', year: 2021 } },
        // 4: A／range 2019–2023
        { sel: { actress: 'A', period: { type: 'range', from: 2019, to: 2023 } }, name: 'A', year: 2022, expActress: 'A', expPeriod: { type: 'year', year: 2022 } },
        // 5: A／range 2019–2023
        { sel: { actress: 'A', period: { type: 'range', from: 2019, to: 2023 } }, name: 'A', year: 2015, expActress: 'A', expPeriod: { type: 'year', year: 2015 } },
        // 7: A／year 2020
        { sel: { actress: 'A', period: { type: 'year', year: 2020 } }, name: 'A', year: 2021, expActress: 'A', expPeriod: { type: 'year', year: 2021 } },
    ];
    for (const c of cases) {
        const out = toggleGanttCell(c.sel, c.name, c.year);
        assert.equal(out.actress, c.expActress);
        assert.deepEqual(out.period, c.expPeriod);
    }
});

// ── 18. selection: toggleGanttCell 再點同一格只取消年份、女優保留（表第 6 列） ──────

test('selection: toggleGanttCell 再點同一格只取消年份、女優保留（表第 6 列）', () => {
    const cases = [
        // 6: 再點同一格 → 取消年份、女優保留
        { sel: { actress: 'A', period: { type: 'year', year: 2021 } }, expActress: 'A', expPeriod: { type: 'all' } },
        // 8: 年份同但女優不是她 → 換成她、年份不取消
        { sel: { actress: 'B', period: { type: 'year', year: 2021 } }, expActress: 'A', expPeriod: { type: 'year', year: 2021 } },
    ];
    for (const c of cases) {
        const out = toggleGanttCell(c.sel, 'A', 2021);
        assert.equal(out.actress, c.expActress);
        assert.deepEqual(out.period, c.expPeriod);
    }
});

// ── 20. selection: toggleGanttCell year 為 null 且尚未選她時只選女優、年份不動（表第 9、10b 列） ──

test('selection: toggleGanttCell year 為 null 且尚未選她時只選女優、年份不動（表第 9、10b 列）', () => {
    const cases = [
        // 9: 未選任何女優
        { sel: { actress: null, period: { type: 'year', year: 2019 } } },
        // 10b: 選的是 B
        { sel: { actress: 'B', period: { type: 'year', year: 2019 } } },
        // 10: 她已被選中 → 永遠不取消女優
        { sel: { actress: 'A', period: { type: 'year', year: 2019 } } },
    ];
    for (const c of cases) {
        const out = toggleGanttCell(c.sel, 'A', null);
        assert.notEqual(out, c.sel);
        assert.equal(out.actress, 'A');
        assert.deepEqual(out.period, { type: 'year', year: 2019 });
    }
});

// ── 22. selection: toggleGanttCell 任何列都不動 maker（表第 11 列） ─────────────────

test('selection: toggleGanttCell 任何列都不動 maker（表第 11 列）', () => {
    const cases = [
        // 1
        { sel: { actress: null, period: { type: 'all' }, maker: 'M' }, name: 'A', year: 2021, expActress: 'A', expPeriod: { type: 'year', year: 2021 } },
        // 2
        { sel: { actress: 'B', period: { type: 'all' }, maker: 'M' }, name: 'A', year: 2021, expActress: 'A', expPeriod: { type: 'year', year: 2021 } },
        // 3
        { sel: { actress: 'A', period: { type: 'all' }, maker: 'M' }, name: 'A', year: 2021, expActress: 'A', expPeriod: { type: 'year', year: 2021 } },
        // 4
        { sel: { actress: 'A', period: { type: 'range', from: 2019, to: 2023 }, maker: 'M' }, name: 'A', year: 2022, expActress: 'A', expPeriod: { type: 'year', year: 2022 } },
        // 5
        { sel: { actress: 'A', period: { type: 'range', from: 2019, to: 2023 }, maker: 'M' }, name: 'A', year: 2015, expActress: 'A', expPeriod: { type: 'year', year: 2015 } },
        // 6
        { sel: { actress: 'A', period: { type: 'year', year: 2021 }, maker: 'M' }, name: 'A', year: 2021, expActress: 'A', expPeriod: { type: 'all' } },
        // 7
        { sel: { actress: 'A', period: { type: 'year', year: 2020 }, maker: 'M' }, name: 'A', year: 2021, expActress: 'A', expPeriod: { type: 'year', year: 2021 } },
        // 8
        { sel: { actress: 'B', period: { type: 'year', year: 2021 }, maker: 'M' }, name: 'A', year: 2021, expActress: 'A', expPeriod: { type: 'year', year: 2021 } },
        // 9
        { sel: { actress: null, period: { type: 'year', year: 2019 }, maker: 'M' }, name: 'A', year: null, expActress: 'A', expPeriod: { type: 'year', year: 2019 } },
        // 10
        { sel: { actress: 'A', period: { type: 'year', year: 2019 }, maker: 'M' }, name: 'A', year: null, expActress: 'A', expPeriod: { type: 'year', year: 2019 } },
        // 10b
        { sel: { actress: 'B', period: { type: 'year', year: 2019 }, maker: 'M' }, name: 'A', year: null, expActress: 'A', expPeriod: { type: 'year', year: 2019 } },
    ];
    for (const c of cases) {
        const out = toggleGanttCell(c.sel, c.name, c.year);
        assert.equal(out.maker, 'M');
        assert.equal(out.actress, c.expActress);
        assert.deepEqual(out.period, c.expPeriod);
    }
});

