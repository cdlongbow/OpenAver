// 168b-T3: conn-state.js pure functions (node:test, no DOM).
import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
const { nextConnState, shouldInterceptNav } = await import('../conn-state.js');

test('test_next_conn_state_ok', () => {
    assert.equal(nextConnState('down', 'ok'), 'ok');
    assert.equal(nextConnState('ok', 'ok'), 'ok');
});

test('test_next_conn_state_error_is_down', () => {
    assert.equal(nextConnState('ok', 'error'), 'down');
    assert.equal(nextConnState('down', 'error'), 'down');
});

test('test_next_conn_state_not_ok_keeps_prev', () => {
    assert.equal(nextConnState('ok', 'not_ok'), 'ok');
    assert.equal(nextConnState('down', 'not_ok'), 'down');
    assert.equal(nextConnState('ok', 'weird'), 'ok');
});

test('test_should_intercept_nav_local_mode_never', () => {
    for (const bridge of [true, false]) {
        for (const state of ['ok', 'down']) {
            assert.equal(shouldInterceptNav({ state, mode: 'local', hasOfflineBridge: bridge }), false);
        }
    }
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

test('test_window_mount', () => {
    assert.equal(window.OpenAver.conn.nextConnState, nextConnState);
    assert.equal(window.OpenAver.conn.shouldInterceptNav, shouldInterceptNav);
});
