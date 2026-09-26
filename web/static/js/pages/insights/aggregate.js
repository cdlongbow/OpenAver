/**
 * aggregate.js — 片庫分析聚合純函式（TASK-156b-T1 / T2 / T4）
 *
 * 純函式，零 window / Alpine / DOM。
 * T1：setRecords / getRecords / buildMakerColorSlots / buildMainMakerYearMap
 * T2：periodRecords / scopeRecords / aggregateYears + UNKNOWN_KEY
 * T4：buildMakerDonutData / classifyRecordAgainstMainMaker + REST_KEY
 * T5：buildActressTop20
 * T6：aggregateTags
 * T156c-T1：aggregateAge
 * T156c-T3：buildGanttRows / ganttYearAxis / buildGanttYearCells /
 *           ganttAgeEligibility / ganttAgeAxis / buildGanttAgeCells
 */

import { computeActressAgeForVideo } from '../../shared/actress-release-age.js';

/** 年份「未知」分類與片商「未知」桶的內部鍵；畫面顯示文字由 charts.js（T3）做 i18n 映射。 */
export const UNKNOWN_KEY = '__unknown__';

/** 具名片商排名太後面被歸併的內部鍵（與 UNKNOWN_KEY 語意不同，不可混用）。 */
export const REST_KEY = '__rest__';


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
    // P3-2：base 真的一筆都沒有時不得只剩單一 UNKNOWN_KEY 空格——比照上面 maker/actress
    // 焦點分支已有的早退寫法，讓呼叫端的「沒有資料」分支正確接手。
    if (!base.length) return { categories: [], series: [], dimmed: [] };
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

/**
 * 片級分類：主要片商作品 / 其他作品 / 無法判定。
 * 呼叫端保證 record.maker 已知且等於當前展開的具名片商。
 */
export function classifyRecordAgainstMainMaker(record, mainMakerYearMap) {
    var actresses = (record && record.actresses) || [];
    if (record.year == null || actresses.length === 0) return 'undetermined';
    var isMain = actresses.some(function (n) {
        return mainMakerYearMap[n + '|' + record.year] === record.maker;
    });
    return isMain ? 'main' : 'other';
}

/**
 * 片商雙層圓餅資料。對傳入的 records 局部排名取前 8 名具名；
 * 第 9 名以後併入 REST_KEY；maker null/空字串併入 UNKNOWN_KEY。
 * 不呼叫 getRecords()／buildMakerColorSlots()。
 */
export function buildMakerDonutData(records, mainMakerYearMap) {
    var list = records || [];
    var total = list.length;
    var counts = new Map();
    var unknownCount = 0;
    list.forEach(function (r) {
        var mk = r && r.maker;
        if (mk == null || mk === '') {
            unknownCount += 1;
            return;
        }
        counts.set(mk, (counts.get(mk) || 0) + 1);
    });
    var named = Array.from(counts.entries());
    named.sort(function (a, b) { return b[1] - a[1] || (a[0] < b[0] ? -1 : 1); });
    var top = named.slice(0, 8);
    var restCount = named.slice(8).reduce(function (s, e) { return s + e[1]; }, 0);

    var inner = top.map(function (e) {
        return { name: e[0], value: e[1], kind: 'named' };
    });
    inner.push({ name: REST_KEY, value: restCount, kind: 'rest' });
    inner.push({ name: UNKNOWN_KEY, value: unknownCount, kind: 'unknown' });

    var outer = [];
    var map = mainMakerYearMap || {};
    top.forEach(function (e) {
        var mkName = e[0];
        var cnt = { main: 0, other: 0, undetermined: 0 };
        list.forEach(function (r) {
            if (!r || r.maker !== mkName) return;
            var cls = classifyRecordAgainstMainMaker(r, map);
            cnt[cls] += 1;
        });
        if (cnt.main) {
            outer.push({ maker: mkName, value: cnt.main, kind: 'main' });
        }
        if (cnt.other) {
            outer.push({ maker: mkName, value: cnt.other, kind: 'other' });
        }
        if (cnt.undetermined) {
            outer.push({ maker: mkName, value: cnt.undetermined, kind: 'undetermined' });
        }
    });
    if (restCount) {
        outer.push({ maker: REST_KEY, value: restCount, kind: 'rest' });
    }
    if (unknownCount) {
        outer.push({ maker: UNKNOWN_KEY, value: unknownCount, kind: 'unknown' });
    }

    return { total: total, inner: inner, outer: outer };
}

