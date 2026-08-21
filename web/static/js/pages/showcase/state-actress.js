/**
 * state-actress.js — Showcase ESM（54b-T1b）
 *
 * 女優模式：loadActresses / filter / sort / CRUD / lightbox / chips helpers。
 * 從 state-base.js import 共用大陣列（F1：移出 Alpine reactive scope）。
 */

import { _actresses, _filteredActresses, _actressesLoaded, _nameToGroup, _loadAliasMap, _killLightboxTimelines, _setActressesLoaded, _setActresses, _setFilteredActresses } from '@/showcase/state-base.js';
import { normalizePillValue } from '@/shared/pill-filter.js';
import { actressAgeValue, actressHeightValue, actressCupValue, actressMetricRange } from '@/shared/actress-metric.js';
import { buildActressPillPredicate } from '@/shared/actress-pill-filter.js';

/** height 顯示單位（CD-116b-11 模組常數，不進 i18n） */
var CM_UNIT = 'cm';

/** 117-T4：片庫加入面板首批／每批可見列數（初值、close 重置、expand 增量三處共用） */
var LIB_PAGE_SIZE = 40;

/** 117-T5：全域併發上限，對齊 core/scraper.py:40 的 MAX_WORKERS = 2（CD-117-8 ①） */
var LIB_MAX_INFLIGHT = 2;

/**
 * height pill value/value2 共用：extractor 解得出數值就用數字字串，否則退回 raw（永不寫入字面 'null'）。
 *
 * Codex PR review P2（#132）：`normalizeHeightPillValue` 同時服務兩種來源——
 * 燈箱點擊來的刮削值（`'160cm'`，需要 extractor 剝單位）與使用者在自訂區間打的字。
 * `<input type="number">` 接受科學記法（`1e2` 是合法輸入、`badInput` 為 false、`Number()` 得 100），
 * 但 `parseInt('1e2')` 在 `e` 就停下 → 1。症狀最惡的是 `≥`：pill 顯示 `≥1cm`、牆上一個人都不會少，
 * 使用者以為「篩選沒作用」，而他打的 100 已經被吃成 1（`=`／`≤` 則是牆幾乎清空，至少看得出來）。
 *
 * 修法刻意**不繞過 extractor**（CD-116b-1「單位剝離唯一落點」；CD-116c-4b 已駁回
 * 「看起來像純數字就跳過 extractor」的分支寫法）：只把**數字字面**先轉成標準十進位形式，
 * `parseInt` 仍是最終裁決者。既有被鎖住的三個案例逐位元組不變——
 * `'0250'`→250、`'25.5'`→25（截斷仍由 parseInt 做）、`'160cm'`→`Number` 得 NaN 故原樣交給 extractor。
 */
function normalizeHeightPillValue(raw) {
    // 空字串／null 明確排除：Number('') 與 Number(null) 都是 0（有限），不擋會把
    // 「沒有值」變成 '0'，與修這條之前的行為不同。這裡只處理「真的有字」的情況。
    var s = raw == null ? '' : String(raw).trim();
    var n = s === '' ? NaN : Number(s);
    var pre = Number.isFinite(n) ? String(n) : raw;
    var h = actressHeightValue({ height: pre });
    return (h == null) ? String(raw) : String(h);
}

/** 116c-T2（CD-116c-2）：空/空白/null 一律回 null；否則回 trim 後的字串 */
function _trimOrNull(v) {
    if (v == null) return null;
    var s = String(v).trim();
    return s === '' ? null : s;
}

/**
 * 116c P2-2（Codex PR review）：單一格「有沒有字」與「能不能取到合法值」的判斷唯一所有者。
 * <input type="number"> 對無法解析的輸入（如 1e999）會把 .value 回成空字串，若只看
 * _trimOrNull(rawText) 會把「使用者確實打了東西但打壞了」誤判成「這格是空的」，導致
 * 狀態機落到錯的分支（態①/②），使用者打的內容或另一格的合法值被靜默吃掉/誤用。
 * badInput（來自 validity.badInput，markup @input 寫入 _pillEditor.badLo/badHi）：
 *   有字（has=true）、但 raw 一律 null——讓 _pillOperandOk 那一關擋下，不新增第二套合法性判斷。
 * 非 badInput：raw = _trimOrNull(rawText)，has = raw != null（沿用既有語意）。
 * 不適用 _pillEditorHasRangeInput()（✓✗ 顯示條件維持只讀 model 值，見該函式旁註解）。
 */
function _pillFieldValue(rawText, isBad) {
    if (isBad) return { has: true, raw: null };
    var t = _trimOrNull(rawText);
    return { has: t != null, raw: t };
}

