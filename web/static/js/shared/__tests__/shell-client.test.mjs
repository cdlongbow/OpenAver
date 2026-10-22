// 168c-T4: shell-client.js (node:test, fake window).
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { callBridge, clientRouting } = await import('../shell-client.js');

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

