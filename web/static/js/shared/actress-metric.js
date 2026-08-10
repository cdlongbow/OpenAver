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
