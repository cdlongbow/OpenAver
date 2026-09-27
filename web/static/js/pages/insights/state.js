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
    buildGanttRows,
    ganttYearAxis,
    buildGanttYearCells,
    ganttAgeEligibility,
    ganttAgeAxis,
    buildGanttAgeCells,
    buildSoloRows,
    buildCostarRows,
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
    initAgeChart,
    updateAgeChart,
    initFieldBarChart,
    updateFieldBarChart,
    disposeAll,
    areChartsAlive,
    reinitYearsAfterDispose,
    reinitDonutAfterDispose,
    reinitTagsAfterDispose,
    reinitAgeAfterDispose,
    reinitFieldBarAfterDispose,
    getDonutChart,
    getTagsChart,
    getAgeChart,
    getFieldBarChart,
    resizeAll,
    colorForMakerName,
} from './charts.js';
import { applyCellFocal } from '../../shared/focal-cell.js';

let _pageshowBound = false;
let _pageAlive = false;
let _previewTimer = null;
// bfcache 還原時可能重啟一次新的 fetch（見 _onPageShow）；離頁前的舊 fetch若晚
// 回來，token 比對讓它被丟棄，不會蓋掉新那次的結果（排序優先於旗標守衛）。
let _loadToken = 0;
/** 主要片商年 map；_loadSnapshot 建一次，與 setMainMakerYearMap 同一物件參考。 */
let _mainMakerYearMap = {};
/**
 * 修正 3（第 3 輪，P2 效能回歸）：ganttView() 單筆快取。模板同一次 reactive
 * tick 內會對同一個 axis 呼叫 ganttView() 好幾次（表頭 x-for／列 x-for／
 * gantt-note 的 x-show＋x-text），每次都重新對 25 列各掃一輪全庫 records
 * 建格子——實測 6521 筆片庫一次 tick 吃 65–80ms。鍵＝axis＋this.ganttRows
 * 參考＋this.period 參考＋favorites 參考，四者皆相同（===）才視為同一次
 * tick、直接回快取；鍵不同（period/focus 換了、favorites 換了、切了軸）
 * 才真的重算。存模組級變數、不進 Alpine reactive proxy——快取物件本身沒有
 * 必要被 Alpine 追蹤，包成 reactive 只會多繞一層 Proxy 開銷。
 */
let _ganttViewCache = null;
/**
 * TASK-156d-T4／CD-156d-3：上一次觸發過強調亮起的置頂名字（年表／分布表各自
 * 一份，可能不同步——例如她在年表自然排序內不觸發，但在分布表是 rank 外附加）。
 * 純粹的一次性比較用內部旗標，不是要被模板讀取的資料，故放模組級 `let`，
 * 不進 Alpine reactive 屬性。非女優焦點時歸零成 `null`（見 `_maybePlayPinPulse`
 * 註解——這保證清除焦點後重新選回同一人仍會重新觸發一次）。
 */
let _lastPinnedGanttName = null;
let _lastPinnedSoloName = null;
let _podiumEntrancePlayed = false;

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

export function shouldPlayPodiumEntrance(alreadyPlayed, podiumRowsLength) {
    return !alreadyPlayed && podiumRowsLength > 0;
}

/**
 * TASK-156d-T9／CD-156d-10a：row3 左半格是否顯示「與她同片」卡的衍生旗標。
 * 女優焦點但零共演時仍應為 false（改顯示 Top20），避免空白的「與她同片」卡。
 */
export function computeCostarVisible(isActressFocused, costarRowsLength) {
    return isActressFocused && costarRowsLength > 0;
}

