/**
 * aggregate.js — 片庫分析聚合純函式（TASK-156b-T1 / T2）
 *
 * 純函式，零 window / Alpine / DOM。
 * T1：setRecords / getRecords / buildMakerColorSlots / buildMainMakerYearMap
 * T2：periodRecords / scopeRecords / aggregateYears + UNKNOWN_KEY
 */

/** 年份「未知」分類與片商「未知」桶的內部鍵；畫面顯示文字由 charts.js（T3）做 i18n 映射。 */
export const UNKNOWN_KEY = '__unknown__';


export var _records = [];

export function setRecords(records) {
    _records.length = 0;
    for (const item of (records || [])) _records.push(item);
}

export function getRecords() {
    return _records;
}

/**
 * 全庫片商 Top8 色票槽位。回傳 { [makerName]: slotIndex }（0-based，0..7）。
 * 只統計 maker 為非 null／非空字串的紀錄；計數遞減、同計數時名稱字串遞增。
 */
export function buildMakerColorSlots(records) {
    var counts = new Map();
    (records || []).forEach(function (r) {
        var mk = r && r.maker;
        if (mk == null || mk === '') return;
        counts.set(mk, (counts.get(mk) || 0) + 1);
    });
    var named = Array.from(counts.entries());
    named.sort(function (a, b) { return b[1] - a[1] || (a[0] < b[0] ? -1 : 1); });
    var top = named.slice(0, 8);
    var slots = {};
    top.forEach(function (e, i) { slots[e[0]] = i; });
    return slots;
}

/**
 * 主要片商年判定。回傳 { [`${actress}|${year}`]: makerName }。
 * 門檻：該女優該年至少 4 部，且最高具名片商佔比 >= 80%。
 * maker 為 null 的片計入分母，但不能被選為主要片商本身。
 */
export function buildMainMakerYearMap(records) {
    var byActressYear = new Map();
    (records || []).forEach(function (r) {
        if (!r || r.year == null) return;
        var actresses = r.actresses || [];
        var seen = new Set();
        actresses.forEach(function (name) {
            if (seen.has(name)) return;
            seen.add(name);
            if (!byActressYear.has(name)) byActressYear.set(name, new Map());
            var ymap = byActressYear.get(name);
            if (!ymap.has(r.year)) ymap.set(r.year, new Map());
            var mkmap = ymap.get(r.year);
            var mk = r.maker || null;
            mkmap.set(mk, (mkmap.get(mk) || 0) + 1);
        });
    });
    var result = {};
    byActressYear.forEach(function (ymap, name) {
        ymap.forEach(function (mkmap, year) {
            var total = 0;
            mkmap.forEach(function (c) { total += c; });
            var bestMk = null;
            var bestCount = 0;
            mkmap.forEach(function (c, mk) {
                if (mk === null) return;
                if (c > bestCount) {
                    bestCount = c;
                    bestMk = mk;
                }
            });
            if (bestMk && total >= 4 && bestCount / total >= 0.8) {
                result[name + '|' + year] = bestMk;
            }
        });
    });
    return result;
}

/**
 * 依 period 篩選紀錄。
 * {type:'all'} 保留 year===null；{type:'year',year:N} 只留 year===N。
 */
export function periodRecords(records, period) {
    if (period === undefined) period = { type: 'all' };
    var list = records || [];
    if (!period || period.type === 'all') return list.slice();
    if (period.type === 'year') {
        return list.filter(function (r) { return r.year === period.year; });
    }
    return list.slice();
}

/**
 * period 篩選後再依 focus 過濾。focus===null 時等同 periodRecords。
 */
export function scopeRecords(records, period, focus) {
    if (period === undefined) period = { type: 'all' };
    if (focus === undefined) focus = null;
    var base = periodRecords(records, period);
    if (!focus) return base;
    if (focus.type === 'actress') {
        return base.filter(function (r) {
            return (r.actresses || []).includes(focus.value);
        });
    }
    if (focus.type === 'maker') {
        return base.filter(function (r) { return r.maker === focus.value; });
    }
    return base;
}

