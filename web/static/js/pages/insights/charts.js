/**
 * charts.js — 片庫分析 ECharts 組裝（TASK-156b-T3 / T4）
 *
 * ECharts 實例與 option 一律存模組級 Map，不進 Alpine reactive scope（CD-156-4）。
 * §3.10 spike 產物：divideShape='split'；setOption 不全域套用 notMerge（維持預設 merge
 * 以便 universalTransition 一對多分裂）。
 */

import {
    UNKNOWN_KEY,
    REST_KEY,
    getRecords,
    aggregateYears,
    aggregateTags,
    buildMakerColorSlots,
    periodRecords,
    scopeRecords,
    buildMakerDonutData,
} from './aggregate.js';

/** @type {'split'|'clone'} spike 選定值——見 TASK-156b-T3 執行紀錄 */
export const YEARS_DIVIDE_SHAPE = 'split';

/** @type {Map<string, object>} */
const _charts = new Map();
/** @type {Map<string, ResizeObserver>} */
const _observers = new Map();
/** @type {string[]} */
let _lastYearCats = [];
/** @type {Record<string, number>} */
let _makerSlots = {};
/** @type {Record<string, string>} 全庫主要片商年 map（init 算一次，重繪複用） */
let _mainMakerYearMap = {};
/** @type {{w:number,h:number}} */
let _donutLastGoodSize = { w: 280, h: 220 };
/** @type {{ getPeriod: Function, setPeriod: Function, getFocus: Function, setFocus?: Function }|null} */
let _yearsCallbacks = null;
/** @type {{ getPeriod: Function, getFocus: Function, setFocus: Function }|null} */
let _donutCallbacks = null;
/** @type {{ getPeriod: Function, getFocus: Function }|null} */
let _tagsCallbacks = null;

// ── 純函式（node:test 可測）──────────────────────────────────────────

export function resolveYearBarColorMode(focus) {
    return focus && focus.type === 'actress' ? 'byMaker' : 'neutral';
}

export function shouldAnimate(prefersReducedMotion) {
    return !prefersReducedMotion;
}

/**
 * 計算圓餅 startAngle，使目標具名片商扇形中點落在正上方（ECharts 預設 90°）。
 * name===null／不在 inner／total===0 → 回傳 90（原位）。
 */
export function computeDonutStartAngle(inner, name) {
    const list = inner || [];
    let total = 0;
    for (let i = 0; i < list.length; i++) {
        total += list[i].value || 0;
    }
    if (!name || total === 0) return 90;
    let sumBefore = 0;
    let found = null;
    for (let i = 0; i < list.length; i++) {
        if (list[i].name === name) {
            found = list[i];
            break;
        }
        sumBefore += list[i].value || 0;
    }
    if (!found) return 90;
    const midFrac = (sumBefore + (found.value || 0) / 2) / total;
    let angle = 90 + 360 * midFrac;
    angle = ((angle % 360) + 360) % 360;
    return angle;
}


/**
 * getImageData 四分量 → CSS 色字串。a===255 回 rgb()，否則 rgba(..., a/255)。
 * 純函式，供 node:test 守 alpha 不被丟掉。
 */
export function formatRgbaChannels(r, g, b, a) {
    if (a === 255) {
        return 'rgb(' + r + ', ' + g + ', ' + b + ')';
    }
    return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + (a / 255) + ')';
}

// ── 色票／CSS 讀取 ───────────────────────────────────────────────────

let _colorProbe = null;

function _ensureProbe() {
    if (_colorProbe || typeof document === 'undefined') return;
    _colorProbe = document.createElement('span');
    _colorProbe.style.cssText =
        'position:absolute;left:-9999px;top:-9999px;width:0;height:0;overflow:hidden;pointer-events:none;';
    document.body.appendChild(_colorProbe);
}

function cssColorToRgb(cssColor) {
    // FE-CSS-25：getComputedStyle 可能讀回 oklch(...)；zrender 只認 hex/rgb/hsl，
    // 用 1×1 canvas fillStyle→getImageData 轉成 sRGB（保留 alpha）。
    if (typeof document === 'undefined') return cssColor || '#888888';
    const c = document.createElement('canvas');
    c.width = 1;
    c.height = 1;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    if (!ctx) return cssColor || '#888888';
    ctx.fillStyle = '#000000';
    ctx.fillStyle = cssColor;
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
    return formatRgbaChannels(r, g, b, a);
}

