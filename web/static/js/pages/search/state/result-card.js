/**
 * SearchState - Result Card Mixin
 * 包含：結果卡片顯示、編輯、翻譯、標籤、本地狀態
 */
import { openLocal } from '@/shared/open-local.js';

// TASK-106-T3 CD-106-8: 純函式，module-level named export（非 this.-bound method）
// 三分隔符 `、`/`，`（U+FF0C 全形逗號）/`,`，對齊 core/scrapers/actress/wiki_ja.py:108 先例。
export function parseActorsInput(str) {
    return str.split(/[、，,]/).map(s => s.trim()).filter(Boolean);
}

// TASK-113c-T7（Opus 審核裁決 2）：回傳「原始圖片 URL」，不是 proxy URL——proxy 包裹
// 留在各呼叫點自行處理（與既有 search-flow.js::resolveStagingCoverUrl 契約一致）。
// 契約：`_previewFailed` 為 truthy → 只用 cover（preview 已知失敗，不再嘗試）；
// 否則沿用既有 `preview_cover_url || cover` 優先序（FE-JS-01：|| 對空字串 fallback 是
// 刻意行為，preview_cover_url 恆為字串，非 null/undefined）。
export function resolveResultCoverUrl(result) {
    if (!result) return '';
    if (result._previewFailed) return result.cover || '';
    return result.preview_cover_url || result.cover || '';
}

// TASK-113c-T7：決定「這次 preview 失敗要不要觸發 cover fallback」。
// 只有「還沒 fallback 過」且「preview/cover 都存在且不同」才值得換——已經在用 cover
// （_previewFailed 已 true）、沒有 cover 可退、或 preview 跟 cover 根本是同一個 URL，
// 都應該落回既有 PHASE 1/2 行為（cache-bust 重試／直接 latch）。
// TASK-113c-T7（Sonnet review P2）：這一發 `@error` 是不是「已經切走的那一張」遲到的？
// 燈箱／detail 的 `<img>` 都是**單一元素跨候選重用**，使用者按下一張時，上一張還在飛的
// 請求失敗後才回來。舊碼寫的是頁面層 boolean（切走即被重置，寫錯了也無害）；本 task 改
// 寫的是**跟著資料走的持久旗標** `_previewFailed`——寫到錯的候選上，那一筆會整個 session
// 停在 cover、明明 preview 是好的。所以持久旗標必須配 stale guard。
// `expectedRawUrl` 為空（如女優燈箱無影片）→ 不判 stale，交給呼叫端既有分支處理。
export function isStaleCoverError(actualSrc, expectedRawUrl) {
    if (!expectedRawUrl || !actualSrc) return false;
    return actualSrc !== `/api/proxy-image?url=${encodeURIComponent(expectedRawUrl)}`;
}

export function shouldFallbackToCover(result) {
    if (!result || result._previewFailed) return false;
    const preview = result.preview_cover_url;
    const cover = result.cover;
    return !!preview && !!cover && preview !== cover;
}

