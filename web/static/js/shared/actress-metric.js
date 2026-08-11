/**
 * actress-metric.js — 女優數值取值單一所有者（116a-T1）。
 *
 * 排序（state-actress.js）與篩選（actress-pill-filter.js）共用同一組 extractor，
 * 避免兩份取值邏輯漂移（CD-116a-1）。
 * 零 import、零 Alpine 依賴。
 */

export var CUP_RANK = { A:1, B:2, C:3, D:4, E:5, F:6, G:7, H:8, I:9, J:10, K:11 };

export function actressAgeValue(a) {
    return a.age != null ? Number(a.age) : null;
}

export function actressHeightValue(a) {
    var h = parseInt(a.height);
    return isNaN(h) ? null : h;
}

/** 沿用 || 非 ??：rank 表 1–11 恆 truthy，邊界永不觸發（CD-116a-1b）。 */
export function actressCupValue(a) {
    return CUP_RANK[a.cup] || null;
}

/**
 * actressMetricRange(list, extractor) — 116c-T2（CD-116c-6）。
 *
 * 參數是 extractor 函式本身，不是 dim 字串——避免在本模組再擺一張
 * { age, height, cup } 表（那張表的所有者是 actress-pill-filter.js）。
 *
 * list 空、或該維度全部取不到值 → null。純函式、零 Alpine 依賴。
 */
export function actressMetricRange(list, extractor) {
    var min = null;
    var max = null;
    for (var i = 0; i < list.length; i++) {
        var v = extractor(list[i]);
        if (v == null) continue;
        if (min == null || v < min) min = v;
        if (max == null || v > max) max = v;
    }
    return min == null ? null : { min: min, max: max };
}
