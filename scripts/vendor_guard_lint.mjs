#!/usr/bin/env node
/**
 * vendor_guard_lint.mjs — 第三方 vendor 檔案對帳守衛（plan-125 功能 D）
 *
 * 承 plan-125 CD-1／CD-4／CD-5／CD-6／CD-7／CD-11／CD-12：
 * 讀機器可讀清單 `web/static/vendor/manifest.json`，與磁碟實際內容三態對帳——
 *   ① 磁碟多出未登記檔案 → RED（有人加了第三方檔沒留痕）
 *   ② 清單有一筆但磁碟找不到 → RED（刪了忘記清）
 *   ③ 檔案還在但 hash 對不上 → RED（換版本／手改了沒更新清單）
 *
 * 為什麼讀 JSON 不 parse Markdown（CD-1，gotchas FE-GUARD-08）：
 * 人讀清單 `docs/THIRD_PARTY.md` 是散文格式，手刻 Markdown 表格 tokenizer 正是
 * 103-T8「852 行 tokenizer → 10 個假陰性」的同型錯誤，且失效方向是**假陰性**
 * （「沒被抓到」與「沒有 bug」永遠分不出來）。這裡一律 `JSON.parse`，零手刻解析。
 *
 * 兩條獨立掃描路徑（**不是一次遞迴走完**）：
 *   A. 遞迴掃 `web/static/vendor/**`  → 對帳 manifest.vendor[]（15 筆）
 *      該目錄下的物理檔案有 16 個，多出來的那個是 manifest.json 自己（CD-12 具名排除）。
 *   B. 單獨檢查 `core/focal/facefinder` → 對帳 manifest.facefinder（第 16 筆）
 *      **不得寫成遞迴掃 `core/focal/`**——同目錄的 pigo.py／detector.py／gate.py 是
 *      持續維護的移植碼，不是「與磁碟逐位元組對帳」的標的（CD-2）。
 *
 * 離線（CD-6）：不連網。「與上游相同」由 manifest 記錄的 upstream_sha256 承載，
 * 驗上游是 vendored 當下的一次性動作，不是每次 lint 都做。
 *
 * fail-closed：manifest 讀不到／不是合法 JSON／vendor[] 為空 → 一律 RED，不靜默通過。
 *
 * 用法：
 *   node scripts/vendor_guard_lint.mjs                # 掃真 repo
 *   node scripts/vendor_guard_lint.mjs <scratch-root>  # 掃 scratch 副本（供 mutation 自驗）
 *
 * 非 pytest（遵 CLAUDE.md「lint 守衛寫 lint config、不寫 pytest」）。串 `npm run lint`。
 */

import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const argv2 = process.argv[2];
const ROOT = argv2 && !argv2.startsWith('--') ? resolve(argv2) : join(__dirname, '..');

const VENDOR_REL = 'web/static/vendor';
const FACEFINDER_REL = 'core/focal/facefinder';
/** CD-12：守衛自己的清單就住在被掃描的目錄裡，必須排除，否則第一次跑就恆紅。
 *  刻意用**單一具名路徑**精確比對，不用 `*.json` 萬用字元——那會讓未來任何
 *  `.json` 格式的 vendor 資產靜默逃過登記。 */
const MANIFEST_REL = `${VENDOR_REL}/manifest.json`;

/** banner 結束標記。CD-5：格式固定為 `/*! ... *\/\n` 緊接原始第一個位元組。 */
const BANNER_START = Buffer.from('/*!', 'latin1');
const BANNER_END = Buffer.from('*/\n', 'latin1');

/** vendor[] 每筆的必填欄位。 */
const VENDOR_REQUIRED = [
  'path', 'package', 'version', 'upstream_url',
  'upstream_sha256', 'local_sha256', 'license', 'vendored_date', 'banner_added',
];
/** facefinder 的必填欄位——**獨立一份**，不複用 vendor 的白名單（CD-3）。
 *  涵蓋與 vendor 同名的 9 個 provenance 欄位（不因為它是另一種身分就少要求出處），
 *  但 `copyright`／`note` 是 facefinder 專有的**選填**補充，不列必填——
 *  這正是不能整支複用 vendor 白名單的原因：複用會漏掉這兩欄的語意差異，
 *  而 facefinder 的 `package` 欄是 "esimov/pigo (cascade)" 這種非套件生態系格式，
 *  不能拿去做 npm 套件名解析。 */
const FACEFINDER_REQUIRED = [
  'path', 'package', 'version', 'upstream_url',
  'upstream_sha256', 'local_sha256', 'license', 'vendored_date', 'banner_added',
];

let hadError = false;
const err = (msg) => {
  console.error(`✗ vendor_guard_lint: ${msg}`);
  hadError = true;
};

const sha256 = (buf) => createHash('sha256').update(buf).digest('hex');

/**
 * 剝掉我們加在檔頭的 banner，回傳其後的原始位元組。
 * **全程 Buffer，不轉字串**（CD-5／B-3）——`readFileSync(p,'utf8')` 對非法 UTF-8
 * 序列會替換成 U+FFFD，hash 因而失真；`bootstrap-icons/fonts/*.woff{,2}` 是真二進位，
 * 本來就在對帳範圍內，這不是假想情境。
 */