function resolveColor(expr) {
    _ensureProbe();
    if (!_colorProbe) return '#888888';
    _colorProbe.style.color = '';
    _colorProbe.style.color = expr;
    const css = getComputedStyle(_colorProbe).color || '#888888';
    return cssColorToRgb(css);
}

function cssVar(name) {
    return resolveColor('var(' + name + ')');
}

function readPrefersReducedMotion() {
    return (
        typeof window !== 'undefined' &&
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches
    );
}

function tKey(key, params) {
    if (typeof window !== 'undefined' && typeof window.t === 'function') {
        return window.t(key, params);
    }
    return key;
}

function labelForCategory(cat) {
    return cat === UNKNOWN_KEY ? tKey('insights.unknown') : cat;
}

function neutralOther() {
    return resolveColor(
        'color-mix(in oklch, var(--color-base-content) 22%, transparent)',
    );
}

function colorForMaker(name) {
    if (name && Object.prototype.hasOwnProperty.call(_makerSlots, name)) {
        const slot = _makerSlots[name]; // 0..7
        return cssVar('--insights-maker-' + (slot + 1));
    }
    return neutralOther();
}

function neutralUnknown() {
    return resolveColor(
        'color-mix(in oklch, var(--color-base-content) 12%, transparent)',
    );
}

/** 外圈「其他作品」：主色淡化（poc tint 35%）。 */
function tintMakerColor(rgbStr) {
    return resolveColor(
        'color-mix(in srgb, ' + rgbStr + ' 35%, var(--surface-1))',
    );
}

function surfaceBorder() {
    return cssVar('--surface-1');
}

function labelForDonutKey(key) {
    if (key === REST_KEY) return tKey('insights.donut.other');
    if (key === UNKNOWN_KEY) return tKey('insights.donut.unknown');
    return key;
}

export function setMakerColorSlots(slots) {
    _makerSlots = slots || {};
}

export function refreshMakerColorSlots() {
    _makerSlots = buildMakerColorSlots(getRecords());
}

export function setMainMakerYearMap(map) {
    _mainMakerYearMap = map || {};
}

export function colorForMakerName(name) {
    return colorForMaker(name);
}

// ── 生命週期 ─────────────────────────────────────────────────────────

export function areChartsAlive() {
    if (_charts.size === 0) return false;
    for (const chart of _charts.values()) {
        if (!chart || chart.isDisposed()) return false;
    }
    return true;
}

export function disposeAll() {
    for (const ro of _observers.values()) {
        try {
            ro.disconnect();
        } catch {
            /* ignore */
        }
    }
    _observers.clear();
    for (const chart of _charts.values()) {
        try {
            if (chart && !chart.isDisposed()) chart.dispose();
        } catch {
            /* ignore */
        }
    }
    _charts.clear();
    // 保留 _yearsCallbacks：bfcache 還原後 reinit 還要用同一組 getter/setter
}

export function resizeAll() {
    for (const chart of _charts.values()) {
        if (chart && !chart.isDisposed()) chart.resize();
    }
}

/**
 * bfcache 還原且圖表已被 dispose 時：對既有 DOM 重新 init + setOption。
 */
export function reinitYearsAfterDispose() {
    const el = document.getElementById('yearsChart');
    if (!el || typeof window.echarts === 'undefined') return;
    if (!_yearsCallbacks) return;
    initYearsChart(el, _yearsCallbacks);
    updateYearsChart({
        period: _yearsCallbacks.getPeriod(),
        focus: _yearsCallbacks.getFocus(),
    });
}

/**
 * bfcache 還原：圓餅與年份同一套 callbacks 生命週期。
 */
export function reinitDonutAfterDispose() {
    const el = document.getElementById('donutChart');
    if (!el || typeof window.echarts === 'undefined') return;
    if (!_donutCallbacks) return;
    initDonutChart(el, _donutCallbacks);
    updateDonutChart({
        period: _donutCallbacks.getPeriod(),
        focus: _donutCallbacks.getFocus(),
    });
}

/**
 * bfcache 還原：標籤樹圖與 years/donut 同一套 callbacks 生命週期。
 */
