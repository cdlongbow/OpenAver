/**
 * actress-pill-filter.js — 女優數值 pill 比對層（116a-T2）。
 *
 * 純函式，無 Alpine 依賴。取值走 actress-metric.js（CD-116a-1），
 * 不 import pill-filter.js（CD-116a-3 結構性防誤用）。
 */

import { actressAgeValue, actressHeightValue, actressCupValue } from './actress-metric.js';

var EXTRACTORS = { age: actressAgeValue, height: actressHeightValue, cup: actressCupValue };
var FIELD_NAME = { age: 'age', height: 'height', cup: 'cup' };

export function buildActressPillPredicate(actressPills) {
    if (!actressPills || actressPills.length === 0) return function () { return true; };
    var matchers = actressPills.map(_buildOne);
    return function (actress) { return matchers.every(function (m) { return m(actress); }); };
}

function _buildOne(pill) {
    // hasOwnProperty 查表（比照 115 pill-filter.js 的 alias 查表）：裸 EXTRACTORS[dim] 會讓
    // Object.prototype 的 key 漏進來——dim='toString' 取到函式、通過 !extractor 檢查、
    // 最後 predicate 對每一位女優回 true（fail-open，正好與本模組的契約相反）。
    if (!Object.prototype.hasOwnProperty.call(EXTRACTORS, pill.dim)) return function () { return false; };
    var extractor = EXTRACTORS[pill.dim];
    if (!extractor || pill.op !== '=') return function () { return false; };  // fail-closed：未知維度／116a 唯一合法 op 以外一律不符合
    var wrapper = {}; wrapper[FIELD_NAME[pill.dim]] = pill.value;
    var pillValue = extractor(wrapper);
    if (pillValue == null) return function () { return false; };  // pill 自身值都解不出來 → 沒有人符合（防禦性，理論上不會發生）
    return function (actress) {
        var actressValue = extractor(actress);
        return actressValue != null && actressValue === pillValue;  // spec §4.3 第 2 條：取不到值一律不符合
    };
}
