/**
 * state-videos.js — Showcase ESM（54b-T1b）
 *
 * 影片資料流：fetchVideos / filter / sort / paginate / animate。
 * 無 data 初始值（全部在 stateBase 已有）。
 * 從 state-base.js import 共用大陣列（F1：移出 Alpine reactive scope）。
 */

import { _videos, _filteredVideos, _nameToGroup, _tagToGroup, _setVideos, _setFilteredVideos } from '@/showcase/state-base.js';
import { applyCellFocal } from '@/shared/focal-cell.js';
import { openLocal } from '@/shared/open-local.js';
import { normalizePillValue, buildPillPredicate } from '@/shared/pill-filter.js';

export function stateVideos() {
    return {

        // --- 99a-T2: 揭露 applyCellFocal 供 F1 grid template @load / $watch 呼叫（load-gated，
        // aspect-aware object-position；取代舊 focalStyle 的 reactive :style binding，見 98b-T6 姊妹
        // gotcha：naturalWidth 在 decode 完成前恆為 0，reactive binding 不會因 load 事件重跑）---
        applyCellFocal,

        // --- API 呼叫 ---
        async fetchVideos() {
            this.loading = true;
            this.error = '';
            try {
                const resp = await fetch('/api/showcase/videos');
                if (!resp.ok) {
                    _videos.length = 0;
                    this.videoCount = 0;
                    _filteredVideos.length = 0;
                    this.filteredCount = 0;
                    this.error = window.t('showcase.error.server_error', { status: resp.status });
                    return;
                }
                const data = await resp.json();
                if (!data.success) {
                    _videos.length = 0;
                    this.videoCount = 0;
                    _filteredVideos.length = 0;
                    this.filteredCount = 0;
                    this.error = data.error || window.t('showcase.error.load_failed');
                    return;
                }
                // Re-assign module-level var via splice/push to keep the same reference
                // (core.js uses direct assignment; ESM re-exports work because we read
                // _videos/_filteredVideos at call time, not at import time)
                var vids = data.videos || [];
                // 67-A2: per-card 三態旗標。video 物件由此唯一來源流穿整條 render 鏈
                // （_videos → _filteredVideos → paginatedVideos slice，皆同 ref），故初始化一處即涵蓋
                // 初次載入/retry/翻頁/搜尋/排序；後端不回此欄位。補封面走 refreshVideoData reset。
                vids.forEach(function (v) { if (v._imgLoaded === undefined) v._imgLoaded = false; });
                _setVideos(vids);
                this.videoCount = _videos.length;
                _setFilteredVideos(_videos);
                this.filteredCount = _filteredVideos.length;
            } catch (e) {
                console.error('Failed to fetch videos:', e);
                _videos.splice(0, _videos.length);
                this.videoCount = 0;
                _filteredVideos.splice(0, _filteredVideos.length);
                this.filteredCount = 0;
                this.error = window.t('showcase.error.cannot_connect');
            } finally {
                this.loading = false;
            }
        },

        // --- 重試（async 安全） ---
        async retry() {
            this.error = '';
            const savedPage = this.page;
            await this.fetchVideos();
            this.applyFilterAndSort(true);  // 跳過 pagination，下面統一處理
            this.page = savedPage;
            this.updatePagination();
            // Settle: retry 也用 settle（不碰 opacity → 不閃）
            if (this.mode === 'grid' && !this.error) {
                var gen = ++this._animGeneration;
                this.$nextTick(() => { requestAnimationFrame(() => {
                    if (this._animGeneration !== gen) return;
                    var grid = this._getActiveGrid();
                    window.ShowcaseAnimations?.playSettle?.(grid);
                }); });
            }
        },

        // --- 互動邏輯 ---
        onSearchChange() {
            // B8: 透過 _animateFilter 觸發篩選動畫
            this._animateFilter();
            // TASK-115-T8：改走單一判斷點（CD-8），無 pill 時行為逐位元組不變
            // （_reconcileHeroCard 的「無 pill 分支」就是這裡原本的 if/else）。
            this._reconcileHeroCard();
        },

        // TASK-115-T1: metadata pill filter mutations（UI 殼屬 T5；比對屬 T2）
        normalizePillValue,

        addPill(dim, value) {
            var norm = normalizePillValue(value);
            if (!dim || !norm) return;
            var key = dim + '::' + norm;
            var exists = this.pills.some(p => p.dim + '::' + normalizePillValue(p.value) === key);
            if (exists) return;  // 靜默去重：不重跑 _animateFilter/_reconcileHeroCard
            this.pills = [...this.pills, { dim: dim, value: value }];  // value 存原始字面（CD-3）
            this._animateFilter();
            this._reconcileHeroCard();
        },

        removePill(dim, value) {
            var key = dim + '::' + normalizePillValue(value);
            var next = this.pills.filter(p => (p.dim + '::' + normalizePillValue(p.value)) !== key);
            if (next.length === this.pills.length) return;  // 沒命中：不重跑
            this.pills = next;
            this._animateFilter();
            this._reconcileHeroCard();
        },

        // TASK-115-T9: 搜尋框 Backspace 刪最後一枚 pill（IME 組字中一律不刪）
        onSearchBackspace(event) {
            if (event.isComposing) return;
            // 有字：交給瀏覽器原生刪字，不 preventDefault、不動 pill
            if (event.target.value !== '') return;
            // 游標必須在最左且選取為 collapsed；非 collapsed 選取不得刪 pill
            if (!(event.target.selectionStart === 0 && event.target.selectionEnd === 0)) return;
            if (this.pills.length === 0) return;
            var last = this.pills[this.pills.length - 1];
            this.removePill(last.dim, last.value);
        },

        clearAllFilters() {
            this.search = '';
            this.actressSearch = '';
            this.pills = [];
            // TASK-115-T8：不再直接呼叫 _clearPreciseMatch()（T7 留下的暫時補丁）——
            // pills=[]、search='' 之後，_reconcileHeroCard() 的「無 pill 分支」本來就會
            // 走到同一個 _clearPreciseMatch() 呼叫，讓收斂單一判斷點的精神落實（RULING 3：
            // 兩處各自宣稱自己是「清 hero 狀態」的權威，收成一處）。
            this._animateFilter();           // 影片格：CD-2 步驟 7-9（唯一一次）
            this.applyActressFilterAndSort(); // 女優格：對應 onActressSearchChange() 的行為，不經 _animateFilter
            this._reconcileHeroCard();
            Alpine.store('ui').toolbarOpen = false;
            // 無條件執行：使用者主動按下的清除鈕，即使已空跑一次也無害，且維持「按下必清」的誠實承諾
        },

        // TASK-115-T8：hero card（女優資料卡＋搜尋列愛心鈕）唯一判斷點（CD-8）。
        // 無 pill：完全不限制，交給下面「無 pill 分支」的既有邏輯判斷（逐位元組保留
        // onSearchChange 舊有的 if/else 語意）。有 pill：僅當恰好一枚女優 pill 且
        // 自由文字為空才顯示（spec §4.8）。
        _shouldShowHeroCard() {
            if (this.pills.length === 0) return true;
            return this.pills.length === 1
                && this.pills[0].dim === 'actress'
                && this.search.trim() === '';
        },

        // 七個既有觸發點（CD-8 原列六個＋RULING 1 併入 searchActressFilms）全部間接透過
        // 本方法，不再各自決定。回傳 _checkPreciseActressMatch() 的 promise（若有呼叫），
        // 讓 searchActressFilms() 的 ghost-fly 主流程可以 await 到真正的比對結果；
        // 其餘呼叫端維持既有的 fire-and-forget 用法，忽略回傳值不影響行為。
        _reconcileHeroCard() {
            if (!this._shouldShowHeroCard()) {
                this._clearPreciseMatch();
                return;
            }
            if (this.pills.length === 1) {
                // 有 pill 分支：唯一一枚女優 pill、文字為空（_shouldShowHeroCard 已保證）
                return this._checkPreciseActressMatch(this.pills[0].value, 'pill');
            }
            // 無 pill 分支：逐位元組保留現況（onSearchChange 舊有的 if/else）
            var trimmed = this.search.trim();
            if (trimmed) {
                return this._checkPreciseActressMatch(trimmed, 'manual');
            }
            this._clearPreciseMatch();
        },

        onSortChange() {
            this._sortWithFlip(() => {
                this.applyFilterAndSort();
            });
        },

        toggleOrder() {
            this._sortWithFlip(() => {
                this.order = this.order === 'asc' ? 'desc' : 'asc';
                this.applyFilterAndSort();
            });
        },

        // --- 44c T6: Active grid helper ---
        _getActiveGrid() {
            return this.showFavoriteActresses
                ? document.querySelector('.actress-grid')
                : document.querySelector('.showcase-grid');
        },

        /**
         * B7/B15: 排序動畫共用 helper — flip-guard → capture → change → Flip reorder
         * @param {Function} changeFn - 執行 data change 的函數
         */
        _sortWithFlip(changeFn) {
            var savedPage = this.page;
            var grid = null;
            var positionMap = null;

            // Step 0: capture（grid mode 或女優模式）
            if (this.mode === 'grid' || this.showFavoriteActresses) {
                grid = this._getActiveGrid();
                if (grid) {
                    grid.classList.add('flip-guard');
                    void grid.offsetHeight;  // force reflow
                    positionMap = window.ShowcaseAnimations?.capturePositions?.(grid) || null;
                }
            }

            // Step 1: data change
            changeFn();
            this.page = savedPage;
            this.updatePagination();
            this.saveState();

            // Step 2: animate
            if (grid && positionMap) {
                var gen = ++this._animGeneration;
                this.$nextTick(() => { requestAnimationFrame(() => {
                    if (this._animGeneration !== gen) {
                        grid.classList.remove('flip-guard');
                        return;
                    }
                    var result = window.ShowcaseAnimations?.playFlipReorder?.(grid, positionMap);
                    if (!result) {
                        // fallback: Flip 回傳 null（delta 全零、reduced motion 等）
                        grid.classList.remove('flip-guard');
                        window.ShowcaseAnimations?.playEntry?.(grid);
                    }
                    // flip-guard 由 playFlipReorder 的 onComplete 移除
                }); });
            } else if (grid) {
                // capture 失敗 fallback
                grid.classList.remove('flip-guard');
                var gen = ++this._animGeneration;
                this.$nextTick(() => { requestAnimationFrame(() => {
                    if (this._animGeneration !== gen) return;
                    window.ShowcaseAnimations?.playEntry?.(grid);
                }); });
            }
        },

        /**
         * B8/B15: 篩選動畫共用 helper — flip-guard → capture → change → Flip filter
         * onSearchChange() 和 searchFromMetadata() 共用
         */
        _animateFilter() {
            var grid = null;
            var state = null;

            // Step 0: capture（僅 grid mode，且僅影片模式）
            //
            // 115-T7 review：`showFavoriteActresses` 為真時**一律不碰 DOM 動畫**。
            // 本函式是「影片側篩選」的動畫，而 `captureFlipState()` 只認得 `.av-card-preview`；
            // 餵它一面 `.actress-card` 會回 null → 掉進下面的 capture-failed fallback →
            // 對整面女優牆重播一次 playEntry 入場動畫。使用者看到的是：在女優模式按清除，
            // 每張女優卡無故閃一下（淡出↓20px 再淡回），而既有的 onActressSearchChange()
            // 那條路本來就是零動畫。
            //
            // 修在這裡而不是在 clearAllFilters() 加旗標：這是「任何呼叫端在女優模式下走到
            // _animateFilter 都會中」的類別問題，不是單一呼叫點的問題。onSearchChange() /
            // searchFromMetadata() 兩條既有路徑只在影片模式可達，故行為逐位元組不變。
            if (this.mode === 'grid' && !this.showFavoriteActresses) {
                grid = this._getActiveGrid();
                if (grid) {
                    grid.classList.add('flip-guard');
                    void grid.offsetHeight;  // force reflow
                    state = window.ShowcaseAnimations?.captureFlipState?.(grid) || null;
                }
            }

            // Step 1: data change
            this.applyFilterAndSort();
            this.saveState();

            // Step 2: animate
            if (grid && state) {
                var gen = ++this._animGeneration;
                this.$nextTick(() => { requestAnimationFrame(() => {
                    if (this._animGeneration !== gen) {
                        grid.classList.remove('flip-guard');
                        return;
                    }
                    var result = window.ShowcaseAnimations?.playFlipFilter?.(grid, state);
                    if (!result) {
                        grid.classList.remove('flip-guard');
                        window.ShowcaseAnimations?.playEntry?.(grid);
                    }
                    // flip-guard 由 playFlipFilter 的 onComplete 移除
                }); });
            } else if (grid) {
                // capture 失敗 fallback
                grid.classList.remove('flip-guard');
                var gen = ++this._animGeneration;
                this.$nextTick(() => { requestAnimationFrame(() => {
                    if (this._animGeneration !== gen) return;
                    window.ShowcaseAnimations?.playEntry?.(grid);
                }); });
            }
        },

        /**
         * B9/B13: 分頁動畫 — state-first + playEntry
         * @param {string} direction - 'next' | 'prev'
         * @param {number} [targetPage] - 目標頁碼（goToPage 用，prevPage/nextPage 不傳）
         */
        _animatePageChange(direction, targetPage) {
            // 清理可能殘留的 flip-guard（sort/filter 動畫被翻頁打斷時）
            var grid = document.querySelector('.showcase-grid');
            if (grid) grid.classList.remove('flip-guard');

            // 計算目標頁碼
            var newPage = targetPage;
            if (newPage === undefined) {
                newPage = direction === 'next' ? this.page + 1 : this.page - 1;
            }

            // State mutation FIRST（不再困在回調中）
            this.page = newPage;
            this.updatePagination();
            this.saveState();
            window.scrollTo(0, 0);

            // Grid mode：播放進場動畫
            if (this.mode === 'grid') {
                var gen = ++this._animGeneration;
                this.$nextTick(() => { requestAnimationFrame(() => {
                    if (this._animGeneration !== gen) return;  // stale
                    var grid = document.querySelector('.showcase-grid');
                    window.ShowcaseAnimations?.playEntry?.(grid);
                }); });
            }
        },

        switchMode(m) {
            if (!['grid', 'table', 'list'].includes(m)) return;
            if (m === this.mode) return;
            var oldMode = this.mode;
            this.mode = m;
            // F2: 切到 grid 時若 perPage=0 則降級
            if (m === 'grid' && this.perPage == 0) {
                this.perPage = 120;
                this.updatePagination();
            }
            this.saveState();  // M2c: 持久化狀態
            this.$nextTick(() => {
                window.ShowcaseAnimations?.playModeCrossfade?.(oldMode, m);
            });
        },

        prevPage() {
            if (this.page > 1) {
                this._animatePageChange('prev');
            }
        },

        nextPage() {
            if (this.page < this.totalPages) {
                this._animatePageChange('next');
            }
        },

        // Status bar 頁面跳轉 (M3g)
        goToPage(p) {
            const num = parseInt(p);
            if (Number.isNaN(num) || num < 1 || num > this.totalPages) return;
            if (num === this.page) return;
            var direction = num > this.page ? 'next' : 'prev';
            this._animatePageChange(direction, num);
        },

        /**
         * 49a-T4 / Codex P2: 開啟隱藏 select 的 native picker
         */
        openPagePicker(selectEl) {
            if (!selectEl) return;
            if (typeof selectEl.showPicker === 'function') {
                try { selectEl.showPicker(); return; } catch (e) { /* fall through */ }
            }
            selectEl.click();
        },

        // --- 資料處理 ---
        applyFilterAndSort(skipPagination) {
            // --- Stage 1: pill 精準比對（TASK-115-T2, CD-6）---
            var pillPredicate = buildPillPredicate(this.pills, _nameToGroup, _tagToGroup);
            var pillFiltered = _videos.filter(pillPredicate);

            // --- Stage 2: 自由文字模糊比對 (M4a)（現況邏輯，body 逐字保留，僅改輸入來源陣列）---
            if (this.search && this.search.trim()) {
                // 分割多個關鍵字（用空格分隔，過濾空字串）
                const terms = this.search.toLowerCase().trim().split(/\s+/).filter(t => t.length > 0);

                var filtered = pillFiltered.filter(video => {
                    const searchable = [
                        video.title,
                        video.original_title,
                        video.actresses,
                        video.number,
                        video.maker,
                        video.tags,
                        video.release_date,
                        video.path,
                        video.director,
                        video.series,
                        video.label,
                        video.user_tags
                    ].filter(Boolean).join(' ').toLowerCase();

                    // 番號的正規化版本（移除空格和連字號）
                    const numNorm = video.number ? video.number.toLowerCase().replace(/[\s\-]/g, '') : '';

                    // 每個關鍵字都要匹配（AND 邏輯）
                    return terms.every(term => {
                        const termNorm = term.replace(/[\s\-]/g, '');
                        // 番號模糊匹配
                        if (numNorm && numNorm.includes(termNorm)) return true;
                        // alias 展開 match：搜尋詞反查 alias group，任一 alias name 命中即可
                        var termNames = _nameToGroup[term] || [term];
                        if (termNames.some(function(n) { return searchable.includes(n.toLowerCase()); })) return true;
                        // tag alias 展開：搜尋詞反查 tag alias group，任一同義 tag 命中即可（A3-4）
                        var termTagNames = _tagToGroup[term] || null;
                        if (termTagNames) {
                            if (termTagNames.some(function(tn) { return searchable.includes(tn.toLowerCase()); })) return true;
                        }
                        return false;
                    });
                });
                _setFilteredVideos(filtered);
                this.filteredCount = _filteredVideos.length;
            } else {
                // 空搜尋：pill 篩選結果即為最終結果
                _setFilteredVideos(pillFiltered);
                this.filteredCount = _filteredVideos.length;
            }

            // --- 排序 (M4b) ---
            _filteredVideos.sort((a, b) => {
                // 1. 女優卡置頂邏輯
                const aIsHero = a.path && a.path.indexOf('actress:') === 0;
                const bIsHero = b.path && b.path.indexOf('actress:') === 0;
                if (aIsHero && !bIsHero) return -1;
                if (!aIsHero && bIsHero) return 1;

                // 2. Random 排序
                if (this.sort === 'random') {
                    return Math.random() - 0.5;
                }

                // 3. 其他排序：取得比較值
                let va, vb;
                switch (this.sort) {
                    case 'title':
                        va = a.title || '';
                        vb = b.title || '';
                        break;
                    case 'actor':
                        va = a.actresses || '';
                        vb = b.actresses || '';
                        break;
                    case 'num':
                        va = a.number || '';
                        vb = b.number || '';
                        break;
                    case 'maker':
                        va = a.maker || '';
                        vb = b.maker || '';
                        break;
                    case 'date':
                        va = a.release_date || '';
                        vb = b.release_date || '';
                        break;
                    case 'size':
                        va = a.size || 0;
                        vb = b.size || 0;
                        break;
                    case 'mdate':
                        va = a.mtime || 0;
                        vb = b.mtime || 0;
                        break;
                    default:
                        va = a.path || '';
                        vb = b.path || '';
                }

                // 4. 比較邏輯
                if (va < vb) return this.order === 'asc' ? -1 : 1;
                if (va > vb) return this.order === 'asc' ? 1 : -1;
                return 0;
            });

            // --- 重置頁碼並更新分頁 ---
            if (!skipPagination) {
                this.page = 1;
                this.updatePagination();
            }
        },

        updatePagination() {
            // F2: grid mode 禁用「全部」— perPage=0 降級為 120
            if (parseInt(this.perPage) === 0 && this.mode === 'grid') {
                this.perPage = 120;
            }
            const perPage = Math.max(0, parseInt(this.perPage) || 0);
            if (perPage === 0) {
                this.paginatedVideos = _filteredVideos.slice();
                this.totalPages = 1;
                this.page = 1;
            } else {
                this.totalPages = Math.max(1, Math.ceil(_filteredVideos.length / perPage));
                // clamp page 到有效範圍
                if (this.page > this.totalPages) this.page = this.totalPages;
                if (this.page < 1) this.page = 1;
                const start = (this.page - 1) * perPage;
                this.paginatedVideos = _filteredVideos.slice(start, start + perPage);
            }
        },

        // --- 播放影片 (PyWebView 整合) ---
        playVideo(path) {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.open_file(path)
                    .then(opened => {
                        if (!opened) this.showToast(window.t('showcase.video.play_failed'), 'error');
                    })
                    .catch(err => {
                        console.error('Failed to open file:', err);
                        this.showToast(window.t('showcase.video.play_failed'), 'error');
                    });
            } else {
                window.open('/api/gallery/player?path=' + encodeURIComponent(path), '_blank');
            }
        },

        // 工具方法：從 paginatedVideos 的 index 映射到 filteredVideos 的 index
        getCurrentFilteredIndex(paginatedIndex) {
            const perPage = parseInt(this.perPage);
            return perPage === 0 ? paginatedIndex : (this.page - 1) * perPage + paginatedIndex;
        },

        // 開啟資料夾（複製路徑到剪貼簿 + PyWebView 桌面模式額外開啟資料夾）
        openLocal,

    };
}