export function reinitTagsAfterDispose() {
    const el = document.getElementById('tagsChart');
    if (!el || typeof window.echarts === 'undefined') return;
    if (!_tagsCallbacks) return;
    initTagsChart(el, _tagsCallbacks);
    updateTagsChart({
        period: _tagsCallbacks.getPeriod(),
        focus: _tagsCallbacks.getFocus(),
    });
}

/**
 * @param {HTMLElement} containerEl
 * @param {{ getPeriod: Function, setPeriod: Function, getFocus: Function }} callbacks
 */
export function initYearsChart(containerEl, callbacks) {
    if (!containerEl || typeof window.echarts === 'undefined') return;
    _yearsCallbacks = callbacks;

    let chart = _charts.get('years');
    if (chart && !chart.isDisposed()) {
        chart.dispose();
    }
    chart = window.echarts.init(containerEl);
    _charts.set('years', chart);

    const prevRo = _observers.get('years');
    if (prevRo) prevRo.disconnect();
    const ro = new ResizeObserver(() => {
        const c = _charts.get('years');
        if (c && !c.isDisposed()) c.resize();
    });
    ro.observe(containerEl);
    _observers.set('years', ro);

    // 每次 init 都掛在新實例上（dispose 後舊 listener 隨實例消失）
    // 整支長條「柱身以外空白」也要能點到——用 getZr 原始像素，不是 series click。
    chart.getZr().on('click', (ev) => {
        const c = _charts.get('years');
        if (!c || c.isDisposed() || !_yearsCallbacks) return;
        // zrender 事件：優先 offsetX/Y；少數版本掛在 ev.event
        const oe = ev && ev.event ? ev.event : ev;
        const ox = oe && oe.offsetX != null ? oe.offsetX : ev.offsetX;
        const oy = oe && oe.offsetY != null ? oe.offsetY : ev.offsetY;
        if (ox == null || oy == null) return;
        const pointInPixel = [ox, oy];
        if (!c.containPixel('grid', pointInPixel)) return;
        const pointInGrid = c.convertFromPixel({ seriesIndex: 0 }, pointInPixel);
        let idx = Array.isArray(pointInGrid) ? pointInGrid[0] : pointInGrid;
        if (typeof idx === 'number') idx = Math.round(idx);
        if (idx == null || idx < 0 || idx >= _lastYearCats.length) return;
        const catName = _lastYearCats[idx];
        if (catName === undefined || catName === UNKNOWN_KEY) return;
        const y = parseInt(catName, 10);
        if (Number.isNaN(y)) return;
        const cur = _yearsCallbacks.getPeriod();
        if (cur && cur.type === 'year' && cur.year === y) {
            _yearsCallbacks.setPeriod({ type: 'all' });
        } else {
            _yearsCallbacks.setPeriod({ type: 'year', year: y });
        }
    });
}

export function getYearsChart() {
    return _charts.get('years') || null;
}

// ── 年份長條 setOption ───────────────────────────────────────────────

function _buildAxisLabels(categories) {
    return categories.map(labelForCategory);
}

/** 從即將／當下的 maker series 名單取 seriesKey（不含全庫色票）。 */
function _makerKeysFromAggSeries(aggSeries) {
    return (aggSeries || []).map(function (s) {
        return s.name == null ? UNKNOWN_KEY : s.name;
    });
}

/**
 * 從已渲染的 ECharts series 讀出單一字面 seriesKey
 * （清除方向：舊的 N 個 maker series）。
 */
function _makerKeysFromRenderedSeries(seriesArr) {
    const keys = [];
    for (let i = 0; i < (seriesArr || []).length; i++) {
        const s = seriesArr[i];
        if (!s) continue;
        const sk = s.universalTransition && s.universalTransition.seriesKey;
        if (typeof sk === 'string' && sk) {
            keys.push(sk);
            continue;
        }
        const id = s.id;
        if (typeof id === 'string' && id.indexOf('years-maker-') === 0) {
            keys.push(id.slice('years-maker-'.length));
        }
    }
    return keys;
}

function _opacityForIndex(dimmed, i) {
    return dimmed && dimmed[i] ? 0.35 : 1;
}

/**
 * @param {{ period: object, focus: object|null }} state
 */
