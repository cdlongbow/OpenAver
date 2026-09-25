/**
 * state.js — 片庫分析 Alpine 狀態（TASK-156b-T3 擴充）
 *
 * records[] 存 aggregate 模組級，不進 this.*（CD-156-4）。
 * ECharts 實例只經 charts.js 模組級 Map（CD-156-4 2.1）。
 * bfcache：pageshow(persisted) 在本頁私有 listener 處理（CD-156-5）。
 */

import {
    setRecords,
    getRecords,
    scopeRecords,
    periodRecords,
    buildMakerColorSlots,
    buildMainMakerYearMap,
    buildActressTop20,
} from './aggregate.js';
import {
    setMakerColorSlots,
    setMainMakerYearMap,
    initYearsChart,
    updateYearsChart,
    initDonutChart,
    updateDonutChart,
    initTagsChart,
    updateTagsChart,
    disposeAll,
    areChartsAlive,
    reinitYearsAfterDispose,
    reinitDonutAfterDispose,
    reinitTagsAfterDispose,
    getDonutChart,
    getTagsChart,
    resizeAll,
    colorForMakerName,
} from './charts.js';
import { applyCellFocal } from '../../shared/focal-cell.js';

let _pageshowBound = false;
let _pageAlive = false;
let _previewTimer = null;

/** 預覽浮層實測尺寸（160 寬照片 + 名字列）；與 .insights-preview CSS 對齊。 */
const PREVIEW_POPUP = { width: 160, height: 224 };
const PREVIEW_GAP = 8;
const PREVIEW_OPEN_DELAY_MS = 250;

function _photoUrl(name, favorites) {
    if (!name) return '';
    const fav = favorites && favorites[name];
    const photoName = (fav && fav.photoName) || name;
    return '/api/actresses/photo/' + encodeURIComponent(photoName);
}

/**
 * 預覽浮層 position:fixed 座標。錨點右側優先；溢出則翻左側／上移；夾在視窗內。
 * @param {{top:number,left:number,width:number,height:number}} anchor
 * @param {{width:number,height:number}} viewport
 * @param {{width:number,height:number}} popup
 * @returns {{left:number,top:number}}
 */
export function computePreviewPosition(anchor, viewport, popup) {
    var gap = PREVIEW_GAP;
    var left = anchor.left + anchor.width + gap;
    if (left + popup.width > viewport.width) {
        left = anchor.left - popup.width - gap;
    }
    if (left < 0) {
        left = Math.max(0, viewport.width - popup.width);
    }
    var top = anchor.top;
    if (top + popup.height > viewport.height) top = viewport.height - popup.height - gap;
    if (top < 0) top = 0;
    return { left: left, top: top };
}

