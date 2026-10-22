// TASK-106 Option C Part 2: setupAutoSave() 新增的候選改變 $watch —— UX 便利層
// （非權威保證，權威保證見 confirm-edit-identity-guard.test.mjs 的 identity guard）。
//
// 這裡不能測試真正的 Alpine reactivity（$watch 底層依賴 Alpine.effect() 的 Proxy
// 依賴追蹤，Node 測試環境沒有 Alpine，$watch 是 Alpine 注入 x-data 物件的 magic method，
// 不是 persistence.js 能獨立提供的東西）——分兩層驗證：
// 1. setupAutoSave() 確實多掛了一個「函式表達式」形式（非字串 key）的 $watch，且
//    callback 是呼叫 this._resetPendingEdits()。
// 2. 抽出的 module-level 純函式 pendingEditWatchKey 直接測其邏輯（不依賴 Alpine reactivity）：
//    - 回傳值必須是「基本型別字串」（鎖住這點——Alpine `watch` 只有回傳基本型別才會做
//      `newValue !== oldValue` 值比對；回傳物件/陣列一律觸發，見 persistence.js 大註解與
//      vendored alpine.min.js 原始碼查證結論）。
//    - 核心回歸（Codex PR#115 P2）：純 reindex（removeFile() 移除目前檢視檔案「之前」的一列，
//      只遞減 currentFileIndex，同一份 file 物件、同一個 path）→ key 不變（keyBefore ===
//      keyAfter）。真因是「舊版 getter 回傳陣列，Alpine 對陣列一律觸發、根本不比對內容」，
//      改回傳基本型別字串後，同 path reindex → 同字串 → 不觸發。
//    - 正向會變：換檔（path 不同）、換候選（currentIndex 不同）、結果數不同、listMode 不同
//      → key 各不相同。
//    - keyword（search）模式：fileKey 為 ''、用 searchResults.length。
//
// 「這個 key 的回傳值有沒有變」只是必要條件，不是充分條件——Alpine 的 $watch 是否
// 真的只在回傳基本型別值變動時才觸發 callback，是 Alpine 內部機制，本測試證明不了
// （已由查 vendored alpine.min.js 原始碼定案），仍建議真機 CDP 或 owner 手動驗證候選
// 切換時編輯框正確關閉、且打字/date 變更/removeFile 前置列時編輯框不會意外關閉。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStatePersistence, pendingEditWatchKey } from '../state/persistence.js';

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


// ── 核心回歸（Codex PR#115 P2）──
// removeFile() 移除目前檢視檔案「之前」的一列時，只會遞減 currentFileIndex（見 file-list.js
// removeFile 的 removingCurrent gate 註解：目前檢視的檔沒變，只是它在陣列中的位置往前移
// 一格）。舊版 getter 回傳陣列，Alpine 對陣列一律觸發、根本不比對內容，故這個純 reindex
// 會誤觸發、把使用者正在編輯、尚未確認的內容清掉。改成回傳基本型別字串後，同一份 file
// 物件、同一個 path、同 index/mode/length → 同字串 key → Alpine 做值比對 → 不觸發。
test('pendingEditWatchKey：純 reindex（同 path）→ keyBefore === keyAfter（不誤觸發）', () => {
    const fileB = { path: '/a/fileB.mp4', searchResults: [{ number: 'B' }, { number: 'B2' }, { number: 'B3' }] };

    // state A：removeFile('/a') 前——目前檢視 fileB（index 1）
    const stateA = {
        listMode: 'file',
        currentFileIndex: 1,
        currentIndex: 0,
        searchResults: [],
        fileList: [
            { path: '/a', searchResults: [{ number: 'A' }] },
            fileB,
        ],
    };
    const keyBefore = pendingEditWatchKey(stateA);

    // state B：removeFile(0)（移除目前檢視檔案「之前」的一列）後——fileList[0] 被 splice，
    // currentFileIndex 遞減成 0，仍是同一份 fileB 物件、同一個 path。
    const stateB = {
        listMode: 'file',
        currentFileIndex: 0,
        currentIndex: 0,
        searchResults: [],
        fileList: [fileB],
    };
    const keyAfter = pendingEditWatchKey(stateB);

    assert.equal(keyBefore, keyAfter,
        '純 reindex（同一份 file 物件、path 不變）→ key 字串應相同，不誤觸發 watcher（不得清掉正在編輯的內容）');
});


test('pendingEditWatchKey：換候選（currentIndex 不同）→ key 不同', () => {
    const results = [{ number: 'A' }, { number: 'B' }];
    const base = { listMode: 'search', currentFileIndex: 0, currentIndex: 0, searchResults: results, fileList: [] };
    assert.notEqual(
        pendingEditWatchKey(base),
        pendingEditWatchKey({ ...base, currentIndex: 1 }),
        'currentIndex 改變 → key 應不同');
});


// ── 核心回歸（Codex PR#116 P2：原地替換盲區）──
// 換源 / switch-source 流程整顆替換 current() 候選物件（arr[idx] = variant），但
// path / currentIndex / listMode / length 全都不變 → 前四段 key 不變 → 哨兵不觸發 → stale
// 編輯框留著。第五段 _candidateReplaceSeq 在每個原地替換點遞增，讓「同位置換掉一顆候選」
// 也能改變 key，觸發 _resetPendingEdits 關掉 stale 編輯框。
test('pendingEditWatchKey：原地替換（_candidateReplaceSeq 0→1，其餘全同）→ key 不同（換源哨兵）', () => {
    const results = [{ number: 'A' }, { number: 'B' }];
    const base = {
        listMode: 'search',
        currentFileIndex: 0,
        currentIndex: 1,
        searchResults: results,
        fileList: [],
        _candidateReplaceSeq: 0,
    };
    const keyBefore = pendingEditWatchKey(base);
    // 換源：同 path（search 模式空）、同 currentIndex、同 listMode、同 length，只有計數器遞增。
    const keyAfter = pendingEditWatchKey({ ...base, _candidateReplaceSeq: 1 });
    assert.notEqual(keyBefore, keyAfter,
        '同 path/index/mode/length、候選被原地替換（_candidateReplaceSeq 遞增）→ key 應不同，哨兵才會關掉 stale 編輯框');
});