export function updateYearsChart(state) {
    const chart = _charts.get('years');
    if (!chart || chart.isDisposed()) return;

    const period = state.period || { type: 'all' };
    const focus = state.focus || null;
    const records = getRecords();
    const agg = aggregateYears(records, period, focus);
    const categories = agg.categories || [];
    const dimmed = agg.dimmed || [];
    _lastYearCats = categories.slice();

    const reduceMotion = readPrefersReducedMotion();
    const animate = shouldAnimate(reduceMotion);
    const colorMode = resolveYearBarColorMode(focus);

    const normalColor = cssVar('--color-primary');
    const selectedColor = resolveColor(
        'color-mix(in oklch, var(--color-primary) 55%, white 45%)',
    );

    if (!categories.length) {
        chart.clear();
        chart.setOption({
            animation: animate,
            graphic: [
                {
                    type: 'text',
                    left: 'center',
                    top: 'middle',
                    style: {
                        text: tKey('insights.no_data'),
                        fontSize: 11,
                        fill: cssVar('--text-muted'),
                    },
                },
            ],
        });
        return;
    }

    const axisData = _buildAxisLabels(categories);
    const prevOpt = chart.getOption();
    const prevSeries = (prevOpt && prevOpt.series) || [];

    /** @type {object[]} */
    let series;

    if (colorMode === 'byMaker') {
        // 進入方向：seriesKey = 即將 setOption 的新 maker 名單；
        // 先把舊 total 的 seriesKey 對齊，再 replaceMerge 成 N 段。
        const newKeys = _makerKeysFromAggSeries(agg.series);
        if (prevSeries.length === 1) {
            try {
                chart.setOption({
                    series: [
                        {
                            id: prevSeries[0].id || 'years-total',
                            universalTransition: {
                                enabled: true,
                                seriesKey: newKeys,
                                divideShape: YEARS_DIVIDE_SHAPE,
                            },
                        },
                    ],
                });
            } catch {
                /* ignore */
            }
        }

        series = (agg.series || []).map((s) => {
            const mk = s.name;
            const color =
                mk === UNKNOWN_KEY || mk === null
                    ? neutralUnknown()
                    : colorForMaker(mk);
            const data = (s.data || []).map((v, i) => ({
                value: v,
                itemStyle: { opacity: _opacityForIndex(dimmed, i) },
            }));
            const key = mk == null ? UNKNOWN_KEY : mk;
            return {
                id: 'years-maker-' + key,
                name: labelForCategory(key),
                type: 'bar',
                stack: 'total',
                barMaxWidth: 26,
                data,
                itemStyle: {
                    color,
                    borderColor: surfaceBorder(),
                    borderWidth: 2,
                },
                emphasis: { focus: 'series' },
                universalTransition: {
                    enabled: true,
                    seriesKey: key,
                    divideShape: YEARS_DIVIDE_SHAPE,
                },
            };
        });
    } else {
        // 清除方向：seriesKey = 當下已渲染的舊 maker series；否則退回 agg 名單
        const keysFromPrev = _makerKeysFromRenderedSeries(prevSeries);
        const transitionKeys =
            keysFromPrev.length > 0
                ? keysFromPrev
                : _makerKeysFromAggSeries(agg.series);

        const src = (agg.series && agg.series[0] && agg.series[0].data) || [];
        const anySelected = period.type === 'year';
        const data = src.map((v, i) => {
            const cat = categories[i];
            const selected =
                anySelected && cat !== UNKNOWN_KEY && Number(cat) === period.year;
            const opacity = anySelected && !selected ? 0.35 : 1;
            const isUnknown = cat === UNKNOWN_KEY;
            return {
                value: v,
                itemStyle: {
                    color: isUnknown
                        ? neutralUnknown()
                        : selected
                          ? selectedColor
                          : normalColor,
                    opacity,
                },
            };
        });
        series = [
            {
                id: 'years-total',
                name:
                    focus && focus.type === 'maker'
                        ? focus.value
                        : tKey('insights.row.years'),
                type: 'bar',
                barMaxWidth: 26,
                data,
                universalTransition: {
                    enabled: true,
                    seriesKey: transitionKeys,
                    divideShape: YEARS_DIVIDE_SHAPE,
                },
            },
        ];
    }

    try {
        chart.dispatchAction({ type: 'hideTip' });
    } catch {
        /* ignore */
    }

    // 兩個方向都保留 universalTransition + replaceMerge；不全域 notMerge。
    chart.setOption(
        {
            animation: animate,
            animationDuration: 250,
            animationDurationUpdate: 400,
            graphic: [],
            grid: { left: 4, right: 8, top: 8, bottom: 20, containLabel: true },
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'shadow' },
                textStyle: { fontSize: 11 },
            },
            xAxis: {
                type: 'category',
                data: axisData,
                axisLine: { lineStyle: { color: cssVar('--stroke-default') } },
                axisLabel: { fontSize: 11, color: cssVar('--text-muted') },
                axisTick: { show: false },
            },
            yAxis: {
                type: 'value',
                splitLine: { lineStyle: { color: cssVar('--stroke-subtle') } },
                axisLabel: { fontSize: 11, color: cssVar('--text-muted') },
            },
            series,
        },
        { replaceMerge: ['series'] },
    );
}

