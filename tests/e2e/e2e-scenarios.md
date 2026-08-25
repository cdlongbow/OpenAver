# E2E 用戶旅程劇本（v2 — 2026-05-14 align 後）

> 純文字劇本，**人類用瀏覽器手動 / AI 用 Playwright MCP** 皆可照跑。
> 對應 spec：`feature/59-onboarding-help-polish/spec-59.md` §8 + plan-59c.md
> **AI 首次操作前先讀 `app-guide.md`**（同目錄）了解各頁面操作方式。

---

## 執行方式

### Server 啟動

```bash
source venv/bin/activate && uvicorn web.app:app --host 127.0.0.1 --port 8000
```

### Playwright MCP Server 選擇

| Server | 用途 | 啟動方式 |
|--------|------|---------|
| `playwright`（headless） | Clean state 跑（無 cache）；CI-like 一致性；建議 US1–US4 用 | 已在 MCP config |
| `playwright-cdp`（CDP attach） | 視覺確認、需看動畫（US3 constellation / US5 photo enrichment）；共享 Chrome 已登入狀態 | Chrome 啟動加 `--remote-debugging-port=9222` |

**Risk-2 — Cache 黏性**：CDP attach 模式會沿用 Chrome ESM module map cache；改 JS 模組後 e2e 跑前用 Incognito 視窗或切 headless server。

### 執行時機

| 時機 | 範圍 | 時間 |
|------|------|------|
| Milestone pre-merge | US1–US7 全套（外部 API 失敗 skip 並記原因） | 10–20 分 |
| Release 前 | US1–US7 全套（保險） | 10–20 分 |
| Feature branch 含 template 改動 | 受影響的 US（1–2 個） | 5 分內 |

---

## 前置條件（所有 US 共通）

- Dev server 已啟動於 `http://localhost:8000`
- DB 已有至少 10 部影片（US3–US7 需要）
- 4 locale 翻譯檔齊全（US6 需要）

每個 US 在 Setup 段列獨立重置指令；US 之間 state 殘留處置見 plan-59c §7 Risk-3。

---

## US1: 新手 Onboarding

**故事**：用戶第一次開軟體 → tutorial 自動觸發 → 7 步 spotlight 走完 → 完成狀態持久化（加資料夾 / 掃描 / Showcase 依賴 PyWebView picker，不在本 US；由 US2 / US3 涵蓋實際資料流）。

### Setup

- Dev server 已啟動於 `http://localhost:8000`
- 清 tutorial flag（browser_evaluate）：
  ```js
  localStorage.removeItem('openaver_tutorial_completed');
  ```
- 確認後端 `config.json` 中 `general.tutorial_completed = false`（或無此 key）；可呼 `GET /api/tutorial-status` 確認 `{"completed": false}`
- 資料：不需預先資料（測試 onboarding 零資料狀態）

### Steps

1. `browser_navigate` → `http://localhost:8000/scanner`
2. `browser_wait_for` selector=`#tutorialOverlay.active` timeout=3s
3. `browser_snapshot` 驗：
   - `#tutorialOverlay` 存在且有 `.active` class
   - `#btnSelectFolder` 在頁面上（spotlight 模式靠 CSS box-shadow punch-out 命中此元素）
   - `#tutorialProgress` 文字含 `1 / 7`
4. `browser_click` → `#tutorialNext`；`browser_wait_for` `#tutorialProgress` text contains `2 / 7`
5. `browser_snapshot` 驗 `#btnGenerate` 在 viewport 內（step 2 spotlight 命中產生網頁按鈕）
6. `browser_click` → `#tutorialNext`；驗進度 `3 / 7`、sidebar `a[href="/scanner"]` 取得 outline（sidebar mode）
7. `browser_click` → `#tutorialNext`；驗進度 `4 / 7`、sidebar `a[href="/showcase"]` outline
8. `browser_click` → `#tutorialNext` × 3 → 依序驗 step 5/6/7：
   - step 5：sidebar `a[href="/search"]` outline、進度 `5 / 7`
   - step 6：sidebar `a[href="/settings"]` outline、進度 `6 / 7`
   - step 7：sidebar `a[href="/help"]` outline、進度 `7 / 7`、`#tutorialNext` innerText 變為 `tutorial.done` 翻譯（如「完成」/「Done」）
9. `browser_click` → `#tutorialNext`（done）；`browser_wait_for` `#tutorialOverlay` 消失或 `:not(.active)`
10. `browser_evaluate` → `localStorage.getItem('openaver_tutorial_completed')` 預期 `=== 'true'`
11. **H1 Help verify**：`browser_click` → `#sidebar a[href="/help"]`；`browser_wait_for` URL = `/help` timeout=3s
    - **驗**：`h2.card-title` 至少 1 個存在且 innerText **不含** `help.` 字串（無 raw i18n key）
    - **驗**：`.terminal-copy-btn` 可見（curl 複製按鈕 render 正常）

**Tutorial Restart 分支**：
- `browser_navigate` → `http://localhost:8000/scanner?tutorial=restart`
- `browser_wait_for` `#tutorialOverlay.active` timeout=2s
- 驗 `#tutorialProgress` 從 `1 / 7` 開始（重播一律從 step 1）

**重整後不自動觸發驗證**：
- `browser_navigate` 重新整理 `http://localhost:8000/scanner`
- `browser_wait_for` 2s（等可能的 auto-trigger）
- `browser_snapshot` 驗 `#tutorialOverlay` 不存在或 `:not(.active)`

### 完成後 state

- `localStorage.openaver_tutorial_completed === 'true'`
- `GET /api/tutorial-status` 回 `{"completed": true}`（可選驗）
- DOM：`#tutorialOverlay` 不存在或無 `.active` class
- Help 頁所有 `h2.card-title` 無 `help.` 字串

### PyWebView 例外

N/A — tutorial flow 是 browser-only，無需 PyWebView picker。Step 6 sidebar 模式指回 `/scanner` 自身（CD-59-2：避開 `#btnUpdate` 首載隱藏導致 silent skip）。

### Regression 偵測點

- `#btnSelectFolder` 不存在 → tutorial step 1 silent skip → 觀察 `#tutorialProgress` 一開始就是 `2 / 7` 而非 `1 / 7`
- sidebar mode dim 區域算錯 → overlay 沒覆蓋主內容（視覺：主內容仍亮、sidebar 也被 dim）
- locale 切換後文案沒抓對 step → i18n raw key 顯示（如 `tutorial.step1_title` 字串出現在 overlay）
- `tutorial_completed` 沒持久化到後端 → 重整後 tutorial 再次自動觸發（步驟「重整後不自動觸發驗證」失敗）
- `?tutorial=restart` 不從 step 1 起算 → 進度顯示非 `1 / 7`

---

## US2: Search → 整理 → 即時上架

**故事**：用戶在 Search 頁查番號 → SSE 多來源結果 → 觸發整理（scrape）→ 觀察 GhostFly 飛 sidebar Showcase icon → DB 即時 upsert → 切到 Showcase 確認新片到位。

### Setup

- DB 已連上 Scanner tracked directory（否則 `db_sync_status` 會回 `not_linked`）
- 預先放小型有效 MP4 fixture（`tests/fixtures/e2e/SONE-205.mp4`，建議 < 1MB **真實 mp4**，不要用 0-byte placeholder — Scanner/filter/organize 任一層若檢查 size 或 metadata 會 skip 假檔造成假陽性）
- 該路徑須在 Settings → favorite folder 或 Scanner tracked directory 內
- 該番號尚未存在於 DB：
  ```js
  // browser_evaluate
  fetch('/api/search/local-status?numbers=SONE-205').then(r => r.json())
  // 預期 {"SONE-205":{"exists":false}}
  ```
- 若 fixture 或 linked directory 不存在 → **skip US2 並記錄原因**
- Search 頁初始狀態（清除任何殘留搜尋）

### Steps

1. `browser_navigate` → `http://localhost:8000/search`
2. `browser_type` 番號 `SONE-205` 至搜尋輸入框，`browser_press_key` `Enter`
3. `browser_wait_for` selector=`#resultCard` (x-show pageState === 'result') timeout=15s
4. **Sub-A — Detail card render 驗收**：`browser_snapshot` 驗
   - `#resultCard` 內含封面 `<img>` 已載入（`naturalWidth > 0`）
   - 番號 text 含 `SONE-205`、女優欄位非空、片商欄位非空
   - 多來源指示器（如 source badge）至少 1 個
5. **觸發整理（file-list 模式批次）** — 走 file-list 流。`scrapeAll()` 只處理 `f.searched && f.searchResults.length > 0 && !f.scraped` 的 file，所以必須先 `searchAll()` 讓每個 fileList item 取得 searchResults，才能整理。順序：
   - **5a. 進 file-list 模式（明確操作）**：
     - 先確認 Settings → favorite folder 已指向放有 fixture mp4 的目錄；若未設定或目錄為空 → **skip US2 並記錄原因**
     - **清空 Search state**（step 1-4 已停在 `pageState === 'result'`，`#btnFavorite` 只在 `#emptyState` 顯示）：
       - `browser_click` → `#btnClear`（`search.html:288`，`x-show="hasContent"`，`@click="clearAll()"`）；或
       - `browser_evaluate` `() => Alpine.$data(document.querySelector('[x-data*="search"]')).clearAll()` 直接清狀態
     - `browser_wait_for` `#emptyState` 可見（`pageState === 'empty'`，`search.html:306`）
     - `browser_click` → `#btnFavorite`（`search.html:316`，`@click="loadFavorite()"`；按鈕在 `#emptyState` 內，必須先清空 result state 才能命中）
     - PyWebView/files/drop 是另一條進場路徑（`setFileList()`），browser e2e 不適用
     - `browser_wait_for` `#btnSearchAll` 可見（`search.html:758`，`x-show="listMode === 'file'"`）+ fileList 顯示 fixture
   - **5b. 先跑 searchAll**：`browser_click` → `#btnSearchAll`（`searchAll()`，`state/batch.js:140`）
   - `browser_wait_for` `#batchProgress` 出現（searchAll SSE 進行中）
   - `browser_wait_for` `#batchProgress` 消失 timeout=60s（searchAll 完成，每個 file 取得 `searched=true` + `searchResults`）
   - **5c. 跑 scrapeAll**（gate 在 `scrapeAll()` 內判，不是 button disabled）：
     - `#btnScrapeAll` 的 `:disabled` 綁的是 `isScrapeAllProcessing`（`search.html:777`），不是「有沒有可整理檔」— 該 button 在 5b 完成後仍可點，但若 fileList 無可整理檔則 click 後直接 toast
     - **驗 fileList 至少一筆**：`browser_evaluate` `() => Alpine.$data(document.querySelector('[x-data*="search"]')).fileList.filter(f => f.searched && f.searchResults?.length > 0 && !f.scraped).length`，預期 `>= 1`（對應 `batch.js:336-338` `scrapableFiles` filter）
     - `browser_click` → `#btnScrapeAll`（`scrapeAll()`，搬移檔案 + 改名 + 建目錄）
   - **失敗模式提示**：跳過 5b 或 fileList 無 searchResults，點 #btnScrapeAll 會 toast `search.toast.no_scrapable_files`（`state/batch.js:341`）
   - `browser_wait_for` `#scrapeProgress` 出現（整理 SSE 進行中；`#batchProgress` 是 searchAll 用，不通用）
   - `browser_wait_for` `#scrapeProgress` 消失 timeout=60s（整理 SSE 完成）
