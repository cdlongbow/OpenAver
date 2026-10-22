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