// ── 片商雙層圓餅 ─────────────────────────────────────────────────────

/**
 * @param {HTMLElement} containerEl
 * @param {{ getPeriod: Function, getFocus: Function, setFocus: Function }} callbacks
 */
export function initDonutChart(containerEl, callbacks) {
    if (!containerEl || typeof window.echarts === 'undefined') return;
    _donutCallbacks = callbacks;

    let chart = _charts.get('donut');
    if (chart && !chart.isDisposed()) {
        chart.dispose();
    }
    chart = window.echarts.init(containerEl);
    _charts.set('donut', chart);

    const prevRo = _observers.get('donut');
    if (prevRo) prevRo.disconnect();
    const ro = new ResizeObserver(() => {
        const c = _charts.get('donut');
        if (c && !c.isDisposed()) {
            c.resize();
            // 半徑依容器像素重算——resize 後補一次 setOption
            if (_donutCallbacks) {
                updateDonutChart({
                    period: _donutCallbacks.getPeriod(),
                    focus: _donutCallbacks.getFocus(),
                });
            }
        }
    });
    ro.observe(containerEl);
    _observers.set('donut', ro);

    chart.on('click', (params) => {
        if (!_donutCallbacks || typeof _donutCallbacks.setFocus !== 'function') {
            return;
        }
        // 只接受內圈（seriesIndex 0）具名扇形；rest／unknown 無效果。
        // 不做 actress-focus 早退（D156-6：女優焦點下點片商直接切換）。
        if (params.seriesIndex !== 0) return;
        const data = params.data;
        if (!data || data.kind !== 'named' || !data.name) return;
        const name = data.name;
        // 點擊當下扇形處於 emphasis/hover；若不先 downplay，後續 startAngle
        // transition 會被跳過（角度一步到終值，只剩 select/emphasis 的位移在動）。
        try {
            chart.dispatchAction({ type: 'downplay' });
        } catch {
            /* ignore */
        }
        const cur = _donutCallbacks.getFocus();
        if (cur && cur.type === 'maker' && cur.value === name) {
            _donutCallbacks.setFocus(null);
        } else {
            _donutCallbacks.setFocus({ type: 'maker', value: name });
        }
    });
}

export function getDonutChart() {
    return _charts.get('donut') || null;
}

/**
 * §4.2 wiring：無焦點／片商焦點 → periodRecords；女優焦點 → scopeRecords。
 * @param {{ period: object, focus: object|null }} state
 */