/**
 * 女優 Top20 排名。對傳入的 records 展開 actresses 計數；
 * 排序：count 遞減 → monthCount 遞減 → name 遞增。
 * monthCount ＝相異非 null 的 record.month 個數。
 * 若 focus 為女優且她的真實 rank > 20，附加她那一列。
 * 不呼叫 getRecords()。
 */
export function buildActressTop20(records, focus) {
    var counts = new Map();
    (records || []).forEach(function (r) {
        var names = (r && r.actresses) || [];
        var seenInRecord = new Set();
        names.forEach(function (name) {
            if (!name || seenInRecord.has(name)) return;
            seenInRecord.add(name);
            var entry = counts.get(name);
            if (!entry) {
                entry = { name: name, count: 0, months: new Set() };
                counts.set(name, entry);
            }
            entry.count += 1;
            if (r.month != null && r.month !== '') {
                entry.months.add(r.month);
            }
        });
    });

    var all = Array.from(counts.values()).map(function (e) {
        return {
            name: e.name,
            count: e.count,
            monthCount: e.months.size,
        };
    });
    all.sort(function (a, b) {
        return b.count - a.count || b.monthCount - a.monthCount || (a.name < b.name ? -1 : 1);
    });
    all.forEach(function (row, i) {
        row.rank = i + 1;
    });

    var rows = all.slice(0, 20);
    var herRank = 0;
    var herRow = null;
    if (focus && focus.type === 'actress' && focus.value) {
        for (var i = 0; i < all.length; i++) {
            if (all[i].name === focus.value) {
                herRank = all[i].rank;
                herRow = all[i];
                break;
            }
        }
    }
    if (focus && focus.type === 'actress' && herRank > 20) { rows.push(herRow); }
    return { rows: rows };
}

/**
 * 標籤矩形樹圖資料整形。
 * >50% 涵蓋率標籤進 pulled（上方一行文字）；其餘取前 40 進 rest（樹圖面積）。
 * 標籤字面原樣計數（同片用 Set 去重）；不做別名／大小寫合併。
 * total===0 時 pulled/rest 皆空、coverage=0，不除以零。
 *
 * @param {Array<{tags?: string[]}>} records
 * @returns {{
 *   total: number,
 *   withTagCount: number,
 *   coverage: number,
 *   pulled: Array<[string, number]>,
 *   rest: Array<[string, number]>,
 * }}
 */
export function aggregateTags(records) {
    var list = records || [];
    var total = list.length;
    var map = new Map();
    list.forEach(function (r) {
        var seen = new Set();
        ((r && r.tags) || []).forEach(function (t) {
            if (seen.has(t)) return;
            seen.add(t);
            map.set(t, (map.get(t) || 0) + 1);
        });
    });
    var named = Array.from(map.entries()).sort(function (a, b) {
        return b[1] - a[1] || (a[0] < b[0] ? -1 : 1);
    });
    var pulled = named.filter(function (e) { return total && (e[1] / total) > 0.5; });
    var rest = named.filter(function (e) { return !(total && (e[1] / total) > 0.5); });
    var top = rest.slice(0, 40);
    var withTagCount = list.filter(function (r) {
        return r && r.tags && r.tags.length;
    }).length;
    var coverage = total ? withTagCount / total : 0;
    return {
        total: total,
        withTagCount: withTagCount,
        coverage: coverage,
        pulled: pulled,
        rest: top,
    };
}