export function libraryInsightsState() {
    return {
        snapshot: null,
        snapshotError: null,
        period: { type: 'all' },
        focus: null,
        scopedCount: 0,
        top20Rows: [],
        // TASK-156d-T3／CD-156d-2：row3 左半格＋row7 三個可切換顯示旗標（不用 x-show，
        // FE-ALPINE-17——vendored Alpine 的 x-show 晚一幀且一翻轉就立即 display:none，
        // 淡出播不完）。初始狀態＝無焦點：副本 A 顯示、與她同片／row7 副本 B 隱藏。
        showTop20InRow3: true,
        showCostar: false,
        showTop20InRow7: false,
        ganttRows: [],
        // 修正 1（第 2 輪）：圖例名單存進 reactive 欄位，見 ganttLegendMakers() 註解。
        ganttLegend: [],
        soloRows: [],
        costarRows: [],
        previewActress: null,
        previewAnchorRect: null,
        // 模板色點／格子塗色直接呼叫（charts.js 匯出）
        colorForMakerName,
        // P3-3：以女優名為 key，記錄該人頭像照片曾經載入失敗——取代舊版
        // @error 直接改寫 DOM textContent 的寫法（會把 x-if 錨點一併砍掉，
        // Alpine 之後永遠無法再插回新內容）。焦點格與 Top20 共用同一份。
        photoFailed: {},

        // 模板 @load / $watch 呼叫（同 showcase 揭露慣例）
        applyCellFocal,

        markPhotoFailed(name) {
            if (!name) return;
            this.photoFailed[name] = true;
        },

        recomputeScopedCount() {
            this.scopedCount = scopeRecords(
                getRecords(),
                this.period,
                this.focus,
            ).length;
        },

        isPeriodEmpty(types) {
            return !!(
                this.focus &&
                types.indexOf(this.focus.type) !== -1 &&
                this.scopedCount === 0 &&
                !this.snapshotError &&
                this.snapshot &&
                this.snapshot.logicalTitles > 0
            );
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

        redrawAge() {
            updateAgeChart({
                period: this.period,
                focus: this.focus,
                favorites: this.snapshot && this.snapshot.actressFavorites,
            });
        },

        redrawDirector() {
            updateFieldBarChart(
                { period: this.period, focus: this.focus },
                'director',
            );
        },

        redrawSeries() {
            updateFieldBarChart(
                { period: this.period, focus: this.focus },
                'series',
            );
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

        recomputeGantt() {
            this.ganttRows = buildGanttRows(
                getRecords(),
                _mainMakerYearMap,
                this.period,
                this.focus,
            );
        },

        /**
         * TASK-156c-T4／CD-156c-1／2／5：女優片商分布列表。
         * 呼叫順序在 recomputeGantt() 之後——ganttNames 依賴這次剛算好的
         * this.ganttRows（互斥名單），不是上一輪殘留的舊值。
         * `this.ganttLegend` 是全庫前 8 色票名稱陣列（reactive，T3 存好），
         * 不是舊版模組級 `_makerColorSlots` 物件——避免重建非 reactive 變數
         * 讓模板讀到 stale 資料（見 T3「圖例不渲染」的教訓）。
         * segments 一次算好存進 soloRows，模板只讀結果（FE perf 慣例同 T3）。
         */
        recomputeSolo() {
            const ganttNames = (this.ganttRows || []).map(function (r) {
                return r.name;
            });
            this.soloRows = buildSoloRows(
                getRecords(),
                _mainMakerYearMap,
                this.period,
                this.focus,
                ganttNames,
                this.ganttLegend,
            );
        },

        /**
         * TASK-156d-T4／CD-156d-3：她那列置頂後的一次性強調亮起。掛在既有三個
         * `recomputeGantt()+recomputeSolo()` 呼叫點之後（`_loadSnapshot` 成功、
         * `$watch('period')`、`$watch('focus')`）。年表／分布表各自獨立判斷、
         * 各自獨立比對 `_lastPinnedGanttName`/`_lastPinnedSoloName`（她可能在
         * 其中一張卡是自然排序內置頂、另一張是 rank 外附加置頂，兩者不必同步）。
         * 非女優焦點／片商焦點時視為「無置頂」，把記錄值歸零成 `null`——這保證
         * 「清除焦點後重新選回同一人」仍會重新觸發一次強調亮起（同一人連續兩次
         * 被置頂才不重播）。
         *
         * review P2（定稿輪數 2）：年表切到「年齡」軸時，`ganttView('age')` 會用
         * `ganttAgeEligibility` 濾掉沒生日的女優——她若無生日，`this.ganttRows[0]`
         * 仍是她（`pinned===true`，資料層置頂沒問題），但 DOM 實際渲染出來的第一列
         * 會是別人。**`ganttAxis` 是 `.gantt-card` 自己巢狀 `x-data="{ ganttAxis:
         * 'year' }"` 的子層狀態，不在這個父層元件上**——`this.ganttAxis` 在這裡
         * 讀不到值（恆為 `undefined`），呼叫 `this.ganttView(this.ganttAxis)` 只會
         * 一直落到年份分支，驗不出年齡軸的過濾（definite 輪 1 的錯誤修法，已改正）。
         * 改成直接讀 DOM 實際渲染出來的第一列名字（瀏覽器已經套用了不論哪個軸的
         * 過濾結果，不需要重新猜是哪個軸），核對是否等於這次要置頂的名字，不符合
         * 就跳過年表那一條 `playPulse`（不對 DOM 第一列動手，那是別人的列），
         * 分布表（`soloRows` 沒有年齡篩選）不受影響、照常播放。
         */
        _maybePlayPinPulse() {
            const isActress = !!(this.focus && this.focus.type === 'actress');
            const ganttFirst = (this.ganttRows || [])[0];
            const soloFirst = (this.soloRows || [])[0];
            const ganttName =
                isActress && ganttFirst && ganttFirst.pinned === true
                    ? ganttFirst.name
                    : null;
            const soloName =
                isActress && soloFirst && soloFirst.pinned === true
                    ? soloFirst.name
                    : null;

            const ganttChanged = ganttName !== _lastPinnedGanttName;
            const soloChanged = soloName !== _lastPinnedSoloName;
            _lastPinnedGanttName = ganttName;
            _lastPinnedSoloName = soloName;

            if (!ganttChanged && !soloChanged) return;
            this.$nextTick(() => {
                const motion = window.OpenAver.motion;
                if (ganttChanged && ganttName) {
                    const el = document.querySelector(
                        '.gantt-table .gantt-row:not(.gantt-head-row)',
                    );
                    const nameEl = el && el.querySelector('.gantt-name');
                    const renderedName = nameEl
                        ? nameEl.textContent.trim()
                        : null;
                    if (el && renderedName === ganttName) motion.playPulse(el);
                }
                if (soloChanged && soloName) {
                    const el = document.querySelector('#soloList .solo-row');
                    if (el) motion.playPulse(el);
                }
            });
        },

        _playPodiumEntrance() {
            const wrap = this.$refs.top20Row3El;
            if (!wrap) return;
            const slots = Array.from(wrap.querySelectorAll('.podium-slot'));
            const groups = slots
                .map(function (slot) {
                    return {
                        stand: slot.querySelector('.podium-stand'),
                        items: Array.from(
                            slot.querySelectorAll('.podium-avatar, .podium-name, .podium-count'),
                        ),
                    };
                })
                .filter(function (g) { return !!g.stand; });
            if (!groups.length) return;
            window.OpenAver.motion.playRise(groups);
        },

        /**
         * TASK-156c-T5 / CD-156c-1 / 6：與她同片搭檔列表。
         * 呼叫順序在 recomputeSolo() 之後。
         */
        recomputeCostar() {
            const focus = this.focus;
            const focusName =
                focus && focus.type === 'actress' ? focus.value : '';
            this.costarRows = buildCostarRows(
                getRecords(),
                this.period,
                focus,
            ).map(function (row) {
                return { name: row.name, count: row.count, self: focusName };
            });
        },

        /**
         * 年表顯示組裝。axis==='age' 時從 ganttRows 再濾沒生日的列。
         * 修正 3（第 3 輪）：同一次 tick 內對同一 axis 的重複呼叫共用
         * `_ganttViewCache`（見該模組級變數註解）；`this.ganttRows`／
         * `this.period` 仍要在快取判斷之前讀出來，讓 Alpine 對這個 getter
         * 的依賴追蹤不因為加了快取而漏掉 period/focus 變動。
         */
        ganttView(axis) {
            const rowsRef = this.ganttRows;
            const periodRef = this.period;
            const favs =
                (this.snapshot && this.snapshot.actressFavorites) || {};
            if (
                _ganttViewCache &&
                _ganttViewCache.axis === axis &&
                _ganttViewCache.rowsRef === rowsRef &&
                _ganttViewCache.periodRef === periodRef &&
                _ganttViewCache.favs === favs
            ) {
                return _ganttViewCache.result;
            }
            const all = getRecords();
            let result;
            if (axis === 'age') {
                const names = (this.ganttRows || []).map(function (r) {
                    return r.name;
                });
                const elig = ganttAgeEligibility(names, all, favs);
                const ageAxis = ganttAgeAxis(elig.eligibleNames, all, favs);
                const eligSet = new Set(elig.eligibleNames);
                const rows = (this.ganttRows || [])
                    .filter(function (r) {
                        return eligSet.has(r.name);
                    })
                    .map(function (r) {
                        return {
                            name: r.name,
                            appended: !!r.appended,
                            cells: buildGanttAgeCells(
                                r.name,
                                all,
                                favs,
                                _mainMakerYearMap,
                                ageAxis,
                            ),
                        };
                    });
                result = {
                    axis: ageAxis,
                    rows: rows,
                    skippedCount: elig.skippedCount,
                };
            } else {
                const yearAxis = ganttYearAxis(all);
                const yearRows = (this.ganttRows || []).map(function (r) {
                    return {
                        name: r.name,
                        appended: !!r.appended,
                        cells: buildGanttYearCells(
                            r.name,
                            all,
                            _mainMakerYearMap,
                            yearAxis,
                        ),
                    };
                });
                result = { axis: yearAxis, rows: yearRows, skippedCount: 0 };
            }
            _ganttViewCache = {
                axis: axis,
                rowsRef: rowsRef,
                periodRef: periodRef,
                favs: favs,
                result: result,
            };
            return result;
        },

        ganttCellTitle(cell, axis) {
            if (!cell || cell.state === 'empty') return '';
            const tFn =
                typeof window !== 'undefined' && typeof window.t === 'function'
                    ? window.t
                    : null;
            const label =
                axis === 'age'
                    ? tFn
                        ? tFn('insights.gantt.age_label', { age: cell.age })
                        : String(cell.age)
                    : String(cell.year);
            if (cell.state === 'main') {
                return tFn
                    ? tFn('insights.gantt.tooltip_main', {
                        label: label,
                        total: cell.filmCount,
                        maker: cell.maker,
                        count: cell.makerCount,
                    })
                    : label;
            }
            return tFn
                ? tFn('insights.gantt.tooltip_dot', {
                    label: label,
                    total: cell.filmCount,
                })
                : label;
        },

        /**
         * 修正 1（第 2 輪，真瀏覽器重現）：舊版直接讀模組級非 reactive
         * 變數 `_makerColorSlots`——模板首次渲染（快照載完前）算出 []，
         * 之後 `_loadSnapshot` 寫入 `_makerColorSlots` 不是 Alpine 追蹤的
         * 依賴，x-for 永遠不會重跑，圖例恆空（0 個 .gantt-legend-item）。
         * 改讀 reactive 欄位 `this.ganttLegend`（`_loadSnapshot` 寫入時
         * 觸發依賴），排序改在 `_loadSnapshot` 算好存進去，這裡只回傳。
         */
        ganttLegendMakers() {
            return this.ganttLegend;
        },

        /**
         * 修正 3（第 3 輪，P2 效能回歸）：年份模式只需要欄數，不該經由
         * ganttView() 取（那會連 25 列的格子都建一次）。直接用
         * ganttYearAxis() 算橫軸長度——全庫只需算一次（不隨 period/focus
         * 變，`getRecords()` 整個 session 內只在換快照時變）。
         *
         * 修正 4（第 4 輪，P3 效能回歸）：年齡模式當初也比照年份模式自己
         * 重跑 ganttAgeEligibility／ganttAgeAxis 避開 ganttView()，但這個
         * 顧慮在 ganttView() 加了單筆 tick 快取（`_ganttViewCache`，見該
         * 模組級變數註解）之後已經過時——同一次 tick 內模板本來就會經
         * 表頭／列 x-for 呼叫 ganttView(axis) 把格子建一次，這裡改讀
         * `this.ganttView(axis).axis.length` 只是把那次計算提前觸發，
         * 命中同一把快取、不會多花一次全庫掃描。實測 6521 筆真實片庫、
         * 真實 actressFavorites（23/25 頂尖女優落在年齡合格名單）：改前
         * 切到年齡軸一次完整 tick 約 31–41ms，改後約 5–9ms。
         */
        ganttGridStyle(axis) {
            let n;
            if (axis === 'age') {
                n = this.ganttView(axis).axis.length;
            } else {
                n = ganttYearAxis(getRecords()).length;
            }
            return (
                'grid-template-columns: var(--gantt-name-w) repeat(' +
                n +
                ', minmax(var(--gantt-cell-min-w), 1fr))'
            );
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

        /**
         * TASK-156d-T3／CD-156d-2：`$watch('focus')` 的唯一動效/捲動 sink。
         * TASK-156d-T9／CD-156d-10b：`costarVisible` 翻轉時才觸發 row3 左半格
         * 佔用者循序淡出淡入＋row7 副本 B 獨立淡出淡入（女優焦點但零共演時
         * `costarVisible` 維持 false，不播放）；捲動邏輯仍依 `isActressFocused`
         * 翻轉（CD-156d-10e，不變）。
         * 讀 `this.focus`（reactive）而非把它複製成本地閉包變數跨 `$nextTick` 使用
         * ——CD-156d-2 步驟 4 逐字要求，快速連續觸發時才能永遠依「當下最新」值判斷。
         *
         * `oldCostarRowsLength`：呼叫方（`$watch('focus')`）在 `recomputeCostar()`
         * 覆寫 `this.costarRows` 之前先讀出來的舊值長度。**不能改用 `this.showCostar`
         * 當 `wasCostarVisible` 的代理值**——`showCostar` 只在動畫 `onComplete` 才被
         * 寫入，若同一位女優被快速連點兩次、第二次點擊發生在第一次進場動畫的
         * onComplete 觸發之前，`showCostar` 仍是 stale 的舊值（false），會讓這次
         * 翻轉被誤判成「沒有翻轉」而略過 killTweens／leave 序列，導致第一次動畫
         * 的 onComplete 之後仍把畫面切成「顯示與她同片」——即使焦點已經被第二次
         * 點擊清除。這個迴歸由 `test_interrupt_during_fade_out_matches_direct_set`
         * 抓到（100% 重現，非計時抖動）。改用「當下這輪 `$watch` 開始時、尚未被
         * 覆寫的 `costarRows.length`」＋`wasActress` 算 `wasCostarVisible`，兩者
         * 都是同步值，不受動畫完成時機影響。
         */
        _handleActressFocusChange(oldValue, oldCostarRowsLength) {
            const wasActress = !!(oldValue && oldValue.type === 'actress');
            const isNowActress = this.isActressFocused;
            const switchedActress =
                isNowActress &&
                wasActress &&
                oldValue.value !== (this.focus && this.focus.value);

            // CD-156d-6：false→true，或維持 true 但換成不同的人 → 捲回頂端。
            // true→false（含清除）不捲動。
            if (isNowActress && (!wasActress || switchedActress)) {
                window.scrollTo({
                    top: 0,
                    behavior: window.OpenAver.prefersReducedMotion ? 'auto' : 'smooth',
                });
            }

            // TASK-156d-T9／CD-156d-10b：淡出淡入的觸發條件是 costarVisible 翻轉，
            // 不是 isActressFocused 翻轉——女優焦點但零共演時 costarVisible 維持
            // false，不應播放任何動畫。
            const wasCostarVisible = computeCostarVisible(wasActress, oldCostarRowsLength);
            const isNowCostarVisible = this.costarVisible;
            if (wasCostarVisible === isNowCostarVisible) return;

            const motion = window.OpenAver.motion;
            const top20El = this.$refs.top20Row3El;
            const costarEl = this.$refs.costarEl;
            const row7El = this.$refs.row7El;
            // CD-156d-2 步驟 4：每次新觸發前先對這次牽涉到的全部元素 killTweens，
            // 再永遠依當下最新 isActressFocused 從步驟 1/2 重新開始。
            motion.killTweens([top20El, costarEl, row7El].filter(Boolean));

            if (isNowCostarVisible) {
                // 步驟 1：進入焦點——costarEl 先淡出既有的 row3 副本 A。
                motion.playFadeTo(top20El, {
                    opacity: 0,
                    duration: 0.25,
                    onComplete: () => {
                        // CD-156d-5 不變式 2：隱藏後清掉殘留 inline opacity:0，
                        // 讓 style.opacity 回到 ''（下次淡入前用 fromOpacity 強制起始值）。
                        motion.clearProps(top20El, 'opacity');
                        this.showTop20InRow3 = false;
                        this.showCostar = true;
                        this.$nextTick(() => {
                            motion.playFadeTo(costarEl, {
                                fromOpacity: 0,
                                opacity: 1,
                                duration: 0.25,
                            });
                        });
                    },
                });
                // row7 副本 B 同時獨立處理：立即顯示、$nextTick 內淡入。
                this.showTop20InRow7 = true;
                this.$nextTick(() => {
                    motion.playFadeTo(row7El, {
                        fromOpacity: 0,
                        opacity: 1,
                        duration: 0.5,
                    });
                });
            } else {
                // 步驟 2：離開焦點（含清除）——對稱：costarEl 先完全淡出才切回
                // 副本 A 並淡入。
                motion.playFadeTo(costarEl, {
                    opacity: 0,
                    duration: 0.25,
                    onComplete: () => {
                        // CD-156d-5 不變式 2：隱藏後清掉殘留 inline opacity:0。
                        motion.clearProps(costarEl, 'opacity');
                        this.showCostar = false;
                        this.showTop20InRow3 = true;
                        this.$nextTick(() => {
                            motion.playFadeTo(top20El, {
                                fromOpacity: 0,
                                opacity: 1,
                                duration: 0.25,
                            });
                        });
                    },
                });
                // row7 副本 B 同時獨立淡出後才隱藏。
                motion.playFadeTo(row7El, {
                    opacity: 0,
                    duration: 0.5,
                    onComplete: () => {
                        // CD-156d-5 不變式 2：隱藏後清掉殘留 inline opacity:0。
                        motion.clearProps(row7El, 'opacity');
                        this.showTop20InRow7 = false;
                    },
                });
            }
        },

        _hasPreviewPhoto(name) {
            // 收藏存在不代表本機有照片檔（來源沒圖／下載失敗時收藏仍會落地，
            // 見 web/routers/insights.py favorites_by_primary 的 hasPhoto 計算）；
            // spec §3.4.1「只有收藏女優有照片；沒照片的人只顯示首字，不出現預覽」
            // 要看後端算好的 hasPhoto，不能只看「是不是收藏」。
            const favs = this.snapshot && this.snapshot.actressFavorites;
            const fav = favs && name && favs[name];
            return !!(fav && fav.hasPhoto);
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

        /**
         * spec §3.1 片數格：主數字下方小字「全庫 N 部」——固定用 logicalTitles
         * （全庫邏輯片數，不隨 period／focus 縮），不是 scopedCount。
         */
        totalCountLabel() {
            const n = this.snapshot ? this.snapshot.logicalTitles : 0;
            const nStr = Number(n).toLocaleString();
            return typeof window !== 'undefined' && typeof window.t === 'function'
                ? window.t('insights.total_count', { n: nStr })
                : 'insights.total_count';
        },

        clearPeriod() {
            // 只改 reactive 欄位；$watch('period') 是唯一重繪入口
            this.period = { type: 'all' };
        },

        clearFocus() {
            this.focus = null;
        },

        /**
         * CD-156c-8：焦點 type 落在 focusTypes（字串或陣列）時加期間後綴。
         */
        _titleWithPeriod(baseKey, focusTypes) {
            const tFn =
                typeof window !== 'undefined' && typeof window.t === 'function'
                    ? window.t
                    : null;
            const base = tFn ? tFn(baseKey) : baseKey;
            const types = Array.isArray(focusTypes)
                ? focusTypes
                : [focusTypes];
            if (
                !this.focus ||
                types.indexOf(this.focus.type) === -1
            ) {
                return base;
            }
            let periodLabel;
            if (this.period && this.period.type === 'year') {
                periodLabel = String(this.period.year);
            } else {
                periodLabel = tFn
                    ? tFn('insights.donut.library_wide')
                    : 'insights.donut.library_wide';
            }
            return base + ' · ' + periodLabel;
        },

        /**
         * D156-12：片商焦點時標題後綴＝期間標籤（全庫／該年）；其餘不加後綴。
         */
        donutTitle() {
            return this._titleWithPeriod('insights.row.makers', 'maker');
        },

        /**
         * D156-12：女優焦點時標題後綴＝期間標籤（全庫／該年）；其餘不加後綴。
         */
        get top20Title() {
            return this._titleWithPeriod(
                'insights.row.actress_top20',
                'actress',
            );
        },

        /**
         * TASK-156d-T2：Top20 拆兩張卡——頒獎台（前三名，固定 3 插槽）。
         * 焦點女優 rank<=3 天然落在這裡，不需要額外分支（CD-156d-1）。
         */
        get podiumRows() {
            return (this.top20Rows || []).filter((r) => r.rank <= 3);
        },

        /**
         * TASK-156d-T2：Top20 拆兩張卡——精簡名單（第 4–20 名 ＋ 焦點女優
         * rank>20 的附加列，附加列的 rank 是她的真實名次，天然 >3）。
         */
        get restRows() {
            return (this.top20Rows || []).filter((r) => r.rank > 3);
        },

        /**
         * TASK-156d-T3／CD-156d-2：row3 左半格佔用者切換（頒獎台＋名單 ↔ 與她同片）
         * 只在女優焦點時觸發；片商焦點與無焦點視覺上相同（顯示頒獎台＋名單）。
         */
        get isActressFocused() {
            return !!(this.focus && this.focus.type === 'actress');
        },

        /**
         * TASK-156d-T9／CD-156d-10a：命名可讀性用 getter，模板不需要直接綁定。
         */
        get costarVisible() {
            return computeCostarVisible(this.isActressFocused, this.costarRows.length);
        },

        get ganttTitle() {
            return this._titleWithPeriod('insights.row.gantt', 'actress');
        },

        /**
         * CD-156c-8：女優或片商焦點都加期間後綴（`_titleWithPeriod` 第二參數
         * 已設計成接受陣列）。
         */
        get soloTitle() {
            return this._titleWithPeriod('insights.row.actress_distribution', [
                'actress',
                'maker',
            ]);
        },

        /**
         * CD-156c-5：尾端「N 部 · M 家」。M＝相異具名 maker 個數（不含未知），
         * 即使被併進 other 段也算一家（見 aggregate.js buildSoloRows 註解）。
         */
        soloRowLabel(row) {
            const tFn =
                typeof window !== 'undefined' && typeof window.t === 'function'
                    ? window.t
                    : null;
            return tFn
                ? tFn('insights.solo.count_label', {
                    n: row.total,
                    m: row.namedMakerCount,
                })
                : row.total + ' / ' + row.namedMakerCount;
        },

        /**
         * CD-156c-5：「其他」段 tooltip，列出被併入的具名片商（最多 15 家）。
         */
        soloOtherTitle(seg) {
            const tFn =
                typeof window !== 'undefined' && typeof window.t === 'function'
                    ? window.t
                    : null;
            const others = seg.others || [];
            const list =
                others
                    .slice(0, 15)
                    .map(function (o) {
                        return o.maker;
                    })
                    .join('、') + (others.length > 15 ? '…' : '');
            return tFn
                ? tFn('insights.solo.other_title', { n: others.length, list: list })
                : list;
        },

        /**
         * CD-156c-6：尾端「N 部」。
         */
        costarRowLabel(row) {
            const tFn =
                typeof window !== 'undefined' && typeof window.t === 'function'
                    ? window.t
                    : null;
            return tFn
                ? tFn('insights.costar.count_label', { n: row.count })
                : String(row.count);
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

        _ageCallbacks() {
            const self = this;
            return {
                getPeriod: () => self.period,
                getFocus: () => self.focus,
                getFavorites: () =>
                    self.snapshot && self.snapshot.actressFavorites,
            };
        },

        _fieldCallbacks() {
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
            // Finding 2：離頁前快照尚未載完（fetch 仍在飛）時，cleanup 已把
            // _pageAlive 設 false，該次回應會被 _loadSnapshot 丟棄——bfcache 還原
            // 回這頁不會自動重跑 init()，此時 this.snapshot 仍是 null 且非
            // snapshotError，要在這裡重新發起一次載入，否則永遠停在空畫面。
            if (this.snapshot === null) {
                _pageAlive = true;
                return this._loadSnapshot();
            }
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
                const ageEl = document.getElementById('ageChart');
                if (ageEl) {
                    reinitAgeAfterDispose();
                    const age = getAgeChart();
                    if (!age || age.isDisposed()) {
                        initAgeChart(ageEl, this._ageCallbacks());
                        updateAgeChart({
                            period: this.period,
                            focus: this.focus,
                            favorites:
                                this.snapshot &&
                                this.snapshot.actressFavorites,
                        });
                    }
                }
                const directorEl = document.getElementById('directorChart');
                if (directorEl) {
                    reinitFieldBarAfterDispose('director');
                    const director = getFieldBarChart('director');
                    if (!director || director.isDisposed()) {
                        initFieldBarChart(
                            directorEl,
                            'director',
                            this._fieldCallbacks(),
                        );
                        this.redrawDirector();
                    }
                }
                const seriesEl = document.getElementById('seriesChart');
                if (seriesEl) {
                    reinitFieldBarAfterDispose('series');
                    const series = getFieldBarChart('series');
                    if (!series || series.isDisposed()) {
                        initFieldBarChart(
                            seriesEl,
                            'series',
                            this._fieldCallbacks(),
                        );
                        this.redrawSeries();
                    }
                }
            } else {
                resizeAll();
            }
        },

        /**
         * 抓快照＋建圖，供 init() 首次載入與 _onPageShow() bfcache 還原後重載共用。
         * token 是這次呼叫的序號；resolve 時序號被後一次呼叫蓋過（或 _pageAlive
         * 已被 cleanup 設 false）就丟棄，不寫入 this.*（Finding 2 的競態修法）。
         */
        async _loadSnapshot() {
            const token = ++_loadToken;
            try {
                const resp = await fetch('/api/insights/snapshot');
                if (!_pageAlive || token !== _loadToken) return;
                if (!resp.ok) {
                    this.snapshotError = true;
                    this.snapshot = null;
                    this.scopedCount = 0;
                    return;
                }
                const data = await resp.json();
                if (!_pageAlive || token !== _loadToken) return;

                const records = data.records || [];
                const rest = { ...data };
                delete rest.records;

                setRecords(records);
                var slots = buildMakerColorSlots(getRecords());
                setMakerColorSlots(slots);
                this.ganttLegend = Object.keys(slots)
                    .map(function (name) {
                        return { name: name, slot: slots[name] };
                    })
                    .sort(function (a, b) {
                        return a.slot - b.slot || (a.name < b.name ? -1 : 1);
                    })
                    .map(function (e) {
                        return e.name;
                    });
                var mmMap = buildMainMakerYearMap(getRecords());
                setMainMakerYearMap(mmMap);
                _mainMakerYearMap = mmMap;
                this.snapshot = rest;
                this.snapshotError = null;
                // P3-3：新快照可能代表照片檔已落地（或 bfcache 還原後重試機會）；
                // 舊的失敗記錄不該永久卡住，讓 x-if 有機會重新嘗試載入。
                this.photoFailed = {};
                this.recomputeScopedCount();
                this.recomputeTop20();
                this.recomputeGantt();
                this.recomputeSolo();
                this._maybePlayPinPulse();
                this.recomputeCostar();
                if (shouldPlayPodiumEntrance(_podiumEntrancePlayed, this.podiumRows.length)) {
                    _podiumEntrancePlayed = true;
                    this.$nextTick(() => this._playPodiumEntrance());
                }

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
                const ageEl = document.getElementById('ageChart');
                if (ageEl) {
                    initAgeChart(ageEl, this._ageCallbacks());
                    updateAgeChart({
                        period: this.period,
                        focus: this.focus,
                        favorites:
                            this.snapshot && this.snapshot.actressFavorites,
                    });
                }
                const directorEl = document.getElementById('directorChart');
                if (directorEl) {
                    initFieldBarChart(
                        directorEl,
                        'director',
                        this._fieldCallbacks(),
                    );
                    this.redrawDirector();
                }
                const seriesEl = document.getElementById('seriesChart');
                if (seriesEl) {
                    initFieldBarChart(
                        seriesEl,
                        'series',
                        this._fieldCallbacks(),
                    );
                    this.redrawSeries();
                }
            } catch {
                if (!_pageAlive || token !== _loadToken) return;
                this.snapshotError = true;
                this.snapshot = null;
                this.scopedCount = 0;
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
                this.redrawAge();
                this.redrawDirector();
                this.redrawSeries();
                this.recomputeTop20();
                this.recomputeGantt();
                this.recomputeSolo();
                this._maybePlayPinPulse();
                this.recomputeCostar();
            });
            this.$watch('focus', (value, oldValue) => {
                // TASK-156d-T9／CD-156d-10b：在 recomputeCostar() 覆寫 this.costarRows
                // 之前先記錄舊值長度，供 _handleActressFocusChange 算 wasCostarVisible
                // 用（見該函式內部註解——讀 this.showCostar 當代理值在「同一位女優
                // 快速二連點、第二次點擊發生在第一次動畫 onComplete 之前」的情境會
                // 是 stale 的，因為 showCostar 只在 onComplete 才寫入）。
                const oldCostarRowsLength = this.costarRows.length;
                this.recomputeScopedCount();
                this.redrawYears();
                this.redrawDonut();
                this.redrawTags();
                this.redrawAge();
                this.redrawDirector();
                this.redrawSeries();
                this.recomputeTop20();
                this.recomputeGantt();
                this.recomputeSolo();
                this._maybePlayPinPulse();
                this.recomputeCostar();
                this._handleActressFocusChange(oldValue, oldCostarRowsLength);
            });

            if (window.__registerPage) {
                window.__registerPage({
                    cleanup: () => {
                        _pageAlive = false;
                        disposeAll();
                    },
                });
            }

            await this._loadSnapshot();
        },
    };
}
