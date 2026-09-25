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
    buildMakerColorSlots,
    buildMainMakerYearMap,
} from './aggregate.js';
import {
    setMakerColorSlots,
    setMainMakerYearMap,
    initYearsChart,
    updateYearsChart,
    initDonutChart,
    updateDonutChart,
    disposeAll,
    areChartsAlive,
    reinitYearsAfterDispose,
    reinitDonutAfterDispose,
    getDonutChart,
    resizeAll,
    colorForMakerName,
} from './charts.js';

let _pageshowBound = false;
let _pageAlive = false;

function _photoUrl(name, favorites) {
    if (!name) return '';
    const fav = favorites && favorites[name];
    const photoName = (fav && fav.photoName) || name;
    return '/api/actresses/photo/' + encodeURIComponent(photoName);
}

export function libraryInsightsState() {
    return {
        snapshot: null,
        snapshotError: null,
        period: { type: 'all' },
        focus: null,
        scopedCount: 0,

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
                    // $watch('focus') 是唯一重繪入口
                    self.focus = next;
                },
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
            });
            this.$watch('focus', () => {
                this.recomputeScopedCount();
                this.redrawYears();
                this.redrawDonut();
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
            } catch {
                if (!_pageAlive) return;
                this.snapshotError = true;
                this.snapshot = null;
                this.scopedCount = 0;
            }
        },
    };
}