export function updateDonutChart(state) {
    const chart = _charts.get('donut');
    if (!chart || chart.isDisposed()) return;

    const period = state.period || { type: 'all' };
    const focus = state.focus || null;
    const allRecords = getRecords();

    let dataRecords;
    let highlightKey = null;
    if (focus && focus.type === 'actress') {
        dataRecords = scopeRecords(allRecords, period, focus);
    } else {
        dataRecords = periodRecords(allRecords, period);
        if (focus && focus.type === 'maker') {
            highlightKey = focus.value;
        }
    }

    const donut = buildMakerDonutData(dataRecords, _mainMakerYearMap);
    const total = donut.total;
    const reduceMotion = readPrefersReducedMotion();
    const animate = shouldAnimate(reduceMotion);

    if (!total) {
        chart.clear();
        chart.setOption({
            animation: animate,
            graphic: [
                {
                    type: 'text',
                    left: 'center',
                    top: 'middle',
                    style: {
                        text: tKey('insights.no_data'),
                        fontSize: 11,
                        fill: cssVar('--text-muted'),
                    },
                },
            ],
            series: [],
        });
        return;
    }

    function opacityFor(name) {
        if (!highlightKey) return 1;
        return name === highlightKey ? 1 : 0.35;
    }

    const top5Names = {};
    donut.inner
        .filter((e) => e.kind === 'named')
        .slice(0, 5)
        .forEach((e) => {
            if (total && e.value / total >= 0.04) {
                top5Names[e.name] = true;
            }
        });

    const innerData = donut.inner.map((e) => {
        let color;
        if (e.kind === 'unknown') {
            color = neutralUnknown();
        } else if (e.kind === 'rest') {
            color = neutralOther();
        } else {
            color = colorForMaker(e.name);
        }
        return {
            name: e.name,
            value: e.value,
            kind: e.kind,
            itemStyle: {
                color,
                opacity: opacityFor(e.name),
                borderColor: surfaceBorder(),
                borderWidth: 2,
            },
            label: {
                show: !!top5Names[e.name],
            },
        };
    });

    const outerData = donut.outer.map((e) => {
        let color;
        let displayName;
        if (e.kind === 'rest') {
            color = neutralOther();
            displayName = labelForDonutKey(REST_KEY);
        } else if (e.kind === 'unknown') {
            color = neutralUnknown();
            displayName = labelForDonutKey(UNKNOWN_KEY);
        } else if (e.kind === 'undetermined') {
            color = neutralUnknown();
            displayName = e.maker;
        } else if (e.kind === 'main') {
            color = colorForMaker(e.maker);
            displayName = e.maker;
        } else {
            // other：主色淡化
            color = tintMakerColor(colorForMaker(e.maker));
            displayName = e.maker;
        }
        return {
            name: displayName + '|' + e.kind,
            value: e.value,
            maker: e.maker,
            kind: e.kind,
            itemStyle: {
                color,
                opacity: opacityFor(e.maker),
                borderColor: surfaceBorder(),
                borderWidth: 1,
            },
        };
    });

    let boxW = chart.getWidth();
    let boxH = chart.getHeight();
    if (boxW < 150 || boxH < 100) {
        boxW = _donutLastGoodSize.w;
        boxH = _donutLastGoodSize.h;
    } else {
        _donutLastGoodSize.w = boxW;
        _donutLastGoodSize.h = boxH;
    }
    const vPad = 8;
    // 窄寬（如 390）時外標籤會吃掉左右各 ~90px，maxOuterR 被寬度卡住 → 外徑 < 85% 高。
    // 改為內側標籤並縮 labelMargin，讓圓餅撐滿可用高度。
    const narrow = boxW < 420;
    const labelMargin = narrow ? 8 : 90;
    const usableW = Math.max(60, boxW - labelMargin * 2);
    const usableH = Math.max(60, boxH - vPad * 2);
    const maxOuterR = Math.min(usableW, usableH) / 2;
    const rOuterOuter = Math.round(maxOuterR * 0.99);
    const rOuterInner = Math.round(maxOuterR * 0.8);
    const rInnerOuter = Math.round(maxOuterR * 0.62);
    const rInnerInner = Math.round(maxOuterR * 0.38);

    const startAngle = computeDonutStartAngle(
        donut.inner,
        highlightKey,
    );

    const centerSub = tKey('insights.unit');
    const centerText =
        (total || 0).toLocaleString('zh-Hant') + '\n{sub|' + centerSub + '}';

    try {
        chart.dispatchAction({ type: 'hideTip' });
    } catch {
        /* ignore */
    }

    /** 點擊 hover 的 emphasis 會讓 startAngle transition 失效；圓餅關閉 emphasis。 */
    const emphasisOff = { disabled: true };

    const innerLabel = narrow
        ? {
              show: true,
              position: 'inside',
              formatter: function (p) {
                  const nm = p.data && p.data.name;
                  if (!top5Names[nm]) return '';
                  return Math.round(p.percent) + '%';
              },
              fontSize: 10,
              color: cssVar('--text-primary'),
              overflow: 'truncate',
          }
        : {
              show: true,
              formatter: function (p) {
                  const nm = p.data && p.data.name;
                  if (!top5Names[nm]) return '';
                  return (
                      labelForDonutKey(nm) +
                      ' ' +
                      Math.round(p.percent) +
                      '%'
                  );
              },
              fontSize: 11,
              color: cssVar('--text-secondary'),
              overflow: 'none',
              width: labelMargin + 20,
              alignTo: 'labelLine',
              edgeDistance: 4,
          };

    const innerLabelLine = narrow
        ? { show: false }
        : {
              show: true,
              length: 8,
              length2: 6,
              lineStyle: { color: cssVar('--stroke-default') },
          };

    chart.setOption(
        {
            animation: animate,
            animationDuration: 250,
            animationDurationUpdate: 400,
            graphic: [
                {
                    type: 'text',
                    left: 'center',
                    top: 'middle',
                    z: 10,
                    style: {
                        text: centerText,
                        textAlign: 'center',
                        fontSize: narrow ? 14 : 16,
                        fontWeight: 700,
                        fill: cssVar('--text-primary'),
                        lineHeight: 17,
                        rich: {
                            sub: {
                                fontSize: 9,
                                fontWeight: 400,
                                fill: cssVar('--text-muted'),
                                lineHeight: 12,
                            },
                        },
                    },
                },
            ],
            tooltip: {
                trigger: 'item',
                textStyle: { fontSize: 11 },
                formatter: function (p) {
                    const d = p.data || {};
                    const title =
                        p.seriesIndex === 0
                            ? labelForDonutKey(d.name)
                            : labelForDonutKey(d.maker);
                    return (
                        title +
                        '<br/>' +
                        (d.value || 0).toLocaleString('zh-Hant') +
                        '（' +
                        p.percent +
                        '%）'
                    );
                },
            },
            series: [
                {
                    id: 'donut-inner',
                    type: 'pie',
                    name: 'inner',
                    center: ['50%', '50%'],
                    radius: [rInnerInner, rInnerOuter],
                    startAngle,
                    clockwise: true,
                    animationTypeUpdate: 'transition',
                    avoidLabelOverlap: true,
                    minShowLabelAngle: 8,
                    selectedMode: highlightKey ? 'single' : false,
                    selectedOffset: 6,
                    emphasis: emphasisOff,
                    label: innerLabel,
                    labelLine: innerLabelLine,
                    data: innerData.map((d) => ({
                        ...d,
                        selected: !!(highlightKey && d.name === highlightKey),
                    })),
                },
                {
                    id: 'donut-outer',
                    type: 'pie',
                    name: 'outer',
                    center: ['50%', '50%'],
                    radius: [rOuterInner, rOuterOuter],
                    startAngle,
                    clockwise: true,
                    animationTypeUpdate: 'transition',
                    avoidLabelOverlap: false,
                    emphasis: emphasisOff,
                    label: { show: false },
                    labelLine: { show: false },
                    data: outerData,
                },
            ],
        },
        { replaceMerge: ['series'] },
    );
}

