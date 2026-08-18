// TASK-120-C1 AC-5：罩杯排序真路徑——L+ 不得當 null 沉底。
// 對抗性種子 [無資料, Z, A, L, K]：Array.sort 穩定，兩個 Infinity 回 0
// 會原封不動留下輸入序；若把 L／Z 排在無資料前面種，今天的壞碼也會假 GREEN。
//
// 走 search/__tests__/alias-loader.mjs（120-C1 擴成完整 importmap 對照），
// 不自帶第二支 loader。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;
globalThis.localStorage = { getItem: () => null, removeItem: () => {} };
globalThis.Alpine = globalThis.Alpine || {
    store: () => ({ toolbarOpen: false, showcaseHasSearch: false }),
};

register(new URL('../../search/__tests__/alias-loader.mjs', import.meta.url), import.meta.url);

const { stateActress } = await import('../state-actress.js');
const { _setActresses, _filteredActresses } = await import('../state-base.js');

const SEED = [
    { name: '無資料', cup: null },
    { name: 'Z', cup: 'Z' },
    { name: 'A', cup: 'A' },
    { name: 'L', cup: 'L' },
    { name: 'K', cup: 'K' },
];

function namesAfterCupSort(order) {
    const c = Object.assign({}, stateActress(), {
        actressSort: 'cup',
        actressOrder: order,
        actressSearch: '',
    });
    _setActresses(SEED);
    c.applyActressFilterAndSort();
    return _filteredActresses.map((a) => a.name);
}

test('cup 升冪：A,K,L,Z,無資料（AC-5，對抗性種子）', () => {
    assert.deepEqual(namesAfterCupSort('asc'), ['A', 'K', 'L', 'Z', '無資料']);
});

test('cup 降冪：Z,L,K,A,無資料（AC-5，無資料恆最後）', () => {
    assert.deepEqual(namesAfterCupSort('desc'), ['Z', 'L', 'K', 'A', '無資料']);
});
