# Scraper fixtures — FC2 官方站

| 前綴 | 站台 | scraper |
|------|------|---------|
| `fc2official_` | `adult.contents.fc2.com`（官方） | `core/scrapers/fc2_official.py`（來源 id `fc2`） |

`core/scrapers/fc2_javten.py`（來源 id `fc-javten`）**刻意不收 fixture**，理由見本檔最後一節。

來源：`feature/118-fc2-dual-source/poc-artifacts/`（POC 當日 byte-faithful 複製；不得 reformat / strip 尾空白）。

> **行尾會被正規化，這是預期的**：`.gitattributes:9` 的 `*.html text eol=lf` 對本目錄照樣生效
> （`tests/fixtures/**/*.html -whitespace` 只關掉 `git diff --check` 的尾空白告警，**沒有**關掉 eol 轉換）。
> 站方送的是 CRLF，進版控後是 LF。**這不是「被 reformat」**：
> BE-ENV-04 在乎的尾空白**逐行保留**，且實測解析結果逐欄位相同。
> 118b 的 `fc2official_*` 當初就是這樣進來的（`a_4938576.html` 3 行 CRLF → 進版控少 3 bytes），已出貨驗證過。
> **加新 fixture 時直接 `cp`，不要為了「保住 CRLF」去動 `.gitattributes`**——那會讓本目錄長出第二套慣例。

## 官方站（`fc2official_`）

| 檔名 | 番號 | 抓取日期 | 當時官方是否仍上架 | 守的是哪條 CD |
|------|------|----------|-------------------|---------------|
| `fc2official_4938576.html` | FC2-PPV-4938576 | 2026-08-13 | 仍上架 | CD-118b-3（og:title 截斷、JSON-LD `name` 完整） |
| `fc2official_4938582.html` | FC2-PPV-4938582 | 2026-08-13 | 仍上架 | CD-118b-5／6／9（標籤 scope、兩個 softDevice、劇照兩種寬度） |
| `fc2official_1723984.html` | FC2-PPV-1723984 | 2026-08-13 | 仍上架 | CD-118b-7 正向側（`reviewCount=72`、`ratingValue=5`）＋ CD-118b-8（JSON-LD image 為 `http://`） |
| `fc2official_1723985_notfound.html` | FC2-PPV-1723985 | 2026-08-13 | 不存在的番號（HTTP 200 軟 404） | CD-118b-4／5（HTTP 200 軟 404、20 個假標籤） |

### 軟 404 事實（CD-118b-4 判準依據）

`fc2official_1723985_notfound.html`（來源 `s_1723985.html`）是 **HTTP 200** 的軟 404，**31,403 bytes**，與另一份不存在番號的頁面（`s_3000000.html`）**位元組數完全相同**。後人不必重跑 POC 即可用此事實。

## javten 鏡像站（`fc-javten`）——**刻意不收 fixture**

owner 2026-08-14 拍板（T8），並把已收的 7 份真檔從 git 歷史一併移除。理由：

- **真檔擋不住這條來源唯一會壞的方式。** javten 是第三方鏡像站，它改版時本地真檔還是舊
  結構——測試照樣全綠，線上卻全滅。
- **也不可能補 canary。** 它跟 javlibrary 一樣有 Cloudflare 擋在前面（`curl_cffi` 三種
  impersonate 實測全 403），連不上就沒有定期探測。這條來源的迴歸偵測只能靠真實使用者回報。
- 換句話說 3.3 MB 的真檔換不到對應的保障。

**代價（已知且接受）**：AC-2.2（三顆官方已下架片逐欄位）與 AC-2.3（日文原詞 vs `/tw/` 機翻）
的解析驗證失去。`tests/unit/test_fc2_javten_scraper.py` 只保留不依賴 HTML 內容的那半邊
（傳給 `fetch()` 的 URL 已剝語言段、落地 host 白名單）。

> **不要用合成 HTML 補回那兩支。** 合成 HTML 會抹平空佔位與 null，那是假綠——`v0.11.8`
> 就是這樣讓 Codex 抓到 3 條 bug。要嘛真檔要嘛沒有。

以下是當初從真檔量到、**與檔案本身無關**的站台事實，留著供後人不必重跑 POC：

### 機翻咬的是標籤，不是標題（2026-08-14 實測）

同一片日文版標籤是 `['ハメ撮り','制服','素人',…]`，`/tw/` 版是 `['奇聞趣事','均勻','業餘',…]`，
而**標題兩邊都是日文原題**。所以「有沒有拿到日文版」的可證偽點只能放在標籤。

### 日文版 URL 契約（CD-118a-19 的依據，2026-08-14 實測）

- 日文版 ＝ **無語言段 ＋ 必須帶標題 slug**：`/video/{內部id}/id{番號}/{slug}`
- **`/ja/` 是 404**；**少了 slug 是 500**；`/video/{亂數id}/id{番號}` 是 404（內部 id 躲不掉）
- 命中 → 從 `/search?kw=N` **302 到** `/video/\d+/id<番號>/…`；查無 → **不重導**，停在 `/search?kw=N`（title `Search For : N`）
- **判準用最終 URL 的形狀，不偵測任何文案字串**

### 解析結果與 owner 既有 DB 逐欄相同（2026-08-14 實測三顆已下架片）

標題／`maker`／`tags` 逐字相符，`rating` 皆 5.0、`samples` 皆 5 張——
**這證明庫裡的 FC2 資料當初就是從這條日文路徑抓的**，解析器對得上真實資料。

### 站方沒有發售日（2026-08-14 實測）

整份 HTML 中 `販売日`／`発売日` 出現 **0 次**。`fc-javten` 結構性拿不到發售日（官方站有）。
不要試圖從別處推導——那會寫一個編出來的日期進 NFO。