6. **GhostFly + DB sync 觀察**：
   - 整理觸發後 `[data-search-ghost]` 元素於 DOM 短暫出現（飛行中）→ 動畫結束後自動移除
   - `browser_wait_for` `#sidebar-showcase-link.pulse-once` timeout=5s（一圈停止；`base.html:537,541`）
   - **驗 db_sync_status**：`browser_evaluate` 取最後一筆 organize response：
     ```js
     // batch.js:94 處設 result.db_sync_status；無公開 API 觀測，靠 _handleDbSyncFeedback toast
     // 改驗 toast：page console 應印 [GhostFly] 或 toast text 含 "已整理"
     ```
7. `browser_navigate` → `/showcase`；驗剛整理的片出現在 grid（搜尋框輸入 `SONE-205` 應命中 1 筆）
8. **Sub-B — 多筆 query 導航**（**獨立 sub-flow，與 organize 流分開跑**；條件 `N >= 2`）：
   - `browser_navigate` → `/search`，搜 `SSIS`（預期多筆）
   - 切到 Detail mode（按 `A` 鍵或點切換按鈕）；驗 navIndicator 顯示 `1/N`，`N >= 2`
   - `browser_press_key` `Tab` 或 click 非搜尋框元素以 blur（方向鍵在搜尋框 focus 時不觸發）
   - `browser_press_key` `ArrowRight` → 驗番號改變、indicator `2/N`
   - `browser_press_key` `ArrowLeft` → 回 `1/N`
   - 驗 Sample Gallery 全程未開啟（無 `.sample-gallery.show` 之類）

### 完成後 state

- `SONE-205` 在 DB 中存在：`fetch('/api/search/local-status?numbers=SONE-205')` 回 `{"SONE-205":{"exists":true}}`
- Sidebar showcase link 有過 `pulse-once` 動畫（class 自動移除，1 圈後恢復）
- DOM 無 `[data-search-ghost]` 殘留元素（GhostFly clone 已清除）

### PyWebView 例外

- S5「拖入檔案」依賴 PyWebView file dialog / drag-drop → 用「Setup 預設已有番號」繞過，不在 browser 跑
- 若走 file-list 模式整理本地檔案，「加入檔案」按鈕 picker 亦為 PyWebView-only → US2 假設 fixture 已位於 tracked directory，不點 picker

### Regression 偵測點

- `db_sync_status` 沒觸發 → SSE 斷線或 `try_inflow_upsert` 失敗 → `#sidebar-showcase-link.pulse-once` 不出現
- GhostFly clone 殘留 DOM → 動畫結束未清理 → `[data-search-ghost]` 元素留在 body
- 起飛點抓錯（grid / file-list 視角 width=0）→ B2 fix `_findDbSyncSourceEl` 五級 fallback；觀察動畫起點偏離預期
- 方向鍵在搜尋框 focus 時被觸發 → 切片亂跳；應 blur 後才生效
- X2 跨頁污染：切到 Showcase 再回 Search，搜尋結果意外殘留 / 清空（視設計而定，記錄當時行為）

---

## US3: Showcase 瀏覽 + Lightbox + 魔杖探索

**故事**：用戶開 Showcase 看收藏 → 翻頁 → 點卡片進 Lightbox → 鍵盤切片 → 點魔杖進相似探索（似星空 constellation）→ 鑽入新主圖。

### Setup

- Showcase 已有至少 10 部影片（依 `videoCount` 計）
- DB 已建好 metadata（cover_url / actresses / tags 完整）
- 清 similar mode 殘留：`browser_evaluate` 設 `Alpine.store?` 或直接重整頁面
- 清 lightbox 殘留：URL 無 `?id=` 等深連結參數

### Steps

1. `browser_navigate` → `http://localhost:8000/showcase`
2. `browser_wait_for` selector=`[x-for="(video, index) in paginatedVideos"]` 渲染（or wait for first card `.av-card-preview:not(.hero-card)` 出現）timeout=5s
   - **驗**：grid 內卡片數 > 0、總數顯示（`videoCount` text 或 grid item count）
3. **翻頁驗收**：點 `.pager-btn`（next 箭頭 `›`，`showcase.html:1227`）
   - `browser_wait_for` page 變化（page indicator 更新或 selected option 改變）
   - **驗**：卡片內容與第 1 頁不同（取第 1 張卡片 number text 對比）
4. **進 Lightbox**：`browser_click` 任一卡片封面（`.av-card-preview:not(.hero-card)` 內 `<img>` 或封面區）
   - `browser_wait_for` selector=`.showcase-lightbox.show` timeout=2s（`showcase.html:517-518`，`lightboxOpen` 為 true 時加 `.show`）
5. **鍵盤導航**：
   - `browser_press_key` `ArrowRight` → 驗番號 / 封面更新（lightbox 內主圖換片）
   - `browser_press_key` `ArrowLeft` → 回前一片
   - `browser_press_key` `Escape` → 驗 `.showcase-lightbox` 失去 `.show` class（lightbox 關閉）
6. **魔杖進入相似探索**：重開 lightbox（重複 step 4）
   - `browser_click` → `.lightbox-similar-btn`（`showcase.html:532`，內含 `<i class="bi bi-magic">`）
   - `browser_wait_for` selector=`.similar-stage` 可見且 `similarModeOpen === true` timeout=3s（`state-similar.js:75`）
7. **Constellation 動畫驗收**：
   - **驗**：`.similar-stage-inner` 渲染、`.similar-rail` 至少 1 條非 `.rail--hidden`（`showcase.html:1072`）
   - **驗**：周圍有相似片 card（plan 預期 8 張）
8. **鑽入（slip-through）**：`browser_click` 任一相似片 card
   - `browser_wait_for` 主圖更新（封面飛中央）
   - **驗**：仍在 similar mode（`.similar-stage` 仍可見），不是退回 Lightbox
9. **退出 similar mode 而非整個 Lightbox**：`browser_press_key` `Escape`
   - **驗**：`.similar-stage` 消失 / `similarModeOpen === false`
   - **驗**：`.showcase-lightbox.show` 仍存在（lightbox 主體還在）
10. `browser_press_key` `Escape` 再一次 → 驗 lightbox 完全關閉

### 完成後 state

- `.showcase-lightbox` 失去 `.show` class
- `.similar-stage` 不可見 / `similarModeOpen === false`
- DOM 無 `[data-search-ghost]` clone 殘留
- URL 未殘留 lightbox state（依設計：可能保留 `?id=`，記錄當時行為）

### PyWebView 例外

N/A — Showcase / Lightbox / 魔杖 探索 完整 browser-only。

### Regression 偵測點

- ESC 在 similar mode 直接關 Lightbox → 應只退 similar mode（兩段式）；現象：`.showcase-lightbox` 一次 ESC 就消失
- 鍵盤導航在搜尋框 focus 時觸發 → ArrowLeft/Right 改變字元而非切片
- Similar stage rail 全部 `.rail--hidden` → 動畫初始化失敗（`playInitialExpand` 沒跑或 GSAP 沒載）
- 翻頁後 lightbox 開啟回到 page 1 → 翻頁 state 沒保留
- `.lightbox-similar-btn` 不可見 → SSR `__CLIP_ENABLED__` 或 router 沒揭露魔杖（v0.8.7 後規則式應永遠可見，若 hidden 表示誤觸 v0.8.6 opt-in gate 殘留）

---

## US4: 跨語言 Tag Alias 篩選

**故事**：用戶在 Showcase 用中文 tag 搜尋 → alias 自動展開（中⇄日⇄英）→ 結果含同義詞匹配 → 點 tag chip 進一步篩選。

### Setup

- DB 有至少 1 個 tag alias group（如「女僕」⇄「メイド」⇄「maid」）；可透過 Scanner 頁 Tag 別名管理 chip 牆預建，或：
  ```bash
  curl -X POST http://localhost:8000/api/tag-aliases \
       -H "Content-Type: application/json" \
       -d '{"primary_name":"女僕","aliases":["メイド","maid"]}'
  ```
- Showcase 有對應 tag 的影片（至少 1 部 tags 含「メイド」，但**不**含「女僕」）
- 清空 Showcase 搜尋框（`browser_evaluate $store...` 或重整）

### Steps

1. `browser_navigate` → `http://localhost:8000/showcase`
2. `browser_wait_for` `filteredCount` 顯示初始總數（`showcase.html:1170` `<b x-text="filteredCount">`）
3. `browser_click` Showcase 搜尋框（`x-model="search"`，`showcase.html:72`）
4. `browser_type` `女僕`（中文 primary）
5. `browser_wait_for` alias 展開觸發：grid 重新 filter
   - **驗**：`filteredCount` 變化（包含 alias 命中結果）
   - **驗**：含「メイド」tag 的影片出現（雖然搜尋框是中文）