/**
 * 收藏女優發行當天年齡分布。
 * 單位＝（片, 收藏女優）配對；同片多位各算一筆。女優焦點時只算她本人。
 * 年齡一律走 computeActressAgeForVideo（含 239 合輯規則與日曆合法性）。
 * 涵蓋率＝至少一配對算出年齡的片數 ÷ scope 片數；中位數＝配對中位數（偶數取平均）。
 * 直方圖 1 歲一格，範圍＝有資料的最小～最大連續。
 *
 * @param {Array<{actresses?: string[], date?: string|null, duration?: number|null}>} records
 * @param {Record<string, {birth?: string|null}>|null|undefined} favorites
 * @param {{type: string, value: string}|null|undefined} focus
 * @returns {{
 *   total: number,
 *   recordsWithAge: number,
 *   coverage: number,
 *   pairCount: number,
 *   median: number|null,
 *   histogram: Record<number, number>,
 *   categories: string[],
 *   counts: number[],
 * }}
 */
export function aggregateAge(records, favorites, focus) {
    var list = records || [];
    var total = list.length;
    var favs = favorites || {};
    var focusActress = focus && focus.type === 'actress' ? focus.value : null;
    var ages = [];
    var recordsWithAge = 0;

    list.forEach(function (r) {
        var recordHasAge = false;
        var names = focusActress
            ? [focusActress]
            : ((r && r.actresses) || []);
        var seen = new Set();
        names.forEach(function (name) {
            if (seen.has(name)) return;
            seen.add(name);
            if (
                focusActress &&
                (!(r && r.actresses) || r.actresses.indexOf(name) === -1)
            ) {
                return;
            }
            var fav = favs[name];
            if (!fav || !fav.birth) return;
            var age = computeActressAgeForVideo({
                birth: fav.birth,
                releaseDate: r && r.date,
                durationMinutes: r && r.duration,
            });
            if (age != null) {
                ages.push(age);
                recordHasAge = true;
            }
        });
        if (recordHasAge) recordsWithAge += 1;
    });

    var pairCount = ages.length;
    var coverage = total ? recordsWithAge / total : 0;

    var median = null;
    if (ages.length) {
        var sorted = ages.slice().sort(function (a, b) { return a - b; });
        var mid = Math.floor(sorted.length / 2);
        median = sorted.length % 2
            ? sorted[mid]
            : (sorted[mid - 1] + sorted[mid]) / 2;
    }

    var histogram = {};
    var categories = [];
    var counts = [];
    if (ages.length) {
        var minA = ages[0];
        var maxA = ages[0];
        for (var i = 1; i < ages.length; i++) {
            if (ages[i] < minA) minA = ages[i];
            if (ages[i] > maxA) maxA = ages[i];
        }
        for (var a = minA; a <= maxA; a++) {
            histogram[a] = 0;
        }
        ages.forEach(function (age) {
            histogram[age] += 1;
        });
        for (var a2 = minA; a2 <= maxA; a2++) {
            categories.push(String(a2));
            counts.push(histogram[a2]);
        }
    }

    return {
        total: total,
        recordsWithAge: recordsWithAge,
        coverage: coverage,
        pairCount: pairCount,
        median: median,
        histogram: histogram,
        categories: categories,
        counts: counts,
    };
}

/**
 * 欄位前 8 名統計（導演／系列）。
 * 回傳 { total, withValueCount, coverage, top: [[name, count], ...] }。
 * record[field] 為 null 或空字串不進 top 排名但計入 total。
 * @param {object[]} records
 * @param {string} field
 */
export function aggregateFieldTop8(records, field) {
    var counts = new Map();
    var total = 0;
    var withValueCount = 0;
    (records || []).forEach(function (r) {
        if (!r) return;
        total++;
        var v = r[field];
        if (v == null || v === '') return;
        withValueCount++;
        counts.set(v, (counts.get(v) || 0) + 1);
    });
    var named = Array.from(counts.entries());
    named.sort(function (a, b) {
        return b[1] - a[1] || (a[0] < b[0] ? -1 : 1);
    });
    var top = named.slice(0, 8);
    var coverage = total ? withValueCount / total : 0;
    return {
        total: total,
        withValueCount: withValueCount,
        coverage: coverage,
        top: top,
    };
}

