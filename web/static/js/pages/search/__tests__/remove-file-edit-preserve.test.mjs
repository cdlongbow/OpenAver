// Codex P1 fix（回歸自 294a2f52 106-T5）: removeFile(index) 對「非當前檔」的移除
// 不該觸發 switchToFile（T5 讓 switchToFile 無條件呼叫 _resetPendingEdits()，見
// reset-pending-edits.test.mjs）——否則使用者正在編輯 A 檔（未確認）時移除另一列 B 檔，
// A 仍是目前檢視的檔、候選也沒變，卻被無謂觸發的 switchToFile 靜默清空編輯 buffer。
//
// 只有移除的正是目前檢視的檔（removingCurrent）時，currentFileIndex 才會真的落到
// 別的檔，這時才需要真的 switchToFile（連帶其 reset）。
//
// 用 spy 取代 switchToFile（模擬其「真的換檔會 reset editingActors」的副作用），
// 讓測試同時對「呼叫與否」與「呼叫後果」都 mutation-sensitive：
// 若 `if (removingCurrent)` guard 被還原成無條件呼叫，非當前檔移除測試會轉紅。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateFileList } from '../state/file-list.js';

test('removeFile: 移除非當前檔（較後面的 row）→ 不呼叫 switchToFile、editingActors 存活、currentFileIndex/currentIndex 不變', () => {
    const switchToFileCalls = [];
    const fakeThis = {
        ...searchStateFileList(),
        switchToFile(index) {
            switchToFileCalls.push(index);
            // 模擬真實 switchToFile 的副作用（T5 _resetPendingEdits()）
            this.editingActors = false;
        },
        saveState: () => {},
        fileList: [
            { path: '/a/x1.mp4', number: 'ABC-001' }, // A：目前正在看（index 0）
            { path: '/a/x2.mp4', number: 'ABC-002' }, // B：要移除的（index 1，較後面）
        ],
        currentFileIndex: 0,
        currentIndex: 3,
        editingActors: true,
    };

    fakeThis.removeFile(1);

    assert.equal(switchToFileCalls.length, 0, '移除非當前檔不應呼叫 switchToFile');
    assert.equal(fakeThis.editingActors, true, '非當前檔被移除，A 檔未確認的編輯應存活');
    assert.equal(fakeThis.currentFileIndex, 0, 'currentFileIndex 應仍指向 A（未移除、index 在其之後不需調整）');
    assert.equal(fakeThis.currentIndex, 3, 'currentIndex（候選 index）不受移除其他檔影響');
});

test('removeFile: 移除較前面的非當前檔（currentFileIndex 需 decrement 重新指向）→ 不呼叫 switchToFile、editingActors 存活', () => {
    const switchToFileCalls = [];
    const fakeThis = {
        ...searchStateFileList(),
        switchToFile(index) {
            switchToFileCalls.push(index);
            this.editingActors = false;
        },
        saveState: () => {},
        fileList: [
            { path: '/a/x0.mp4', number: 'ABC-000' }, // 要移除的（index 0，較前面）
            { path: '/a/x1.mp4', number: 'ABC-001' }, // 目前正在看（index 1）
        ],
        currentFileIndex: 1,
        currentIndex: 2,
        editingActors: true,
    };

    fakeThis.removeFile(0);

    assert.equal(switchToFileCalls.length, 0, '移除非當前檔不應呼叫 switchToFile（即使 currentFileIndex 需 decrement 重新指向）');
    assert.equal(fakeThis.editingActors, true, '正在看的檔只是被重新指到新 index，未確認的編輯應存活');
    assert.equal(fakeThis.currentFileIndex, 0, 'currentFileIndex 應 decrement 後重新指向同一個檔（原 index 1 → 移除 index 0 後變 0）');
    assert.equal(fakeThis.currentIndex, 2, 'currentIndex（候選 index）不受影響');
});

test('removeFile: 移除當前正在看的檔 → 真的呼叫 switchToFile（reset 生效）', () => {
    const switchToFileCalls = [];
    const fakeThis = {
        ...searchStateFileList(),
        switchToFile(index) {
            switchToFileCalls.push(index);
            this.editingActors = false;
        },
        saveState: () => {},
        fileList: [
            { path: '/a/x1.mp4', number: 'ABC-001' },
            { path: '/a/x2.mp4', number: 'ABC-002' }, // 目前正在看這個（index 1），要被移除
        ],
        currentFileIndex: 1,
        currentIndex: 0,
        editingActors: true,
    };

    fakeThis.removeFile(1);

    assert.equal(switchToFileCalls.length, 1, '移除當前正在看的檔應真的觸發 switchToFile');
    assert.equal(switchToFileCalls[0], 0, '移除後 currentFileIndex 應 clamp 到剩餘最後一檔（原本只剩 index 0）');
    assert.equal(fakeThis.editingActors, false, '真的換檔應清掉未確認編輯（switchToFile 內部 _resetPendingEdits）');
});