6. `browser_evaluate` 確認 `_tagToGroup` 雙向 map 已載入：
   ```js
   // Alpine store 或 window-level state；可透過 fetch 確認 API 同步
   fetch('/api/tag-aliases').then(r => r.json())
   ```
7. **點 tag chip 進一步篩選**：在任一影片卡片內找 `.lb-tag` 或 grid tag chip（`@click.prevent.stop="searchFromMetadata(tag.trim(), 'tag')"`，`showcase.html:378`）
   - `browser_click` 其中一個 tag chip
   - **驗**：搜尋框 `x-model="search"` 更新為 chip 文字、grid 再次 filter
8. **清除搜尋驗收**：清空搜尋框（`browser_type` 空字串或 `browser_press_key` `Escape` if cleared on ESC）
   - **驗**：`filteredCount` 回到 step 2 初始總數、所有影片回來

### 完成後 state

- 搜尋框 `search` model 為空
- `filteredCount === videoCount`（無篩選狀態）
- DB `tag_aliases` group 仍存在（清理由用戶手動或 disposable fixture 處理）

### PyWebView 例外

N/A — Tag alias UI / chip 互動 完全 browser-only。

### Regression 偵測點

- Alias 不展開 → `_tagToGroup` map 沒載入或 `/api/tag-aliases` 端點失敗 → 中文搜尋只匹配 tag 字串完全相同的影片
- Chip click 沒更新 `search` model → `searchFromMetadata` 沒設置 store；觀察搜尋框 input value 未改變
- A5 SimilarRanker DB 整合 cache 失效 → CRUD 後 ranker 仍用舊 alias map（不在本 US 範圍，由 US3 魔杖驗收 cover）
- 搜尋框清空後 `filteredCount` 卡在篩選態 → `applyFilterAndSort` 未在 `search` 變為 `''` 時觸發

---

## US5: 女優最愛流

**故事**：用戶在 Search 查女優名 → 看 actress profile → 加最愛 → 切到 Showcase 女優模式 → 點女優卡進 actress lightbox → 換頭像（alias 展開本地候選）。

### Setup

- 至少 1 個女優在 Search 端有 profile 可查（如 `三上悠亜`）
- 該女優目前**不**在最愛清單（避免 false positive）：
  ```js
  fetch('/api/actresses/三上悠亜').then(r => r.json())
  // 預期 is_favorite: false（或 404 / 該女優 profile 不存在）
  ```
- Showcase 有至少 1 部該女優的影片

### Steps

1. `browser_navigate` → `http://localhost:8000/search`
2. `browser_type` `三上悠亜` 至搜尋框、`browser_press_key` `Enter`
3. `browser_wait_for` 搜尋結果出現；驗女優欄位含 `三上悠亜`
4. **加最愛**：找 actress favorite heart（`search.html:132-143`，`.bi-heart` → `.bi-heart-fill` 切換）
   - `browser_click` heart icon（`x-show="actressProfile && !actressProfile?.is_favorite"`）
   - `browser_wait_for` heart 變為 `.bi-heart-fill`（`is_favorite === true`）
   - **驗**：`fetch('/api/actresses/三上悠亜').then(r => r.json())` 回傳 `is_favorite === true`
5. `browser_navigate` → `http://localhost:8000/showcase`
6. **切到女優模式**：點女優模式 toggle（`showcase.html:57,63` `@click="...toggleActressMode()"`）
   - `browser_wait_for` `showFavoriteActresses === true`（`state-actress.js:14`）
   - **驗**：actress grid 渲染（女優卡片代替影片卡片）
7. **點女優卡開 actress lightbox**：`browser_click` 任一女優卡（如 `三上悠亜`）
   - `browser_wait_for` `.actress-lightbox-meta` 可見（`showcase.html:582`）
   - **驗**：女優 metadata 渲染、影片清單可見
8. **換頭像（alias 本地候選）**：找「換頭像」按鈕 / `manage_photo_path` 入口
   - 點換頭像 → 預期跳本地候選清單 modal（**PyWebView 例外**：folder picker 為原生 API，瀏覽器無法觸發 → 改驗 alias 展開後候選列表的 UI 渲染，不驗 picker 本身）
   - **驗**：候選列表展開 alias 名做多名查詢（v0.8.8 A2）— UI 顯示候選圖片來自 alias 名查詢

### 完成後 state

- `GET /api/actresses/三上悠亜` 回傳含 `is_favorite === true`
- Showcase 處於 `showFavoriteActresses === true` 模式（或保留依用戶切換歷史）
- DB 無寫入意外的 photo path（picker 沒實際選擇）

### PyWebView 例外

- **換頭像 picker**：`window.pywebview.api.select_file()` 為 PyWebView-only；瀏覽器 fallback 行為依設計（可能跳 alert 或 silent skip）
- **繞過策略**：步驟 8 改驗「alias 展開候選列表」UI 渲染，不驗實際選圖；如需驗 photo 寫入，改用 API `POST /api/actresses/{name}/photo` 直接 curl

### Regression 偵測點

- 加最愛後 heart icon 沒更新 → state sync 失敗、`actressProfile.is_favorite` 未刷新
- 女優模式切換後 grid 沒重新 filter → `toggleActressMode` 沒觸發 `applyFilterAndSort` 或 `paginatedActresses` 未更新
- Alias 展開沒套用到本地候選查詢 → v0.8.8 A2 regression（本地路徑應呼 `AliasRepository.resolve(name)` 展開）
- Actress lightbox 開啟後鍵盤 ESC 不關 → 焦點鎖 / `x-trap` 設定錯

---

## US6: i18n 完整切換

**故事**：用戶在 Settings 頁依序切換 4 個 locale（繁 → 简 → あ → EN → 繁）→ 每次切換後驗多頁面 UI 文字在當前語系正確顯示無 raw i18n key → 驗 Dark/Light mode 切換並重載保留 → 驗 tutorial 文案在當前語系正確。

### Setup

- Dev server 已啟動於 `http://localhost:8000`
- 4 locale 翻譯檔齊全（`locales/zh_TW.json`、`locales/zh_CN.json`、`locales/ja.json`、`locales/en.json`）
- 重置 locale 為 `zh-TW`（可直接點 `.locale-toggle-btn` 循環或直接呼 API）：
  ```bash
  curl -X PUT http://localhost:8000/api/config/general/locale \
       -H "Content-Type: application/json" -d '{"value":"zh-TW"}'
  ```
- DB 有至少 1 部影片（US6 step 6 驗 Scanner 頁時用得到）
- 清 tutorial flag（確保 tutorial 可在 step 8 重播）：
  ```js
  // browser_evaluate
  localStorage.removeItem('openaver_tutorial_completed');
  ```

### Steps

1. `browser_navigate` → `http://localhost:8000/settings`；`browser_wait_for` `.locale-toggle-btn` 可見 timeout=3s
   - **驗**：`.locale-toggle-btn` innerText 為 `繁`（目前 locale = zh-TW）
2. **切換 zh-TW → zh-CN**：`browser_click` → `.locale-toggle-btn`
   - `browser_wait_for` 頁面 reload 完成（URL 仍 `/settings`）timeout=5s
   - `browser_snapshot` 驗：
     - `.locale-toggle-btn` innerText 為 `简`（locale 已切換）
     - sidebar `a[href="/showcase"]` 文字**不含** `sidebar.showcase`（無 raw key）
     - 頁面標題區文字非 `settings.` 開頭字串
3. **切換 zh-CN → ja**：`browser_click` → `.locale-toggle-btn`
   - `browser_wait_for` 頁面 reload 完成 timeout=5s
   - **驗**：`.locale-toggle-btn` innerText 為 `あ`
   - **驗**：sidebar 任一 `a[href]` innerText **不含** `sidebar.` 字串（無 raw key）
4. **切換 ja → en**：`browser_click` → `.locale-toggle-btn`
   - `browser_wait_for` 頁面 reload 完成 timeout=5s
   - **驗**：`.locale-toggle-btn` innerText 為 `EN`
   - **驗**：`#saveBtn`（settings.html:762）文字不含 `settings.action.` 字串
5. **切換 en → zh-TW（回到繁體）**：`browser_click` → `.locale-toggle-btn`
   - `browser_wait_for` 頁面 reload timeout=5s
   - **驗**：`.locale-toggle-btn` innerText 回到 `繁`
6. **Dark/Light mode 切換**：
   - `browser_click` → `.theme-toggle-btn`（settings.html:40；`@click="toggleThemeWithTransition()"`）
   - `browser_wait_for` 1s（過場動畫）
   - **驗**：`html` element 的 `data-theme` attribute 切換（light → dim 或 dim → light）
   - `browser_navigate` 重新整理 `http://localhost:8000/settings`
   - `browser_wait_for` `.theme-toggle-btn` 可見 timeout=3s
   - **驗**：`html[data-theme]` 保留上次切換後的值（重載後不 fallback）
7. **Scanner 頁 locale 驗收**：`browser_navigate` → `http://localhost:8000/scanner`
   - `browser_wait_for` `#btnGenerate` 可見 timeout=3s
   - **驗**：`#btnGenerate` innerText **不含** `scanner.` 字串（無 raw i18n key）
   - **驗**：頁面任何可見文字**不含** `tutorial.` 字串（在覆蓋 overlay 未開啟的情況下）
8. **Help 頁 locale 驗收**：`browser_navigate` → `http://localhost:8000/help`
   - `browser_wait_for` `h2.card-title` 至少 1 個 timeout=3s
   - **驗**：所有 `h2.card-title` innerText **不含** `help.` 字串（help.html Hero/card 均為 Jinja 渲染，非 raw key）
   - **驗**：`.terminal-copy-btn` 可見（curl copy 按鈕 render 正常，help.html:71）
9. **Tutorial 文案 locale 驗收**：`browser_navigate` → `http://localhost:8000/scanner?tutorial=restart`
   - `browser_wait_for` `#tutorialOverlay.active` timeout=3s
   - **驗**：`#tutorialTitle`（tutorial.js:97）innerText **不含** `tutorial.step1_title` 字串（當前 locale 應有翻譯顯示，非 raw key）
   - **驗**：`#tutorialProgress` 文字格式正確（含 `/`，如 `1 / 7`）
   - `browser_click` → `#tutorialClose` 關閉 tutorial（由 `tutorial.js` 動態建立，行號易漂移）