function stripBanner(buf) {
  if (buf.length < BANNER_START.length ||
      !buf.subarray(0, BANNER_START.length).equals(BANNER_START)) {
    throw new Error('banner 格式不符：檔案未以 /*! 起始');
  }
  const end = buf.indexOf(BANNER_END);
  if (end === -1) {
    throw new Error('banner 格式不符：找不到 */\\n 結束標記');
  }
  return buf.subarray(end + BANNER_END.length);
}

/** 遞迴列出目錄下所有檔案，回傳相對 ROOT 的 POSIX 路徑。
 *  CD-11：**只跳過 dotfile**（檔名以 `.` 開頭，如 `.DS_Store`），
 *  其餘任何檔案一律要登記——包含 `Thumbs.db` 這種不以 `.` 開頭的系統暫存檔
 *  （它出現在 vendor 目錄本來就該被問一句，紅了刪掉即可）。
 *  刻意**不用副檔名白名單**：那會漏掉未來真的該登記的新格式。
 *
 *  **dot-目錄要照樣遞迴進去**（review P2）：CD-11 講的是「跳過 dotfile」，
 *  把同一個 `startsWith('.')` 判斷套到目錄上，會讓
 *  `web/static/vendor/.hidden/evil.js` 這種東西整支逃過對帳而 lint 全綠——
 *  那正是本守衛要防的事。dot-**檔案**跳過、dot-**目錄**照走，兩者分開決策。 */
function walkFiles(absDir, relPrefix, out) {
  for (const entry of readdirSync(absDir, { withFileTypes: true })) {
    const abs = join(absDir, entry.name);
    const rel = `${relPrefix}/${entry.name}`;
    if (entry.isDirectory()) {
      walkFiles(abs, rel, out); // dot-目錄不例外
    } else if (entry.isFile()) {
      if (entry.name.startsWith('.')) continue; // 只有 dot-**檔案**跳過
      out.push(rel);
    }
  }
  return out;
}

/** 逐筆檢查必填欄位（值不得為 undefined/null/空字串；boolean false 是合法值）。 */
function checkRequired(obj, required, label) {
  let ok = true;
  for (const key of required) {
    const v = obj[key];
    if (v === undefined || v === null || v === '') {
      err(`${label} 缺必填欄位 \`${key}\``);
      ok = false;
    }
  }
  return ok;
}

/** 對單一檔案做 hash 對帳。回傳 true 表示這一筆通過。 */
function reconcileEntry(entry, label) {
  const abs = join(ROOT, ...entry.path.split('/'));
  if (!existsSync(abs) || !statSync(abs).isFile()) {
    // 三態②：清單有一筆，檔案不在了
    err(`${label} 清單有記錄但磁碟找不到檔案：${entry.path}`);
    return false;
  }
  const buf = readFileSync(abs); // Buffer，不帶 'utf8'
  const localHash = sha256(buf);

  // 三態③：磁碟內容 vs 記錄的 local_sha256（唯一的對帳依據，CD-6）
  if (localHash !== entry.local_sha256) {
    err(`${label} 內容與清單不符：${entry.path}\n` +
        `    磁碟 local_sha256 = ${localHash}\n` +
        `    清單 local_sha256 = ${entry.local_sha256}\n` +
        `    → 換了版本／手改了內容？請更新 ${MANIFEST_REL}（並確認上游來源）`);
    return false;
  }

  // 額外的離線自檢（CD-6）：banner_added 為 true 的，剝掉 banner 後必須等於 upstream_sha256。
  // 這是 spec §2.3「加了 banner 之後仍要能驗證我們沒有改動上游程式碼」的機器驗證版。
  // CD-4：走不走這條路徑，唯一依據是 manifest 的顯式旗標，**不做內容嗅探**
  //       （GSAP／bootstrap-icons 原生自帶 /*!，嗅探會把上游的 banner 誤剝）。
  // banner_added:false ⇒ 我們沒有動過這個檔，所以「我們這份」與「上游那份」必須是同一個 hash。
  // 兩者不同代表 manifest 自相矛盾：不是旗標填錯，就是有人改了上游程式碼、把 local_sha256
  // 更新成新值讓磁碟比對過關，而 upstream_sha256 仍留著原始值。後者正是本 branch 要防的事
  // ——不加這條的話，那種改動會安靜地拿到綠燈（review P3，已實測可重現）。
  if (entry.banner_added === false && entry.local_sha256 !== entry.upstream_sha256) {
    err(`${label} ${entry.path}：清單自相矛盾——banner_added 是 false（我們沒改過它），\n` +
        `    但 local_sha256 與 upstream_sha256 不同。\n` +
        `    → 這個檔案其實被改過？還是 banner_added 該是 true？`);
    return false;
  }

  if (entry.banner_added === true) {
    let stripped;
    try {
      stripped = stripBanner(buf);
    } catch (e) {
      err(`${label} ${entry.path}：${e.message}\n` +
          `    → 這一筆標了 banner_added:true，檔頭應該是 /*! ... */ 加一個換行後緊接原碼`);
      return false;
    }
    const upstreamHash = sha256(stripped);
    if (upstreamHash !== entry.upstream_sha256) {
      err(`${label} ${entry.path}：剝除 banner 後與上游不符\n` +
          `    剝除後 sha256 = ${upstreamHash}\n` +
          `    清單 upstream_sha256 = ${entry.upstream_sha256}\n` +
          `    → banner 後面多了空行？或原始程式碼被動過？`);
      return false;
    }
  }
  return true;
}

