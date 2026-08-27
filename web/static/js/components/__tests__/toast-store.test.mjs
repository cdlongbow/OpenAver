// TASK-131b-T3: Alpine.store('toast') show/hide + toastState 委派

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {} };

const { createToastStore } = await import('../toast-store.js');
const { toastState } = await import('../../shared/state-toast.js');

test('show(msg, type, duration) 後 message／type／visible 三個欄位正確', () => {
    const store = createToastStore();
    store.show('hello', 'error', 3000);
    assert.equal(store.message, 'hello');
    assert.equal(store.type, 'error');
    assert.equal(store.visible, true);
    if (store._timer) clearTimeout(store._timer);
});

test('duration 到期後 visible 變 false、_timer 清 null', async () => {
    const store = createToastStore();
    store.show('temp', 'info', 50);
    assert.equal(store.visible, true);
    await delay(80);
    assert.equal(store.visible, false);
    assert.equal(store._timer, null);
});

test('連續兩則：後到的覆蓋先到的，第一則計時器被取消', async () => {
    const store = createToastStore();
    store.show('A', 'error', 1000);
    await delay(200);
    store.show('B', 'success', 4000);
    await delay(1300); // t0+1500ms
    assert.equal(store.visible, true);
    assert.equal(store.message, 'B');
    if (store._timer) clearTimeout(store._timer);
});

test('hide() 後 visible === false 且 _timer === null', () => {
    const store = createToastStore();
    store.show('x', 'success', 5000);
    assert.equal(store.visible, true);
    assert.ok(store._timer);
    store.hide();
    assert.equal(store.visible, false);
    assert.equal(store._timer, null);
});

test('toastState().showToast 委派到 Alpine.store(\'toast\').show 且參數逐字傳過去', () => {
    const calls = [];
    const fakeStore = {
        show(...args) { calls.push(args); },
    };
    globalThis.Alpine = { store: () => fakeStore };
    try {
        toastState().showToast('delegated', 'warning', 1234);
        assert.equal(calls.length, 1);
        assert.deepEqual(calls[0], ['delegated', 'warning', 1234]);
    } finally {
        delete globalThis.Alpine;
    }
});