function _yearRange(base) {
    var years = [];
    var hasNull = false;
    base.forEach(function (r) {
        if (r.year == null) { hasNull = true; return; }
        years.push(r.year);
    });
    if (!years.length) return { years: [], hasNull: hasNull };
    var minYear = Math.min.apply(null, years);
    var maxYear = Math.max.apply(null, years);
    var range = [];
    for (let y = minYear; y <= maxYear; y++) { range.push(y); }
    return { years: range, hasNull: hasNull };
}

function _buildDimmed(categories, period) {
    if (!period || period.type === 'all') {
        return categories.map(function () { return false; });
    }
    var target = String(period.year);
    return categories.map(function (c) { return c !== target; });
}

/**
 * 年份長條資料整形。基底永遠用 scopeRecords(records,{type:'all'},focus)；
 * period 只影響 dimmed，不影響 series[].data 數值。
 */
export function aggregateYears(records, period, focus) {
    if (period === undefined) period = { type: 'all' };
    if (focus === undefined) focus = null;

    const base = scopeRecords(records, { type: 'all' }, focus);

    if (focus && focus.type === 'maker') {
        if (!base.length) return { categories: [], series: [], dimmed: [] };
        var makerRange = _yearRange(base);
        var makerCats = makerRange.years.map(String);
        if (makerRange.hasNull) makerCats = makerCats.concat([UNKNOWN_KEY]);
        var makerCounts = {};
        makerRange.years.forEach(function (y) { makerCounts[y] = 0; });
        var makerUnknown = 0;
        base.forEach(function (r) {
            if (r.year == null) { makerUnknown += 1; return; }
            makerCounts[r.year] = (makerCounts[r.year] || 0) + 1;
        });
        var makerData = makerRange.years.map(function (y) { return makerCounts[y] || 0; });
        if (makerRange.hasNull) makerData = makerData.concat([makerUnknown]);
        return {
            categories: makerCats,
            series: [{ name: focus.value, data: makerData }],
            dimmed: _buildDimmed(makerCats, period),
        };
    }

    if (focus && focus.type === 'actress') {
        if (!base.length) return { categories: [], series: [], dimmed: [] };
        var actRange = _yearRange(base);
        var actCats = actRange.years.map(String);
        if (actRange.hasNull) actCats = actCats.concat([UNKNOWN_KEY]);

        var byYear = {};
        actRange.years.forEach(function (y) { byYear[y] = {}; });
        var makerTotals = {};
        var unknownByMaker = {};
        base.forEach(function (r) {
            var mk = r.maker || UNKNOWN_KEY;
            makerTotals[mk] = (makerTotals[mk] || 0) + 1;
            if (r.year == null) {
                unknownByMaker[mk] = (unknownByMaker[mk] || 0) + 1;
                return;
            }
            if (!byYear[r.year]) byYear[r.year] = {};
            byYear[r.year][mk] = (byYear[r.year][mk] || 0) + 1;
        });
        var makers = Object.keys(makerTotals);
        makers.sort(function (a, b) {
            return makerTotals[b] - makerTotals[a] || (a < b ? -1 : 1);
        });
        var actSeries = makers.map(function (mk) {
            var data = actRange.years.map(function (y) {
                return (byYear[y] && byYear[y][mk]) || 0;
            });
            if (actRange.hasNull) data = data.concat([unknownByMaker[mk] || 0]);
            return { name: mk, data: data };
        });
        return {
            categories: actCats,
            series: actSeries,
            dimmed: _buildDimmed(actCats, period),
        };
    }

    // 無焦點：全庫 min..max + 尾端固定 UNKNOWN_KEY
    var noneRange = _yearRange(base);
    var noneCats = noneRange.years.map(String).concat([UNKNOWN_KEY]);
    var noneCounts = {};
    noneRange.years.forEach(function (y) { noneCounts[y] = 0; });
    var noneUnknown = 0;
    base.forEach(function (r) {
        if (r.year == null) { noneUnknown += 1; return; }
        noneCounts[r.year] = (noneCounts[r.year] || 0) + 1;
    });
    var noneData = noneRange.years.map(function (y) { return noneCounts[y] || 0; });
    noneData = noneData.concat([noneUnknown]);
    return {
        categories: noneCats,
        series: [{ name: null, data: noneData }],
        dimmed: _buildDimmed(noneCats, period),
    };
}
