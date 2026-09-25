/**
 * aggregate.js — 片庫分析聚合純函式（TASK-156b-T1）
 *
 * 純函式，零 window / Alpine / DOM。
 * 交付：setRecords / getRecords（模組級狀態骨架）＋
 * buildMakerColorSlots / buildMainMakerYearMap（CD-156-3）。
 */

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
