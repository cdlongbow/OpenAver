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
test('〔g〕主動移除排除 token：{num}{suffix} → {num}', () => {
  assert.equal(stripFolderExcludedTokens('{num}{suffix}', EXCL), '{num}');
});

test('〔g2〕資料夾有效 token 不動', () => {
  assert.equal(stripFolderExcludedTokens('{actor}', EXCL), '{actor}');
  assert.equal(stripFolderExcludedTokens('{num}/{maker}', EXCL), '{num}/{maker}');
});

test('〔g3〕只含 {suffix} 的層剝成空字串（呼叫端據此丟棄）', () => {
  assert.equal(stripFolderExcludedTokens('{suffix}', EXCL), '');
});

test('〔g4〕殘留分隔符刻意保留（不猜、不清，D-A6/U-A2）', () => {
  assert.equal(stripFolderExcludedTokens('{num}-{suffix}', EXCL), '{num}-');
  assert.equal(stripFolderExcludedTokens('[{num}]{suffix}', EXCL), '[{num}]');
});

test('〔g5〕未知 token 保留、不誤傷', () => {
  assert.equal(stripFolderExcludedTokens('{studio}{suffix}', EXCL), '{studio}');
});

test('〔g6〕無過度移除：更長/畸形 token 不匹配', () => {
  assert.equal(stripFolderExcludedTokens('{mysuffix}', EXCL), '{mysuffix}');
  assert.equal(stripFolderExcludedTokens('{suffixx}', EXCL), '{suffixx}');
  assert.equal(stripFolderExcludedTokens('{suffix', EXCL), '{suffix');
});

test('〔g7〕空 excluded 集合（filename 情境 / fetch 失敗）→ no-op', () => {
  assert.equal(stripFolderExcludedTokens('{num}{suffix}', new Set()), '{num}{suffix}');
});

test('〔g8〕多個排除 token 皆移除', () => {
  const excl2 = new Set(['{suffix}', '{day}']);
  assert.equal(stripFolderExcludedTokens('{num}{day}{suffix}', excl2), '{num}');
});

// ── normalizeFolderLayers：先 slice(0,3) 再剝 {suffix}（順序關鍵，Codex PR 二審 P1）──
test('〔h〕Codex 二審 P1：前導 suffix-only 不得提升第 4 層', () => {
  // 後端有效集合＝前 3 = [{suffix}, A, B] → 剝 {suffix} → [A, B]；C（第 4 層死資料）不出現
  assert.deepEqual(normalizeFolderLayers(['{suffix}', 'A', 'B', 'C'], EXCL), ['A', 'B']);
});

test('〔h2〕>3 層無 suffix：仍只保留前 3（死資料丟棄、不提升）', () => {
  assert.deepEqual(normalizeFolderLayers(['A', 'B', 'C', 'D'], EXCL), ['A', 'B', 'C']);
});

test('〔h3〕層內 suffix 剝除、順序內容不變', () => {
  assert.deepEqual(normalizeFolderLayers(['{num}{suffix}', '{actor}'], EXCL), ['{num}', '{actor}']);
});

test('〔h4〕全空 / 只含 suffix → 空清單', () => {
  assert.deepEqual(normalizeFolderLayers([], EXCL), []);
  assert.deepEqual(normalizeFolderLayers(['{suffix}'], EXCL), []);
});

test('〔h5〕空 excluded（fetch 失敗）→ 僅保留前 3、不剝除', () => {
  assert.deepEqual(normalizeFolderLayers(['{num}{suffix}', 'A', 'B', 'C'], new Set()),
    ['{num}{suffix}', 'A', 'B']);
});

// ── buildNamingPreview 新測項（CD-146a-13，非搬家） ──

test('〔i〕createFolder=false 直接回檔名，不含資料夾層（folderLayerList 非空也一樣）', () => {
  const out = buildNamingPreview({
    filenameFormat: '{num} {title}',
    createFolder: false,
    folderLayerList: ['{actor}'],
    formatVariables: [],
    tokens: { num: 'SSNI-618', title: '標題' },
  });
  assert.equal(out, 'SSNI-618 標題.mp4');
});

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

test('〔i3〕空 formatVariables（fetch 失敗降級）不拋錯、folder_ok 過濾等同空集合', () => {
  assert.doesNotThrow(() => {
    const out = buildNamingPreview({
      filenameFormat: '{num}',
      createFolder: true,
      folderLayerList: ['{actor}'],
      formatVariables: [],
      tokens: { num: 'SSNI-618', actor: '女優' },
    });
    assert.equal(out, '女優/SSNI-618.mp4');
  });
});

// ── formatNfoTitle / buildNfoTitlePreview（TASK-154b-T4）────────────────────
test('formatNfoTitle 對同一個變數出現兩次都要替換', () => {
  assert.equal(
    formatNfoTitle('{num}-{actor}-{actor}', { num: 'ABC-123', actor: '三上悠亞' }),
    'ABC-123-三上悠亞-三上悠亞',
  );
});

test('formatNfoTitle 空 actor 保留結尾分隔符（AC-b3）', () => {
  assert.equal(
    formatNfoTitle('{num}-{title}-{actor}', { num: 'ABC-123', title: '片名', actor: '' }),
    'ABC-123-片名-',
  );
});

test('formatNfoTitle 預設格式 [{num}]{title}（AC-b1）', () => {
  assert.equal(
    formatNfoTitle('[{num}]{title}', { num: 'ABC-123', title: '片名' }),
    '[ABC-123]片名',
  );
});

test('buildNfoTitlePreview 薄包裝呼叫 formatNfoTitle', () => {
  assert.equal(
    buildNfoTitlePreview('{num}-{title}', { num: 'SSNI-618', title: '絕對領域' }),
    'SSNI-618-絕對領域',
  );
});
