// TASK-131b-T3: Alpine.store('toast') show/hide + toastState 委派

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {} };

const { createToastStore } = await import('../toast-store.js');
const { toastState } = await import('../../shared/state-toast.js');


test('duration 到期後 visible 變 false、_timer 清 null', async () => {
    const store = createToastStore();
    store.show('temp', 'info', 50);
    assert.equal(store.visible, true);
    await delay(80);
    assert.equal(store.visible, false);
    assert.equal(store._timer, null);
});


// ── TASK-172-T4: toast 動作鈕（action）──


test('show() 後到的無 action toast 會清掉前一則的 action', () => {
    const store = createToastStore();
    const act = { label: '復原', onClick() {} };
    store.show('A', 'success', 6000, act);
    assert.equal(store.action, act);
    store.show('B', 'info', 2500);
    assert.equal(store.action, null);
    assert.equal(store.message, 'B');
    if (store._timer) clearTimeout(store._timer);
});


test('showToast 把第四個參數 action 原樣轉發', () => {
    const calls = [];
    const fakeStore = {
        show(...args) { calls.push(args); },
    };
    globalThis.Alpine = { store: () => fakeStore };
    try {
        const act = { label: '復原', onClick() {} };
        toastState().showToast('delegated', 'success', 6000, act);
        assert.equal(calls.length, 1);
        assert.deepEqual(calls[0], ['delegated', 'success', 6000, act]);
        assert.equal(calls[0][3], act);
    } finally {
        delete globalThis.Alpine;
    }
});