### 完成後 state

- `html[data-theme]` 保留最後切換的 theme 值
- `window.__locale` 為 `zh-TW`（最終循環回繁體）
- `/api/config/general/locale` GET 回傳 `{"value":"zh-TW"}`（可選驗）
- `#tutorialOverlay` 不存在或無 `.active` class（已關閉）
- Help 頁所有 `h2.card-title` 無 `help.` 字串

### PyWebView 例外

N/A — locale 切換、Dark/Light mode、tutorial 文案驗收均為 browser-only。Settings 頁最愛資料夾 picker 為 PyWebView-only，本 US 不涉及。

### Regression 偵測點

- locale 切換後某頁出現 raw key（如 `tutorial.step1_title` 顯示在 overlay）→ 對應 locale JSON 缺翻譯或 `window.t()` fallback 未命中；觀察：`#tutorialTitle` innerText 直接是 key 字串
- Dark mode 重載後 fallback 回 Light → `toggleThemeWithTransition` 沒把 `data-theme` 寫入 DB / localStorage；觀察：`html[data-theme]` 重載後變回預設值
- locale 循環跳過某個 locale → `cycleLocale()` 的 `order` array 缺項；觀察：`.locale-toggle-btn` 從 `简` 直接跳 `EN`（漏掉 `あ`）
- Help 頁 Hero 文字出現 `help.hero.` 開頭 raw key → Jinja `t()` 呼叫失敗（locale JSON 缺鍵 + no fallback）

---

## US7: 控制狂工作流（進階分流）

**故事**：進階用戶在 Settings 自訂命名格式 + 切換搜尋來源 + 關翻譯 → 回 Search 刮削一片驗自訂格式套用 → 在 Scanner 頁新增 Tag Alias group → 最後在 Help 頁複製 AI curl 指令。

### Setup

- Dev server 已啟動於 `http://localhost:8000`
- DB 有至少 1 部影片，且有一部**尚未刮削**的本地 MP4 fixture（US7 step 3 需要）
- Settings 已有預設命名格式（`[{num}][{maker}] {title}`）；若不確定可先呼：
  ```bash
  curl http://localhost:8000/api/config | python3 -c "import sys,json; print(json.load(sys.stdin).get('organize',{}).get('filename_format',''))"
  ```
- 清 Tag Alias（避免 step 4 衝突）：
  ```bash
  # 可選：確認現有 tag alias 不含測試用 primary name「アクション」
  curl http://localhost:8000/api/tag-aliases
  ```

### Steps

1. **修改命名格式**：`browser_navigate` → `http://localhost:8000/settings`
   - `browser_wait_for` `#filenameFormat` 可見（settings.html:546）timeout=3s
   - `browser_triple_click`（或 `browser_click` + Ctrl+A）→ 清空 `#filenameFormat` 輸入框
   - `browser_type` → `#filenameFormat` 輸入自訂格式字串：`[{num}] {title}`
   - `browser_click` → `#saveBtn`（settings.html:762；`@submit.prevent="saveConfig"`）
   - `browser_wait_for` `.toast.toast-end` 可見 timeout=3s（settings.html:823；`_toast.visible`）
   - **驗**：toast `alert` 含 class `alert-success`（非 `alert-error`）
2. **翻譯開關切換**：
   - `browser_wait_for` `#translateEnabled` 可見（settings.html:198）timeout=3s
   - `browser_evaluate` 取目前狀態：`document.getElementById('translateEnabled').checked`（記下初始值 `true`/`false`）
   - `browser_click` → `#translateEnabled`（toggle checkbox）
   - **驗**：`document.getElementById('translateEnabled').checked` 值翻轉
   - `browser_click` → `#saveBtn`；`browser_wait_for` toast timeout=3s；**驗** `alert-success`
   - `browser_navigate` 重新整理 `http://localhost:8000/settings`
   - `browser_wait_for` `#translateEnabled` 可見 timeout=3s
   - **驗**：`#translateEnabled` checked 狀態與切換後一致（設定保留）
   - （測試完還原：再 toggle 一次回原始狀態 + save）
3. **刮削一片驗自訂命名格式**：兩種路徑擇一執行：
   - **路徑 A（UI flow）**：`browser_navigate` → `http://localhost:8000/search`；用 favorite-folder / tracked dir 載入 fixture（PyWebView picker 例外），依 US2 step 5 的 file-list 三段（searchAll → 等 #batchProgress → scrapeAll → 等 #scrapeProgress）走完
   - **路徑 B（API curl，最短驗收）**：`POST /api/scrape-single`（`web/routers/scraper.py:50`，會呼 `organize_file()` 真實搬移 + 改名；對比之下 `/api/enrich-single` 只補 metadata 不改檔名，不適用）：
     ```bash
     curl -s -X POST http://localhost:8000/api/scrape-single \
       -H "Content-Type: application/json" \
       -d "{\"file_path\":\"/path/to/$FIXTURE_NUM.mp4\",\"number\":\"$FIXTURE_NUM\"}"
     # 回傳 dict：success / new_folder / new_filename
     ```
   - **驗**：兩條路徑都需確認檔名套用自訂格式：
     ```js
     // browser_evaluate（path A 完成後）
     fetch('/api/search/local-status?numbers=<番號>').then(r => r.json())
     // 預期 exists: true
     ```
     或 path B response 的 `new_filename` 字串符合 Settings 設定的 `filenameFormat` template
4. **Tag Alias 新增**：`browser_navigate` → `http://localhost:8000/scanner`
   - `browser_wait_for` `#tagAliasCard` 可見（scanner.html:394）timeout=3s
   - 若 `#tagAliasCard` 卡片折疊（`.tagAliasCardCollapsed === true`）：`browser_click` → `#tagAliasCard .card-title`（點 header 展開；scanner.html:397）
   - `browser_wait_for` `.tag-alias-wall`（scanner.html:461）或 `.actress-alias-body`（scanner.html:430）可見
   - `browser_type` `アクション` → `.actress-alias-body input[x-model="tagAliasInput"]`（scanner.html:435）
   - `browser_click` → `.actress-alias-body button[\\@click="addTagAliasGroup()"]`（scanner.html:440）
   - `browser_wait_for` `.tag-alias-wall` 出現新 chip timeout=3s
   - **驗**：`.tag-alias-wall` 內含 `アクション` 文字的 alias chip 出現
5. **Help curl 複製**：`browser_navigate` → `http://localhost:8000/help`
   - `browser_wait_for` `.terminal-copy-btn` 可見（help.html:71）timeout=3s
   - `browser_click` → `.terminal-copy-btn`（`@click="copyCurlCommand()"`）
   - **驗**：`browser_evaluate` 取剪貼簿內容：
     ```js
     navigator.clipboard.readText().then(t => t)
     ```
     預期包含 `/api/capabilities`（capabilities endpoint URL）
   - **驗**：`.terminal-copy-btn` 旁的反饋文字或 icon 變化（可選；依 UI 實作而定）

### 完成後 state

- `#filenameFormat` 在 Settings 仍顯示 `[{num}] {title}`（除非 step 2 還原動作覆蓋）
- 翻譯開關 `#translateEnabled` 已還原到初始狀態
- Tag alias `アクション` group 存在於 DB：`GET /api/tag-aliases` 回傳含 `primary_name: "アクション"` 的 group
- Help curl 按鈕可點擊且剪貼簿含 `/api/capabilities`

### PyWebView 例外

- Settings 頁「最愛資料夾」picker（`selectFavoriteFolder()`）為 PyWebView-only；本 US 不點 picker，只改命名格式與翻譯開關等文字設定，無影響。
- step 3 整理（scrape）流程若依賴 PyWebView picker 選檔 → 用 Setup 預先放好的 tracked fixture 繞過；不點 `#btnSelectFolder`。

### Regression 偵測點

- 自訂命名格式 API 沒 validate → 儲存時 `alert-error` toast（如含非法字元）；觀察：step 1 save 後 toast class 為 `alert-error`
- 翻譯開關重載後沒保留 → `saveConfig` 沒把 `translateEnabled` 寫入後端；觀察：step 2 重整後 `#translateEnabled` checked 狀態回到 opposite
- Tag alias CRUD 後 Showcase filter 沒吃到新 alias → `tag_alias` store reload 沒觸發；用 US4 驗收 `女僕` → `アクション` 的 alias 展開（若兩者 alias 有連結）
- Help curl 按鈕複製到的 URL 不含 `/api/capabilities` → `copyCurlCommand()` 函數 hardcode 的 URL 錯誤；或剪貼簿 API 在 headless 瀏覽器被 block（需 CDP attach 模式）

---

## US8: 區網存取閘門 + agent token（v0.13.7 / v0.13.8 新增）

**故事**：主人在設定頁開啟「需要密碼才能連線」→ 自己這台永遠不用輸密碼 → Help 頁出現 agent token 區塊 → 從區網位址連進來的裝置看到的是一張看不出是 OpenAver 的偽裝頁 → 改密碼後所有裝置與 token 一起失效。

> **為什麼分兩段**：閘門判的是「連進來的位址」。`localhost`／`127.0.0.1` 在閘門第 2 步就短路——**用 loopback 驗閘門會得到一個必然成功、但什麼都沒證明的結果**。故「被擋」那半必須打本機的 LAN 位址（同一台機器連自己的 LAN IP，peer 位址就是那個 LAN IP，閘門會正常生效，不需要第二台機器）。

### Setup

- Dev server 已啟動。**注意**：`uvicorn web.app:app` 起的 dev server **無法**開伺服器模式——LAN listener 需要 `standalone.py` 呼叫過 `lan_listener.wire(app, local_port=...)`，dev 模式下 toggle 會回「無法啟動 LAN 伺服器」。要跑本 US 的 [MCP] 段需先用一支 wire 過的啟動腳本（見 `web/lan_listener.py:120-135` 的 lifecycle 註解）。
- **先備份再跑**：本 US 會寫 `web/config.json`（`server_mode`）與 DB 的 `access_auth`／`access_tickets`。跑完還原。
- 起始狀態：密碼保護關閉（`GET /api/access/settings` 回 `enabled:false`）。

