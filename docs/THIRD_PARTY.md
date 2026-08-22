# 第三方來源與授權（Third-Party Notices）

這份清單記錄 OpenAver **版控中、不是我們寫的**檔案：它是誰的、哪一版、什麼授權、怎麼重新取得。

受眾是 clone / fork 這個 repo 的人（含未來的維護者與 AI 助理）。使用者不需要讀這份文件。

> **逐檔 sha256 不寫在這裡**，一律在機器可讀清單 [`../web/static/vendor/manifest.json`](../web/static/vendor/manifest.json)。
> 理由：同一個 hash 寫兩個地方一定會漂，而人讀文件落後不會被任何機器抓到。
> 那份 manifest 由 `npm run lint`（`scripts/vendor_guard_lint.mjs`）對帳——換檔、加檔、少檔、改一個位元組，都會讓 lint 變紅。

**重新取得任何一個檔案**——每個檔案的上游 URL 都在 manifest 裡，所以不必逐檔抄指令：

```bash
# 重新下載全部 16 個第三方檔案（含 core/focal/facefinder）到原位
python3 -c "
import json, urllib.request
m = json.load(open('web/static/vendor/manifest.json'))
for e in m['vendor'] + [m['facefinder']]:
    urllib.request.urlretrieve(e['upstream_url'], e['path'])
    print('fetched', e['path'])
"
# ⚠ Alpine 六檔下載回來是「上游原檔」，會少掉我們加的那行檔頭 banner。
#   補回 banner 之前 npm run lint 會紅（local_sha256 對不上），這是預期行為。
```

單獨取回某一個檔案時，`curl -sSL -o <path> <upstream_url>` 即可，兩個欄位都在 manifest 的對應那筆。各套件的代表性範例見下方各節。

三個區塊：