// ── 標籤矩形樹圖（TASK-156b-T6）─────────────────────────────────────

function _pctLabel(n, d) {
    if (!d) return '0%';
    return Math.round((n / d) * 100) + '%';
}

function _isDimTheme() {
    return (
        typeof document !== 'undefined' &&
        document.documentElement.getAttribute('data-theme') === 'dim'
    );
}

/**
 * @param {HTMLElement} containerEl
 * @param {{ getPeriod: Function, getFocus: Function }} callbacks
 */
export function initTagsChart(containerEl, callbacks) {
    if (!containerEl || typeof window.echarts === 'undefined') return;
    _tagsCallbacks = callbacks;

    let chart = _charts.get('tags');
    if (chart && !chart.isDisposed()) {
        chart.dispose();
    }
    chart = window.echarts.init(containerEl);
    _charts.set('tags', chart);

    const prevRo = _observers.get('tags');
    if (prevRo) prevRo.disconnect();
    const ro = new ResizeObserver(() => {
        const c = _charts.get('tags');
        if (c && !c.isDisposed()) c.resize();
    });
    ro.observe(containerEl);
    _observers.set('tags', ro);
}

export function getTagsChart() {
    return _charts.get('tags') || null;
}

/**
 * §4.2 wiring：無焦點 periodRecords；片商／女優焦點 scopeRecords。
 * 刻意不設 animationDurationUpdate（含 0）——ECharts 6.1.0 treemap 在
 * animationDurationUpdate:0 ＋版面驟縮時會把格子算成 NaN。
 * @param {{ period: object, focus: object|null }} state
 */
