// TASK-106 Option C Part 2: setupAutoSave() 新增的候選改變 $watch —— UX 便利層
// （非權威保證，權威保證見 confirm-edit-identity-guard.test.mjs 的 identity guard）。
//
// 這裡不能測試真正的 Alpine reactivity（$watch 底層依賴 Alpine.effect() 的 Proxy
// 依賴追蹤，Node 測試環境沒有 Alpine，$watch 是 Alpine 注入 x-data 物件的 magic method，
// 不是 persistence.js 能獨立提供的東西）——用 spy 取代 this.$watch，只驗證：
// 1. setupAutoSave() 確實多掛了一個「函式表達式」形式（非字串 key）的 $watch，且
//    callback 是呼叫 this._resetPendingEdits()。
// 2. 抽出該 watcher 的 getter 函式本身直接測試其純邏輯（不依賴 Alpine reactivity）：
//    - 候選在陣列中的位置改變（currentIndex/currentFileIndex/listMode）→ getter 回傳值不同。
//    - 候選清單被整批替換（陣列參照換了、長度也不同）→ getter 回傳值不同。
//    - 只有候選物件內部欄位被直寫（模擬打字/date 變更/checkLocalStatus/translateWithAI 等
//      不透過 editingX 流程的直寫）、candidate 在陣列中的位置未變 → getter 回傳值不變
//      （deepEqual）。這證明我們選的複合表達式只讀 primitives（index/mode/length），
//      不會像 `$watch('current()', cb)` 那樣被 Alpine 內部的 JSON.stringify 深度追蹤
//      進候選物件的巢狀欄位而在打字時誤觸發（見 persistence.js 該段落大註解 + Alpine
//      官方文件 https://alpinejs.dev/magics/watch「Deep watching」段的查證結論）。
//
// 「這個 getter 的回傳值有沒有變」只是必要條件，不是充分條件——Alpine 的 $watch 是否
// 真的只在回傳值變動時才觸發 callback（而非任何被讀取到的 reactive 依賴變動就觸發），
// 是 Alpine 內部機制，本測試證明不了，需真機 CDP 或 owner 手動驗證候選切換時編輯框
// 正確關閉、且打字/date 變更時編輯框不會意外關閉。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStatePersistence } from '../state/persistence.js';

function captureWatchers(fakeThisOverrides = {}) {
    const watchCalls = [];
    const fakeThis = {
        ...searchStatePersistence(),
        $watch: (keyOrGetter, cb) => watchCalls.push({ keyOrGetter, cb }),
        _setTimer: () => {},
        _resetPendingEdits: () => { fakeThis._resetPendingEditsCalls = (fakeThis._resetPendingEditsCalls || 0) + 1; },
        ...fakeThisOverrides,
    };
    searchStatePersistence().setupAutoSave.call(fakeThis);
    return { fakeThis, watchCalls };
}

test('setupAutoSave: 掛了一個函式表達式（非字串 key）的 $watch，callback 呼叫 _resetPendingEdits', () => {
    const { fakeThis, watchCalls } = captureWatchers();

    const functionWatchers = watchCalls.filter(w => typeof w.keyOrGetter === 'function');
    assert.equal(functionWatchers.length, 1, '應恰好新增一個函式表達式 $watch（候選改變偵測）');

    functionWatchers[0].cb();
    assert.equal(fakeThis._resetPendingEditsCalls, 1, '該 watcher 的 callback 應呼叫 _resetPendingEdits()');

    // 既有 4 個字串 key 的 $watch（searchResults/currentIndex/fileList/listMode，autosave 用）不受影響
    const stringWatchers = watchCalls.filter(w => typeof w.keyOrGetter === 'string');
    assert.equal(stringWatchers.length, 4, '既有 4 個 autosave 用的字串 $watch 應保留');
});

test('候選改變 watcher 的 getter：純數值/字串複合值，位置改變時不同、僅內部欄位直寫時相同', () => {
    const watchCalls = [];
    const fakeThis = {
        ...searchStatePersistence(),
        $watch: (keyOrGetter, cb) => watchCalls.push({ keyOrGetter, cb }),
        _setTimer: () => {},
        _resetPendingEdits: () => {},
        listMode: 'search',
        currentFileIndex: 0,
        currentIndex: 0,
        searchResults: [{ number: 'A', title: 'orig' }, { number: 'B', title: 'orig-b' }],
        fileList: [],
    };
    searchStatePersistence().setupAutoSave.call(fakeThis);
    const getter = watchCalls.find(w => typeof w.keyOrGetter === 'function').keyOrGetter;

    const snapshot1 = getter();

    // 模擬「打字」/「date @change」/「checkLocalStatus」/「translateWithAI」等不透過
    // editingX 流程、直接 mutate 候選物件內部欄位的既有寫法——候選在陣列中的位置不變。
    fakeThis.searchResults[0].title = 'mutated during typing';
    fakeThis.searchResults[0].date = '2026-01-01';
    fakeThis.searchResults[0]._localStatus = { exists: true };

    const snapshot2 = getter();
    assert.deepEqual(snapshot2, snapshot1, '候選內部欄位直寫、位置未變 → 複合表達式回傳值應相同（只讀 primitives，不因巢狀欄位變動而改變）');

    // 候選真的換位（currentIndex 改變）→ 回傳值應不同
    fakeThis.currentIndex = 1;
    const snapshot3 = getter();
    assert.notDeepEqual(snapshot3, snapshot1, 'currentIndex 改變 → 複合表達式回傳值應不同');

    // 清單被整批替換（長度改變）→ 回傳值應不同（即使 currentIndex/currentFileIndex/listMode 都改回原值）
    fakeThis.currentIndex = 0;
    fakeThis.searchResults = [{ number: 'C', title: 'new' }];
    const snapshot4 = getter();
    assert.notDeepEqual(snapshot4, snapshot1, '清單被整批替換（長度改變）→ 複合表達式回傳值應不同');
});
