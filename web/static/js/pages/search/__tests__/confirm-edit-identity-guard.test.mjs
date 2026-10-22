// TASK-106 Option C Part 1: confirmEditTitle/confirmEditChineseTitle/confirmEditActors
// identity guard —— 本次重構的唯一權威保證。
// Codex PR#116 P2: confirmEditDate 補齊同一 pattern（date picker 原本是唯一沒有此守衛的
// 可編輯欄位，@change 在事件當下才 re-resolve current()，若候選在打開日曆到選好日期之間
// 被換掉會寫錯檔）。
//
// 根因（見 task 交付說明）：buffered edits（editingX flag + editedXValue buffer）
// 必須在「displayed candidate 已經換了」時被丟棄，唯一正確訊號是 current() 候選物件的
// 參照本身，不是任何呼叫端「猜」何時該 reset。confirmEditX 開頭一律先比對
// this.current() 是否仍是開編輯當下（startEditX）捕獲的同一個物件參照；不同就不寫、
// 關掉 editingX、直接 return——不管是 navigate/switchToFile/scrapeAll loop/grid/lightbox
// 或任何未來新增的路徑移動的 current()，一律結構性擋下。
//
// 移除 guard（或比錯欄位）→ 本檔案第一組測試（含 confirmEditDate）應轉紅（B 被誤寫）。
//
// Codex PR#115 P2 fix：三個欄位（_editSourceTitle/_editSourceChineseTitle/_editSourceActors）
// 各自獨立，不共用單一 `_editSourceCandidate`——title/chinese/actor 三個 editingX 可同時
// 開啟（各自獨立的 flag，無互斥），若共用一個欄位，後開啟的編輯器會覆蓋先開啟者捕獲的
// 來源，讓先開啟者的 guard 誤判「候選未換」而把 stale 內容寫進後開啟者當下的候選
// （data pollution）。見本檔案「跨欄位污染」測試組——若退回共用單一欄位，該測試轉紅。
//
// result-card.js 用瀏覽器 importmap 別名 `@/shared/...`，plain `node --test`
// 需掛 alias-loader resolve hook 才能 import（同 confirm-edit-actors-fetch-spy.test.mjs）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;

register(new URL('./alias-loader.mjs', import.meta.url), import.meta.url);
const { searchStateResultCard } = await import('../state/result-card.js');

function makeFakeThis(overrides = {}) {
    return {
        ...searchStateResultCard(),
        saveState: () => {},
        ...overrides,
    };
}

// ==================== 核心：candidate 已換 → 不寫、editingX 關閉、不 saveState ====================

test('confirmEditActors: current() 已換到別的候選（B）→ B.actors 不被寫入，editingActors 關閉，不 saveState', () => {
    const A = { number: 'A-001', actors: ['原始女優'] };
    const B = { number: 'B-002', actors: ['B原始女優'] };
    let saveCalls = 0;

    const fakeThis = makeFakeThis({
        editingActors: true,
        editedActorsValue: '亂寫的女優',
        _editSourceActors: A,   // startEditActors 開編輯時捕獲的是 A
        current: () => B,          // 但呼叫 confirm 時 current() 已經是 B（被別的路徑換走）
        saveState: () => { saveCalls++; },
    });

    searchStateResultCard().confirmEditActors.call(fakeThis);

    assert.deepEqual(B.actors, ['B原始女優'], 'B.actors 不應被 stale 編輯寫入');
    assert.equal(fakeThis.editingActors, false, '即使 guard 擋下寫入，仍應關閉編輯態（UI 不留在編輯模式）');
    assert.equal(saveCalls, 0, 'guard 擋下時不應呼叫 saveState');
});


// ==================== 對照組：candidate 未換 → 正常寫入（guard 不誤擋合法確認） ====================

test('confirmEditActors: current() 仍是開編輯當下的同一物件 → 正常寫入 + saveState', () => {
    const A = { number: 'A-001', actors: ['原始女優'] };
    let saveCalls = 0;

    const fakeThis = makeFakeThis({
        editingActors: true,
        editedActorsValue: '新女優一, 新女優二',
        _editSourceActors: A,
        current: () => A,
        saveState: () => { saveCalls++; },
    });

    searchStateResultCard().confirmEditActors.call(fakeThis);

    assert.deepEqual(A.actors, ['新女優一', '新女優二'], 'candidate 未換時應正常寫入');
    assert.equal(fakeThis.editingActors, false);
    assert.equal(saveCalls, 1, 'candidate 未換時應呼叫一次 saveState');
});


// ==================== startEditX 捕獲各自的 _editSource* 欄位 ====================


// ==================== 跨欄位污染（Codex PR#115 P2）：title/actors 同時開啟編輯 ====================