export function updateTagsChart(state) {
    const chart = _charts.get('tags');
    if (!chart || chart.isDisposed()) return;

    const period = state.period || { type: 'all' };
    const focus = state.focus || null;
    const allRecords = getRecords();

    let dataRecords;
    if (focus && (focus.type === 'maker' || focus.type === 'actress')) {
        dataRecords = scopeRecords(allRecords, period, focus);
    } else {
        dataRecords = periodRecords(allRecords, period);
    }

    const agg = aggregateTags(dataRecords);
    const total = agg.total;
    const reduceMotion = readPrefersReducedMotion();
    const animate = shouldAnimate(reduceMotion);

    const hintEl = document.getElementById('tagsHint');
    if (hintEl) {
        hintEl.textContent = tKey('insights.tags.coverage', {
            pct: _pctLabel(agg.withTagCount, total),
        });
    }

    const pulledEl = document.getElementById('tagsPulled');
    if (pulledEl) {
        if (agg.pulled.length && total) {
            const prefix = tKey('insights.tags.almost_all');
            const parts = agg.pulled.map(function (e) {
                return e[0] + ' ' + Math.round((e[1] / total) * 100) + '%';
            });
            pulledEl.textContent = prefix + parts.join('、');
        } else {
            pulledEl.textContent = '';
        }
    }

    if (!agg.rest.length) {
        chart.clear();
        chart.setOption(
            {
                animation: animate,
                animationDuration: 250,
                graphic: [
                    {
                        type: 'text',
                        left: 'center',
                        top: 'middle',
                        style: {
                            text: tKey('insights.tags.empty'),
                            fontSize: 11,
                            fill: cssVar('--text-muted'),
                        },
                    },
                ],
                series: [],
            },
            true,
        );
        return;
    }

    const top40 = agg.rest;
    const maxV = top40[0][1];
    const minV = top40[top40.length - 1][1];
    const borderColor = surfaceBorder();
    const isDim = _isDimTheme();
    const lLo = isDim ? 70 : 90;
    const lHi = isDim ? 40 : 60;

    const data = top40.map(function (e) {
        const t =
            maxV > minV ? (e[1] - minV) / (maxV - minV) : 1;
        const lightness = Math.round(lLo + (lHi - lLo) * t);
        const color = resolveColor(
            'oklch(' + lightness + '% 0.045 250)',
        );
        const textColor = lightness >= 60 ? '#1c1c1c' : '#f2f2f2';
        return {
            name: e[0],
            value: e[1],
            _pct: _pctLabel(e[1], total),
            itemStyle: { color: color },
            label: { color: textColor },
        };
    });

    try {
        chart.dispatchAction({ type: 'hideTip' });
    } catch {
        /* ignore */
    }

    // notMerge:true；刻意不設 animationDurationUpdate（NaN 規避）。
    chart.setOption(
        {
            animation: animate,
            animationDuration: 250,
            graphic: [],
            tooltip: {
                trigger: 'item',
                textStyle: { fontSize: 11 },
                formatter: function (p) {
                    return tKey('insights.tags.tooltip', {
                        name: p.name,
                        count: (p.value || 0).toLocaleString('zh-Hant'),
                        pct: (p.data && p.data._pct) || '0%',
                    });
                },
            },
            series: [
                {
                    type: 'treemap',
                    roam: false,
                    nodeClick: false,
                    breadcrumb: { show: false },
                    left: 0,
                    top: 0,
                    right: 0,
                    bottom: 0,
                    visibleMin: 30,
                    label: {
                        show: true,
                        formatter: function (p) {
                            return p.name + '\n' + p.value;
                        },
                        fontSize: 11,
                        overflow: 'truncate',
                    },
                    upperLabel: { show: false },
                    itemStyle: {
                        borderColor: borderColor,
                        borderWidth: 1,
                        gapWidth: 1,
                    },
                    emphasis: { label: { show: true } },
                    data: data,
                },
            ],
        },
        true,
    );
}
