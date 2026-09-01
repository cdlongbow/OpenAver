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

        cardActionState,

        switchToWishlist() {
            if (this.listMode !== 'wishlist') {
                this._preWishlistDisplayMode = this.displayMode;
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
            this.listMode = 'search';
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

        async loadWishlist() {
            try {
                const resp = await fetch('/api/wishlist');
                if (!resp.ok) {
                    console.error('[Wishlist] list 請求失敗:', resp.status);
                    return;
                }
                const data = await resp.json();
                this.wishlistItems = data;
                this.wishlistLoaded = true;
            } catch (err) {
                console.error('[Wishlist] list 查詢失敗:', err);
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
    };
}
