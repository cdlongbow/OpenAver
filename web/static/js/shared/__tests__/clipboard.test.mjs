// TASK-168b-T7: copyText 三層降級（bridge → navigator.clipboard → execCommand）

import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;

let execCalls;
let taValues;
function stubDocument(execResult) {
    execCalls = 0;
    taValues = [];
    globalThis.document = {
        createElement: () => {
            const ta = { value: '', style: {}, select: () => {}, remove: () => {} };
            return ta;
        },
        body: { appendChild: (ta) => { taValues.push(ta.value); } },
        execCommand: () => {
            execCalls += 1;
            if (execResult instanceof Error) throw execResult;
            return execResult;
        },
    };
}
function setNavigator(value) {
    Object.defineProperty(globalThis, 'navigator', { value, configurable: true });
}

const { copyText, execCommandCopy } = await import('../clipboard.js');

beforeEach(() => {
    delete globalThis.pywebview;
    stubDocument(false);
    setNavigator({});
});
afterEach(() => {
    delete globalThis.pywebview;
    delete globalThis.document;
    delete globalThis.navigator;
});

function counter(impl) {
    const fn = (...a) => { fn.calls += 1; return impl(...a); };
    fn.calls = 0;
    return fn;
}

test('bridge 回 ok:true 時回 true，navigator 與 execCommand 零呼叫', async () => {
    const T = '路徑/中文 🎬 ABC-123';
    const got = [];
    const bridge = counter((t) => { got.push(t); return Promise.resolve({ ok: true }); });
    const write = counter(() => Promise.resolve());
    globalThis.pywebview = { api: { copy_text: bridge } };
    setNavigator({ clipboard: { writeText: write } });
    stubDocument(true);
    assert.equal(await copyText(T), true);
    assert.deepEqual(got, [T]);
    assert.equal(bridge.calls, 1);
    assert.equal(write.calls, 0);
    assert.equal(execCalls, 0);
});

test('bridge 回 ok:false 時降到 navigator 而非當成功', async () => {
    const bridgeGot = [];
    const writeGot = [];
    const bridge = counter((t) => { bridgeGot.push(t); return Promise.resolve({ ok: false }); });
    const write = counter((t) => { writeGot.push(t); return Promise.resolve(); });
    globalThis.pywebview = { api: { copy_text: bridge } };
    setNavigator({ clipboard: { writeText: write } });
    assert.equal(await copyText('x'), true);
    assert.equal(bridge.calls, 1);
    assert.equal(write.calls, 1);
    assert.deepEqual(bridgeGot, ['x']);
    assert.deepEqual(writeGot, ['x']);
});

test('bridge 回 undefined、{}、reject 皆降到 navigator', async () => {
    for (const impl of [() => Promise.resolve(undefined), () => Promise.resolve({}), () => Promise.reject(new Error('x')), () => { throw new Error('sync'); }]) {
        const write = counter(() => Promise.resolve());
        globalThis.pywebview = { api: { copy_text: impl } };
        setNavigator({ clipboard: { writeText: write } });
        assert.equal(await copyText('x'), true);
        assert.equal(write.calls, 1);
    }
});

test('navigator 成功時 execCommand 零呼叫', async () => {
    const got = [];
    const write = counter((t) => { got.push(t); return Promise.resolve(); });
    setNavigator({ clipboard: { writeText: write } });
    stubDocument(true);
    assert.equal(await copyText('日本語 🎞'), true);
    assert.deepEqual(got, ['日本語 🎞']);
    assert.equal(write.calls, 1);
    assert.equal(execCalls, 0);
});

test('navigator.writeText reject 時降到 execCommand', async () => {
    setNavigator({ clipboard: { writeText: () => Promise.reject(new Error('denied')) } });
    stubDocument(true);
    assert.equal(await copyText('x'), true);
    assert.equal(execCalls, 1);
    assert.deepEqual(taValues, ['x']);
});

test('window.pywebview 缺席時直接走 navigator', async () => {
    const write = counter(() => Promise.resolve());
    setNavigator({ clipboard: { writeText: write } });
    assert.equal(await copyText('x'), true);
    assert.equal(write.calls, 1);
});

test('navigator 為 {} 時降到 execCommand', async () => {
    setNavigator({});
    stubDocument(true);
    assert.equal(await copyText('中文 🎬 x'), true);
    assert.equal(execCalls, 1);
    assert.deepEqual(taValues, ['中文 🎬 x']);
});

test('三層全失敗回 false 且不丟例外', async () => {
    globalThis.pywebview = { api: { copy_text: () => Promise.reject(new Error('a')) } };
    setNavigator({ clipboard: { writeText: () => Promise.reject(new Error('b')) } });
    stubDocument(false);
    assert.equal(await copyText('x'), false);
    stubDocument(new Error('c'));
    assert.equal(await copyText('x'), false);
});

test('document 不存在時 copyText 回 false 不丟', async () => {
    delete globalThis.document;
    assert.equal(await copyText('x'), false);
});

test('execCommandCopy 例外視為失敗並移除 textarea', () => {
    let removed = 0;
    globalThis.document = {
        createElement: () => ({ value: '', style: {}, select: () => {}, remove: () => { removed += 1; } }),
        body: { appendChild: () => {} },
        execCommand: () => { throw new Error('boom'); },
    };
    assert.equal(execCommandCopy('x'), false);
    assert.equal(removed, 1);
});
