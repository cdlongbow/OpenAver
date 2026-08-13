# Scraper fixtures — FC2 官方站

來源：`feature/118-fc2-dual-source/poc-artifacts/`（POC 當日 byte-faithful 複製；不得 reformat / strip 尾空白）。

| 檔名 | 番號 | 抓取日期 | 當時官方是否仍上架 | 守的是哪條 CD |
|------|------|----------|-------------------|---------------|
| `fc2official_4938576.html` | FC2-PPV-4938576 | 2026-08-13 | 仍上架 | CD-118b-3（og:title 截斷、JSON-LD `name` 完整） |
| `fc2official_4938582.html` | FC2-PPV-4938582 | 2026-08-13 | 仍上架 | CD-118b-5／6／9（標籤 scope、兩個 softDevice、劇照兩種寬度） |
| `fc2official_1723984.html` | FC2-PPV-1723984 | 2026-08-13 | 仍上架 | CD-118b-7 正向側（`reviewCount=72`、`ratingValue=5`）＋ CD-118b-8（JSON-LD image 為 `http://`） |
| `fc2official_1723985_notfound.html` | FC2-PPV-1723985 | 2026-08-13 | 不存在的番號（HTTP 200 軟 404） | CD-118b-4／5（HTTP 200 軟 404、20 個假標籤） |

## 軟 404 事實（CD-118b-4 判準依據）

`fc2official_1723985_notfound.html`（來源 `s_1723985.html`）是 **HTTP 200** 的軟 404，**31,403 bytes**，與另一份不存在番號的頁面（`s_3000000.html`）**位元組數完全相同**。後人不必重跑 POC 即可用此事實。
