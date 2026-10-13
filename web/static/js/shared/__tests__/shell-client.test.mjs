// 168c-T4: shell-client.js (node:test, fake window).
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { whenBridgeReady, callBridge, clientRouting } = await import('../shell-client.js');

function freshWindow(api) {
    const w = new EventTarget();
    if (api) w.pywebview = { api };
    globalThis.window = w;
    return w;
}

test('test_client_routing_old_shell_missing_method_routes_to_server', () => {
    const REQ = ['a', 'b'];
    const full = { a() {}, b() {} };
    const rows = [
        ['client', full, 'bridge'],
        ['client', { a() {} }, 'server'],
        ['client', { b() {} }, 'server'],
        ['client', {}, 'server'],
        ['client', null, 'server'],
        ['local', full, 'server'],
        ['', full, 'server'],
        [undefined, full, 'server'],
    ];
    for (const [mode, bridge, want] of rows) {
        assert.equal(clientRouting(mode, bridge, REQ), want, `${mode} ${bridge && Object.keys(bridge)}`);
    }
});

test('whenBridgeReady: already ready / event arrives / timeout', async () => {
    let w = freshWindow();
    w.__oaBridgeKind = 'server';
    assert.equal(await whenBridgeReady(20), true);

    w = freshWindow();
    const p = whenBridgeReady(500);
    w.dispatchEvent(new Event('oabridgeready'));
    assert.equal(await p, true);

    freshWindow();
    assert.equal(await whenBridgeReady(20), false);
});

test('callBridge: missing bridge / missing method / throw never propagate', async () => {
    freshWindow();
    assert.deepEqual(await callBridge('x'), { ok: false, reason: 'no_bridge' });
    freshWindow({});
    assert.deepEqual(await callBridge('x'), { ok: false, reason: 'no_bridge' });
    freshWindow({ x() { throw new Error('boom'); } });
    assert.deepEqual(await callBridge('x'), { ok: false, reason: 'error' });
    freshWindow({ x: async () => ({ ok: true, v: 1 }) });
    assert.deepEqual(await callBridge('x', 1), { ok: true, v: 1 });
});

test('callBridge: untrusted retries exactly once after waiting for ready', async () => {
    let calls = 0;
    const w = freshWindow({ x: async () => { calls += 1; return { ok: false, reason: 'untrusted' }; } });
    w.__oaBridgeKind = 'server';
    const p = callBridge('x');
    await new Promise((r) => setTimeout(r, 10));
    assert.equal(w.__oaBridgeKind, undefined);
    w.dispatchEvent(new Event('oabridgeready'));
    const reply = await p;
    assert.equal(calls, 2);
    assert.equal(reply.reason, 'untrusted');
});
