/**
 * charts.js — 片庫分析 ECharts 組裝（TASK-156b-T3）
 *
 * ECharts 實例與 option 一律存模組級 Map，不進 Alpine reactive scope（CD-156-4）。
 * §3.10 spike 產物：divideShape='split'；setOption 不全域套用 notMerge（維持預設 merge
 * 以便 universalTransition 一對多分裂）。
 */

import {
    UNKNOWN_KEY,
    getRecords,
    aggregateYears,
    buildMakerColorSlots,
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
/** @type {{ getPeriod: Function, setPeriod: Function, getFocus: Function }|null} */
let _yearsCallbacks = null;

// ── 純函式（node:test 可測）──────────────────────────────────────────

export function resolveYearBarColorMode(focus) {
    return focus && focus.type === 'actress' ? 'byMaker' : 'neutral';
}

export function shouldAnimate(prefersReducedMotion) {
    return !prefersReducedMotion;
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

function tKey(key) {
    if (typeof window !== 'undefined' && typeof window.t === 'function') {
        return window.t(key);
    }
    return key;
}

function labelForCategory(cat) {
    return cat === UNKNOWN_KEY ? tKey('insights.unknown') : cat;
}

function colorForMaker(name) {
    if (name && Object.prototype.hasOwnProperty.call(_makerSlots, name)) {
        const slot = _makerSlots[name]; // 0..7
        return cssVar('--insights-maker-' + (slot + 1));
    }
    return resolveColor(
        'color-mix(in oklch, var(--color-base-content) 22%, transparent)',
    );
}

function neutralUnknown() {
    return resolveColor(
        'color-mix(in oklch, var(--color-base-content) 12%, transparent)',
    );
}

function surfaceBorder() {
    return cssVar('--surface-1');
}

export function setMakerColorSlots(slots) {
    _makerSlots = slots || {};
}

export function refreshMakerColorSlots() {
    _makerSlots = buildMakerColorSlots(getRecords());
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