/**
 * 主要片商年表列選取。
 * 候選＝mainMakerYearMap 裡至少一組 (y, mk) 同時符合 period／maker 焦點（交集）；
 * 女優焦點忽略 focus，只看 period。排序＝範圍內 classify==='main' 片數遞減、name 遞增，取 25；
 * 女優焦點且她不在前 25、但 records 有她的片 → 附加末列。
 * 不呼叫 getRecords()。
 */
export function buildGanttRows(records, mainMakerYearMap, period, focus) {
    if (period === undefined) period = { type: 'all' };
    if (focus === undefined) focus = null;
    var map = mainMakerYearMap || {};
    var yearFocus = period && period.type === 'year' ? period.year : null;
    var makerFocus = focus && focus.type === 'maker' ? focus.value : null;

    var candidateSet = new Set();
    Object.keys(map).forEach(function (key) {
        var sep = key.lastIndexOf('|');
        if (sep < 0) return;
        var name = key.slice(0, sep);
        var y = Number(key.slice(sep + 1));
        var e = { year: y, maker: map[key] };
        if (yearFocus != null && e.year !== yearFocus) return;
        if (makerFocus != null && e.maker !== makerFocus) return;
        candidateSet.add(name);
    });

    var scoped;
    if (focus && focus.type === 'maker') {
        scoped = scopeRecords(records, period, focus);
    } else {
        scoped = periodRecords(records, period);
    }

    function mainCountFor(name) {
        var c = 0;
        scoped.forEach(function (r) {
            if (!r || (r.actresses || []).indexOf(name) === -1) return;
            if (classifyRecordAgainstMainMaker(r, map) === 'main') c += 1;
        });
        return c;
    }

    var rows = Array.from(candidateSet).map(function (name) {
        return { name: name, mainCount: mainCountFor(name) };
    });
    rows.sort(function (a, b) {
        return b.mainCount - a.mainCount || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    });
    var top = rows.slice(0, 25);

    if (focus && focus.type === 'actress' && focus.value) {
        var herName = focus.value;
        var already = top.some(function (r) { return r.name === herName; });
        if (!already) {
            var hasFilm = (records || []).some(function (r) {
                return r && (r.actresses || []).indexOf(herName) !== -1;
            });
            if (hasFilm) {
                top.push({
                    name: herName,
                    mainCount: mainCountFor(herName),
                    appended: true,
                });
            }
        }
    }
    return top;
}

/**
 * 年表年份橫軸：全庫有年份紀錄的 min..max 連續，忽略 null／period／focus。
 * 不呼叫 getRecords()。
 */
export function ganttYearAxis(records) {
    var years = [];
    (records || []).forEach(function (r) {
        if (r && r.year != null) years.push(r.year);
    });
    if (!years.length) return [];
    var minY = Math.min.apply(null, years);
    var maxY = Math.max.apply(null, years);
    var range = [];
    for (var y = minY; y <= maxY; y++) range.push(y);
    return range;
}

/**
 * 年表年份格子。empty＝無片；main＝該年是她的主要片商年；否則 dot。
 * 不呼叫 getRecords()。
 */
