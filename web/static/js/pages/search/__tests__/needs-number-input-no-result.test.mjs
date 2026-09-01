// 139b-T12: 拖檔查無結果時，「手動輸入番號」鉛筆必須出現
//
// 背景（owner 實測回報）：拖入 ABC-999.mp4 → 檔名解析成功（file.number = 'ABC-999'）
// → 八個來源全部查無結果 → 畫面上三個出口全關：
//   ① #errorState 的「使用番號進階搜尋」不出現——拖檔查無結果走 pageState='result'
//      （file-list.js:65/132），那顆膠囊掛在 pageState==='error'（search.html:377）。
//   ② 結果卡右上角的來源膠囊不渲染——它包在 x-if="current().source || current()._source"
//      （search.html:487），沒有結果就沒有 source。
//   ③ 檔案列的鉛筆被藏起來——舊條件是 !file.number，而番號解析成功。
// ⇒ 番號打錯了卻沒有任何地方可以改。修法：② 這種「查過了、沒有結果」也算需要人手介入。
//
// 這支測正反兩向都鎖：不只鎖新 case 為 true，也鎖「有結果」與「還沒查」維持 false，
// 否則把判斷式改成 `return true` 也會綠。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateBase } from '../state/base.js';

globalThis.window = globalThis;

const { needsNumberInput } = searchStateBase();

test('139b-T12: 番號解析成功但查無結果 → 鉛筆出現（本卡新增）', () => {
  assert.equal(
    needsNumberInput({ number: 'ABC-999', searched: true, searchResults: [] }),
    true,
    '八個來源都查不到時，這一列是死路，必須給更正番號的入口',
  );
});

test('139b-T12: 搜尋失敗（error 分支）同樣是 searched + 空陣列 → 鉛筆出現', () => {
  // file-list.js:146-147 的 error 分支與 no-result 分支設的是同一組欄位。
  assert.equal(
    needsNumberInput({ number: 'ABC-999', searched: true, searchResults: [] }),
    true,
  );
});

test('139b-T12: 檔名解析不出番號 → 鉛筆仍出現（原有行為不得回歸）', () => {
  assert.equal(needsNumberInput({ number: null }), true);
  assert.equal(needsNumberInput({ number: '' }), true);
});

test('139b-T12: 查到結果 → 鉛筆不出現', () => {
  assert.equal(
    needsNumberInput({ number: 'ABC-123', searched: true, searchResults: [{ number: 'ABC-123' }] }),
    false,
    '有候選可挑時不該冒出更正番號按鈕',
  );
});

test('139b-T12: 還沒查 → 鉛筆不出現，且不得因 searchResults 未定義而爆炸', () => {
  assert.equal(
    needsNumberInput({ number: 'ABC-123', searched: false }),
    false,
    '尚未搜尋的檔案沒有「查不到」這回事',
  );
  assert.equal(
    needsNumberInput({ number: 'ABC-123' }),
    false,
    'searched 欄位還不存在時（剛建 fileList）同樣不顯示',
  );
});