### Steps

1. **[MCP] 認證關閉時 Help 頁沒有多出任何東西**：`browser_navigate` → `/help`
   - **驗**：頁面文字**不含** `Agent Token`、DOM **不含** `oav_`（AC8：PIN 未開時 Help 頁與現況逐位元組相同）
2. **[MCP] 設定頁的控制組是單列不是直向堆疊**：`browser_navigate` → `/settings`，找到伺服器模式膠囊旁的「需要密碼才能連線」
   - **驗**：控制組高度約 28px 量級（**不是** 80px 的三行堆疊）、PIN 欄是四格密碼樣式（**不是**瀏覽器預設的 332px 寬 input）
   - **驗**：兩個密碼輸入框都有 `autocapitalize="off"`（手機鍵盤自動大寫會造成靜默鎖死）
3. **[MCP] 設密碼**：勾選 → 輸入 4 位英數（例 `aB3x`）→ 儲存
   - **驗**：出現「密碼設定已儲存」；欄位顯示為遮罩 ＋ 眼睛鈕可切換真值（**真值只給本機**）
   - **驗**：打英文（不是數字）時儲存鈕是**可按的**（0.13.7 修過：寫死 4 位數字會讓英文密碼得到一顆永遠按不下去的灰按鈕）
4. **[MCP] 自己這台永不被要求密碼**：`browser_navigate` → `/`、`/settings`、`/showcase`
   - **驗**：三頁都正常顯示，沒有偽裝頁（AC2；loopback 免密碼）
5. **[MCP] Help 頁出現 agent 區塊**：`browser_navigate` → `/help`
   - **驗**：出現 `Agent Token` 標題、眼睛鈕、複製鈕、一行含 `Authorization: Bearer` 的 curl 範例、以及 SSE 已知限制那句
   - **驗**：**沒有**「重新產生」按鈕（114b-T8 拔除；作廢路徑只有「到設定頁重存密碼」一條）
   - **驗**：眼睛遮罩狀態下按複製，剪貼簿拿到的是**真值不是遮罩字串**（需 CDP attach 模式，headless 剪貼簿常被 block）
6. **[人工／curl] 區網位址三態**（打 `http://<本機 LAN IP>:<lan_port>`，**不可用 localhost**）：
   - 不帶憑證 → **200 但是偽裝頁 HTML**（無標題、無文字、只有一個不顯眼的輸入框）
   - 帶 `Authorization: Bearer <亂字串>` → **401 JSON**（`{"success":false,"reason":"unauthorized"}`），不是偽裝頁
   - 帶 `Authorization: Bearer <真 token>` → `/api/capabilities` 200，且回應裡 `network.auth` 寫明 bearer、**所有 curl 範例都帶 header**、回應本身**不含** `oav_` 真值
7. **[人工／curl] agent 真的做得到事**：照 capabilities 裡任一支 `side_effect` 端點的 example 原文執行一次寫入 → 成功且讀得回來；同一支端點**不帶 token** 再打一次 → 偽裝頁，且**確認資料沒有被寫進去**
8. **[MCP] 改密碼即全撤**：回設定頁，把密碼**存成同一組**（不改值）
   - **驗**：`/help` 的 token **換成新的一組**（R5：認證設定一被動，票與 token 全部失效，「填一模一樣的 PIN」也不例外）
9. **還原**：取消勾選密碼保護、關閉伺服器模式、還原備份的 `config.json` 與 DB

### 完成後 state

- `GET /api/access/settings` 回 `enabled:false`
- `access_tickets` 表為空
- `/help` 回到「無 agent 區塊」的形狀

### PyWebView 例外

桌面 App 走 loopback，行為與 step 4 相同（永不要求密碼）。step 6–7 的區網三態在 PyWebView 內驗不到，一律用 curl。

### Regression 偵測點

- 從區網連進來看到的是**登入畫面**而不是偽裝頁 → 偽裝設計失效（登入畫面等於向掃到 IP 的人宣告「這裡有東西且值得保護」）
- 自己這台被要求密碼 → 閘門的 loopback 判斷接錯邊（`::ffff:127.0.0.1` 形狀是最常見的漏認），症狀是**桌面版自鎖且畫面是一張假頁**，使用者完全不知道發生什麼事
- 拿錯 token 的 agent 收到 HTML 200 而不是 401 → agent 分不出「我 token 錯了」與「這台根本不是 OpenAver」
- capabilities 的範例不帶 header 或 `auth` 欄寫 `none` → agent 照抄全部 401，然後回頭說「你這台壞了」；**這條所有單元測試都會是綠的**
- 改密碼後舊裝置還連得進來 → 有人繞過 `core/access_auth.py` 直接寫票表（有一條 lint 規則在守，但它擋不掉表名不以字面值出現的寫法）
- 手機輸入正確密碼卻永遠進不去 → 輸入框少了 `autocapitalize="off"`，或存／比對前沒做 NFKC 折疊（全形數字與 ASCII 是不同碼位）

---

## US9: 封面牆條件篩選 ＋ 從片庫加入女優 ＋ 直式海報卡型（v0.13.9 ~ v0.13.14 新增）

**故事**：主人在燈箱點一個標籤 → 搜尋列長出一枚可移除的 pill、牆上只剩符合的片 → 再點一個片商，兩個條件取交集 → 切到女優牆，用 `+` 從片庫把常看的女優一次收好幾個 → 切回影片牆，把卡型換成直式海報，整面牆變直立卡只露封面正面 → 關掉 App 隔天再開，選的還在。

> **為什麼合成一個 US**：這五支 branch（115 metadata pill / 116 女優數值 pill / 117 從片庫加入 / 118 FC2 來源 / 119 直式海報）全部落在**同一面牆與同一條工具列**上，彼此的 regression 會互相掩蓋（例如 pill 讓工具列變兩行，就看不出卡型切換有沒有壞）。分開跑會把同一組幾何量五遍。

### Setup

- Dev server 已啟動，片庫非空（`GET /api/showcase/videos` 的 `total > 0`）。
- **會寫 DB 的步驟已逐條標注**（step 5 的愛心、step 7 的焦點 ✓）。不想寫就跳過那兩步，其餘全部唯讀。
- **視窗寬度以 `window.innerWidth` 為準**，不要用 `document.documentElement.clientWidth`——CSS `@media` 與 JS 的 `_isNarrow` 用的都是**含捲軸**的視窗寬，用 clientWidth 會製造一個 15px 的錯位（見 `gotchas.md` `FE-CSS-13`）。
- **headless 瀏覽器先確認 `document.visibilityState === "visible"`**，背景分頁下 Playwright 的真 click 會全部靜默無效且不報錯（`FE-MOTION-04`）。

### Steps

1. **[MCP] 點 metadata 長出 pill**：`/showcase` → 點任一張卡開燈箱 → 點標籤列的任一個標籤
   - **驗**：燈箱關閉、搜尋列出現一枚 pill（形如 `標籤：<值>`）、牆上只剩符合的片
   - **驗**：搜尋框**沒有**被填入那個標籤的文字（115 的核心：pill 取代「把字塞進搜尋框」）
   - **驗**：狀態列讀「符合 **1** 個條件的 **N** 部」
2. **[MCP] 兩枚 pill 取交集 ＋ 與打字並存**：再開一張卡 → 點片商
   - **驗**：兩枚 pill 並存、N 變小（交集不是聯集）
   - **驗**：在搜尋框打字 → 模糊比對與 pill 同時生效
   - **驗**：pill 是**精準**比對（點進來的是畫面上那一個，不會多帶別的）
3. **[MCP] 移除 pill 的三條路**：按 pill 的 ✕ ／ 搜尋框空字串時按 Backspace ／ 清除鈕
   - **驗**：三條都能移除，且**輸入法組字中（`isComposing`）按 Backspace 不刪 pill**
   - **驗**：pill 全清後回到未篩選的片數
   - **驗**：工具列**維持單列**（不因 pill 變兩行；長系列名的 pill 是第一個撐得動 grid track 的內容）
4. **[MCP] 女優數值 pill**：切女優牆 → 點任一位開燈箱 → 點年齡／身高／罩杯任一格
   - **驗**：女優牆搜尋列長出條件 pill、三顆 op 鈕（`≤` / `=` / `≥`）**即點即套**（不需要再按確認）
   - **驗**：常駐自訂區間列可填上下限；**打壞的數字（如 `1e`）不會被靜默當成沒填而套用舊值**
   - **驗**：同維度再點一次是**取代**不是疊加（真實上限 3 枚）
5. **[MCP][寫 DB] 從片庫加入女優**：女優牆搜尋列的 `+`
   - **驗**：`+` 只在「搜尋列是空的、或搜了但一個都沒找到」時出現
   - **驗**：置中彈窗列出**庫內**女優依片數由多到少；別名合併成一列、片數是合併後總數
   - **驗**：搜尋比對的是全部資料（打一個還沒被捲出來的人也找得到）、**別名也搜得到**
   - **驗**：連按 5 位 → 每列各自「排隊中 → 轉圈 → 實心愛心」，**同時 in-flight 最多 2**、同一位不管按幾下只送一次
   - **驗**：清單滑到接近底部**自動**接下一批（沒有「展開更多」按鈕）
   - **還原**：把這次加的取消收藏
6. **[MCP] 卡型選單四條 ＋ 直式海報**（`innerWidth = 1920`）：工具列模式選單
   - **驗**：選單是**四條**（完整封面／直式海報／詳細／文字），工具列圖示數量**沒有變多**
   - **驗**：選「直式海報」→ 整面牆變直立卡、一列 **7** 張、只露封面右半、常駐 footer 只剩番號
   - **驗**：**選了直式海報之後，選單仍然是四條**（若收成三條就代表切不回完整封面，使用者沒有任何復原路徑）
   - **驗**：active 標示落在「直式海報」那一條
   - **驗**：觸發鈕的 `title` 讀得到卡型（`模式: 直式海報`）
   - **驗**：切換是**原地變形**不是淡出淡入（切換期間卡片 `opacity` 全程 ≥ 0.95、grid 容器高度不塌陷）
   - **驗**：按 `A` 四段循環 完整封面 → 直式海報 → 文字 → 詳細；在**女優牆**按 `A` 一律無效