function main() {
  const manifestAbs = join(ROOT, ...MANIFEST_REL.split('/'));

  // ---- fail-closed①：清單讀不到／不是合法 JSON ----
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(manifestAbs, 'utf8'));
  } catch (e) {
    err(`讀不到或無法解析 ${MANIFEST_REL}（${e.message}）——fail-closed，不靜默通過`);
    process.exit(1);
  }

  // ---- fail-closed②：vendor[] 不存在或為空 ----
  if (!Array.isArray(manifest.vendor) || manifest.vendor.length === 0) {
    err(`${MANIFEST_REL} 的 vendor[] 不存在或為空——fail-closed，不靜默通過`);
    process.exit(1);
  }
  if (!manifest.facefinder || typeof manifest.facefinder !== 'object') {
    err(`${MANIFEST_REL} 缺 facefinder 條目——fail-closed，不靜默通過`);
    process.exit(1);
  }

  // 注意：頂層還有 `_comment` 這個純說明字串。這裡**只讀 vendor 與 facefinder 兩個具名欄位**，
  // 不對頂層做無條件遍歷——否則 `_comment` 會被誤判成第三個資料群。
  const vendorEntries = manifest.vendor;
  const facefinder = manifest.facefinder;

  // ---- schema：必填欄位 ----
  const seenPaths = new Set();
  for (const entry of vendorEntries) {
    const label = `vendor[${entry.path ?? '(無 path)'}]`;
    checkRequired(entry, VENDOR_REQUIRED, label);
    if (typeof entry.banner_added !== 'boolean') {
      err(`${label} 的 banner_added 必須是 boolean（顯式旗標，不靠內容嗅探）`);
    }
    // vendor[] 的每一筆都必須落在被掃描的目錄底下。否則那筆會被 reconcileEntry 對帳、
    // 卻永遠不會出現在 walkFiles 的結果裡——「清單↔磁碟一一對應」就破了一個洞，
    // 而且 `..` 之類的相對路徑會讓守衛去讀掃描範圍外的檔案。
    if (typeof entry.path === 'string' &&
        (!entry.path.startsWith(`${VENDOR_REL}/`) || entry.path.includes('..'))) {
      err(`${label} 的 path 必須位於 ${VENDOR_REL}/ 底下且不得含 \`..\`（facefinder 例外，它有自己的欄位）`);
    }
    // 同一個 path 登記兩次會讓「未登記檔案」的比對失去意義（兩筆都宣稱擁有同一個檔案）
    if (seenPaths.has(entry.path)) {
      err(`${label} 的 path 在清單裡重複登記`);
    }
    seenPaths.add(entry.path);
  }
  checkRequired(facefinder, FACEFINDER_REQUIRED, 'facefinder');

  // ---- 路徑 A：遞迴掃 web/static/vendor/** ----
  const vendorDirAbs = join(ROOT, ...VENDOR_REL.split('/'));
  if (!existsSync(vendorDirAbs)) {
    err(`掃描根目錄不存在：${VENDOR_REL}——fail-closed`);
    process.exit(1);
  }
  const diskFiles = walkFiles(vendorDirAbs, VENDOR_REL, []);
  const registered = new Set(vendorEntries.map((e) => e.path));

  for (const rel of diskFiles) {
    if (rel === MANIFEST_REL) continue; // CD-12：具名排除守衛自己的清單檔
    if (!registered.has(rel)) {
      // 三態①：磁碟多出未登記檔案
      err(`磁碟多出未登記的第三方檔案：${rel}\n` +
          `    → 新增 vendor 檔案時要同時登記進 ${MANIFEST_REL}（含 sha256 與上游 URL）`);
    }
  }

  // ---- 逐筆對帳（vendor 15 筆） ----
  let okCount = 0;
  for (const entry of vendorEntries) {
    if (reconcileEntry(entry, 'vendor')) okCount += 1;
  }

  // ---- 路徑 B：單獨檢查 core/focal/facefinder（第 16 筆，非遞迴） ----
  if (facefinder.path !== FACEFINDER_REL) {
    err(`facefinder.path 應為 ${FACEFINDER_REL}，實際為 ${facefinder.path}`);
  }
  if (reconcileEntry(facefinder, 'facefinder')) okCount += 1;

  if (hadError) process.exit(1);
  console.log(
    `✓ vendor_guard_lint: ${okCount} 筆第三方檔案與 ${MANIFEST_REL} 對帳一致` +
    `（${vendorEntries.length} 個 vendor 檔 + facefinder；` +
    `其中 ${vendorEntries.filter((e) => e.banner_added).length} 筆另驗過剝除 banner 後與上游相同）`
  );
}

main();
