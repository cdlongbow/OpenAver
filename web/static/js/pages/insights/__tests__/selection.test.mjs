import { test } from 'node:test';
import assert from 'node:assert/strict';

const selMod = await import('../selection.js');
const {
    emptySel,
    toggleYear,
    toggleActress,
    toggleMaker,
    toggleGanttCell,
    scopeRecords,
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


// ── 2. selection: year==null 只在 all 入範圍 ───────────────────────────


// ── 4. selection: scopeRecords skipDim=actress 不套女優條件 ────────────


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


// ── 22. selection: toggleGanttCell 任何列都不動 maker（表第 11 列） ─────────────────


