// Codex P1 fix（回歸自 294a2f52 106-T5，TASK-106 Option C 後重新定調）: removeFile(index)
// 對「非當前檔」的移除不該觸發 switchToFile——移除的是別的檔時，目前檢視的檔/候選沒變，
// 不需要（也不該）跳去 switchToFile 重新顯示（會把畫面跳回候選 0）。
//
// 只有移除的正是目前檢視的檔（removingCurrent）時，currentFileIndex 才會真的落到
// 別的檔，這時才需要真的 switchToFile 換到鄰檔重新顯示。
//
// Option C 後，switchToFile 本身不再直接碰 editingX（那是 persistence.js 的 $watch
// 的工作，見 reset-pending-edits.test.mjs / confirm-edit-identity-guard.test.mjs）——
// 所以本檔測試的斷言重點改為「removingCurrent gate 是否正確決定要不要呼叫
// switchToFile」（純顯示層決策），不再靠 spy 模擬 switchToFile 清 editingActors 來
// 間接驗證編輯是否被保留。「非當前檔移除時 editingActors 存活」在新機制下是
// trivial 的（switchToFile 完全沒被呼叫，任何 state 自然不變）；真正的 mutation-sensitive
// 守衛是「該不該呼叫 switchToFile」這件事本身。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateFileList } from '../state/file-list.js';

test('removeFile: 移除非當前檔（較後面的 row）→ 不呼叫 switchToFile、editingActors 存活、currentFileIndex/currentIndex 不變', () => {
    const switchToFileCalls = [];
    const fakeThis = {
        ...searchStateFileList(),
        switchToFile(index) {
            switchToFileCalls.push(index);
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
    assert.equal(fakeThis.editingActors, true, '非當前檔被移除，A 檔未確認的編輯應存活（switchToFile 根本沒被呼叫）');
    assert.equal(fakeThis.currentFileIndex, 0, 'currentFileIndex 應仍指向 A（未移除、index 在其之後不需調整）');
    assert.equal(fakeThis.currentIndex, 3, 'currentIndex（候選 index）不受移除其他檔影響');
});

test('removeFile: 移除較前面的非當前檔（currentFileIndex 需 decrement 重新指向）→ 不呼叫 switchToFile、editingActors 存活', () => {
    const switchToFileCalls = [];
    const fakeThis = {
        ...searchStateFileList(),
        switchToFile(index) {
            switchToFileCalls.push(index);
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

test('removeFile: 移除當前正在看的檔 → 真的呼叫 switchToFile（display 重繪生效，clamp 到剩餘最後一檔）', () => {
    const switchToFileCalls = [];
    const fakeThis = {
        ...searchStateFileList(),
        switchToFile(index) {
            switchToFileCalls.push(index);
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

    assert.equal(switchToFileCalls.length, 1, '移除當前正在看的檔應真的觸發 switchToFile（重新顯示鄰檔）');
    assert.equal(switchToFileCalls[0], 0, '移除後 currentFileIndex 應 clamp 到剩餘最後一檔（原本只剩 index 0）');
    // Option C: editingActors 是否被清不再是 switchToFile 呼叫本身的責任（那是 persistence.js
    // $watch 偵測到候選/檔位置改變後才觸發），本測試不對此斷言——見
    // confirm-edit-identity-guard.test.mjs / reset-pending-edits.test.mjs。
});
