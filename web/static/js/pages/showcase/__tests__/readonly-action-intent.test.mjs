// TASK-104-T4：readonly_action intent 結構回歸鎖。
//
// state-lightbox.js（`@/showcase/...` importmap alias）與 state-rescrape.js
// （`@/shared/...` / `@/components/...` importmap alias）皆只有瀏覽器認得，plain Node
// 的 ESM resolver 無法直接 import（同一限制見 sync-actress-fields.test.mjs 開頭、
// scanner/__tests__/init-order.test.mjs）。故比照 init-order.test.mjs 的手法：
// readFileSync 讀原始碼 → brace-match 抽出目標函式 body → 剝註解後對 body 做字串斷言。
//
// 鎖的契約（CD-104-5「零分支」+ plan-104 T4 DoD）：
//   - enrichVideo（放大鏡）→ enrich-single body 必含 readonly_action:'ingest'，
//     且函式 body 不得再出現 is_readonly_source（無條件送，不分支）。
//   - rescrapeConfirm 的 lightbox commit 分支（enrich-single POST）→ body 必含
//     readonly_action:'rescrape'，同樣不分支 is_readonly_source。
//   - fetchSamples → body 不含 readonly_action（後端 fetch-samples 不讀此欄位，T3 確認）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const lightboxSrc = readFileSync(new URL('../state-lightbox.js', import.meta.url), 'utf8');
const rescrapeSrc = readFileSync(new URL('../../../shared/state-rescrape.js', import.meta.url), 'utf8');

function stripComments(code) {
  return code
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '');
}

// 抽「<sig> 起的下一個 `{` 開始 brace-match 到對應 `}`」的函式 body（比照 init-order.test.mjs）。
function extractFnBody(code, sig, label) {
  const sigIdx = code.indexOf(sig);
  assert.ok(sigIdx >= 0, `原始碼應含 \`${sig}\`（${label}）`);
  const open = code.indexOf('{', sigIdx);
  assert.ok(open >= 0, `${label} 應有 {`);
  let depth = 0;
  for (let i = open; i < code.length; i++) {
    const ch = code[i];
    if (ch === '{') depth++;
    else if (ch === '}') {
      depth--;
      if (depth === 0) return stripComments(code.slice(open + 1, i));
    }
  }
  throw new Error(`${label} 大括號未閉合（brace-match 失敗）`);
}

test('enrichVideo（放大鏡）body 無條件送 readonly_action:\'ingest\'，不分支 is_readonly_source', () => {
  const body = extractFnBody(lightboxSrc, 'async enrichVideo(video) {', 'enrichVideo');
  assert.match(
    body,
    /readonly_action:\s*'ingest'/,
    'enrich-single POST body 應含 readonly_action: \'ingest\'',
  );
  assert.ok(
    !body.includes('is_readonly_source'),
    'enrichVideo body 不得再分支 is_readonly_source（CD-104-5 零分支：兩種片同 handler，唯一分支在後端）',
  );
});

test('fetchSamples body 不含 readonly_action（後端 fetch-samples 不讀此欄位）', () => {
  const body = extractFnBody(lightboxSrc, 'async fetchSamples(video) {', 'fetchSamples');
  assert.ok(
    !body.includes('readonly_action'),
    'fetchSamples 不應送 readonly_action —— 後端 fetch-samples 端點不讀此欄位（T3 確認），僅靠按鈕解禁即可',
  );
});

test('rescrapeConfirm（lightbox apply）enrich-single body 無條件送 readonly_action:\'rescrape\'，不分支 is_readonly_source', () => {
  const body = extractFnBody(rescrapeSrc, 'async rescrapeConfirm() {', 'rescrapeConfirm');
  // lightbox commit 分支才打 enrich-single（search / switch-source 分支各自 return，見檔案註解）；
  // 只鎖該 fetch 呼叫涵蓋的區段：從 `/api/enrich-single` 起到緊接著的 `});` 收尾。
  const fetchIdx = body.indexOf("fetch('/api/enrich-single'");
  assert.ok(fetchIdx >= 0, 'rescrapeConfirm 應呼叫 /api/enrich-single（lightbox commit 分支）');
  const bodyCloseIdx = body.indexOf('});', fetchIdx);
  assert.ok(bodyCloseIdx >= 0, '應找得到 fetch(...) 呼叫收尾');
  const fetchCallSrc = body.slice(fetchIdx, bodyCloseIdx);

  assert.match(
    fetchCallSrc,
    /readonly_action:\s*'rescrape'/,
    'enrich-single POST body 應含 readonly_action: \'rescrape\'',
  );
  assert.ok(
    !fetchCallSrc.includes('is_readonly_source'),
    'rescrapeConfirm 的 enrich-single 呼叫不得分支 is_readonly_source（CD-104-5 零分支，Search 共用同一 handler、無條件送）',
  );
});