export function buildGanttYearCells(name, records, mainMakerYearMap, yearAxis) {
    var map = mainMakerYearMap || {};
    var byYear = new Map();
    (records || []).forEach(function (r) {
        if (!r || r.year == null) return;
        if ((r.actresses || []).indexOf(name) === -1) return;
        if (!byYear.has(r.year)) byYear.set(r.year, []);
        byYear.get(r.year).push(r);
    });
    return (yearAxis || []).map(function (year) {
        var films = byYear.get(year) || [];
        if (!films.length) {
            return { year: year, state: 'empty', maker: null, filmCount: 0, makerCount: 0 };
        }
        var mainMk = map[name + '|' + year];
        if (mainMk) {
            var makerCount = 0;
            films.forEach(function (r) {
                if (r.maker === mainMk) makerCount += 1;
            });
            return {
                year: year,
                state: 'main',
                maker: mainMk,
                filmCount: films.length,
                makerCount: makerCount,
            };
        }
        return { year: year, state: 'dot', maker: null, filmCount: films.length, makerCount: 0 };
    });
}

/**
 * 年齡模式資格：favorites[name] 不存在或無 birth → 略過；有 birth 即合格
 * （即使所有片算不出年齡也不算略過）。不呼叫 getRecords()。
 */
export function ganttAgeEligibility(names, records, favorites) {
    var favs = favorites || {};
    var eligibleNames = [];
    var skipped = 0;
    (names || []).forEach(function (name) {
        var fav = favs[name];
        if (!fav || !fav.birth) { skipped += 1; return; }
        eligibleNames.push(name);
    });
    return { eligibleNames: eligibleNames, skippedCount: skipped };
}

/**
 * 年齡模式橫軸：顯示中各列年齡的 min..max 連續。
 * 年齡一律走 computeActressAgeForVideo。不呼叫 getRecords()。
 */
export function ganttAgeAxis(eligibleNames, records, favorites) {
    var favs = favorites || {};
    var nameSet = new Set(eligibleNames || []);
    var ages = [];
    (records || []).forEach(function (r) {
        if (!r) return;
        var seen = new Set();
        (r.actresses || []).forEach(function (name) {
            if (!nameSet.has(name) || seen.has(name)) return;
            seen.add(name);
            var fav = favs[name];
            if (!fav || !fav.birth) return;
            var age = computeActressAgeForVideo({
                birth: fav.birth,
                releaseDate: r.date,
                durationMinutes: r.duration,
            });
            if (age != null) ages.push(age);
        });
    });
    if (!ages.length) return [];
    var minA = Math.min.apply(null, ages);
    var maxA = Math.max.apply(null, ages);
    var range = [];
    for (var a = minA; a <= maxA; a++) range.push(a);
    return range;
}

/**
 * 年表年齡格子。某歲有片且至少一部落在她自己的主要片商年且片商相同 → main；
 * 有片否則 → dot；無片 → empty。不呼叫 getRecords()。
 */
export function buildGanttAgeCells(name, records, favorites, mainMakerYearMap, ageAxis) {
    var map = mainMakerYearMap || {};
    var favs = favorites || {};
    var fav = favs[name];
    var byAge = new Map();
    if (fav && fav.birth) {
        (records || []).forEach(function (r) {
            if (!r || (r.actresses || []).indexOf(name) === -1) return;
            var age = computeActressAgeForVideo({
                birth: fav.birth,
                releaseDate: r.date,
                durationMinutes: r.duration,
            });
            if (age == null) return;
            if (!byAge.has(age)) byAge.set(age, []);
            byAge.get(age).push(r);
        });
    }
    return (ageAxis || []).map(function (age) {
        var films = byAge.get(age) || [];
        if (!films.length) {
            return { age: age, state: 'empty', maker: null, filmCount: 0, makerCount: 0 };
        }
        var mainMk = null;
        films.forEach(function (r) {
            if (mainMk) return;
            if (r.year == null) return;
            var mk = map[name + '|' + r.year];
            if (mk && mk === r.maker) mainMk = mk;
        });
        if (mainMk) {
            var makerCount = 0;
            films.forEach(function (r) {
                if (r.maker === mainMk) makerCount += 1;
            });
            return {
                age: age,
                state: 'main',
                maker: mainMk,
                filmCount: films.length,
                makerCount: makerCount,
            };
        }
        return { age: age, state: 'dot', maker: null, filmCount: films.length, makerCount: 0 };
    });
}
