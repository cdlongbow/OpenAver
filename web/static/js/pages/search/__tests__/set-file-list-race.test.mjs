// TASK-103-T5 P1 fix（Codex PR review）: setFileList abort 未接通到 parse 階段
//
// 修正前：setFileList 只把 setFileListSignal 接到 filter-files fetch，:310-312 的
// finally 在 filter 一結束就 _clearAbort，:319 呼叫 parseFilenames 完全沒傳 signal。
// 後果：連續選 A、B 兩批檔案時，A 的 parse 請求不會被 B abort；A 若晚於 B 回應，
// 仍會用自己的 parseResults 重建 this.fileList，把 B 已經寫好的結果蓋掉
// （last-return-wins clobber），且 parse catch 裡的 AbortError 早退是永遠打不到的死碼。
//
// 修正後：_getAbortSignal('setFileList') 拿到的 signal 貫穿 filter fetch + parseFilenames
// 兩個 await 邊界，_clearAbort 挪到函式最外層 finally（比對 signal，不誤刪新 controller）。
//
// 本測試建構「真」的 A/B 競態（非直接 mock 出 AbortError）：parseFilenames mock 尊重
// signal——signal 已 abort 或稍後被 abort 都 reject AbortError，否則 pending 到測試手動
// resolve，手法照抄 handle-file-drop-race.test.mjs 的 makeParseFilenamesMock()。fake `this`
// 用 base + search-flow + file-list 三個 mixin 組出真實的 _getAbortSignal/_clearAbort/
// _abortControllers，不手抄 abort 邏輯（同 set-file-list-fallback.test.mjs 既有手法）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateFileList } from '../state/file-list.js';
import { searchStateSearchFlow } from '../state/search-flow.js';
import { searchStateBase } from '../state/base.js';

globalThis.window = globalThis;

function makeAbortError() {
  return new DOMException('The operation was aborted', 'AbortError');
}

// 照抄 handle-file-drop-race.test.mjs：模擬真實 fetch 對 AbortSignal 的接線——
// signal 已 abort 或稍後被 abort 都會 reject，否則 pending 到測試手動 resolve。
function makeParseFilenamesMock() {
  const calls = [];
  function parseFilenames(filenames, { signal } = {}) {
    const call = { filenames, signal };
    const promise = new Promise((resolve, reject) => {
      call.resolve = resolve;
      call.reject = reject;
      if (signal) {
        if (signal.aborted) {
          reject(makeAbortError());
        } else {
          signal.addEventListener('abort', () => reject(makeAbortError()), { once: true });
        }
      }
    });
    calls.push(call);
    return promise;
  }
  return { parseFilenames, calls };
}

// filter-files 端點：焦點在 parse 階段的競態，這裡不模擬 filter 自身被 abort——
// 一律快速 resolve success:false（沿用原始 paths），讓兩批請求都正常走到 parseFilenames。
function stubFilterFilesFetch() {
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({ success: false }),
  });
}

function makeFakeThis(overrides = {}) {
  return Object.assign(
    {},
    searchStateBase(),
    searchStateSearchFlow(),
    searchStateFileList(),
    { _resetCoverState() {} },
    overrides,
  );
}

const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
};

test('P1 fix: 連續 setFileList(A) → setFileList(B)，A 的 parse 晚於 B 才 resolve → 最終 fileList 是 B，A 不得覆蓋（last-return-wins clobber 守衛）', async () => {
  stubFilterFilesFetch();
  window.t = (key) => key;
  const { parseFilenames, calls } = makeParseFilenamesMock();
  window.SearchFile = {
    parseFilenames,
    detectSuffixes: () => [],
    extractChineseTitle: () => null,
  };

  const toasts = [];
  const fakeThis = makeFakeThis({
    showToast(msg, type) { toasts.push({ msg, type }); },
    switchToFile: async () => {},
  });

  const pathsA = ['/a/A-001.mp4'];
  const pathsB = ['/b/B-002.mp4'];

  // 不 await：A、B 緊接觸發，模擬使用者快速連續選檔
  const pA = fakeThis.setFileList(pathsA);
  const pB = fakeThis.setFileList(pathsB);

  await flush();
  assert.equal(calls.length, 2, 'A、B 應各觸發一次 parseFilenames 呼叫');

  // B 先回應（正常路徑），A 之後才回應（反序：模擬 A 的回應姍姍來遲）
  calls[1].resolve([{ filename: 'B-002.mp4', number: 'B-002', has_subtitle: false }]);
  calls[0].resolve([{ filename: 'A-001.mp4', number: 'A-001', has_subtitle: false }]);
  await flush();
  await Promise.all([pA, pB]);

  assert.equal(fakeThis.fileList.length, 1, 'fileList 應只有 B 的一筆，A 不得疊加或覆蓋');
  assert.equal(fakeThis.fileList[0].number, 'B-002', '最終 fileList 必須是 B 的內容，A 事後才 resolve 也不得覆蓋');
  assert.equal(toasts.length, 0, 'A 被 abort 不得產生任何 toast/錯誤狀態');
});

test('P1 fix: registry 語意——B 完成後 setFileList key 被正確清除，A 的 stale finally 不誤刪/誤留', async () => {
  stubFilterFilesFetch();
  window.t = (key) => key;
  const { parseFilenames, calls } = makeParseFilenamesMock();
  window.SearchFile = {
    parseFilenames,
    detectSuffixes: () => [],
    extractChineseTitle: () => null,
  };

  const fakeThis = makeFakeThis({
    showToast() {},
    switchToFile: async () => {},
  });

  const pA = fakeThis.setFileList(['/a/A-001.mp4']);
  const pB = fakeThis.setFileList(['/b/B-002.mp4']);
  await flush();

  calls[1].resolve([{ filename: 'B-002.mp4', number: 'B-002', has_subtitle: false }]);
  calls[0].resolve([{ filename: 'A-001.mp4', number: 'A-001', has_subtitle: false }]);
  await flush();
  await Promise.all([pA, pB]);

  assert.equal(
    fakeThis._abortControllers.setFileList,
    undefined,
    'B 完成後 registry 內 setFileList key 應被清空；A 的 finally（比對舊 signal）不得覆蓋/殘留',
  );
});