export function stateActress() {
    return {

        // --- 44a: 女優模式狀態初始值 ---
        showFavoriteActresses: false,   // mode toggle，切換影片/女優 grid
        actressCount: 0,                // mirror _actresses.length
        filteredActressCount: 0,        // mirror _filteredActresses.length
        paginatedActresses: [],         // CD-9：全量 = _filteredActresses，不分頁
        actressSearch: '',              // 女優搜尋框（獨立於 search）
        actressSort: 'video_count',     // 預設排序
        actressOrder: 'desc',           // 預設降冪
        actressLoading: false,          // 載入中
        actressLightboxIndex: -1,       // 指向 _filteredActresses 的索引
        currentLightboxActress: null,   // 當前 lightbox 女優；與 currentLightboxVideo 互斥
        actressLightboxSource: null,    // T5: 'hero' | 'grid' | null — 進入路徑（CD-9）
        _ghostFlyInFlight: false,       // T7: 跨模式 ghost fly 並發保護 flag（CD-13）
        _actressChipsExpanded: { aliases: false, info: false },  // chips 展開狀態
        _addActressName: '',            // + 新增 input（T4 直接新增路徑沿用）
        _addingActress: false,          // 新增 loading

        // 117-T3/T4: 從片庫加入女優面板（T5 接手 queue）
        actressAddPanelOpen: false,
        _libRows: [],
        _libLoading: false,
        _libError: null,            // null | true（布林旗標；文案在 markup 由 t() 取）
        _libQuery: '',
        _libVisibleCount: LIB_PAGE_SIZE,
        _libTotal: 0,
        _libLoadGen: 0,             // 117-T4: stale response guard
        _libRowState: {},
        _libCovered: {},
        _libInFlight: 0,
        _libQueue: [],        // 排隊中的 primary_name 陣列（FIFO＝使用者點擊順序）；markup 未綁，仍宣告
        _libRowError: {},     // primary_name → i18n key 字串（只在 'error' 態有值）

        // T3.3: Remove Actress fluent-modal 狀態
        removeActressModalOpen: false,
        _removeActressLoading: false,
        _pendingRemoveActressName: null,

        // 44b: 精準匹配狀態
        _isPreciseActressMatch: false,
        _matchedActress: null,
        _preciseMatchSource: null,
        _favoriteHeartLoading: false,
        _heroCardImageError: false,
        _heroCardImageLoaded: false,   // 67-A3: hero actress photo 載入旗標（獨立於 video _imgLoaded，CD-67-4）
        _fetchSamplesLoading: false,
        _fetchSamplesFailed: {},

        // --- helpers in return {} ---

        // 44a: helper — 更新 actressLightboxIndex + currentLightboxActress 一致性
        // 100b-T2a（§B-1c，裁決2）：video→actress 橋接的主要收斂點——本函式是
        // openActressLightbox()/prevActressLightbox()/nextActressLightbox() 三者共用的賦值
        // helper，涵蓋 actress→actress 切換與 video-grid→actress-grid 首次開啟兩種情境。
        // x-if="currentLightboxActress"（showcase.html）可能由 false 翻 true（重新掛載）——
        // reset 必須排在賦值 currentLightboxActress **之前**同步呼叫（gotchas-frontend §8b：
        // $watch 姊妹 watcher 是非同步 effect flush，對掛載那一幀擋不住）。
        _setActressLightboxIndex(idx) {
            this._resetMask();
            this.actressLightboxIndex = idx;
            this.currentLightboxActress = (idx >= 0 && idx < _filteredActresses.length)
                ? _filteredActresses[idx] : null;
            this.currentLightboxVideo = null;    // 互斥：清除影片
            this._actressChipsExpanded = { aliases: false, info: false };
            this._refreshActressPhotoLoaded();   // §B-2b：切換/開啟女優皆走此函式，唯一呼叫點
        },

        // 44b: 精準匹配 helpers
        _clearPreciseMatch() {
            this._isPreciseActressMatch = false;
            this._matchedActress = null;
            this._preciseMatchSource = null;
            this._favoriteHeartLoading = false;
            this._heroCardImageError = false;
            this._heroCardImageLoaded = false;   // 67-A3: 換命中對象要重現 skeleton
        },

        // TASK-115-T8：staleness guard 依「目前有效的判斷詞」來源分流。
        // 'manual'/'metadata' 兩條既有路徑逐位元組不變（比對 this.search）；
        // 'pill' 是新分支——有 pill 時 this.search 依規則必須是空字串，capturedTerm 卻是
        // pill 的 value（非空字串），兩者必然不相等，若沿用舊的單一比較式，這個 guard
        // 會在每次呼叫都無條件擋下，女優 pill 永遠查不到人、hero card 永遠不出現且無錯誤。
        _isExpectedHeroCardTerm(capturedTerm, source) {
            if (source === 'pill') {
                return this.pills.length === 1
                    && this.pills[0].dim === 'actress'
                    && this.search.trim() === ''
                    && normalizePillValue(this.pills[0].value) === normalizePillValue(capturedTerm);
            }
            return this.search.trim() === capturedTerm;
        },

        async _checkPreciseActressMatch(term, source) {
            var capturedTerm = (term || '').trim();
            if (!_actressesLoaded && _actresses.length === 0) {
                await this.loadActresses();
            }
            if (!this._isExpectedHeroCardTerm(capturedTerm, source)) return;
            this._heroCardImageError = false;
            this._heroCardImageLoaded = false;   // 67-A3: 換命中對象要重現 skeleton
            var found = _actresses.find(function(a) {
                var group = _nameToGroup[a.name] || [a.name];
                return group.indexOf(capturedTerm) !== -1;
            });
            if (found) {
                this._isPreciseActressMatch = true;
                this._matchedActress = found;
                this._preciseMatchSource = source;
                // T5: hero card 出現動畫 — 只在 is_favorite 時觸發（card 才會 x-show=true）
                if (found.is_favorite && !this.showFavoriteActresses) {
                    var self = this;
                    this.$nextTick(function () {
                        requestAnimationFrame(function () {
                            var heroEl = document.querySelector('.hero-card');
                            window.ShowcaseAnimations?.playHeroCardAppear?.(heroEl);
                        });
                    });
                }
            } else if (source === 'metadata' || source === 'pill') {
                this._isPreciseActressMatch = true;
                this._matchedActress = { name: capturedTerm, is_favorite: false };
                this._preciseMatchSource = source;
            } else {
                this._clearPreciseMatch();
            }
        },

        // --- 44a: 女優模式核心方法 ---

        toggleActressMode() {
            // CD-116b-8b：切換影片/女優模式時無條件 teardown 浮層草稿
            this._teardownPillEditors();
            if (this.lightboxOpen) this.closeLightbox();
            var self = this;
            var isEnteringActress = !this.showFavoriteActresses;
            var oldMode = isEnteringActress ? (this.mode || 'grid') : 'actress';
            var newMode = isEnteringActress ? 'actress' : (this.mode || 'grid');
            var gen = ++this._animGeneration;

            // Codex P1: 抽出 callback body 作 fallback；若 playModeCrossfade 不可用直接同步呼叫
            var flipAndFadeIn = function () {
                if (self._animGeneration !== gen) return;
                // 翻轉（觸發 x-if 重新掛載 DOM）
                self.showFavoriteActresses = isEnteringActress;
                var needEntry = false;
                if (isEnteringActress) {
                    self._clearPreciseMatch();
                    if (_actresses.length === 0) {
                        self.loadActresses();
                    } else {
                        needEntry = true;
                    }
                } else {
                    needEntry = true;
                    // TASK-115-T8：無條件呼叫（不再用 `if (searchTerm)` 短路）——pill 跨模式
                    // 保留（spec §4.10），「文字為空但有一枚持久化的女優 pill」這個切回情境
                    // 若只在文字非空才 reconcile 會漏掉，卡不會在切回影片模式時出現。
                    self._reconcileHeroCard();
                }
                // Phase 2: $nextTick 後 fade-in 新容器
                var gen2 = ++self._animGeneration;
                self.$nextTick(function () {
                    if (self._animGeneration !== gen2) return;
                    var newSelector = newMode === 'actress' ? '.actress-grid'
                        : newMode === 'table' ? '.showcase-table-wrapper'
                        : newMode === 'list' ? '.showcase-list-wrapper'
                        : '.showcase-grid';
                    var newEl = document.querySelector(newSelector);
                    // Codex P2: reduced-motion / gsap missing 由 helper 內 shouldSkip / typeof 守衛處理
                    window.ShowcaseAnimations?.playContainerFadeIn?.(newEl);
                    if (needEntry) {
                        var grid = self._getActiveGrid();
                        window.ShowcaseAnimations?.playEntry?.(grid);
                    }
                });
                self.saveState();
            };

            var fade = window.ShowcaseAnimations && window.ShowcaseAnimations.playModeCrossfade;
            if (typeof fade === 'function') {
                fade.call(window.ShowcaseAnimations, oldMode, null, null, {
                    onOldFadeComplete: flipAndFadeIn
                });
            } else {
                // P1 fallback: animations.js 不可用 → 直接同步翻轉 + 進入 fade-in
                flipAndFadeIn();
            }
        },

        async loadActresses() {
            this.actressLoading = true;
            try {
                var resp = await fetch('/api/actresses');
                if (!resp.ok) {
                    _actresses.splice(0, _actresses.length);
                    _filteredActresses.splice(0, _filteredActresses.length);
                    this.actressCount = 0;
                    this.filteredActressCount = 0;
                    return;
                }
                var data = await resp.json();
                if (!data.success) {
                    _actresses.splice(0, _actresses.length);
                    _filteredActresses.splice(0, _filteredActresses.length);
                    this.actressCount = 0;
                    this.filteredActressCount = 0;
                    return;
                }
                var acts = data.actresses || [];
                _setActresses(acts);
                // 45: alias map（冪等，init 可能已載入）
                await _loadAliasMap();
                this.applyActressFilterAndSort();
                // 卡片進場動畫
                var gen = ++this._animGeneration;
                var self = this;
                this.$nextTick(function () { requestAnimationFrame(function () {
                    if (self._animGeneration !== gen) return;
                    var grid = self._getActiveGrid();
                    window.ShowcaseAnimations?.playEntry?.(grid);
                }); });
            } catch (e) {
                console.error('[Showcase] Failed to fetch actresses:', e);
                _actresses.splice(0, _actresses.length);
                _filteredActresses.splice(0, _filteredActresses.length);
                this.actressCount = 0;
                this.filteredActressCount = 0;
            } finally {
                this.actressLoading = false;
                _setActressesLoaded(true);
            }
        },

        applyActressFilterAndSort() {
            // Stage 0（116a-T2）：pill 精準比對，跑在既有名字模糊搜尋之前（鏡射 spec §3.1 步驟 6）
            var pillMatch = buildActressPillPredicate(this.actressPills);
            var base = _actresses.filter(pillMatch);

            // 1. Filter（名字模糊搜尋，改讀 base 而非 _actresses）
            var q = this.actressSearch.trim();
            var filtered = base.slice();
            if (q) {
                var ql = q.toLowerCase();
                filtered = base.filter(function (a) {
                    var group = _nameToGroup[a.name] || [a.name];
                    return group.some(function(n) { return n && n.toLowerCase().includes(ql); });
                });
            }

            // 2. Sort
            var sort = this.actressSort;
            var order = this.actressOrder;
            filtered = filtered.slice().sort(function (a, b) {
                if (sort === 'name') {
                    var cmp = a.name.localeCompare(b.name, 'ja');
                    return order === 'asc' ? cmp : -cmp;
                }
                var va, vb;
                if (sort === 'video_count') {
                    va = a.video_count || 0;
                    vb = b.video_count || 0;
                } else if (sort === 'added_at') {
                    va = a.created_at || '';
                    vb = b.created_at || '';
                } else if (sort === 'age') {
                    va = actressAgeValue(a);    va = va != null ? va : Infinity;
                    vb = actressAgeValue(b);    vb = vb != null ? vb : Infinity;
                } else if (sort === 'height') {
                    va = actressHeightValue(a); va = va != null ? va : Infinity;
                    vb = actressHeightValue(b); vb = vb != null ? vb : Infinity;
                } else if (sort === 'cup') {
                    va = actressCupValue(a);    va = va != null ? va : Infinity;
                    vb = actressCupValue(b);    vb = vb != null ? vb : Infinity;
                } else {
                    va = a.video_count || 0;
                    vb = b.video_count || 0;
                }
                // null-last：Infinity 值永遠排最後（不因 desc 翻轉）
                if (va === Infinity && vb === Infinity) return 0;
                if (va === Infinity) return 1;
                if (vb === Infinity) return -1;
                if (order === 'asc') {
                    return va < vb ? -1 : va > vb ? 1 : 0;
                } else {
                    return va > vb ? -1 : va < vb ? 1 : 0;
                }
            });

            // 3. Update state
            _setFilteredActresses(filtered);
            this.actressCount = _actresses.length;
            this.filteredActressCount = _filteredActresses.length;
            this.paginatedActresses = _filteredActresses.slice();  // CD-9: 全量，不分頁
        },

        // CD-116b-1b：寫入 actressPills 的單一所有者（正規化 ＋ 同維度整包取代 ＋ apply）
        _setActressPill(pill) {
            // 單位剝離唯一落點：走既有 extractor，不得 replace/parseInt（CD-116b-1）；value/value2 對稱
            var v = pill.dim === 'height' ? normalizeHeightPillValue(pill.value) : String(pill.value);
            var v2 = pill.value2 == null || pill.value2 === ''
                ? null
                : (pill.dim === 'height' ? normalizeHeightPillValue(pill.value2) : String(pill.value2));
            var next = this.actressPills.filter(function (p) { return p.dim !== pill.dim; });
            next.push({
                dim: pill.dim,
                op: pill.op,
                value: v,
                value2: v2,
            });
            this.actressPills = next;
            this.applyActressFilterAndSort();  // CD-116a-9：直呼，不走 _sortWithFlip
        },

        // CD-116b-1b：降格為 adapter，簽名不變
        addActressPill(dim, value) {
            this._setActressPill({ dim: dim, op: '=', value: value, value2: null });
        },

        removeActressPill(dim, value) {
            var v = String(value);
            var next = this.actressPills.filter(function (p) { return !(p.dim === dim && p.value === v); });
            if (next.length === this.actressPills.length) return;  // 沒命中：不重跑
            this.actressPills = next;
            // CD-116b-8b：移除的正是編輯中 dim → teardown 草稿
            if (this._pillEditor && this._pillEditor.dim === dim) this._pillEditor = null;
            this.applyActressFilterAndSort();
        },

        // ── TASK-116b-T2：浮層狀態機（無 markup；CD-116b-5 / CD-116b-3 / CD-116b-8）──

        // 開啟：pill（四欄位）→ 草稿（五欄位）淺拷貝映射；不得持有 actressPills 內物件參考
        _openPillEditor(pill) {
            if (pill.op === 'range') {
                this._pillEditor = {
                    dim: pill.dim,
                    op: pill.op,
                    value: pill.value,
                    rangeLo: pill.value,
                    rangeHi: pill.value2,
                    badLo: false,
                    badHi: false,
                };
            } else {
                this._pillEditor = {
                    dim: pill.dim,
                    op: pill.op,
                    value: pill.value,
                    rangeLo: null,
                    rangeHi: null,
                    badLo: false,
                    badHi: false,
                };
            }
        },

        // 第二層防禦（比照 _onActressMetadataClick）：markup 會擋手機按鈕，狀態層也要提早 return
        _togglePillEditor(pill) {
            if (!this._pillPopoverEnabled) return;
            if (this._pillEditor && this._pillEditor.dim === pill.dim) {
                this._pillEditor = null;
                return;
            }
            this._openPillEditor(pill);
        },

        // 116c-T2（CD-116c-2）：三顆鈕操作數的單一判斷點。狀態判定只看「有沒有字」，
        // 不看「是不是合法數字」——1e999 要進態②再被 _pillOperandOk 擋下，不能被當成
        // 「空」而靜默落回態①（使用者打的東西被無聲丟掉，他不會知道）。
        _pillOperandFor(op) {
            var d = this._pillEditor;
            if (!d) return null;
            var lo = _pillFieldValue(d.rangeLo, d.badLo);
            var hi = _pillFieldValue(d.rangeHi, d.badHi);
            var raw;
            if (!lo.has && !hi.has) raw = d.value;                // 態①：pill 目前的值
            else if (!hi.has) raw = lo.raw;                       // 態②：只有左格（壞輸入 raw=null）
            else if (!lo.has) raw = hi.raw;                       // 態②：只有右格（壞輸入 raw=null）
            else raw = (op === '<=') ? hi.raw : lo.raw;           // 態③：≤ 取右，≥ 與 = 取左
            return this._pillOperandOk(raw) ? raw : null;
        },

        // 合法性依維度分流：cup 是 'B' 這種非數字標記，不得跑 Number.isFinite；
        // age/height 才驗有限數（1e999 之類的 Infinity 在此被擋下）。
        _pillOperandOk(raw) {
            if (raw == null) return false;
            var d = this._pillEditor;
            if (!d || d.dim === 'cup') return true;
            return Number.isFinite(Number(raw));
        },

        // 116c-T2（CD-116c-1）：三顆運算子鈕的唯一提交路徑——取操作數 → 寫入 → 關閉。
        // operand 為 null（不合法/無法判定）→ early return，不寫入、不關閉。
        _applyPillOp(op) {
            if (!this._pillEditor) return;
            var operand = this._pillOperandFor(op);
            if (operand == null) return;
            this._setActressPill({ dim: this._pillEditor.dim, op: op, value: operand, value2: null });
            this._pillEditor = null;
        },

        // ✓✗ 的顯示條件（T3 markup 會綁 x-show）：_pillEditor 為 null 時必須安全回 false
        // （浮層是 x-show，關閉時 markup 仍會求值）。必須即時反映輸入內容。
        _pillEditorHasRangeInput() {
            if (!this._pillEditor) return false;
            return _trimOrNull(this._pillEditor.rangeLo) != null
                || _trimOrNull(this._pillEditor.rangeHi) != null;
        },

        // 116c-T2（CD-116c-6）：第 ③ 行資料範圍提示的呈現層。_pillEditor 為 null 時必須
        // 安全回 ''（同上，x-show 求值前提）；cup 恆回 ''（無自訂區間列）。
        _pillDimRangeHint() {
            if (!this._pillEditor) return '';
            var dim = this._pillEditor.dim;
            var extractor = dim === 'age' ? actressAgeValue
                : dim === 'height' ? actressHeightValue
                    : null;
            if (!extractor) return '';
            var range = actressMetricRange(_actresses, extractor);
            if (range == null) return '';
            return '（' + range.min + ' ~ ' + range.max + '）';
        },

        // 提交：自訂區間列的 ✓（CD-116c-3）。單邊語意用委派——不自己組 value2:null 的
        // range 物件，讓 AC-C7（✓ 與運算子鈕逐欄位相同）結構上成立。
        _commitPillEditor() {
            if (!this._pillEditor) return;
            var d = this._pillEditor;
            var lo = _pillFieldValue(d.rangeLo, d.badLo);
            var hi = _pillFieldValue(d.rangeHi, d.badHi);
            if (!lo.has && !hi.has) return;                     // 兩格皆空：✓ 不存在（防禦性 return）
            if (!hi.has) return this._applyPillOp('>=');        // 只有左格 → 委派（壞輸入交給 operandOk 擋）
            if (!lo.has) return this._applyPillOp('<=');        // 只有右格 → 委派（壞輸入交給 operandOk 擋）
            if (lo.raw == null || hi.raw == null) return;       // 116c P2-2：任一格壞輸入 → fail-safe，不寫入、不關閉
            var loN = Number(lo.raw);
            var hiN = Number(hi.raw);
            if (!Number.isFinite(loN) || !Number.isFinite(hiN)) return;   // fail-safe：不寫入、不關閉
            // 對調（spec-116 §5.5 明文保留）：比較用 Number，寫入用 trim 過的原始字串
            var loRaw = lo.raw;
            var hiRaw = hi.raw;
            if (loN > hiN) {
                var tmp = loRaw;
                loRaw = hiRaw;
                hiRaw = tmp;
            }
            this._setActressPill({ dim: d.dim, op: 'range', value: loRaw, value2: hiRaw });
            this._pillEditor = null;
        },

        // ✗ 取消：只丟棄草稿，不碰 actressPills（spec §5.6；函式體不得引用 actressPills）
        _cancelPillEditor() {
            this._pillEditor = null;
        },

        onActressSearchChange() {
            this.applyActressFilterAndSort();
        },

        // TASK-116a-T4: 女優搜尋框 Backspace 刪最後一枚 actressPills（鏡射 onSearchBackspace）
        onActressSearchBackspace(event) {
            if (event.isComposing) return;
            // 有字：交給瀏覽器原生刪字，不 preventDefault、不動 pill
            if (event.target.value !== '') return;
            // 游標必須在最左且選取為 collapsed；非 collapsed 選取不得刪 pill
            if (!(event.target.selectionStart === 0 && event.target.selectionEnd === 0)) return;
            if (this.actressPills.length === 0) return;
            var last = this.actressPills[this.actressPills.length - 1];
            this.removeActressPill(last.dim, last.value);
        },

        onActressSortChange() {
            this._sortWithFlip(() => {
                this.applyActressFilterAndSort();
            });
        },

        toggleActressOrder() {
            this._sortWithFlip(() => {
                this.actressOrder = this.actressOrder === 'asc' ? 'desc' : 'asc';
                this.applyActressFilterAndSort();
            });
        },

        // --- 44a: 女優 Lightbox 方法 ---

        openActressLightbox(index) {
            if (this.lightboxCloseTimer) {
                clearTimeout(this.lightboxCloseTimer);
                this.lightboxCloseTimer = null;
            }
            if (this._lightboxAnimating) return;
            if (this.lightboxOpen && this.actressLightboxIndex === index) return;

            // 若已開啟（切換女優）
            if (this.lightboxOpen && this.actressLightboxIndex !== index) {
                _killLightboxTimelines({ killOpen: false, killSwitch: true });
                var direction = index > this.actressLightboxIndex ? 'next' : 'prev';
                this._setActressLightboxIndex(index);
                this.actressLightboxSource = 'grid';   // T5: 切換女優分支
                // T3: fire-and-forget 即時查 aliases
                this._fetchLiveAliases(this.currentLightboxActress?.name, index);
                var lbGen = ++this._lightboxGeneration;
                var self = this;
                this.$nextTick(function () {
                    if (self._lightboxGeneration !== lbGen) return;
                    var contentEl = document.querySelector('.showcase-lightbox .lightbox-content');
                    if (contentEl && window.ShowcaseAnimations?.playLightboxSwitch) {
                        self._lightboxAnimating = true;
                        var tl = window.ShowcaseAnimations.playLightboxSwitch(contentEl, direction, {
                            onComplete: function () { self._lightboxAnimating = false; }
                        });
                        if (!tl) self._lightboxAnimating = false;
                    }
                });
                return;
            }

            // ★ ghost fly — 在 state 變更前捕獲 fromRect
            var fromRect = null;
            var coverSrc = null;
            if (!this.lightboxOpen) {
                var gridEl = this._getActiveGrid();
                if (gridEl) {
                    var actress = _filteredActresses[index];
                    var cardEl = actress
                        ? gridEl.querySelector('[data-flip-id="actress:' + CSS.escape(actress.name) + '"]')
                        : null;
                    if (cardEl) {
                        var imgEl = cardEl.querySelector('.actress-card-photo img');
                        if (imgEl && imgEl.complete && imgEl.getBoundingClientRect().width > 0) {
                            fromRect = imgEl.getBoundingClientRect();
                            coverSrc = imgEl.src;
                        }
                    }
                }
            }

            this._setActressLightboxIndex(index);
            this.actressLightboxSource = 'grid';   // T5: 首次進入分支
            var lightboxElPre = document.querySelector('.showcase-lightbox');
            if (lightboxElPre) lightboxElPre.classList.add('gsap-animating');
            this.lightboxOpen = true;
            document.body.classList.add('overflow-hidden');
            // T3: fire-and-forget 即時查 aliases
            this._fetchLiveAliases(this.currentLightboxActress?.name, index);

            var self = this;
            var lbGen = ++this._lightboxGeneration;
            this.$nextTick(function () {
                if (self._lightboxGeneration !== lbGen) return;
                var lightboxEl = document.querySelector('.showcase-lightbox');
                if (!lightboxEl) return;

                if (fromRect && window.GhostFly && window.GhostFly.playGridToLightbox) {
                    self._lightboxAnimating = true;
                    window.GhostFly.playGridToLightbox(fromRect, lightboxEl, {
                        coverSrc: coverSrc,
                        onComplete: function () { self._lightboxAnimating = false; }
                    });
                    if (window.ShowcaseAnimations && window.ShowcaseAnimations.playLightboxOpen) {
                        window.ShowcaseAnimations.playLightboxOpen(lightboxEl, { skipCover: true });
                    }
                } else {
                    self._lightboxAnimating = true;
                    var tl = window.ShowcaseAnimations?.playLightboxOpen?.(lightboxEl, {
                        onComplete: function () { self._lightboxAnimating = false; }
                    });
                    if (!tl) self._lightboxAnimating = false;
                }
            });
        },

        closeActressLightbox() {
            this.closeLightbox();
        },

        prevActressLightbox() {
            // 124c-T3（spec-124c §3.4）：對焦編輯進行中不換人。放在 _pickerOpen 之前，
            // 讓四個 chokepoint 的「新 guard ＝第一行」零例外（兩者都是零副作用 early-return，
            // 順序在操作上等價）。走 state-lightbox.js 的共用判斷式而非直接讀遮罩狀態——
            // 100b-T5 CD-1 明訂本檔不得直接碰遮罩狀態識別字（同 this._resetMask() 的慣例）。
            if (this._navBlockedByFocalEdit()) return;
            // 100b PR#108 Codex P2-A：picker（.actress-picker-overlay）開著時擋女優切換——
            // picker 候選是「這個女優」的候選照片，若切到別的女優但 picker 沒關，
            // _onPickerSelect 讀當下 currentLightboxActress?.name 會把舊女優的候選寫進
            // 新女優（張冠李戴）。本函式是**女優模式下**（showFavoriteActresses=true）鍵盤
            // ArrowLeft 女優分支（handleKeydown）與 .lightbox-nav-prev @click 的共同
            // chokepoint，一次擋住兩條路徑。⚠️ 影片模式的 hero-card（精準命中女優）也能開
            // picker，但該情境按方向鍵走的是 video 分支（nextLightboxVideo，無此 guard）——
            // 那條**不會**張冠李戴（overlay 的 x-show 綁 currentLightboxActress、切走即隱藏，
            // _onPickerSelect 亦 null-check capturedName），只留 _pickerOpen 殘留的化妝品級
            // 副作用（吞掉第一次 Esc），屬既有、範圍外。手機 swipe
            // 已在更前面的 _lbTouchEnd 對 _pickerOpen 做同語意 pure-block guard（本函式
            // 因此永遠不會在 swipe-picker-open 情境下被呼叫到，這裡的擋是給前兩條路徑用，
            // 對 swipe 是安全的重複判斷、不影響既有行為）。純擋（不 _closePicker()），
            // 照抄 _lbTouchEnd 既有語意，保持一致。
            if (this._pickerOpen) return;
            _killLightboxTimelines();
            this._lightboxAnimating = false;
            var lbEl = document.querySelector('.showcase-lightbox');
            if (lbEl) lbEl.classList.remove('gsap-animating');

            if (this.actressLightboxIndex <= 0) return;
            var newIdx = this.actressLightboxIndex - 1;
            this._setActressLightboxIndex(newIdx);
            // P2 Codex: 方向鍵切換也要 fetch live alias
            this._fetchLiveAliases(this.currentLightboxActress?.name, newIdx);

            var lbGen = ++this._lightboxGeneration;
            var self = this;
            this.$nextTick(function () {
                if (self._lightboxGeneration !== lbGen) return;
                var contentEl = document.querySelector('.showcase-lightbox .lightbox-content');
                if (contentEl && window.ShowcaseAnimations?.playLightboxSwitch) {
                    self._lightboxAnimating = true;
                    var tl = window.ShowcaseAnimations.playLightboxSwitch(contentEl, 'prev', {
                        onComplete: function () { self._lightboxAnimating = false; }
                    });
                    if (!tl) self._lightboxAnimating = false;
                }
            });
        },

        nextActressLightbox() {
            // 124c-T3（spec-124c §3.4）：對焦編輯進行中不換人。放在 _pickerOpen 之前，
            // 讓四個 chokepoint 的「新 guard ＝第一行」零例外（兩者都是零副作用 early-return，
            // 順序在操作上等價）。走 state-lightbox.js 的共用判斷式而非直接讀遮罩狀態——
            // 100b-T5 CD-1 明訂本檔不得直接碰遮罩狀態識別字（同 this._resetMask() 的慣例）。
            if (this._navBlockedByFocalEdit()) return;
            // 100b PR#108 Codex P2-A：見 prevActressLightbox 同段註解（鏡射 guard，
            // 女優模式下 .lightbox-nav-next @click + 鍵盤 ArrowRight 女優分支的共同
            // chokepoint；影片模式 hero-card 的殘留副作用同該段說明，範圍外）。
            if (this._pickerOpen) return;
            _killLightboxTimelines();
            this._lightboxAnimating = false;
            var lbEl = document.querySelector('.showcase-lightbox');
            if (lbEl) lbEl.classList.remove('gsap-animating');

            if (this.actressLightboxIndex >= _filteredActresses.length - 1) return;
            var newIdx = this.actressLightboxIndex + 1;
            this._setActressLightboxIndex(newIdx);
            // P2 Codex: 方向鍵切換也要 fetch live alias
            this._fetchLiveAliases(this.currentLightboxActress?.name, newIdx);

            var lbGen = ++this._lightboxGeneration;
            var self = this;
            this.$nextTick(function () {
                if (self._lightboxGeneration !== lbGen) return;
                var contentEl = document.querySelector('.showcase-lightbox .lightbox-content');
                if (contentEl && window.ShowcaseAnimations?.playLightboxSwitch) {
                    self._lightboxAnimating = true;
                    var tl = window.ShowcaseAnimations.playLightboxSwitch(contentEl, 'next', {
                        onComplete: function () { self._lightboxAnimating = false; }
                    });
                    if (!tl) self._lightboxAnimating = false;
                }
            });
        },

        // --- 44a T4: Lightbox chips + metadata helpers ---

        _chipsLimit() {
            return window.innerWidth >= 768 ? 10 : 6;
        },

        // TASK-116a-T3: 取代 _actressCoreMetadata()——回傳結構化陣列，年齡/身高/罩杯三格可點（CD-116a-6）
        _actressCoreMetadataParts() {
            var a = this.currentLightboxActress; if (!a) return [];
            var canClick = this.actressLightboxSource === 'grid';   // spec §4.2 的 gate，單一求值點
            // spec §4.3 第 2 條：取不到值一律不符合——比不了大小的值不該變成條件，否則只會產生一枚永遠篩不到人、且畫面不解釋為什麼的死 pill；fail-closed 提前到入口。
            var parts = [];
            if (typeof a.video_count === 'number') {
                parts.push({ key: 'count', text: a.video_count + window.t('showcase.unit.films'), clickable: false });
            }
            if (a.age) parts.push({ key: 'age', text: a.age + window.t('search.unit.age'), clickable: canClick && actressAgeValue({ age: a.age }) != null, dim: 'age', value: a.age });
            if (a.birth) parts.push({ key: 'birth', text: a.birth, clickable: false });
            if (a.height) parts.push({ key: 'height', text: a.height, clickable: canClick && actressHeightValue({ height: a.height }) != null, dim: 'height', value: a.height });
            if (a.cup) parts.push({ key: 'cup', text: a.cup + window.t('search.unit.cup'), clickable: canClick && actressCupValue({ cup: a.cup }) != null, dim: 'cup', value: a.cup });
            if (a.bust && a.waist && a.hip) parts.push({ key: 'bwh', text: a.bust + '-' + a.waist + '-' + a.hip, clickable: false });
            return parts;
        },

        // TASK-116a-T3: 燈箱三格點擊 adapter（CD-116a-6）——先關燈箱再加 pill（FE-ALPINE-04，比照 searchActressFilms() 的順序）
        _onActressMetadataClick(dim, value) {
            if (this.actressLightboxSource !== 'grid') return;   // 防禦性：markup 已用 x-show 擋掉按鈕，這裡是第二層
            this.closeLightbox();
            this.addActressPill(dim, value);
            // 116b-T4：手機上剛從燈箱產生的 pill 必須看得見（toolbar 預設收合）。
            // 桌機無副作用：.mobile-toolbar-open 只在 ≤480px 有樣式、navbar 鈕 lg:hidden。
            Alpine.store('ui').toolbarOpen = true;
        },

        // TASK-116b-T1: 女優 pill 顯示文字（CD-116b-11）——op 切換符號、單位由顯示層補回
        _actressPillDisplayText(pill) {
            var unit = pill.dim === 'age'
                ? window.t('search.unit.age')
                : pill.dim === 'cup'
                    ? window.t('search.unit.cup')
                    : pill.dim === 'height'
                        ? CM_UNIT
                        : '';
            if (pill.op === 'range') {
                return pill.value + '~' + pill.value2 + unit;  // 116c-T2（CD-116c-7）：U+007E，非 en dash
            }
            var prefix = pill.op === '<=' ? '≤' : pill.op === '>=' ? '≥' : '=';
            return prefix + pill.value + unit;
        },

        // --- 44c T2: Actress card footer helpers ---

        _actressCardMiddle(actress) {
            if (!actress) return '';
            return (actress.video_count || 0) + window.t('showcase.unit.films');
        },

        _actressHoverInfo(actress) {
            if (!actress) return '';
            var parts = [];
            if (actress.height) parts.push(actress.height);
            if (actress.cup) parts.push(actress.cup + window.t('search.unit.cup'));
            if (actress.bust && actress.waist && actress.hip) {
                parts.push(actress.bust + '-' + actress.waist + '-' + actress.hip);
            }
            return parts.join(' · ');
        },

        // TASK-124b-T1: 女優卡資訊層 token 清單（M3i）。窄螢幕額外把作品數／年齡塞最前面
        // （video_count/age 用 != null，0 是合法值，CD-124b-12）；後三個 token 逐字鏡射
        // _actressHoverInfo() 的取值條件（truthy 鏈，非 != null 鏈）。
        _actressInfoTokens(actress) {
            if (!actress) return [];
            var tokens = [];
            if (this._isNarrow) {
                if (actress.video_count != null) {
                    tokens.push(actress.video_count + window.t('showcase.unit.films'));
                }
                if (actress.age != null) {
                    tokens.push(actress.age + window.t('search.unit.age'));
                }
            }
            if (actress.height) tokens.push(actress.height);
            if (actress.cup) tokens.push(actress.cup + window.t('search.unit.cup'));
            if (actress.bust && actress.waist && actress.hip) {
                tokens.push(actress.bust + '-' + actress.waist + '-' + actress.hip);
            }
            return tokens;
        },

        _allInfoChips() {
            var a = this.currentLightboxActress; if (!a) return [];
            return [].concat(a.tags || [], [a.hometown, a.nickname, a.agency, a.hobby, a.debut_work]).filter(Boolean);
        },

        _visibleAliases() {
            var all = this.currentLightboxActress?.aliases || [];
            return this._actressChipsExpanded.aliases ? all : all.slice(0, this._chipsLimit());
        },

        _aliasesOverflow() {
            return Math.max(0, (this.currentLightboxActress?.aliases || []).length - this._chipsLimit());
        },

        _visibleInfoChips() {
            var all = this._allInfoChips();
            return this._actressChipsExpanded.info ? all : all.slice(0, this._chipsLimit());
        },

        _infoChipsOverflow() {
            return Math.max(0, this._allInfoChips().length - this._chipsLimit());
        },

        _visibleVideoTags() {
            var tags = (this.currentLightboxVideo?.tags || '').split(',').filter(function(t) { return t.trim(); });
            return this._videoChipsExpanded ? tags : tags.slice(0, this._chipsLimit());
        },

        _videoTagsOverflow() {
            var tags = (this.currentLightboxVideo?.tags || '').split(',').filter(function(t) { return t.trim(); });
            return Math.max(0, tags.length - this._chipsLimit());
        },

        // --- 117-T3/T4: Actress add panel（T5 queue stubs 仍在） ---

        // AC-1.3 / AC-1.6：殼同步開，不 await 網路；每次開啟重載（無快取——片數必須與當下庫一致）
        //
        // CD-117-9（Codex PR review P2，已查證屬實）：只靠 `resolve(sync_primary) ∪ {req.name}`
        // 聯集進 _libCovered 的名字刻意不寫進 actress_aliases 表（見 web/routers/actress.py
        // 的 covered_names 組裝註解）——這代表「關閉再開回到空心、重新載入後看磁碟真相」
        // 不是自動成立的語意，是**這裡**這行 reset 讓它成立。_libCovered 本身沒有其他清空點
        // （全檔唯一寫入處是 _libMarkCovered()）；漏了這行，聯集進來的名字會在整個分頁存活期
        // 間單調遞增、永遠標實心，使用者對那個名字的收藏入口會被永久鎖住（要整頁重整才解）。
        openActressAddPanel() {
            this.actressAddPanelOpen = true;
            this._libQuery = '';
            this._libVisibleCount = LIB_PAGE_SIZE;
            this._libError = null;
            this._libRows = [];
            this._libTotal = 0;
            this._libCovered = {};        // CD-117-9：回到空心，磁碟真相由 _loadLibraryActresses() 的 is_favorite 重新權威判定
            this._libClearRowErrors();    // 117-T5：重開時清掉上一輪的紅字（queued/loading 保留）
            this._loadLibraryActresses();
        },

        closeActressAddPanel() {
            this.actressAddPanelOpen = false;
            this._libQuery = '';
            this._libVisibleCount = LIB_PAGE_SIZE;
            this._libError = null;
            // _libRows 不清：關閉動畫期間避免清單瞬間空掉；下次 open 會覆蓋
        },

        libAddBtnVisible() {
            // 四個依賴各自無條件讀完，再組合（不得寫成短路鏈——Alpine 的 effect
            // 依賴收集會漏訂閱鏈末條件，那個條件之後再變化畫面不會更新）
            var isActress   = this.showFavoriteActresses;
            var hasText     = this.actressSearch !== '';
            var hasPills    = this.actressPills.length > 0;
            var emptyResult = this.filteredActressCount === 0;
            return isActress && ((!hasText && !hasPills) || emptyResult);
        },

        // 形狀照 loadActresses()：ok → json → success；catch 清空；finally 關 loading
        // gen guard：開→關→開時，舊 response 不得覆寫新清單（finally 也要 gen 保護）
        async _loadLibraryActresses() {
            var gen = ++this._libLoadGen;
            this._libLoading = true;
            this._libError = null;
            try {
                var resp = await fetch('/api/actresses/library');
                if (gen !== this._libLoadGen) return;
                if (!resp.ok) {
                    this._libRows = [];
                    this._libTotal = 0;
                    this._libError = true;
                    return;
                }
                var data = await resp.json();
                if (gen !== this._libLoadGen) return;
                if (!data.success) {
                    this._libRows = [];
                    this._libTotal = 0;
                    this._libError = true;
                    return;
                }
                var rows = data.actresses || [];
                this._libRows = rows;
                this._libTotal = data.total ?? rows.length;
                this._libError = null;
            } catch (e) {
                if (gen !== this._libLoadGen) return;
                console.error('[Showcase] Failed to fetch library actresses:', e);
                this._libRows = [];
                this._libTotal = 0;
                this._libError = true;
            } finally {
                // 舊輪的 finally 不得把新輪的 loading 關掉
                if (gen === this._libLoadGen) {
                    this._libLoading = false;
                }
            }
        },

        // AC-5.1/5.2/5.3：完整 _libRows + 掃 names[] 全部別名；normalizePillValue 雙側正規化
        // 次序所有權在後端——此處零 .sort(
        libFilteredRows() {
            var q = normalizePillValue(this._libQuery);
            if (!q) return this._libRows;
            return this._libRows.filter(function (row) {
                var names = (row.names && row.names.length) ? row.names : [row.primary_name];
                return names.some(function (n) {
                    return normalizePillValue(n).indexOf(q) !== -1;
                });
            });
        },

        libVisibleRows() {
            return this.libFilteredRows().slice(0, this._libVisibleCount);
        },

        libHasMore() {
            return this.libFilteredRows().length > this._libVisibleCount;
        },

        // append-only：只加可見數，不重算、不重排（AC-6.4）
        libExpandMore() {
            this._libVisibleCount += LIB_PAGE_SIZE;
        },

        // AC-6.5：無過濾字用伺服器 total；有過濾字用當下相符筆數；?? 保 0（FE-JS-01）
        // 載入中／失敗時底部不顯示進度（避免「共 0 位」假訊號與錯誤文案並陳）
        libProgressText() {
            if (this._libLoading || this._libError) return '';
            var shown = this.libVisibleRows().length;
            var total = this._libQuery.trim()
                ? this.libFilteredRows().length
                : (this._libTotal ?? 0);
            return shown < total
                ? window.t('showcase.actress.panel.progress', { n: shown, m: total })
                : window.t('showcase.actress.panel.progress_all', { m: total });
        },

        // AC-5.4：載入中不顯示（避免閃一下）；_libError 時照常顯示（刻意降級保「打全名新增」）
        libShowDirectAdd() {
            return !this._libLoading
                && this._libQuery.trim() !== ''
                && this.libFilteredRows().length === 0;
        },

        // 原始字串，絕不正規化（正規化後丟 scraper 會查不到人）
        libDirectAddName() {
            return this._libQuery.trim();
        },

        // 走既有 addFavoriteActress 路徑；不進 T5 queue；不關面板、不清 query
        libDirectAdd() {
            if (this._addingActress) return;
            var name = this._libQuery.trim();
            if (!name) return;
            this._addActressName = name;
            return this.addFavoriteActress();
        },

        // AC-3.2/AC-4.1/AC-4.6：row.is_favorite（T1 端點快照）OR 本 session 內
        // _libCovered 涵蓋任一別名（T5）。this 必須在進 .some 前先取出（本檔慣用 ES5
        // function，callback 內拿不到元件 this——寫錯的症狀是「收藏成功但整排愛心都不變
        // 實心」，且直接呼叫 c.libRowFavorited(row) 的單元測試會照樣綠）。
        libRowFavorited(row) {
            if (!row) return false;
            if (row.is_favorite) return true;
            var covered = this._libCovered;
            var names = (row.names && row.names.length) ? row.names : [row.primary_name];
            return names.some(function (n) { return !!covered[n]; });
        },

        // 117-T5：pump 出隊重檢用，只吃單一名字（CD-117-9 權威來源）
        _libNameCovered(name) {
            return !!this._libCovered[name];
        },

        // 117-T5：每列顯示狀態；缺鍵＝'idle'（FE-JS-01 適用於此的字串版本）
        libRowState(row) {
            var name = row && row.primary_name;
            if (!name) return 'idle';
            return this._libRowState[name] || 'idle';
        },

        // 117-T5：該列的失敗原因文字（無錯誤時回 ''，與 libProgressText 同型）
        libRowErrorText(row) {
            var name = row && row.primary_name;
            if (!name) return '';
            var key = this._libRowError[name];
            return key ? window.t(key) : '';
        },

        // 117-T5：入隊（AC-4.3）——同步函式，@click 是 fire-and-forget，此處無「不得等
        // 網路」的 AC，加 async 不改變行為，故不另加字面守衛（僅寫進本註解）。
        libEnqueueFavorite(row) {
            if (this.libRowFavorited(row)) return;               // 已收藏／已 covered → no-op（AC-4.1）
            var name = row && row.primary_name;
            if (!name) return;
            var st = this._libRowState[name];
            if (st === 'queued' || st === 'loading') return;      // 同列連點 → no-op（INV-2 第一道）
            this._libRowError[name] = '';                         // 清掉上一次的失敗原因（重試路徑）
            this._libRowState[name] = 'queued';                   // 同步、當幀 → 立刻看得到「排隊中」
            this._libQueue.push(name);
            this._libPump();                                      // 同步啟動：有額度就當幀轉 'loading'
        },

        // 117-T5：併發上限 pump（CD-117-8①）。_libInFlight 的 ++ 與 -- 全檔各只有一處，
        // 且成對出現在本函式內——L5/L6 lint 鎖住這件事。_libFavoriteRequest() 內部不得
        // throw（見該函式），否則 .finally 之後會冒出 unhandled rejection。
        _libPump() {
            var self = this;
            while (this._libInFlight < LIB_MAX_INFLIGHT && this._libQueue.length > 0) {
                var name = this._libQueue.shift();
                // ── 出隊重檢（CD-117-9 的權威來源在這裡生效）──
                if (this._libNameCovered(name)) {
                    this._libRowState[name] = 'idle';
                    continue;
                }
                this._libInFlight++;                       // ← 全檔唯一一處 ++
                this._libRowState[name] = 'loading';
                this._libFavoriteRequest(name).finally(function () {
                    self._libInFlight--;                   // ← 全檔唯一一處 --
                    self._libPump();
                });
            }
        },

        // 117-T5：單次請求。一律先看 resp.status，不看 data.success——409 的 body 沒有
        // success 欄（〈現況分析 D〉），用 data.success 判會把 409 誤判成失敗，AC-4.5 直接破。
        async _libFavoriteRequest(name) {
            try {
                var resp = await fetch('/api/actresses/favorite', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name }),
                });
                var data = null;
                try { data = await resp.json(); } catch (e) { data = null; }   // 404/504 body 不保證存在

                if (resp.status === 200 && data && data.success) {
                    this._libDone(name, data);
                } else if (resp.status === 409) {
                    this._libDone(name, data);                                // AC-4.5：視為成功
                } else if (resp.status === 404) {
                    this._libFail(name, 'showcase.actress.addNotFound');
                } else if (resp.status === 504) {
                    this._libFail(name, 'showcase.actress.addTimeout');
                } else {
                    this._libFail(name, 'showcase.actress.panel.add_failed');
                }
            } catch (e) {
                console.error('[Showcase] Failed to favorite actress:', e);
                this._libFail(name, 'showcase.actress.panel.add_failed');
            }
        },

        // 117-T5：成功落地（200 與 409 共用，AC-4.6）。covered_names 恆聯集剛送出的
        // name——第二道保險，萬一欄位缺失，使用者看到的仍是「點了、成功了、愛心變實心」。
        _libDone(name, data) {
            this._libMarkCovered((data && data.covered_names) || [], name);
            this._libAddToWall(data && data.actress);
            this._libRowState[name] = 'idle';
            this._libRowError[name] = '';
        },

        // 117-T5：失敗落地（不 toast，裁決②——面板內已有逐列狀態與紅字原因）
        _libFail(name, key) {
            this._libRowState[name] = 'error';
            this._libRowError[name] = key;   // 存 i18n key，不存中文字面
        },

        // 117-T5：covered 標記，list 恆聯集 name；同時清掉每個被 covered 名字底下殘留的
        // 紅字（邊界條件裁決：實心優先，紅字不得留在實心列底下）。
        _libMarkCovered(list, name) {
            var self = this;
            var all = (list || []).concat([name]);
            all.forEach(function (n) {
                self._libCovered[n] = true;
                self._libRowError[n] = '';
            });
        },

        // 117-T5（AC-4.4/CD-117-12）：加進女優牆——data.actress 零轉換 push（形狀照
        // :1011 搜尋頁收藏路徑同款去重寫法），唯一收斂點是 applyActressFilterAndSort()。
        // 不得為了「當場看得到」而繞過篩選：不清空 actressSearch、不移除 actressPills、
        // 不直接 push 進 paginatedActresses。
        _libAddToWall(actress) {
            if (!actress || !actress.name) return;
            if (_actresses.find(function (a) { return a.name === actress.name; })) return;
            _actresses.push(actress);
            this.applyActressFilterAndSort();
        },

        // 117-T5：重開面板時把 'error' 態清成 'idle'（queued/loading/covered 保留，見
        // openActressAddPanel 旁的邊界條件表）。
        _libClearRowErrors() {
            var state = this._libRowState;
            Object.keys(state).forEach(function (name) {
                if (state[name] === 'error') state[name] = 'idle';
            });
        },

        // AC-2.4：只在真的被截斷時掛 title；必須在 mouseenter 量（modal display:none 時寬度全 0）
        libMaybeTitle(e) {
            var el = e.currentTarget;
            if (el.scrollWidth > el.clientWidth) el.title = el.textContent;
            else el.removeAttribute('title');
        },

        // --- 44a T5: Actress CRUD ---

        async addFavoriteActress() {
            if (this._addingActress || !this._addActressName.trim()) return;
            this._addingActress = true;
            try {
                const resp = await fetch('/api/actresses/favorite', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: this._addActressName.trim() }),
                });
                const data = await resp.json();
                if (resp.status === 409) {
                    this.showToast(window.t('showcase.actress.addDuplicate'), 'info');
                } else if (resp.status === 404) {
                    this.showToast(window.t('showcase.actress.addNotFound'), 'error');
                } else if (resp.status === 504) {
                    this.showToast(window.t('showcase.actress.addTimeout'), 'error');
                } else if (data.success) {
                    _actresses.push(data.actress);
                    this.applyActressFilterAndSort();
                    this.showToast(window.t('showcase.actress.addSuccess'), 'success');
                } else {
                    this.showToast(window.t('showcase.actress.addNotFound'), 'error');
                }
            } catch (e) {
                this.showToast(window.t('showcase.actress.addNotFound'), 'error');
            } finally {
                this._addingActress = false;
                this._addActressName = '';
            }
        },

        async addFavoriteFromSearch() {
            if (this._favoriteHeartLoading || this._matchedActress?.is_favorite) return;
            this._favoriteHeartLoading = true;
            var capturedName = this._matchedActress?.name;
            if (!capturedName) { this._favoriteHeartLoading = false; return; }
            try {
                var resp = await fetch('/api/actresses/favorite', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: capturedName })
                });
                if (!this._matchedActress || this._matchedActress.name !== capturedName) return;
                if (resp.status === 200 || resp.status === 409) {
                    var data = await resp.json();
                    var actress = data.actress || data;
                    actress.is_favorite = true;
                    this._matchedActress = actress;
                    if (!_actresses.find(function(a) { return a.name === actress.name; })) {
                        _actresses.push(actress);
                        this.applyActressFilterAndSort();
                    }
                    if (resp.status === 200) {
                        this.showToast(window.t('showcase.actress.addSuccess'), 'success');
                    } else {
                        this.showToast(window.t('showcase.actress.addDuplicate'), 'info');
                    }
                } else if (resp.status === 404) {
                    this.showToast(window.t('showcase.actress.addNotFound'), 'error');
                } else {
                    this.showToast(window.t('showcase.actress.addTimeout'), 'error');
                }
            } catch (err) {
                this.showToast(window.t('showcase.actress.addTimeout'), 'error');
            } finally {
                this._favoriteHeartLoading = false;
            }
        },

        // T3.3: Remove Actress fluent-modal 三段路徑
        openRemoveActressModal() {
            if (!this.currentLightboxActress) return;
            this._pendingRemoveActressName = this.currentLightboxActress.name;
            this.removeActressModalOpen = true;
        },

        cancelRemoveActressModal() {
            this.removeActressModalOpen = false;
            this._pendingRemoveActressName = null;
        },

        async confirmRemoveActress() {
            const name = this._pendingRemoveActressName;
            if (!name) {
                this.removeActressModalOpen = false;
                return;
            }
            this._removeActressLoading = true;
            try {
                const resp = await fetch(`/api/actresses/${encodeURIComponent(name)}`, {
                    method: 'DELETE',
                });
                const data = await resp.json();
                if (data.success) {
                    const idx = _actresses.findIndex(a => a.name === name);
                    if (idx >= 0) _actresses.splice(idx, 1);
                    this.applyActressFilterAndSort();
                    // stale guard: lightbox switched to a different actress during request
                    if (this.currentLightboxActress?.name !== name) {
                        this.showToast(window.t('showcase.actress.removeSuccess'), 'success');
                    } else {
                        this.closeActressLightbox();
                        this.showToast(window.t('showcase.actress.removeSuccess'), 'success');
                        // TASK-115-T8：無條件呼叫，理由同 toggleActressMode() 的等價改動
                        // （pill 跨模式保留，短路會漏掉「文字空但有女優 pill」情境）。
                        this._reconcileHeroCard();
                    }
                } else {
                    this.showToast(data.error || 'Error', 'error');
                }
            } catch (e) {
                this.showToast('Error', 'error');
            } finally {
                this._removeActressLoading = false;
                this.removeActressModalOpen = false;
                this._pendingRemoveActressName = null;
            }
        },

        // --- 44c T7: Search actress films（49a-T7：跨模式 Ghost Fly 動畫）---
        // TASK-115-T8（RULING 1）：本函式是 CD-8 六個既有觸發點清單之外的第 7 個
        // _checkPreciseActressMatch 呼叫點（plan 研究階段漏列，Opus 裁決併入）。
        // 理由：pill 跨模式保留（spec §4.10），使用者可能帶著非女優 pill（例如片商）
        // 從女優模式點「查看她的作品」——此時 this.search 被設成非空的女優名，若直接呼叫
        // _checkPreciseActressMatch 而不經 _reconcileHeroCard，會無視 pills 直接顯示卡，
        // 違反 spec §4.8「有 pill＋有自由文字→不顯示」。改成一律先設定 this.search 再呼叫
        // _reconcileHeroCard()，讓它自然算出「有 pill 則不顯示」——與其餘六個呼叫點同一
        // 決策點（CD-8「六處各自加條件必然漏一處」的教訓，本身就是這條 ruling 的證據）。
        async searchActressFilms(actressName, fromEl) {
            if (!actressName) return;
            if (this._ghostFlyInFlight) return;   // CD-13: 連點保護
            var self = this;
            var wasActressMode = this.showFavoriteActresses;

            try {
                // 捕獲來源 rect / coverSrc（必須在 closeLightbox / state 變更前）
                var fromRect = null;
                var coverSrc = null;
                if (wasActressMode && fromEl) {
                    var fromImg = fromEl.closest('.actress-card')?.querySelector('.actress-card-photo img')
                        || fromEl.closest('.showcase-lightbox')?.querySelector('.lightbox-cover img');
                    if (fromImg) {
                        fromRect = fromImg.getBoundingClientRect();
                        coverSrc = fromImg.src;
                    }
                }

                if (this.lightboxOpen) this.closeLightbox();
                if (wasActressMode) {
                    // 繞過 toggleActressMode() 直接翻旗標——CD-116b-8b 的 teardown 必須就地補上
                    this._teardownPillEditors();
                    this.showFavoriteActresses = false;
                    this.actressSearch = '';
                }
                this.search = actressName;
                this._animateFilter();

                // 非女優模式 / 無 fromEl / 無 coverSrc → fallback
                if (!wasActressMode || !fromRect || !coverSrc) {
                    this._reconcileHeroCard();
                    if (wasActressMode) {
                        var gen0 = ++this._animGeneration;
                        this.$nextTick(function () {
                            if (self._animGeneration !== gen0) return;
                            window.ShowcaseAnimations?.playModeCrossfade?.('actress', self.mode);
                            if (self.mode === 'grid') {
                                var grid0 = self._getActiveGrid();
                                window.ShowcaseAnimations?.playEntry?.(grid0);
                            }
                        });
                    }
                    return;
                }

                // === Ghost Fly 主流程 ===
                this._ghostFlyInFlight = true;
                var gen = ++this._animGeneration;

                // 淡出女優 grid
                window.ShowcaseAnimations?.playModeCrossfade?.('actress', null, null, {
                    onOldFadeComplete: function () {}
                });
                // 影片 grid 淡入
                this.$nextTick(function () {
                    if (self._animGeneration !== gen) return;
                    var newEl = document.querySelector('.showcase-grid');
                    window.ShowcaseAnimations?.playContainerFadeIn?.(newEl);
                    window.ShowcaseAnimations?.playEntry?.(self._getActiveGrid());
                });

                self._isPreciseActressMatch = false;

                await self._reconcileHeroCard();

                if (self._animGeneration !== gen) {
                    self._ghostFlyInFlight = false;
                    return;
                }

                // 等 hero card DOM render（最多 500ms 輪詢）
                var heroCardEl = null;
                var TIMEOUT = 500;
                var elapsed = 0;
                var interval = 30;
                await new Promise(function (resolve) {
                    var checker = setInterval(function () {
                        elapsed += interval;
                        var hero = document.querySelector('.hero-card');
                        if (hero && hero.getBoundingClientRect().width > 0) {
                            heroCardEl = hero;
                            clearInterval(checker);
                            resolve();
                        } else if (elapsed >= TIMEOUT) {
                            clearInterval(checker);
                            resolve();
                        }
                    }, interval);
                });

                // 再次 stale 檢查
                if (self._animGeneration !== gen) {
                    self._ghostFlyInFlight = false;
                    return;
                }

                // CD-12: 降級條件
                var canMainFlow = heroCardEl
                    && self._isPreciseActressMatch
                    && self._matchedActress
                    && self._matchedActress.is_favorite !== false
                    && coverSrc;

                var doFallback = function () {
                    self._ghostFlyInFlight = false;
                    if (fromEl) {
                        var pulseTarget = fromEl.closest('.actress-card')?.querySelector('.actress-card-photo img')
                            || fromEl.closest('.showcase-lightbox')?.querySelector('.lightbox-cover img');
                        window.ShowcaseAnimations?.playSourcePulse?.(pulseTarget);
                    }
                };

                if (canMainFlow) {
                    if (typeof window.GhostFly?.playActressToHeroCard !== 'function') {
                        doFallback();
                        return;
                    }
                    window.GhostFly.playActressToHeroCard(fromRect, heroCardEl, {
                        coverSrc: coverSrc,
                        onComplete: function () { self._ghostFlyInFlight = false; },
                        onFallback: function () { self._ghostFlyInFlight = false; }
                    });
                } else {
                    doFallback();
                }
            } catch (e) {
                self._ghostFlyInFlight = false;
                console.warn('[T7][searchActressFilms]', e);
            }
        },

        // 49a-T3: 開啟 Lightbox 時 async fetch 最新 aliases（Scanner SSOT）
        async _fetchLiveAliases(name, expectedIndex) {
            if (!name) return;
            var capturedName = name;
            var self = this;
            try {
                var resp = await fetch('/api/actress-aliases/' + encodeURIComponent(capturedName), {
                    signal: AbortSignal.timeout(3000)
                });
                if (resp.status === 200) {
                    var data = await resp.json();
                    // Stale-check
                    if (!self.lightboxOpen) return;
                    if (self.currentLightboxActress?.name !== capturedName) return;
                    if (expectedIndex !== null && expectedIndex !== undefined
                        && self.actressLightboxIndex !== expectedIndex) return;
                    var newAliases = (data && data.group && data.group.aliases) || [];
                    self.currentLightboxActress = Object.assign({}, self.currentLightboxActress, {
                        aliases: newAliases
                    });
                }
                // 404 / 5xx → 保留 snapshot，靜默
            } catch (e) {
                if (window.console && console.warn) console.warn('[T3] alias live fetch failed:', e);
            }
        },

    };
}
