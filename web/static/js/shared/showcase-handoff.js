// TASK-161a-T4: 分析頁 → 瀏覽頁的條件寫入純函式（不接線、不碰 storage／DOM）。
// sel 只讀 period/actress/maker 三個業務鍵（FE-ALPINE-14：呼叫端傳進來的是 reactive Proxy）。
import { serializePills } from './pill-filter.js';

export function buildHandoffPills(sel) {
    var pills = [];
    if (sel) {
        var period = sel.period;
        var actress = sel.actress;
        var maker = sel.maker;
        if (actress) pills.push({ dim: 'actress', value: String(actress) });
        if (maker) pills.push({ dim: 'maker', value: String(maker) });
        if (period && period.type === 'year') {
            pills.push({ dim: 'release', op: '=', value: String(period.year) });
        } else if (period && period.type === 'range') {
            pills.push({ dim: 'release', op: 'range', value: String(period.from), value2: String(period.to) });
        }
    }
    return serializePills(pills);
}

function parseOld(rawJson) {
    if (typeof rawJson !== 'string' || rawJson === '') return {};
    try {
        var v = JSON.parse(rawJson);
        return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
    } catch (e) {
        return {};
    }
}

export function applyHandoff(rawJson, sel) {
    var old = parseOld(rawJson);
    return JSON.stringify({
        ...old,
        pills: buildHandoffPills(sel),
        search: '',
        page: 1,
        showFavoriteActresses: false,
    });
}
