// TASK-106-T1 CD-106-1: canEditFile() 單一閘門 computed
//
// canEditFile() 是 searchStateBase() mixin 的 method（讀 this.listMode /
// this.fileList / this.currentFileIndex），非 CD-106-8 列管的 module-level
// 純函式，故用 .call(fakeThis) 呼叫（同 set-file-list-fallback.test.mjs 慣例）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateBase } from '../state/base.js';

globalThis.window = globalThis;

test('canEditFile: listMode="search" → false（keyword search 無 file-mode 閘）', () => {
  const fakeThis = {
    ...searchStateBase(),
    listMode: 'search',
    fileList: [{ path: '/a/x1.mp4' }],
    currentFileIndex: 0,
  };

  assert.equal(searchStateBase().canEditFile.call(fakeThis), false);
});

test('canEditFile: listMode="file" 但 fileList[currentFileIndex] 無 path → false', () => {
  const fakeThis = {
    ...searchStateBase(),
    listMode: 'file',
    fileList: [{ number: 'ABC-123' }],
    currentFileIndex: 0,
  };

  assert.equal(searchStateBase().canEditFile.call(fakeThis), false);
});

test('canEditFile: listMode="file" 且 fileList[currentFileIndex].path 存在 → true', () => {
  const fakeThis = {
    ...searchStateBase(),
    listMode: 'file',
    fileList: [{ path: '/a/x1.mp4' }],
    currentFileIndex: 0,
  };

  assert.equal(searchStateBase().canEditFile.call(fakeThis), true);
});