export function searchStateResultCard() {
    return {
    // ===== T1c: Result Card Computed =====

    current() {
        if (this.listMode === 'file' && this.fileList[this.currentFileIndex]) {
            const results = this.fileList[this.currentFileIndex].searchResults || [];
            return results[this.currentIndex] || {};
        }
        return this.searchResults[this.currentIndex] || {};
    },

    // 改為 method（原為 getter）
    hasSubtitle() {
        if (this.listMode === 'file' && this.fileList[this.currentFileIndex]) {
            return this.fileList[this.currentFileIndex].hasSubtitle || false;
        }
        return false;
    },

    // 當前結果的版本標記 badges（Fix-1）
    currentSuffixes() {
        if (this.listMode === 'file' && this.fileList[this.currentFileIndex]) {
            return this.fileList[this.currentFileIndex].suffixes || [];
        }
        return [];  // 雲端搜尋模式無 suffix
    },

    // 改為 method（原為 getter）
    chineseTitle() {
        if (this.listMode === 'file' && this.fileList[this.currentFileIndex]) {
            return this.fileList[this.currentFileIndex].chineseTitle || null;
        }
        return null;
    },

    hasChineseTitle() {
        const c = this.current();
        return !!(c.translated_title || this.chineseTitle());
    },

    chineseTitleLabel() {
        const c = this.current();
        if (c.translated_title) return window.t('search.label.chinese_title_ai');
        return window.t('search.label.chinese_title');
    },

    chineseTitleText() {
        const c = this.current();
        return c.translated_title || this.chineseTitle() || '-';
    },

    // TASK-113c-T7：模板（hero lightbox / grid card）呼叫的 Alpine 方法包裝，
    // 委派給純函式 resolveResultCoverUrl（module-level export，見上方）。
    // 契約：回傳「原始圖片 URL」，proxy 包裹留在各呼叫點（裁決 2）。
    resolveCoverUrl(result) {
        return resolveResultCoverUrl(result);
    },

    coverUrl() {
        const c = this.current();
        // TASK-113c-T3b/T7: preview_cover_url 優先（破圖修復），_previewFailed 為 true
        // 時改用 cover（見 resolveResultCoverUrl）。proxy 包裹仍在此呼叫點處理（裁決 2）。
        const cover = this.resolveCoverUrl(c);
        if (!cover) return '';
        return `/api/proxy-image?url=${encodeURIComponent(cover)}`;
    },

    canTranslate() {
        const c = this.current();
        return this.appConfig?.translate?.enabled &&
               !this.chineseTitle() &&
               !c.translated_title &&
               c.title &&
               this.hasJapanese(c.title) &&
               !this.isBatchTranslating(this.currentIndex);
    },

    hasLocalBadge() {
        return this.current()?._localStatus?.exists || false;
    },

    localBadgeTitle() {
        const status = this.current()?._localStatus;
        if (!status || !status.exists) return '';
        return status.count > 1
            ? window.t('search.local.has_local_count', { count: status.count })
            : window.t('search.local.has_local');
    },

    // ===== T1c: Title Edit Methods =====

    startEditTitle() {
        const c = this.current();
        this.editedTitleValue = c.title || '';
        this.editingTitle = true;
        // TASK-106 Option C Part 1: 捕獲編輯開啟當下的候選物件參照，供 confirmEditTitle 比對。
        // Codex PR#115 P2: 用 title 專屬欄位，不與 chineseTitle/actors 共用（見 base.js 註解）。
        this._editSourceTitle = c;
        this.$nextTick(() => {
            this.$refs.titleInput?.focus();
            this.$refs.titleInput?.select();
        });
    },

    confirmEditTitle() {
        // TASK-106 Option C Part 1（唯一權威保證）：current() 已換到別的候選/檔（不論是
        // navigate/switchToFile/scrapeAll/grid/lightbox 或任何未來路徑造成的）就擋下寫入，
        // 不寫錯候選。必須在任何寫入之前、最先執行。
        const c = this.current();
        if (c !== this._editSourceTitle) {
            this.editingTitle = false;
            return;
        }
        const newValue = this.editedTitleValue.trim();
        c.title = newValue;
        c._titleEdited = true;
        this.editingTitle = false;
        this.saveState();
    },

    cancelEditTitle() {
        this.editingTitle = false;
    },

    startEditChineseTitle() {
        const c = this.current();
        this.editedChineseTitleValue = this.chineseTitleText() || '';
        this.editingChineseTitle = true;
        // TASK-106 Option C Part 1: 捕獲編輯開啟當下的候選物件參照，供 confirmEditChineseTitle 比對。
        // Codex PR#115 P2: 用 chineseTitle 專屬欄位，不與 title/actors 共用（見 base.js 註解）。
        this._editSourceChineseTitle = c;
        this.$nextTick(() => {
            this.$refs.chineseTitleInput?.focus();
            this.$refs.chineseTitleInput?.select();
        });
    },

    confirmEditChineseTitle() {
        // TASK-106 Option C Part 1（唯一權威保證）：見 confirmEditTitle 同段註解。
        const c = this.current();
        if (c !== this._editSourceChineseTitle) {
            this.editingChineseTitle = false;
            return;
        }
        const newValue = this.editedChineseTitleValue.trim();
        c.translated_title = newValue;
        c._chineseTitleEdited = true;
        this.editingChineseTitle = false;
        this.saveState();
    },

    cancelEditChineseTitle() {
        this.editingChineseTitle = false;
    },

    // ===== T3: Actor Edit Methods =====

    startEditActors() {
        const c = this.current();
        this.editedActorsValue = (c.actors || []).join(', ');
        this.editingActors = true;
        // TASK-106 Option C Part 1: 捕獲編輯開啟當下的候選物件參照，供 confirmEditActors 比對。
        // Codex PR#115 P2: 用 actors 專屬欄位，不與 title/chineseTitle 共用（見 base.js 註解）。
        this._editSourceActors = c;
        this.$nextTick(() => {
            this.$refs.actorsInput?.focus();
            this.$refs.actorsInput?.select();
        });
    },

    confirmEditActors() {
        // TASK-106 Option C Part 1（唯一權威保證）：見 confirmEditTitle 同段註解。
        const c = this.current();
        if (c !== this._editSourceActors) {
            this.editingActors = false;
            return;
        }
        c.actors = parseActorsInput(this.editedActorsValue);
        this.editingActors = false;
        this.saveState();
    },

    cancelEditActors() {
        this.editingActors = false;
    },

    // ===== T7: Date Edit Methods =====

    startEditDate() {
        // TASK-106 Codex PR#116 P2: 打開原生日曆當下捕獲候選物件參照，供 confirmEditDate 比對，
        // 防「選日期期間候選被換（背景批次/換源/切檔）→ 寫錯候選」。掛 date input @focus。
        this._editSourceDate = this.current();
    },

    confirmEditDate(value) {
        // TASK-106 Codex PR#116 P2（與 confirmEditTitle 同源的 identity guard）：current() 已換到
        // 別的候選/檔就擋下寫入、不寫錯候選。必須在寫入前最先執行。掛 date input @change。
        const c = this.current();
        if (c !== this._editSourceDate) return;   // fail-closed：候選變了（含未捕獲 null）就丟棄不寫
        c.date = value;
        this.saveState();
    },

    // ===== T1c: Translate =====

    async translateWithAI() {
        if (this.isTranslating) return;
        this.isTranslating = true;
        try {
            await this._translateWithAILogic();
        } catch (error) {
            console.error('[Translate] 翻譯失敗:', error);
            this.showToast(window.t('search.toast.translate_failed'), 'error');
        } finally {
            this.isTranslating = false;
        }
    },

    /**
     * 核心翻譯邏輯（從 core.js._translateWithAI 搬移）
     * Gemini 模式：只翻譯當前片
     * Ollama 模式：批次翻譯從當前位置開始的 1 片
     */
    async _translateWithAILogic() {
        // === Gemini 模式：只翻譯當前片 ===
        if (this.appConfig?.translate?.provider === 'gemini') {
            let currentResult = null;

            if (this.listMode === 'file' && this.fileList[this.currentFileIndex]) {
                const results = this.fileList[this.currentFileIndex].searchResults || [];
                currentResult = results[this.currentIndex];
            } else {
                currentResult = this.searchResults[this.currentIndex];
            }

            if (!currentResult || !currentResult.title || !this.hasJapanese(currentResult.title)) {
                throw new Error(window.t('search.error.no_translation_needed'));
            }

            const result = await this.translateWithOllama(currentResult.title, 'translate', currentResult);

            if (result.success && result.result) {
                // 41d-T5: 用 captured currentResult ref 避免 await 期間切檔 race
                // currentResult 在 L158/L160 已捕獲為 searchResults 元素的 object reference，
                // 直接賦值即更新原陣列元素，無需 re-index this.fileList[this.currentFileIndex]
                currentResult.translated_title = result.result;
                this.saveState();
            } else {
                throw new Error(result.error || window.t('search.error.translate_failed_generic'));
            }

            return;  // Gemini 模式結束
        }

        // === Ollama 模式：批次翻譯 1 片 ===
        const batch = [];
        const batchMeta = [];

        if (this.listMode === 'file') {
            for (let fi = this.currentFileIndex; fi < this.fileList.length && batch.length < 1; fi++) {
                const file = this.fileList[fi];
                const results = file.searchResults || [];

                for (let ri = 0; ri < results.length && batch.length < 1; ri++) {
                    const result = results[ri];
                    if (result.title && this.hasJapanese(result.title) && !result.translated_title) {
                        batch.push(result);
                        batchMeta.push({ fileIndex: fi, resultIndex: ri });
                    }
                }
            }
        } else {
            for (let i = this.currentIndex; i < this.searchResults.length && batch.length < 1; i++) {
                const result = this.searchResults[i];
                if (result.title && this.hasJapanese(result.title) && !result.translated_title) {
                    batch.push(result);
                    batchMeta.push({ resultIndex: i });
                }
            }
        }

        if (batch.length === 0) {
            throw new Error(window.t('search.error.no_japanese_title'));
        }

        if (this.listMode !== 'file') {
            batchMeta.forEach(meta => {
                this._addBatchTranslatingIndex(meta.resultIndex);
            });
        }

        const titles = batch.map(r => r.title);
        const translations = await this.translateBatch(titles);

        if (translations && translations.length > 0) {
            translations.forEach((trans, i) => {
                if (!trans) return;
                const meta = batchMeta[i];

                if (this.listMode === 'file') {
                    this.fileList[meta.fileIndex].searchResults[meta.resultIndex].translated_title = trans;
                } else {
                    this.searchResults[meta.resultIndex].translated_title = trans;
                    this._deleteBatchTranslatingIndex(meta.resultIndex);
                }
            });

            this.saveState();
        }

        if (this.listMode !== 'file') {
            batchMeta.forEach(meta => {
                this._deleteBatchTranslatingIndex(meta.resultIndex);
            });
        }
    },

    // ===== T1c: User Tags =====

    /**
     * 取得當前 file 的 user_tags（file-level，非 result-level）(P2)
     * user_tags 是 file-level metadata，與哪個候選結果無關。
     */
    currentUserTags() {
        if (this.listMode === 'file') {
            return this.fileList?.[this.currentFileIndex]?.user_tags || [];
        }
        return [];
    },

    showAddTagInput() {
        this.newTagValue = '';
        this.addingTag = true;
        this.$nextTick(() => {
            this.$refs.tagInput?.focus();
        });
    },

    async confirmAddTag() {
        const tag = this.newTagValue.trim();
        if (!tag) {
            this.addingTag = false;
            return;
        }

        const file = this.fileList?.[this.currentFileIndex];
        const filePath = file?.path || '';
        if (!filePath) {
            this.showToast(window.t('search.error.tag_api_failed'), 'error');
            this.addingTag = false;
            return;
        }

        // E5: 前端去重，避免無謂 API call（P2: 用 file-level user_tags）
        const existingTags = this.fileList[this.currentFileIndex].user_tags || [];
        if (existingTags.includes(tag)) {
            this.addingTag = false;
            this.newTagValue = '';
            return;
        }

        try {
            const resp = await fetch('/api/user-tags', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_path: filePath, add: [tag] }),
            });
            const data = await resp.json();
            if (data.success) {
                // P2: 更新 file-level user_tags（用 captured file ref 避免 await 期間切檔 race）
                file.user_tags = data.user_tags;
                this.saveState();
            } else {
                this.showToast(window.t('search.error.tag_api_failed'), 'error');
            }
        } catch {
            this.showToast(window.t('search.error.tag_api_failed'), 'error');
        }

        this.addingTag = false;
        this.newTagValue = '';
    },

    cancelAddTag() {
        this.addingTag = false;
    },

    async removeUserTag(tag) {
        const file = this.fileList?.[this.currentFileIndex];
        const filePath = file?.path || '';
        if (!filePath) {
            this.showToast(window.t('search.error.tag_api_failed'), 'error');
            return;
        }

        try {
            const resp = await fetch('/api/user-tags', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_path: filePath, remove: [tag] }),
            });
            const data = await resp.json();
            if (data.success) {
                // P2: 更新 file-level user_tags（用 captured file ref 避免 await 期間切檔 race）
                file.user_tags = data.user_tags;
                this.saveState();
            } else {
                this.showToast(window.t('search.error.tag_api_failed'), 'error');
            }
        } catch {
            this.showToast(window.t('search.error.tag_api_failed'), 'error');
        }
    },

    /**
     * 補查當前 file 的 user_tags（策略二：前端 lazy fetch）(41b-T3)
     * 只在 listMode === 'file' 且有 file.path 時補查；靜默忽略失敗。
     * 觸發時機：切換 file 索引、頁面載入時。
     * 注意：不要在每次 current() 呼叫時觸發（避免大量 API 請求）。
     * P2: 寫入 fileList[currentFileIndex].user_tags（file-level）
     */
    async fetchUserTagsForCurrent() {
        if (this.listMode !== 'file') return;
        const file = this.fileList?.[this.currentFileIndex];
        if (!file?.path) return;

        try {
            const resp = await fetch(`/api/user-tags?file_path=${encodeURIComponent(file.path)}`);
            const data = await resp.json();
            if (Array.isArray(data.user_tags)) {
                // P2: 寫入 file-level user_tags（用 captured file ref 避免 await 期間切檔 race）
                file.user_tags = data.user_tags;
            }
        } catch {
            // E9: 靜默忽略，不阻擋搜尋結果顯示
        }
    },

    // ===== T1c: Local Badge =====

    openLocal,

    // ===== T18c: Source Link =====

    openSourceUrl(url) {
        if (!url || typeof url !== 'string') return;
        if (!url.startsWith('http://') && !url.startsWith('https://')) return;
        if (window.pywebview?.api?.open_url) {
            window.pywebview.api.open_url(url).then(ok => {
                if (ok) {
                    this.showToast(window.t('search.toast.browser_opened'), 'success');
                } else {
                    window.open(url, '_blank', 'noopener,noreferrer');
                }
            }).catch(() => window.open(url, '_blank', 'noopener,noreferrer'));
        } else {
            window.open(url, '_blank', 'noopener,noreferrer');
        }
    },

    // ===== T6b: Toast =====

    showToast(message, type = 'success', duration = 2500) {
        // 設定 toast 內容
        this._toast.message = message;
        this._toast.type = type;
        this._toast.visible = true;

        // T4.2: 使用 _setTimer 管理（自動取代舊 timer，離頁時可統一清除）
        this._setTimer('toast', () => { this._toast.visible = false; }, duration);
    },

    // ===== T1c: Cover Error =====

    // TASK-113c-T7: preview 失敗且有 cover fallback 時（shouldFallbackToCover）跳過
    // PHASE 1 的 cache-bust 重試、直接改試 cover——對「host 不在白名單→403」這個失敗
    // 模式，cache-bust 本來就無效。
    //
    // **請求數不變式（實測值，非估算）**：fallback 只多送一個請求（preview 那一發），
    // cover 這一棒保有它原本的預算。CDP 實測 2026-08-07：
    //   cover 成功 → preview(403) + cover(200) = **2**
    //   cover 也失敗 → preview(403) + cover(403) + cover&_t=(403) = **3**，然後 latch
    // 三個都停在 PHASE 2 的 placeholder，沒有迴圈。卡片初版 DoD 寫「一律 ≤2」是錯的
    // ——那個數字沒把 cover 自己既有的重試預算算進去。
    handleCoverError() {
        const img = this.$refs.coverImg;
        if (!img) return;

        // No cover URL → stale @error from previous cover, ignore
        const expected = this.coverUrl();
        if (!expected) return;

        // Preview 失敗、cover fallback 可用 → 改試 cover（見上方函式註解）
        const c = this.current();
        if (shouldFallbackToCover(c)) {
            const attrSrc = img.getAttribute('src') || '';
            if (attrSrc !== expected) {
                return; // Stale @error from previous cover
            }

            // 只做「換一個 URL 重載」這一件事，**不**碰 _coverRetried、不另起計時器：
            // cover 這一棒是第一次載入，理應保有它原本的重試預算（PHASE 1 的
            // cache-bust + 5 秒計時），由既有機制接手就好。實測（CDP，2026-08-07）：
            // 早期版本在這裡複製了一份 `_coverRetried = true` ＋ 5 秒計時器，結果
            // ① 它沒有抑制到 PHASE 1（cover 失敗時 _coverRetried 實測仍是 false）
            // ② 反而讓「cover 是大圖、載超過 5 秒」被提前宣告失敗。
            c._previewFailed = true;
            img.src = this.coverUrl();
            return;
        }

        // PHASE 1: First failure — getAttribute stale guard
        if (!this._coverRetried) {
            const attrSrc = img.getAttribute('src') || '';
            if (attrSrc !== expected) {
                return; // Stale @error from previous cover
            }

            this._coverRetried = true;
            if (img.src) {
                const sep = img.src.includes('?') ? '&' : '?';
                img.src = img.src + sep + '_t=' + Date.now();

                const requestId = this._coverRequestId;
                this._setTimer('coverRetry', () => {
                    if (this._coverRequestId !== requestId) return;
                    if (this._coverRetried && !this.coverError) {
                        this._coverRetried = false;
                        this.coverError = window.t('search.cover.load_failed');
                    }
                }, 5000);
                return;
            }
        }

        // PHASE 2: Second failure (retry also failed)
        this._clearTimer('coverRetry');
        this._coverRetried = false;
        this.coverError = window.t('search.cover.load_failed');
    },

    // ===== V1d: Source Switching =====

    /**
     * 切換來源（Alpine method wrapper）
     * 呼叫 ui.js 的 switchSource() 並傳入 Alpine context
     */
    async switchSource() {
        const number = this.current()?.number;
        if (!number) {
            console.warn('[Alpine] switchSource: 無番號資訊');
            return;
        }

        // 呼叫 ui.js 的 switchSource（傳入 Alpine context）
        if (window.switchSourceCore) {
            await window.switchSourceCore(this, number);
        }
    }
    };
}