7. **[MCP][寫 DB] 直式下的人臉逃生口**：直式海報狀態下開燈箱
   - **驗**：焦點編輯鈕**出現**（完整封面時不出現、≤899px 出現）
   - **驗**：按下去 → 遮罩出現 → **真滑鼠拖得動**（往有 headroom 的那一邊；預設右裁時右側 headroom 是 0，往右拖量到的 0 位移不是 bug）→ 按 ✓ → 回牆上那張卡的裁切位置**真的變了**
   - **還原**：把焦點拖回原值，或用 `POST /api/showcase/video/save-focal` 寫回原座標
8. **[MCP] 記憶與強制直式**：
   - **驗**：`innerWidth` 拉到 800 → 畫面仍是直立卡（≤899 強制），拉回 1400 → **仍是直式海報**
   - **驗**：起始選「完整封面」走同一趟 → 拉回後**仍是完整封面**
   - **驗**：跳到 `/search` 再回 `/showcase` → 選的卡型還在；重整也還在
   - **驗**：清空 `localStorage` 重整 → 回到**完整封面**（新使用者的畫面與本版之前逐像素相同）

### 完成後 state

- pill 全清、卡型回到「完整封面」、step 5 的收藏與 step 7 的焦點已還原
- `GET /api/showcase/videos` 的 `total` 與跑之前相同

### Regression 偵測點

- 點 metadata **取代了搜尋框內容**而不是長 pill → 115 的整支功能退回舊行為
- pill 用模糊比對 → 點「山田」帶出「山田花子」，畫面看起來像是有結果、實際是錯的
- 一個叫 `constructor` 的標籤讓整面牆變空白 → alias 查表沒擋原型污染
- 工具列在 360px 被撐成兩行而 `scrollWidth <= innerWidth` **照樣通過** → grid track 用了裸 `1fr`（是裁掉不是捲動，量 scrollWidth 驗不出來，見 `FE-CSS-12`）
- 女優 pill 讓搜尋列變兩行 → pill 的 `padding` 繼承了不該繼承的值
- 從片庫加入時同一位被送兩次、或 in-flight 超過 2 → queue 的兩道不變式破了（enqueue 早退 ＋ 出隊重檢缺一）
- **選了直式海報後選單收成三條** → `_isNarrow` 與 `_posterModeActive()` 兩個語意被合併，使用者切不回完整封面
- 切換卡型時整面淡出再淡入 → Flip 的 capture 跑在狀態寫入之後，動畫靜默退化（**最終畫面看起來是對的**，只有中間幀看得出來）
- 切換卡型時 grid 高度塌陷一下再彈回 → Flip 開了 `absolute`
- 桌面切到直式海報但燈箱沒有焦點編輯鈕 → 方形／無碼封面被右裁時使用者**沒有任何修正入口**
- 首次載入（無 localStorage）的桌面畫面與上一版不同 → 預設值不是 `cover`，或新增的 CSS 沒有全部收在卡型 class 底下

---

## US10: FC2 兩條來源（[人工]，Windows 桌面版限定）

**故事**：主人搜一顆 FC2 番號 → 官方站查得到 → 換一顆官方已下架的 → 官方回不到，改在重刮彈窗把來源切到 `FC2-javten` → 跳出一個真的瀏覽器視窗完成一次人機驗證 → 資料回填。

> **為什麼整段是 [人工]**：`FC2-javten` 需要一個**真的 PyWebView 視窗**讓人點過 Cloudflare 挑戰，dev server 與 headless 瀏覽器都做不到（畫面會直接灰化並說明「僅限桌面應用程式」）。這不是缺覆蓋，是這條路徑的本質。

### Steps

1. **[人工]** 搜一顆**官方站還在**的 FC2 番號（完整格式 `FC2-PPV-xxxxxxx`）
   - **驗**：拿得到日文原題、封面、**發售日**、標籤、賣家；封面與劇照在瀏覽器實載**零破圖**
2. **[人工]** 搜一顆**官方已下架**的
   - **驗**：畫面顯示「找不到資料」（與其他七個來源逐字相同的靜默 miss——這是刻意的，不做「被擋 ≠ 查無此片」的分流）
3. **[人工]** 對同一顆開重刮彈窗 → 來源切 `FC2-javten`
   - **驗**：第一次跳出真的 javten 瀏覽器視窗，點過驗證後**自動接續查詢並回填**，之後不再每次問
   - **驗**：拿得到日文原題／封面／劇照／標籤／賣家／評分；**沒有發售日**（站方頁面結構就沒有，不是抓失敗）
   - **驗**：標籤是**日文版**（`ハメ撮り`／`素人`），不是機翻繁中
4. **[人工]** 在 dev server／區網伺服器／NAS 上看同一顆
   - **驗**：`FC2-javten` 膠囊**灰化並說明「僅限桌面應用程式」**，不會假裝在找然後回一句查無此片

### Regression 偵測點

- 查一顆**確實存在**的片卻說「找不到」→ WebView2 的 `get_current_url()` 不反映轉址（它回的是請求的 URL 不是落地 URL），改讀 `location.href`
- CF 視窗跳出來停在上一頁不動超過 90 秒 → 同視窗第二次導航到同站台時 `NavigationCompleted` 不觸發，導航前要先過一次 `about:blank`
- 兩條需要驗證的來源（JavLibrary／FC2-javten）其中一條掛掉把另一條也拖下水 → 驗證視窗沒有各自獨立
- 升級後的既有使用者**永遠看不到** `FC2-javten` → config migration 寫死了 `[0]` 而不是走訪全部 manual-only 來源（**沒有任何測試會紅**）

---

## US11: 屬性標籤 ＋ 精選 ＋ 分集片 ＋ 發售日條件 ＋ 女優卡資訊區（v0.14.0 ~ v0.14.4 新增）

**故事**：主人打開瀏覽頁 → 開燈箱點標題前那顆星把喜歡的片標起來 → 漏斗選單勾「只看精選」→ 到設定頁把封面左上角的屬性標籤打開，回來整面牆的中字／4K 片都認得出來 → 點發售日長出 `=2024-09` 條件、再打開面板改成整年 → 切到女優牆按眼睛鈕，每張卡下面攤開身高罩杯三圍，點一下就變成條件 → 找到一部分成兩段的片，牆上是一張卡不是兩張。

> **為什麼合成一個 US**：這五件事（0.14.1 屬性標籤 / 0.14.2 分集片合併 / 0.14.3 精選 / 0.14.4 發售日 pill ＋ 女優卡資訊區）全部落在**同一面牆、同一條工具列、同一個燈箱**，且**同時消費同一顆眼睛鈕的展開狀態**（兩面牆共用，見 v0.14.4 已知限制）。分開跑會把同一組幾何量五遍，且彼此的 regression 會互相掩蓋——例如屬性標籤把封面左上角佔滿，就看不出分集片的段別標記有沒有被蓋掉（**兩者都畫在封面上**）。

### Setup

- Dev server 已啟動，片庫非空；**本 US 需要庫裡至少有**：1 部已精選的片、1 組分集片（同資料夾 `-cd1`/`-cd2`）、若干帶 `中文字幕`/`4K` 標籤的片、若干有發售日的片。
  - 本機基準庫實測（2026-08-25）：2114 部、精選 6、分集片 1 組（`SNOS-102`）、中文字幕 504、4K 433、VR 4、有發售日 2035。
- **屬性標籤預設關閉**（opt-in）——step 3 之前牆上不該有任何屬性標籤，那是預設狀態不是壞掉。
- **會寫 DB 的步驟已逐條標注**（step 2 的星、step 3 的設定開關）。不想寫就跳過，其餘全部唯讀。
- 眼睛鈕的展開狀態**會被記住且兩面牆共用**（`localStorage`）——跑完 step 6 要記得收回去，否則下一個 US 的影片牆會是展開的。
- 視窗寬度以 `window.innerWidth` 為準（含捲軸），headless 先確認 `document.visibilityState === "visible"`（同 US9 Setup）。

### Steps

1. **[MCP] 精選在四種呈現裡都是唯讀星標**：`/showcase` → 找一部已精選的片
   - **驗**：番號前面帶一顆 ★，**完整封面／直式海報／詳細／文字四種卡型都有**（切一輪 `A` 鍵）
   - **驗**：**點牆上那顆星＝開燈箱**，不是取消精選（12px 的星做成可點會誤觸，v0.14.3 刻意如此）
   - **驗**：沒精選的片**什麼都不多長**（不是灰星，是沒有）
2. **[MCP][寫 DB] 燈箱那顆星是唯一的開關**：開任一張未精選的片的燈箱 → 點標題最前面那顆星
   - **驗**：金色由下往上灌滿、灌到頂迸火花；**沒有確認框、沒有 toast**
   - **驗**：關掉燈箱 → 牆上那張卡的番號前面立刻有星（不必重整）
   - **驗**：**手機寬度（≤480px）下星星點得到**——左箭頭不會蓋住它（0.14.4 改箭頭對齊封面就是為了這個；箭頭仍在視窗中央＝退版）
   - **還原**：再點一次取消精選
3. **[MCP][寫設定] 封面屬性標籤是 opt-in**：`/settings` → 列表顯示預設 → 「封面屬性標籤」
   - **驗**：**預設全關**；打開之後回 `/showcase`，中字片的封面**左上角**出現標籤
   - **驗**：**最多 3 顆**（找一部同時中字 ＋ 4K ＋ 無碼破解 ＋ VR 的片，畫面上不會擠出第 4 顆）
   - **驗**：逐項關掉其中一種 → 那一種不再顯示，**但該片的標籤本身沒有被改掉**（燈箱標籤列仍讀得到「中文字幕」）
   - **還原**：把開關轉回關閉
