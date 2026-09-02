/**
 * SearchState - Wishlist Mixin（TASK-140-T5）
 * 書籤清單狀態與 API 接線。提供 loadWishlistCount 供 main.js 生命周期呼叫。
 */

// TASK-140-T6：三態互斥的共用 computed。grid／燈箱／detail 三處模板都只問這支，
// 不得各自重寫判斷式（spec F1「同一組三態要出現在三處」）。
export function cardActionState(result) {
    if (result?._localStatus?.exists) {
        return (result._localStatus.count > 1) ? 'play+folder' : 'play';
    }
    return result?._wishlisted ? 'bookmark-remove' : 'bookmark-add';
}

export function searchStateWishlist() {
    return {
        // ===== Wishlist State =====
        wishlistItems: [],
        wishlistCount: 0,
        wishlistLoaded: false,
        wishlistLightboxOpen: false,   // T11a：書籤燈箱開關（獨立狀態機，不與 lightboxOpen 共用）
        wishlistLightboxIndex: -1,     // T11a：書籤燈箱目前顯示的 wishlistItems 索引
        _wishlistLbImgError: false,    // T11a：燈箱封面破圖 flag（開燈箱時必須重設，否則殘留占位）
        // T7 review P2：切進書籤前的 displayMode，切回搜尋段時還原。
        // 沒有它的話：你在 detail 模式看著某一片 → 點書籤段 → 點回來 → 剛才那張卡
        // 不見了、變成整片 grid 牆，得自己在牆上重新找回那一筆。
        // 為什麼不能乾脆不動 displayMode：wishlist 模式下 displayMode 不得為 'detail'
        // （listMode 對帳表 #2/#3/#7/#29 的前提），所以「記住再還原」是唯一解。
        _preWishlistDisplayMode: null,
        // 🔴 Codex PR#175 P2：連 listMode 一起記。原本只記 displayMode，`switchToSearchList()`
        // 硬設 `listMode = 'search'`——但切進書籤之前可能是 `'file'`（把影片檔拖進來比對的那條
        // 流程）。實測重現：`listMode:'file'`／`fileList` 1 筆 → 點書籤 → 點回搜尋 ⇒ listMode
        // 落在 `'search'`，`fileList` 資料還在記憶體裡但 `#fileList`（search.html:1068）連同
        // 整理列、改番號那排控制項（:1014/:1020/:1036）全部隱藏 ⇒ **使用者的拖曳工作階段
        // 看起來整個不見了**，而且會被 $watch 存進 sessionStorage，重新整理也回不來。
        _preWishlistListMode: null,

        // ===== Computed Properties =====
        // TASK-140-T12：F7 清理鈕只在有已入手項目時出現，讀 T8 對帳寫入的 _owned 欄位。
        get ownedWishlistCount() {
            return this.wishlistItems.filter((i) => i._owned).length;
        },

        cardActionState,

        switchToWishlist() {
            if (this.listMode !== 'wishlist') {
                this._preWishlistDisplayMode = this.displayMode;
                this._preWishlistListMode = this.listMode;
            }
            this.listMode = 'wishlist';
            this.displayMode = 'grid';
            // T8 review P2：**每次開啟都重新對帳**，不是只有第一次。
            // spec F6 的對帳時機明寫「開啟書籤清單時」；只在 !wishlistLoaded 時載入的話：
            // 你把書籤裡的片掃描入庫 → 切回書籤分頁 → 角標不會出現、卡片也不會沉底，
            // 除非整頁重新整理（owner hard-gate 第 6 條走的就是這條流程）。
            // 成本是每次切換一支**本地** SQLite 查詢，F6 驗收 5「零對外請求」不受影響。
            // `wishlistLoaded` 保留，但語意收斂成「載入過至少一次」——只用來 gate 空狀態，
            // 避免資料還沒回來就先閃一下「還沒有任何書籤」。
            return this.loadWishlist();
        },

        switchToSearchList() {
            // 還原成切進書籤前的那個模式；沒記到就落回 'search'（這顆鈕的預設語意）。
            this.listMode = this._preWishlistListMode || 'search';
            this._preWishlistListMode = null;
            if (this._preWishlistDisplayMode) {
                this.displayMode = this._preWishlistDisplayMode;
                this._preWishlistDisplayMode = null;
            }
        },

        async loadWishlistCount() {
            try {
                const resp = await fetch('/api/wishlist/count');
                if (!resp.ok) {
                    console.error('[Wishlist] count 請求失敗:', resp.status);
                    return;
                }
                const data = await resp.json();
                this.wishlistCount = data.count;
            } catch (err) {
                console.error('[Wishlist] count 查詢失敗:', err);
            }
        },

        // Codex review P2（Opus 2026-09-02）：這支是**整包覆蓋**（`this.wishlistItems = data`），
        // 而且沒有任何機制能分辨「這個回應是不是已經過期」。過期窗口確實存在：
        // `switchToSearchList()`（上面）不清空 `wishlistItems`，所以切回書籤分頁的那一瞬間，
        // 畫面會先用**上一次的舊資料**把卡片、垃圾桶鈕、清理鈕全部渲染出來，新的 GET 這時
        // 還在飛。使用者於是能在舊 GET 回來之前就按下清理——舊 GET 晚回來就把剛清掉的項目
        // 整包寫回畫面。
        // 窗口大小不是理論值：`GET /api/wishlist` 會對 videos 做**全表掃描**
        // （`get_by_numbers()` 用 `UPPER(number)` 比對，吃不到 `idx_videos_number`，
        // EXPLAIN QUERY PLAN 實測是 `SCAN videos`），片庫越大、機器越慢窗口越寬。
        // 接上既有的 AbortController registry（`_getAbortSignal`/`_clearAbort`，
        // search-flow.js:938-955，setFileList／loadFavorite／loadMore 同一套），讓
        // `cleanupOwnedWishlist()` 有辦法作廢它；順帶讓連續兩次載入變成 last-wins。
        async loadWishlist() {
            const signal = this._getAbortSignal('loadWishlist');
            try {
                const resp = await fetch('/api/wishlist', { signal });
                if (!resp.ok) {
                    console.error('[Wishlist] list 請求失敗:', resp.status);
                    return;
                }
                const data = await resp.json();
                this.wishlistItems = data;
                this.wishlistLoaded = true;
            } catch (err) {
                if (err?.name === 'AbortError') return;   // 被新載入或清理作廢，靜默放棄
                console.error('[Wishlist] list 查詢失敗:', err);
            } finally {
                this._clearAbort('loadWishlist', signal);
            }
        },

        async addToWishlist(result) {
            if (!result?.number) return;

            const prevWishlisted = result._wishlisted;
            // 計數用「增量」不用「快照還原」（sonnet review P2-2）：兩張不同卡片
            // 連點時，後者捕到的 prevCount 已經含前者的樂觀 +1；前者失敗時把
            // wishlistCount 寫回自己的 prevCount，會連後者那筆成功的一起抹掉。
            // 增量回滾（--）在任意交錯順序下都收斂到正確值，而且少一個要維護的狀態。
            result._wishlisted = true;
            this.wishlistCount += 1;
            if (this.wishlistLoaded) {
                this.wishlistItems.unshift(result);
            }

            try {
                const resp = await fetch('/api/wishlist', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        number: result.number,
                        title: result.title || '',
                        actors: result.actors || [],
                        tags: result.tags || [],
                        maker: result.maker || '',
                        director: result.director || '',
                        series: result.series || '',
                        label: result.label || '',
                        duration: result.duration ?? null,
                        date: result.date || '',
                        cover: result.cover || '',
                        preview_cover_url: result.preview_cover_url || '',
                        sample_images: result.sample_images || [],
                        preview_sample_images: result.preview_sample_images || [],
                        source: result.source || '',
                        url: result.url || '',
                    }),
                });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                // 🔴 branch review P2-1（2026-09-02）：端點對「這個番號本來就在」回的是
                // 200 ＋ `added:false`（不是錯誤——加入書籤是冪等的）。不看這個欄位的話，
                // 樂觀 +1 會憑空多算一筆：切換版本會把整顆結果物件換掉、連帶清掉
                // `_wishlisted`，卡片變回「加入書籤」，再按一次就重複計數。
                // 處置與 removeFromWishlist 的 `success:false` 同一套：本地計數已知與 DB
                // 對不上 ⇒ 跟伺服器要權威值；同時把樂觀 unshift 的那筆重複拿掉
                // （原本那筆還在陣列裡，留著會產生同 number 的重複 :key）。
                let data = null;
                try {
                    data = await resp.json();
                } catch (parseErr) {
                    console.error('[Wishlist] add 回應解析失敗:', parseErr);
                }
                if (data?.added === false) {
                    if (this.wishlistLoaded) {
                        this.wishlistItems = this.wishlistItems.filter((i) => i !== result);
                    }
                    await this.loadWishlistCount();
                }
            } catch (err) {
                console.error('[Wishlist] add 失敗:', err);
                result._wishlisted = prevWishlisted;
                this.wishlistCount = Math.max(0, this.wishlistCount - 1);
                if (this.wishlistLoaded) {
                    this.wishlistItems = this.wishlistItems.filter((i) => i !== result);
                }
            }
        },

        async removeFromWishlist(number) {
            if (!number) return;

            const matchedResults = (this.searchResults || []).filter((r) => r.number === number);
            const prevFlags = matchedResults.map((r) => r._wishlisted);
            const removedItem = this.wishlistLoaded
                ? this.wishlistItems.find((i) => i.number === number)
                : null;

            this.wishlistCount = Math.max(0, this.wishlistCount - 1);  // 增量，理由同 addToWishlist
            matchedResults.forEach((r) => { r._wishlisted = false; });
            if (this.wishlistLoaded) {
                this.wishlistItems = this.wishlistItems.filter((i) => i.number !== number);
            }

            try {
                const resp = await fetch(`/api/wishlist/${encodeURIComponent(number)}`, {
                    method: 'DELETE',
                });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                // Codex review P2（Opus 2026-09-02）：端點對「那一列本來就不在」回的是
                // **HTTP 200 `{success:false}`**（wishlist.py:104），不是錯誤碼。只看 `resp.ok`
                // 的話那次會被當成刪除成功，樂觀扣掉的計數永遠補不回來——而 `loadWishlistCount()`
                // 只掛在 main.js 的生命周期初始化，書籤／搜尋分頁來回切**都不會重跑**，數字要
                // 整個離開頁面再回來才會校正。（此處刻意不寫出那支函式的字面名稱：本檔有一條
                // 「不得出現該字面」的守衛，T11a 踩過註解餵飽守衛、這次是註解踩壞守衛。）
                //
                // 這裡刻意**不**回滾。`success:false` 的語意是「伺服器上已經沒有這一列」，
                // 把它 unshift 回去等於在畫面塞一張 DB 裡不存在的幽靈卡、並讓計數高於實際，
                // 比不處理更糟。正確處置是承認本地計數已經和 DB 對不上，直接跟伺服器要
                // 權威值（`/api/wishlist/count` 是單一 COUNT(*)，不走 videos 全表掃描）。
                let data = null;
                try {
                    data = await resp.json();
                } catch (parseErr) {
                    // 2xx 但 body 不是合法 JSON：刪除本身已成功，狀態不動
                    console.error('[Wishlist] remove 回應解析失敗:', parseErr);
                }
                if (data?.success === false) {
                    await this.loadWishlistCount();
                }
            } catch (err) {
                console.error('[Wishlist] remove 失敗:', err);
                this.wishlistCount += 1;
                matchedResults.forEach((r, idx) => { r._wishlisted = prevFlags[idx]; });
                if (this.wishlistLoaded && removedItem) {
                    this.wishlistItems.unshift(removedItem);
                }
            }
        },

        currentWishlistLightboxItem() {
            if (this.wishlistLightboxIndex < 0 || this.wishlistLightboxIndex >= this.wishlistItems.length) return undefined;
            return this.wishlistItems[this.wishlistLightboxIndex];
        },

        openWishlistLightbox(index) {
            this._wishlistLbImgError = false;
            this.wishlistLightboxIndex = index;
            this.wishlistLightboxOpen = true;
        },

        closeWishlistLightbox() {
            this.wishlistLightboxOpen = false;
        },

        // 三支換片的方法都要重設 _wishlistLbImgError（Opus 2026-09-02 補，grok 自報的偏離 #2）：
        // 只在 open() 重設的話，先看到一部沒封面的片、再按箭頭切到有封面的那部，
        // 封面不會出現——畫面停在「無圖」占位，使用者會以為那部也沒封面。
        prevWishlistLightbox() {
            this._wishlistLbImgError = false;
            this.wishlistLightboxIndex = Math.max(0, this.wishlistLightboxIndex - 1);
        },

        nextWishlistLightbox() {
            this._wishlistLbImgError = false;
            this.wishlistLightboxIndex = Math.min(this.wishlistItems.length - 1, this.wishlistLightboxIndex + 1);
        },

        // TASK-140-T12（F7）：破壞性操作，不做樂觀更新——失敗時三件事都不做，只出 error toast
        // （承重段第4條：與 add/remove 的樂觀更新刻意不同，那兩個失敗頂多少一筆書籤，這個失敗
        // 若做了樂觀更新，使用者會以為整理完了但其實沒有）。刻意用「fetch 與 !resp.ok 分開判斷、
        // 各自 early return」的形狀（不是 addToWishlist 那種單一 try/throw），理由見下方
        // mutation M3 錨點說明。
        async cleanupOwnedWishlist() {
            let resp;
            try {
                resp = await fetch('/api/wishlist/cleanup', { method: 'POST' });
            } catch (err) {
                console.error('[Wishlist] cleanup 失敗:', err);
                this.showToast(window.t('search.toast.wishlist_clean_failed'), 'error');
                return;
            }
            if (!resp.ok) {
                console.error('[Wishlist] cleanup 請求失敗:', resp.status);
                this.showToast(window.t('search.toast.wishlist_clean_failed'), 'error');
                return;
            }
            // sonnet review P2：resp.json() 本身會 throw（2xx 但 body 不是合法 JSON——
            // 連線被截斷、反向代理插了非 JSON 內容）。不包的話那條路徑是 unhandled rejection：
            // 畫面上不會有任何 toast，count/items 也沒動，使用者按完完全不知道成功還是失敗。
            let data;
            try {
                data = await resp.json();
            } catch (err) {
                console.error('[Wishlist] cleanup 回應解析失敗:', err);
                this.showToast(window.t('search.toast.wishlist_clean_failed'), 'error');
                return;
            }
            // Codex 二審 P2（Opus 2026-09-02）：清理成功後對 `wishlistItems` 的過濾是**權威值**，
            // 而 `loadWishlist()` 是無條件整包覆蓋。作廢的時機必須是**這裡**（寫入之前），不是
            // 送出 POST 之前——我第一輪放在開頭並註明「之後不可能再有新的 GET」，那個推理是錯的：
            // 兩顆 segmented 鈕在清理期間都沒被擋（search.html:407-415），使用者覺得慢而點
            // 「搜尋」再點「書籤」，`listMode !== 'wishlist'` 成立 ⇒ `switchToWishlist()` 會建出
            // **全新的** controller，開頭那次 abort 碰不到它。而那個新 GET 很可能在伺服器端讀到
            // 刪除前的資料（清理還在跑全表掃描 ＋ 逐筆刪封面），卻晚於清理回來。
            //
            // 放在寫入之前就完整了，三種到達順序都收斂：
            //   ① 此刻仍在飛的 GET（不論它是清理前還是清理中發出的）⇒ 這裡作廢，寫不進來
            //   ② 已經在這之前回來的 GET ⇒ 它寫進去的舊清單接著被下一行的 `!_owned` 過濾掉
            //   ③ 這之後才發出的 GET ⇒ POST 已回，伺服器端 DELETE 早已 commit，讀到的是對的
            this._abortControllers.loadWishlist?.abort();
            const deletedCount = data.deleted_count || 0;
            this.wishlistCount = Math.max(0, this.wishlistCount - deletedCount);
            this.wishlistItems = this.wishlistItems.filter((i) => !i._owned);
            this.showToast(window.t('search.toast.wishlist_cleaned', { count: deletedCount }), 'success');
        },
    };
}