export function libraryInsightsState() {
    return {
        snapshot: null,
        snapshotError: null,
        period: { type: 'all' },
        focus: null,
        scopedCount: 0,
        top20Rows: [],
        previewActress: null,
        previewAnchorRect: null,

        // 模板 @load / $watch 呼叫（同 showcase 揭露慣例）
        applyCellFocal,

        recomputeScopedCount() {
            this.scopedCount = scopeRecords(
                getRecords(),
                this.period,
                this.focus,
            ).length;
        },

        redrawYears() {
            updateYearsChart({ period: this.period, focus: this.focus });
        },

        redrawDonut() {
            updateDonutChart({ period: this.period, focus: this.focus });
        },

        redrawTags() {
            updateTagsChart({ period: this.period, focus: this.focus });
        },

        /**
         * §4.2：無焦點／女優焦點 → periodRecords；片商焦點 → scopeRecords(maker)。
         */
        recomputeTop20() {
            const all = getRecords();
            const focus = this.focus;
            let records;
            if (focus && focus.type === 'maker') {
                records = scopeRecords(all, this.period, focus);
            } else {
                records = periodRecords(all, this.period);
            }
            this.top20Rows = buildActressTop20(records, focus).rows;
        },

        /**
         * 與圓餅 setFocus 同一 sink：寫 this.focus，由 $watch('focus') 重繪。
         * 業務鍵字串比對（FE-ALPINE-14）。
         */
        toggleActressFocus(name) {
            if (!name) return;
            if (
                this.focus &&
                this.focus.type === 'actress' &&
                this.focus.value === name
            ) {
                this.focus = null;
            } else {
                this.focus = { type: 'actress', value: name };
            }
        },

        _hasPreviewPhoto(name) {
            const favs = this.snapshot && this.snapshot.actressFavorites;
            return !!(favs && name && favs[name]);
        },

        openPreview(name, anchorEl) {
            if (!this._hasPreviewPhoto(name)) return;
            if (_previewTimer) {
                clearTimeout(_previewTimer);
                _previewTimer = null;
            }
            let rect = null;
            if (anchorEl && typeof anchorEl.getBoundingClientRect === 'function') {
                const r = anchorEl.getBoundingClientRect();
                rect = {
                    top: r.top,
                    left: r.left,
                    width: r.width,
                    height: r.height,
                };
            }
            this.previewActress = name;
            this.previewAnchorRect = rect;
        },

        scheduleOpenPreview(name, anchorEl) {
            if (!this._hasPreviewPhoto(name)) return;
            if (_previewTimer) {
                clearTimeout(_previewTimer);
                _previewTimer = null;
            }
            const self = this;
            const el = anchorEl;
            _previewTimer = setTimeout(() => {
                _previewTimer = null;
                self.openPreview(name, el);
            }, PREVIEW_OPEN_DELAY_MS);
        },

        cancelOpenPreview() {
            if (_previewTimer) {
                clearTimeout(_previewTimer);
                _previewTimer = null;
            }
            this.closePreview();
        },

        closePreview() {
            this.previewActress = null;
            this.previewAnchorRect = null;
        },

        previewPhotoUrl() {
            if (!this.previewActress) return '';
            return _photoUrl(
                this.previewActress,
                this.snapshot && this.snapshot.actressFavorites,
            );
        },

        previewFavorite() {
            return (
                this.previewActress &&
                this.snapshot &&
                this.snapshot.actressFavorites &&
                this.snapshot.actressFavorites[this.previewActress]
            );
        },

        previewPositionStyle() {
            if (!this.previewAnchorRect) return '';
            // 用 clientWidth/Height（不含捲軸）夾限，與 CDP oracle #19 同一基準；
            // innerWidth 含捲軸時會讓浮層右緣看起來「在視窗內」卻超出 clientWidth。
            const de =
                typeof document !== 'undefined' ? document.documentElement : null;
            const viewport = {
                width: de ? de.clientWidth : 0,
                height: de ? de.clientHeight : 0,
            };
            const pos = computePreviewPosition(
                this.previewAnchorRect,
                viewport,
                PREVIEW_POPUP,
            );
            return {
                position: 'fixed',
                left: pos.left + 'px',
                top: pos.top + 'px',
            };
        },

        actressPhotoUrl(name) {
            return _photoUrl(
                name,
                this.snapshot && this.snapshot.actressFavorites,
            );
        },

        actressHasPhoto(name) {
            return this._hasPreviewPhoto(name);
        },

        clearPeriod() {
            // 只改 reactive 欄位；$watch('period') 是唯一重繪入口
            this.period = { type: 'all' };
        },

        clearFocus() {
            this.focus = null;
        },

        /**
         * D156-12：片商焦點時標題後綴＝期間標籤（全庫／該年）；其餘不加後綴。
         */
        donutTitle() {
            const base =
                typeof window !== 'undefined' && typeof window.t === 'function'
                    ? window.t('insights.row.makers')
                    : 'insights.row.makers';
            if (!this.focus || this.focus.type !== 'maker') return base;
            let periodLabel;
            if (this.period && this.period.type === 'year') {
                periodLabel = String(this.period.year);
            } else {
                periodLabel =
                    typeof window !== 'undefined' && typeof window.t === 'function'
                        ? window.t('insights.donut.library_wide')
                        : 'insights.donut.library_wide';
            }
            return base + ' · ' + periodLabel;
        },

        /**
         * D156-12：女優焦點時標題後綴＝期間標籤（全庫／該年）；其餘不加後綴。
         */
        get top20Title() {
            const base =
                typeof window !== 'undefined' && typeof window.t === 'function'
                    ? window.t('insights.row.actress_top20')
                    : 'insights.row.actress_top20';
            if (!this.focus || this.focus.type !== 'actress') return base;
            let periodLabel;
            if (this.period && this.period.type === 'year') {
                periodLabel = String(this.period.year);
            } else {
                periodLabel =
                    typeof window !== 'undefined' && typeof window.t === 'function'
                        ? window.t('insights.donut.library_wide')
                        : 'insights.donut.library_wide';
            }
            return base + ' · ' + periodLabel;
        },

        focusPhotoUrl() {
            if (!this.focus || this.focus.type !== 'actress') return '';
            return _photoUrl(
                this.focus.value,
                this.snapshot && this.snapshot.actressFavorites,
            );
        },

        focusMakerColor() {
            if (!this.focus || this.focus.type !== 'maker') return '';
            return colorForMakerName(this.focus.value);
        },

        focusInitial() {
            if (!this.focus || !this.focus.value) return '';
            return String(this.focus.value).charAt(0);
        },

        _yearsCallbacks() {
            const self = this;
            return {
                getPeriod: () => self.period,
                getFocus: () => self.focus,
                setPeriod: (next) => {
                    // $watch('period') 會接 recompute + 重繪
                    self.period = next;
                },
            };
        },

        _donutCallbacks() {
            const self = this;
            return {
                getPeriod: () => self.period,
                getFocus: () => self.focus,
                setFocus: (next) => {
                    // $watch('focus') 是唯一重繪入口（與 toggleActressFocus 同一 sink）
                    self.focus = next;
                },
            };
        },

        _tagsCallbacks() {
            const self = this;
            return {
                getPeriod: () => self.period,
                getFocus: () => self.focus,
            };
        },

        _onPageShow(event) {
            if (!event || event.persisted !== true) return;
            // 快照失敗時從未建圖——不要在 bfcache 還原時建空圖表
            if (this.snapshotError) return;
            if (!areChartsAlive()) {
                const el = document.getElementById('yearsChart');
                if (el) {
                    // callbacks 在 dispose 後仍由 charts 模組保留；若無則重掛
                    reinitYearsAfterDispose();
                    // 若 reinit 因 callbacks 空而沒做事，用目前 this 再掛一次
                    if (!areChartsAlive()) {
                        initYearsChart(el, this._yearsCallbacks());
                        updateYearsChart({
                            period: this.period,
                            focus: this.focus,
                        });
                    }
                }
                const donutEl = document.getElementById('donutChart');
                if (donutEl) {
                    reinitDonutAfterDispose();
                    const donut = getDonutChart();
                    if (!donut || donut.isDisposed()) {
                        initDonutChart(donutEl, this._donutCallbacks());
                        updateDonutChart({
                            period: this.period,
                            focus: this.focus,
                        });
                    }
                }
                const tagsEl = document.getElementById('tagsChart');
                if (tagsEl) {
                    reinitTagsAfterDispose();
                    const tags = getTagsChart();
                    if (!tags || tags.isDisposed()) {
                        initTagsChart(tagsEl, this._tagsCallbacks());
                        updateTagsChart({
                            period: this.period,
                            focus: this.focus,
                        });
                    }
                }
            } else {
                resizeAll();
            }
        },

        async init() {
            // pageshow：模組生命週期內只註冊一次；不進 __registerPage cleanup
            if (!_pageshowBound) {
                _pageshowBound = true;
                window.addEventListener('pageshow', (event) => {
                    // 透過目前頁面 Alpine 實例處理；若頁面已卸載則 no-op
                    const root = document.querySelector('.insights-container');
                    if (!root || !window.Alpine) return;
                    const data = window.Alpine.$data(root);
                    if (data && typeof data._onPageShow === 'function') {
                        data._onPageShow(event);
                    }
                });
            }

            _pageAlive = true;

            // $watch 是 period／focus 變更後唯一的 recompute + 重繪入口
            this.$watch('period', () => {
                this.recomputeScopedCount();
                this.redrawYears();
                this.redrawDonut();
                this.redrawTags();
                this.recomputeTop20();
            });
            this.$watch('focus', () => {
                this.recomputeScopedCount();
                this.redrawYears();
                this.redrawDonut();
                this.redrawTags();
                this.recomputeTop20();
            });

            if (window.__registerPage) {
                window.__registerPage({
                    cleanup: () => {
                        _pageAlive = false;
                        disposeAll();
                    },
                });
            }

            try {
                const resp = await fetch('/api/insights/snapshot');
                if (!_pageAlive) return;
                if (!resp.ok) {
                    this.snapshotError = true;
                    this.snapshot = null;
                    this.scopedCount = 0;
                    return;
                }
                const data = await resp.json();
                if (!_pageAlive) return;

                const records = data.records || [];
                const rest = { ...data };
                delete rest.records;

                setRecords(records);
                setMakerColorSlots(buildMakerColorSlots(getRecords()));
                setMainMakerYearMap(buildMainMakerYearMap(getRecords()));
                this.snapshot = rest;
                this.snapshotError = null;
                this.recomputeScopedCount();
                this.recomputeTop20();

                const el = document.getElementById('yearsChart');
                if (el) {
                    initYearsChart(el, this._yearsCallbacks());
                    updateYearsChart({
                        period: this.period,
                        focus: this.focus,
                    });
                }
                const donutEl = document.getElementById('donutChart');
                if (donutEl) {
                    initDonutChart(donutEl, this._donutCallbacks());
                    updateDonutChart({
                        period: this.period,
                        focus: this.focus,
                    });
                }
                const tagsEl = document.getElementById('tagsChart');
                if (tagsEl) {
                    initTagsChart(tagsEl, this._tagsCallbacks());
                    updateTagsChart({
                        period: this.period,
                        focus: this.focus,
                    });
                }
            } catch {
                if (!_pageAlive) return;
                this.snapshotError = true;
                this.snapshot = null;
                this.scopedCount = 0;
            }
        },
    };
}