4. **[MCP] 分集片合成一張卡**：搜到那組 `-cd1`/`-cd2` 的片
   - **驗**：牆上是**一張卡**不是兩張；封面上有段別標記（`{n} 段`／`第 {current}／{total} 段`）
   - **驗**：`GET /api/showcase/videos` 的 `total` 把該組算成 **1**（畫面與 API 同一份判斷）
   - **驗**：開燈箱按播放 → **一段播完自動接續下一段**（瀏覽器內建播放器）
   - **驗（唯讀，不要真的按確認）**：「從收藏移除」的確認文案讀得到「這是分集片（…），確認後會一併移除全部 N 段的紀錄」——與單片版本**不同一句**
5. **[MCP] 發售日點成條件 ＋ 範圍面板**：開任一張有發售日的片 → 點發售日
   - **驗**：搜尋列長出一枚 `=YYYY-MM` 條件、牆上只剩那個月的片；**搜尋框沒有被填字**
   - **驗**：點那枚條件 → 打開面板 → 三顆鈕（`=`／`≤`／`≥`）即點即套；起訖年月可填，**月份留空＝整年**
   - **驗**：可與 ★精選、女優、標籤等其他條件**疊加取交集**；換排序不影響條件
   - **驗**：`innerWidth ≤ 480` 時發售日**仍點得出條件、但面板不開**（與年齡／身高／罩杯今天的手機行為一致，不是壞掉）
6. **[MCP] 女優牆的眼睛鈕與可點數值**：切女優牆 → 按工具列眼睛（或 `S`）
   - **驗**：每張卡下方攤開**身高／罩杯／三圍**；沒有資料的欄位不留空位，**全都查不到的那位不長空盒子**
   - **驗**：年齡／身高／罩杯**點得下去**→ 長出 `=28歲`／`=157cm`／`=B罩杯` 條件；**作品數與三圍點不下去**
   - **驗**：值是「不明」之類**看得到但點不下去**（不會產生一枚永遠篩不到人的條件）
   - **驗**：窄螢幕（≤899px）下 footer **只留名字**且名字看得見（不是被數字擠成幾個像素）
   - **驗**：滑鼠移到卡片上時 footer **不會整條空白**（影片牆同時驗一次）
   - **還原**：再按一次眼睛收回（**跨牆共用，忘了收下一個 US 會受影響**）
7. **[MCP] 燈箱換片箭頭與對焦編輯互斥**：開燈箱
   - **驗**：箭頭**對齊封面**不是視窗中央；封面上那兩顆玻璃圓盤已經拿掉（關閉鈕與魔法棒**仍是**玻璃圓盤）
   - **驗**：摸得到的範圍仍 ≥ 44px
   - **驗**：按下對焦編輯 → **箭頭藏起來**、左右滑動與 ←／→ 鍵**都不換片**；按確認／取消後恢復
8. **[MCP] 罩杯 L 以上**：女優牆排序切「罩杯」
   - **驗**：`L`／`M`／`N` 這些**排在 K 後面**（不是被當成未知丟到最後，也不是字串序排到 A 前面）

### 完成後 state

- 條件全清、卡型回「完整封面」、眼睛鈕收回、屬性標籤開關轉回關閉、step 2 的精選已還原
- `GET /api/showcase/videos` 的 `total` 與跑之前相同；`select count(*) from videos where user_rating!=0` 與跑之前相同

### Regression 偵測點

- 牆上的星**點下去取消了精選** → 12px 的星被做成可點，手指偏一點就靜默取消一片的精選
- 精選只在「完整封面」有星、切到文字模式就不見 → 星標只接了一種卡型（四種都要）
- 手機上點星卻跳到上一片 → 換片箭頭又對齊視窗中央了（0.14.4 修的正是這條）
- 屬性標籤**預設就開著** → opt-in 被翻成 opt-out，所有人的封面左上角突然多東西
- 關掉某一種屬性標籤，**該片的標籤本身也被刪了** → 顯示開關寫進了資料（不可逆）
- 屬性標籤把段別標記蓋掉（或反過來） → 兩者都畫在封面左上角，只有同時存在的片看得出來
- 分集片在牆上變成兩張卡、或 `total` 把它算成 2 → 合併只做在畫面沒做在計數（**兩邊都要**）
- 分集片的移除確認文案跟單片**逐字相同** → 使用者以為只移除一段，實際整組
- 發售日條件在手機上**把面板也開出來** → 窄螢幕沒有走與年齡／身高／罩杯同一條路
- 女優卡展開後**同一個數字上下各出現一次**（桌機年齡除外，那是已知取捨） → 窄螢幕 footer 沒有讓位
- 罩杯排序把 `L` 丟到最後 → 排序表沒有擴到 K 以上

---

## US12: 瀏覽器模式的資料夾選擇彈窗 ＋ 搜尋列跨頁一致性（v0.14.8 / v0.14.9 新增）

**故事**：主人在區網手機／NAS 上用**瀏覽器**開 OpenAver → 按「加資料夾」不再被一句「需要桌面應用程式」擋死，而是開一個資料夾選擇視窗 → 選完回來 → 切到瀏覽頁，搜尋列跟搜尋頁那條**看起來沒有動過** → 在女優分頁按 ✕，影片牆的條件**沒有被一起清掉**。

> **為什麼合成一個 US**：兩支 branch（128 瀏覽器 UX、129 搜尋列 parity）改的是**同兩條搜尋列與同一組彈窗容器**；129 的幾何對齊是靠改 `--spotlight-*-slot` 那組變數達成的，而那組變數同時被彈窗觸發鈕消費——分開跑會漏掉「對齊修好了但按鈕被壓扁」這一類（見 `gotchas.md` `FE-CSS-15`）。

### Setup

- **必須以瀏覽器（非 PyWebView）開啟**——彈窗只在沒有桌面 bridge 時才是這條路；桌面版按同一顆鈕開的是原生對話框，本 US 不涵蓋。
- 至少設定過一個掃描來源（決定彈窗第一次打開的起點）。
- 三個入口各自記自己的上次位置（`localStorage`）——跑完把三個 key 清掉，否則下次跑起點不是預期值。
- **不要按到「選取此資料夾」以外會寫 config 的路徑**（設定頁輸出夾會寫 `config.json`）。

### Steps

1. **[MCP] 四個入口都開得起來**：`/search` 加檔案／加資料夾、`/settings` 輸出資料夾、`/scanner` 加來源
   - **驗**：四個入口**都不再吐「此功能需要在桌面應用程式中使用」**
   - **驗**：彈窗有麵包屑、單擊資料夾進去、「上一層」、以及一顆**常駐**的「選取此資料夾」
   - **驗**：第一次打開的起點是**第一個掃描來源的上一層**（完全沒設過來源才從根目錄）
2. **[MCP] 三個入口各記各的**：在掃描頁選一層深目錄 → 關掉 → 開設定頁的輸出夾
   - **驗**：設定頁**不會**跳到掃描頁剛選的那層
3. **[MCP] 取消要真的取消**（`FE-TIMING-08` 的那條）：選定資料夾後在回應回來前按 Escape／✕／取消，**以及**「取消後立刻重開一個新的選擇器」
   - **驗**：舊的那次選取**不會**回頭寫進畫面、不會蓋掉新選的資料夾、**不會把新開的視窗關掉**
   - **驗**：兩種情況**都要驗**（只驗後者的話 `closeBrowseDir` 那把 gen 是偵測不到的死碼）
4. **[MCP] 拖資料夾進掃描頁不再靜默**：把一個資料夾拖進 `/scanner`
   - **驗**：覆蓋層關掉後**有話說**（「瀏覽器無法直接讀取拖放檔案的路徑，已為您開啟資料夾選擇器」）並**直接把彈窗開起來**
   - **驗**：搜尋頁與掃描頁的拖放提示層**長一樣**（進場動畫、字級、內距、圖示陰影四項；129 以搜尋頁那版為準統一）
5. **[MCP] 兩頁搜尋列逐值對齊**：在 `1024 / 1100 / 1280 / 1440 / 1920` 五個寬度下，量 `/search` 與 `/showcase` 搜尋列外框與輸入框的 `getBoundingClientRect()`
   - **驗**：五個寬度**逐值相同**（1100px 曾經一邊 680px、一邊 430px）
   - **驗**：`/search` 右側**永遠保留約 15px 的捲軸空白帶**（那是必須付的：瀏覽頁的同一段空間真的被捲軸佔著）
   - **驗**：說明文字在**空狀態**裡（不在搜尋列下方），**手機上看得到**
   - **量測前提**：讀 `window.innerWidth`（含捲軸）不是 `clientWidth`（`FE-CSS-13`）
6. **[MCP] 手機兩枚條件不撐成三行**：`innerWidth = 390`，掛兩枚短條件標籤
   - **驗**：兩枚在**同一行**、搜尋列**單行高度**（曾經各佔一行 ＋ 第三行空白輸入框）
   - **已知限制**：兩枚**長**標籤（例如兩個女優名字）仍會各佔一行，那不是 regression
7. **[MCP] ✕ 只管當前分頁**：影片牆掛條件 → 切女優牆
   - **驗**：女優牆一片空白時**不冒出 ✕**（顯示條件只看當前分頁）
   - **驗**：在女優牆按 ✕ **不會**清掉影片牆的搜尋字與條件
   - **驗**：女優分頁打的字**重整後還在**
   - **驗**：搜尋字精準命中某位最愛女優時上方那張大卡，**切頁再切回來還在**（不必重打名字）

### 完成後 state

- 三個入口的「上次位置」localStorage key 已清、`config.json` 的輸出夾未被改動
- 兩牆的搜尋字與條件已清空

### Regression 偵測點

- 瀏覽器按「加資料夾」又回到一句「需要桌面應用程式」→ 四個死路其中一個沒接上
- 取消之後舊回應照樣寫進畫面／關掉新視窗 → 旁支那條 fetch 的 generation guard 掉了（`FE-TIMING-08`）
- 拖資料夾進掃描頁**毫無反應** → 靜默失敗回來了（路徑拿不到是瀏覽器限制，靜默不是）
- 1100px 下兩頁搜尋列寬度不同 → parity 退版，切頁時看得到它變形
- `/search` 右側那條 15px 空白帶消失 → `scrollbar-gutter` 被拿掉，兩頁又對不齊（**只在有捲軸的頁面才看得出來**）
- 搜尋列上的按鈕被壓扁 → slot 變數調小但 `.btn-icon` 沒有 `flex-shrink: 0`（`FE-CSS-15`，**內容不會溢出，是按鈕自己縮**）
- 在女優牆按 ✕ 把影片牆的條件清掉 → 清除範圍又變回全域