1. [前端 vendor（15 檔）](#1-前端-vendor15-檔)
2. [`core/focal/` 的第三方物件（4 個）](#2-corefocal-的第三方物件4-個)
3. [生成物：`tailwind.css`](#3-生成物tailwindcss)

---

## 1. 前端 vendor（15 檔）

全部位於 `web/static/vendor/`，由 `web/templates/base.html` 以 `<script>` / `<link>` 直接載入（無打包步驟）。
15 檔**全部與上游逐位元組相同**，唯一的例外是我們替 Alpine 六檔加的一行檔頭註解（見下方說明）。

### Alpine.js 3.15.12 — MIT

| 檔案 | 上游套件 |
|---|---|
| `alpine/alpine.min.js` | `alpinejs` |
| `alpine/persist.min.js` | `@alpinejs/persist` |
| `alpine/collapse.min.js` | `@alpinejs/collapse` |
| `alpine/focus.min.js` | `@alpinejs/focus` |
| `alpine/intersect.min.js` | `@alpinejs/intersect` |
| `alpine/anchor.min.js` | `@alpinejs/anchor` |

- 上游：<https://alpinejs.dev>　·　授權：MIT
- Vendored：2026-06-21
- **⚠ 本地檔名不等於上游路徑**：五個插件在上游一律叫 `dist/cdn.min.js`，是套件名（`@alpinejs/persist` 等）在區分它們。照本地檔名去組 URL 會 404。逐檔的正確 URL 見 `manifest.json` 的 `upstream_url`。
- **這六檔是本 repo 唯一被我們動過的 vendor 檔**：檔頭各加了一行 `/*! ... */` 版本／授權註解（Alpine 官方 CDN build 本來就不帶 banner，不是我們弄掉的）。原始程式碼一個位元組都沒改——`manifest.json` 同時記錄 `upstream_sha256`（上游原檔）與 `local_sha256`（我們這份），剝掉第一行 banner 後必須等於前者，這件事由守衛每次 lint 驗一次。

**重新取得**（以 core 為例，其餘五筆的 URL 見 manifest）：

```bash
curl -sSL -o web/static/vendor/alpine/alpine.min.js \
  https://cdn.jsdelivr.net/npm/alpinejs@3.15.12/dist/cdn.min.js
# 下載後需依既有格式重新加上檔頭 banner，並更新 manifest.json 的 local_sha256
```

### GSAP 3.14.2 — GreenSock 標準授權

`gsap/` 底下 6 檔：`gsap.min.js`、`Flip.min.js`、`Physics2DPlugin.min.js`、`CustomEase.min.js`、`CustomBounce.min.js`、`DrawSVGPlugin.min.js`

- 上游：<https://gsap.com>　·　授權：`Standard 'no charge' license` — <https://gsap.com/standard-license>
- Vendored：2026-06-21　·　檔內自帶上游 banner，我們未改動
- 授權字串取自上游 `package.json` 的 `license` 欄位。**這不是 MIT**；散布前請讀該授權條款（自 GSAP 3.13 起，過去屬 Club GreenSock 的外掛已納入同一份免費授權，本 repo 用到的 `Physics2DPlugin` / `DrawSVGPlugin` / `CustomBounce` 屬之）。

```bash
curl -sSL -o web/static/vendor/gsap/gsap.min.js \
  https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js
```

### Bootstrap Icons 1.11.1 — MIT

`bootstrap-icons/bootstrap-icons.css`、`bootstrap-icons/fonts/bootstrap-icons.woff`、`bootstrap-icons/fonts/bootstrap-icons.woff2`

- 上游：<https://icons.getbootstrap.com/>　·　授權：MIT（Copyright 2019-2023 The Bootstrap Authors）
- Vendored：2026-06-21　·　CSS 自帶上游 banner，我們未改動

```bash
curl -sSL -o web/static/vendor/bootstrap-icons/bootstrap-icons.css \
  https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css
curl -sSL -o web/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2 \
  https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/fonts/bootstrap-icons.woff2
```

---

## 2. `core/focal/` 的第三方物件（4 個）

無碼片焦點裁切用到的東西。**這裡有兩種不同的身分，不可混為一談**：

- **改寫過的移植（modified port）**——三支 `.py`。它們是把上游 Go 程式碼移植成 Python 的產物，不是原檔的副本。
- **未修改的上游原檔複本（unmodified upstream asset）**——`facefinder`。它與上游逐位元組相同。

`core/focal/__init__.py` 與 `core/focal/worker.py` 是 OpenAver 自己的程式碼，不在此列。

### 2.1 改寫過的移植（三支 `.py`）

| 檔案 | 上游專案 | 授權 | 版權人 | 移植自 |
|---|---|---|---|---|
| `core/focal/pigo.py` | [esimov/pigo](https://github.com/esimov/pigo) | MIT | Copyright (c) 2018 Endre Simo | `b4f89e29eef3acd95c115c67e4a62fd5b99e1b0d`（`v1.4.6-25-gb4f89e2`，2025-05-03）|
| `core/focal/detector.py` | [metatube-community/metatube-sdk-go](https://github.com/metatube-community/metatube-sdk-go) | Apache-2.0 | 上游 `LICENSE` 未填入版權人（Apache-2.0 樣板的 `[yyyy] [name]` 佔位維持原狀）；歸屬 metatube-community 專案 | `579c4d86742c48ca3f2001e35c52170e82009ee8`（`v1.4.0-5-g579c4d8`，2026-04-18）|
| `core/focal/gate.py` | 同上 | Apache-2.0 | 同上 | 同上 |

- **這三支是改寫過的移植，不是原檔**：Go → Python 的語言轉換本身即構成修改，且 `gate.py` 另有刻意的行為分歧（其檔頭 docstring 已記錄）。各檔的 docstring 寫明了移植範圍與不簡化的取捨。
- 移植 commit 由 owner 本機的兩個上游 clone 考據而得（`git log -1` / `git describe --tags`）。**那兩個 clone 不在版控**（納入會讓 repo 暴增並引進不屬於我們的授權），所以這個對應關係只有本清單一份紀錄，沒有第二處可交叉驗證。
- **已知的授權缺口（明確接受的取捨）**：Apache-2.0 §4(b) 要求在被修改的檔案裡標示「已修改」，MIT 要求副本保留版權與授權聲明。本專案選擇讓出處活在這份清單，**不在那三支 `.py` 的檔頭加授權標頭**——理由是為了可讀性去動成熟且有測試覆蓋的偵測碼不划算。這是取捨，不是「已完全符合」。上游兩個專案都沒有 `NOTICE` 檔，故 Apache-2.0 §4(d) 不觸發。

### 2.2 未修改的上游原檔複本（`facefinder`）

| 檔案 | 上游 | 授權 | 版權人 |
|---|---|---|---|
| `core/focal/facefinder`（239KB 二進位）| [esimov/pigo](https://github.com/esimov/pigo) 的 cascade 檔 | MIT | Copyright (c) 2018 Endre Simo |

- 版本釘死的來源：<https://raw.githubusercontent.com/esimov/pigo/v1.4.6/cascade/facefinder>
- **與上游逐位元組相同**，我們沒有改過它。它是 pigo 的臉部偵測 cascade 資料檔，**不是移植、也不是改寫**。
- 該 cascade 檔跨 pigo `v1.4.5` / `v1.4.6` / `master` 內容一致，因此它的 sha256 證明的是「這就是 pigo 的 cascade 原檔」，**不足以指向某個確切 commit**——三支 `.py` 的移植時間點由上面 2.1 的 commit 承載，與這一筆無關。
- sha256 見 `manifest.json` 的 `facefinder` 欄位（它也在守衛的對帳範圍內）。

```bash
curl -sSL -o core/focal/facefinder \
  https://raw.githubusercontent.com/esimov/pigo/v1.4.6/cascade/facefinder
```

---

## 3. 生成物：`tailwind.css`

`web/static/css/tailwind.css`（版控中，隨 release ZIP 出貨）**不是手寫的，也不是別人的原檔**——它是建置產物。

| 項目 | 值 |
|---|---|
| 建置指令 | `scripts/build-css.sh prod`（輸入 `web/static/css/input.css`）|
| 建置工具 | `tools/tailwindcss-extra` — 單檔 binary，**gitignored**、不在版控 |
| 工具來源 | [dobicinaitis/tailwind-cli-extra](https://github.com/dobicinaitis/tailwind-cli-extra) v2.7.5（下載指令見 `scripts/build-css.sh` 的錯誤訊息）|
| 該 binary 內建 | **tailwindcss 4.1.18**（MIT）＋ **daisyui 5.5.14**（MIT）|

**⚠ `package.json` 的 devDependencies 沒有參與 CSS 建置。** 那裡宣告的 `daisyui: ^5.5.17`、`@tailwindcss/cli: ^4.1.18`、`tailwindcss: ^4.1.18` 只是躺著——實際產生 `tailwind.css` 的是上面那顆 binary 裡的 **daisyui 5.5.14**。任何人（含 AI 助理）照 `package.json` 推論「我們的 daisyui 是 5.5.17」都會推錯。

**這個版本漂移目前只被記錄、沒有被消除**：`tailwind.css` 的檔內 banner 只寫 `/*! tailwindcss v4.1.18 | MIT License */`，不含 daisyui 版本；而 `tailwind.css` 是我們的生成物、不是別人的原檔，**不在守衛的對帳範圍**。下次真的重建 CSS 時實際版本會靜靜地換掉，不會有任何機器提醒。

---

## 這份清單守得住什麼、守不住什麼

**守得住**（`npm run lint` 會紅）：`web/static/vendor/` 底下換了檔、加了新檔、刪了檔、或改了任何一個位元組而沒更新 `manifest.json`；以及 `core/focal/facefinder` 被動過。

**守不住**（靠人）：

- `manifest.json` 裡的 `upstream_sha256` 是人填的。**填錯不會被機器抓到**——守衛驗的是「磁碟內容 == 記錄值」，不會連網去問上游。驗上游是 vendored 當下的一次性動作。
- 第 2、3 區只有 `facefinder` 進對帳，2.1 那三支 `.py` 不進（它們是持續維護的移植，不是拿來跟磁碟逐位元組對帳的標的）。之後若有人在別處再加一份第三方程式碼，守衛也看不到。
- 這份清單是**快照**，不是訂閱。它告訴你「vendored 當下是 3.15.12」，不會告訴你上游已經出到哪一版。
