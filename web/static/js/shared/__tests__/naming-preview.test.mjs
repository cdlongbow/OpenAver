import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  stripFolderExcludedTokens, normalizeFolderLayers, buildNamingPreview,
  formatNfoTitle, buildNfoTitlePreview,
} from '../naming-preview.js';

// ── 以下 13 個 test 從 pages/settings/__tests__/chip-editor.test.mjs 搬來（CD-146a-13），
//    僅改 import 來源，斷言與命名逐字保留 ──
// 〔g〕〔g2〕〔g3〕〔g4〕〔g5〕〔g6〕〔g7〕〔g8〕〔h〕〔h2〕〔h3〕〔h4〕〔h5〕

// ── stripFolderExcludedTokens：資料夾情境主動移除 {suffix}（D-A6，Codex PR P1）──
const EXCL = new Set(['{suffix}']);


// ── normalizeFolderLayers：先 slice(0,3) 再剝 {suffix}（順序關鍵，Codex PR 二審 P1）──
test('〔h〕Codex 二審 P1：前導 suffix-only 不得提升第 4 層', () => {
  // 後端有效集合＝前 3 = [{suffix}, A, B] → 剝 {suffix} → [A, B]；C（第 4 層死資料）不出現
  assert.deepEqual(normalizeFolderLayers(['{suffix}', 'A', 'B', 'C'], EXCL), ['A', 'B']);
});


// ── buildNamingPreview 新測項（CD-146a-13，非搬家） ──


test('〔i2〕{suffix} 不進資料夾層（folder_ok:false 排除，套進完整 buildNamingPreview 輸出）', () => {
  const out = buildNamingPreview({
    filenameFormat: '{num} {title}{suffix}',
    createFolder: true,
    folderLayerList: ['{actor}', '{suffix}'],
    formatVariables: [{ name: '{suffix}', folder_ok: false }],
    tokens: { num: 'SSNI-618', title: '標題', suffix: '-cd1', actor: '女優' },
  });
  assert.equal(out, '女優/SSNI-618 標題-cd1.mp4');
});


// ── formatNfoTitle / buildNfoTitlePreview（TASK-154b-T4）────────────────────


test('formatNfoTitle 片名含 {actor} 字面不可被二次代換', () => {
  assert.equal(
    formatNfoTitle('[{num}]{title}', { num: 'ABC-123', title: '片名 {actor}', actor: '三上悠亞' }),
    '[ABC-123]片名 {actor}',
  );
});


