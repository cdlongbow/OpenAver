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

// ── TASK-172-T4: toast 動作鈕（action）──

test('show(msg, type, duration, action) 後 store.action 是傳入的物件；未傳為 null', () => {
    const store = createToastStore();
    assert.equal(store.action, null);
    const act = { label: '復原', onClick() {} };
    store.show('translated', 'success', 6000, act);
    assert.equal(store.action, act);
    store.show('plain', 'info', 2500);
    assert.equal(store.action, null);
    if (store._timer) clearTimeout(store._timer);
});

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

test('hide() 後 action 回 null', () => {
    const store = createToastStore();
    const act = { label: '復原', onClick() {} };
    store.show('x', 'success', 5000, act);
    assert.equal(store.action, act);
    store.hide();
    assert.equal(store.action, null);
    assert.equal(store.visible, false);
    if (store._timer) clearTimeout(store._timer);
});

test('到期後 action 回 null 且 visible 為 false', async () => {
    const store = createToastStore();
    const act = { label: '復原', onClick() {} };
    store.show('temp', 'info', 50, act);
    assert.equal(store.action, act);
    await delay(80);
    assert.equal(store.visible, false);
    assert.equal(store.action, null);
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
