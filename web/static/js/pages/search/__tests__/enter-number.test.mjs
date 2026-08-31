// TASK-139-T5: 前端 enterNumber() 移除改寫邏輯（F1-c）
// 確保手動輸入番號時原樣送出（僅 trim），不再前端猜測格式

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateFileList } from '../state/file-list.js';

globalThis.window = globalThis;
globalThis.window.t = globalThis.window.t || ((k) => k);
await import('../file.js');

function makeState(file) {
    return {
        ...searchStateFileList(),
        fileList: [file],
        switchToFile() {},   // 本測試只驗 file.number，switchToFile 副作用不是本卡範圍
    };
}

for (const input of ['n0762', '200GANA-3360', 'FC2PPV-4943690']) {
    test(`enterNumber: ${input} 送出值僅 trim，不改寫`, () => {
        const file = { number: null };
        const state = makeState(file);
        globalThis.prompt = () => input;
        state.enterNumber(0);
        assert.equal(file.number, input);
    });
}