---

## US13: Windows 啟動、安裝與代理環境（[人工]，Windows 桌面版限定）

**故事**：主人的電腦開著 Clash／v2rayN／公司代理 → 雙擊 `OpenAver_Debug.bat` → App **正常開起來**（不是吐一段 Python 錯誤就結束）。啟動真的失敗時，畫面上那句話**查得到東西**、`debug.log` 裡**真的有原因**。

> **為什麼整段是 [人工]**：代理環境、WebView2 安裝身分、系統訊息視窗、剪貼簿與安裝視窗都在 **Windows 真機的打包產物**上，headless 與 WSL 都做不到。自動化測試涵蓋的是「環境變數那一種代理設定」；**登錄檔那一種只有真機驗得到**。

### Steps

1. **[人工]** 開著代理軟體（環境變數 ＋ 登錄檔兩種設定各試一次）雙擊 `OpenAver_Debug.bat`
   - **驗**：App 正常開起來；探活那句「好了沒？」**沒有被送去代理**（連自己不該過代理）
2. **[人工]** 人為讓伺服器起不來（佔掉端口／擋掉程序），看兩種失敗文案
   - **驗**：**等太久** → 告訴你**實際用的那個端口號**（不是寫死的 8000）
   - **驗**：**程序自己掛了** → **幾秒內**就講（不是乾等 30 秒），而且**不會**把你導去查端口
   - **驗**：兩句都印出 `debug.log` 的**完整路徑**（`C:\Users\你\OpenAver\logs\debug.log`）
   - **驗**：`debug.log` 裡**真的留下最後一次連線失敗的原因**（只留一次，不洗版）
3. **[人工]** 用一般身分（非系統管理員）安裝的 WebView2 的機器上開 App
   - **驗**：認得出來，不會誤判成「沒裝」
   - **驗**：提示視窗是**系統訊息視窗**；安裝視窗**不會閃退**；網址**自動進剪貼簿**
4. **[人工]** 查 `debug.log`
   - **驗**：「視窗沒顯示」不再被記成「用戶取消」

### Regression 偵測點

- 開著代理就崩 → `NO_PROXY`／`trust_env` 那條又被繞過（**只有真的開著代理的機器看得出來**）
- 失敗文案又回到寫死的「端口 8000」→ 使用者照著查永遠查不到東西
- `debug.log` 是空的 → 探活失敗的原因沒有落地，那句「請查看 debug.log」又變成空頭支票
- 少數情況（OpenAver 選好的端口在啟動前一刻被搶走）`debug.log` 只有探活失敗紀錄、查不到真因——**這是已接受的 residual，不是 regression**（uvicorn 綁定失敗走 `sys.exit(1)` ＋ 它自己的 logger 不 propagate，見 plan-130a 殘留段）

---

## Appendix C: Capabilities Smoke（Optional, curl-only）

> 純 curl/API 測試，非 browser user story，**不算 milestone 必跑**。
> CD-59-23：不重複 integration 已覆蓋的單端點 contract；僅作 Agentic AI quick-smoke 清單。
> A3/A5 有寫檔副作用，需先備 disposable fixture 或確認資料可覆蓋。

### 前置條件

```bash
# Dev server 已啟動
source venv/bin/activate && uvicorn web.app:app --host 127.0.0.1 --port 8000

# （A3/A5 用）準備 disposable fixture 番號（確認 DB 內存在或可覆蓋）
FIXTURE_NUM="SONE-205"  # 換成實際有資料的番號（A1-A5 共用，務必在同一 shell session 執行）
```

### A1：探索搜尋

```bash
curl -s "http://localhost:8000/api/search?q=SONE-205&discovery=true" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('title','MISSING'), d.get('actresses','MISSING'), d.get('cover_url','MISSING')[:30])"
```

**驗收**：`title`、`actresses`、`cover_url` 三欄均非 `MISSING` 且非空字串。

### A2：批量搜尋

```bash
curl -s -X POST http://localhost:8000/api/batch-search \
  -H "Content-Type: application/json" \
  -d '{"numbers":["SONE-205","SSIS-001","IPX-001"]}' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(f'count={len(d.get(\"results\",[]))}')"
```

**驗收**：回傳 `count=3`（3 筆結果，部分可能為 `not_found` 但結構存在）。

### A3：補完 metadata（寫 DB — 需 disposable fixture）

```bash
curl -s -X POST http://localhost:8000/api/enrich-single \
  -H "Content-Type: application/json" \
  -d "{\"file_path\":\"/path/to/$FIXTURE_NUM.mp4\",\"number\":\"$FIXTURE_NUM\",\"mode\":\"fill_missing\"}" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('updated_fields:', d.get('updated_fields','MISSING'))"
```

**驗收**：回傳含 `updated_fields` 欄位（可為空 list，表示無需補完）；不回 5xx 錯誤。
**副作用**：寫入 DB（`$FIXTURE_NUM` 的 metadata 可能被更新）。

### A4：收藏庫查詢

```bash
curl -s -X POST http://localhost:8000/api/collection/sql \
  -H "Content-Type: application/json" \
  -d '{"sql":"SELECT COUNT(*) as cnt FROM videos"}' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('rows:', d.get('rows','MISSING'))"
```

**驗收**：回傳 `rows` 非空（如 `[[10]]`）；不回 5xx 或 `{"error":...}` 結構。

### A5：生成 HTML 清單（寫檔 — 需 disposable fixture 或暫目錄）

```bash
# 用 FIXTURE_NUM 作為 numbers 輸入（endpoint 吃 numbers 不吃 ids）
curl -s -X POST http://localhost:8000/api/gallery/generate-from-ids \
  -H "Content-Type: application/json" \
  -d "{\"numbers\":[\"$FIXTURE_NUM\"]}" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('html_path:', d.get('html_path','MISSING'), 'video_count:', d.get('video_count','MISSING'), 'missing:', d.get('missing',[]))"
```

**驗收**：`html_path` 非空字串、`video_count >= 1`（FIXTURE_NUM 在 DB 中時）；回傳是 JSON 不是 HTML 本文。
**副作用**：endpoint 自行決定輸出路徑（通常落在 `output/` 目錄）；測後可手動清掉產出檔案。

---

## ~~舊版 Scenarios（2026-05-14 前）~~ [歷史保留]

> 以下 24 個 scenarios（v1 格式 S/C/T/H/N/X/A）已在 2026-05-14 plan-59c §2 審計後，
> 全數合併進 US1–US7 或標 deprecated。逐項處置原因見下表，原 step 內容已在
> git history（commit before 59c-1）保留，本檔不再重複文字。

### Search

- ~~**S1. 番號精準搜尋**~~ → 併入 US2 step 1–3
- ~~**S2. Detail 模式欄位顯示**~~ → 併入 US2 Sub-A（detail card render 驗收）
- ~~**S3. 方向鍵導航**~~ → 併入 US2 Sub-B（多筆 query 才執行，`N >= 2` 條件）
- ~~**S4. 女優名搜尋**~~ → 併入 US5 step 1–2
- ~~**S5. 拖入檔案/加入檔案**~~ → **deprecated**（PyWebView-only：drag-drop 觸發 file dialog 無法 browser 跑；US2 setup 以「預設已有番號」繞過）

### Showcase

- ~~**C1. 頁面載入 + 卡片渲染**~~ → 併入 US3 step 1
- ~~**C2. 搜尋篩選**~~ → 併入 US4 step 1–2
- ~~**C3. 翻頁**~~ → 併入 US3 step 2（atomic inline）
- ~~**C4. Lightbox**~~ → 併入 US3 step 3–5（含魔杖按鈕補強）

### Settings

- ~~**T1. 語系切換**~~ → 併入 US6 step 1–3
- ~~**T2. Dark / Light Mode**~~ → 保留為獨立 step in US6 step 5
- ~~**T3. 搜尋來源切換**~~ → 併入 US7 step 2
- ~~**T4. 翻譯開關**~~ → 併入 US7 step 3

### Help

- ~~**H1. 頁面載入**~~ → 併入 US1 step 9–10（tutorial 完成後從 sidebar 連 `/help`，驗 `h2.card-title` 非 raw i18n key + `.terminal-copy-btn` 可見）
- ~~**H2. AI curl 複製**~~ → 保留為 US7 末尾 step（capabilities curl 複製）

### Scanner

- ~~**N1. 頁面載入**~~ → 併入 US1 step 1（tutorial 觸發前導覽至 Scanner 頁）
- ~~**N2. 掃描 + 產生網頁**~~ → **deprecated**（PyWebView-only：Scanner 加資料夾依賴原生 picker，瀏覽器無法穩定驅動；scan trigger button 可由實作者選做 atomic check）

### 跨頁面

- ~~**X1. Sidebar 導航**~~ → **deprecated**（US1 step 5–7 已逐一 sidebar 導航，獨立 scenario 冗餘）
- ~~**X2. 頁面間狀態不互相污染**~~ → 保留為 Regression 偵測點 in US2 / US3

### Agentic API

- ~~**A1. 探索搜尋**~~ → 移至 Appendix C（API-only / curl）
- ~~**A2. 批量搜尋**~~ → 移至 Appendix C
- ~~**A3. 補完 metadata**~~ → 移至 Appendix C（寫 DB，需 disposable fixture）
- ~~**A4. 收藏庫查詢**~~ → 移至 Appendix C
- ~~**A5. 生成 HTML 清單**~~ → 移至 Appendix C（寫檔，需 disposable fixture 或暫目錄）

> **CD-59-23**：scenarios 不重複 integration 已測的單端點 contract；A1–A5 維持 curl/API 格式不轉成 browser step，移出 US7 主體放 Appendix C，不算 milestone 必跑。
