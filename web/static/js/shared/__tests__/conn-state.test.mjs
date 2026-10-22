// 168b-T3: conn-state.js pure functions (node:test, no DOM).
import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
const { nextConnState, shouldInterceptNav } = await import('../conn-state.js');


test('test_next_conn_state_error_is_down', () => {
    assert.equal(nextConnState('ok', 'error'), 'down');
    assert.equal(nextConnState('down', 'error'), 'down');
});


test('test_next_conn_state_bad_body_is_down', () => {
    // 2xx but body not notifications JSON (e.g. access gate password page) must not read as connected
    assert.equal(nextConnState('ok', 'bad_body'), 'down');
    assert.equal(nextConnState('down', 'bad_body'), 'down');
});


test('test_should_intercept_nav_truth_table', () => {
    for (const state of ['ok', 'down']) {
        for (const mode of ['client', 'local']) {
            for (const bridge of [true, false]) {
                const want = state === 'down' && mode === 'client' && bridge === true;
                assert.equal(shouldInterceptNav({ state, mode, hasOfflineBridge: bridge }), want);
            }
        }
    }
});

