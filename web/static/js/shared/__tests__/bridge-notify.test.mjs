// 168a-T4: bridge-notify.js 純函式＋hook 測試（node:test，無 DOM）。
// window.t / Alpine 皆 stub；t 回傳 `key|path` 讓斷言同時看得到 key 與 {path} 參數。
import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
globalThis.window.t = (key, params) => (params && params.path !== undefined ? `${key}|${params.path}` : key);

const toastCalls = [];
globalThis.Alpine = { store: () => ({ show: (m, t) => toastCalls.push([m, t]) }) };

const { notifyOpenResult, bridgeReasonMessage, handleBridgeUncovered } = await import('../bridge-notify.js');

function run(result, kind) {
    const calls = [];
    const ret = notifyOpenResult((m, t) => calls.push([m, t]), result, kind);
    return { ret, calls };
}

// local_path 與 server_path 刻意給不同值（BE-TEST-11），uncovered 的 local_path 為 null（真實契約）
const NOT_FOUND = { ok: false, reason: 'not_found', local_path: 'D:\\AV\\A.mp4', server_path: '/srv/av/A.mp4' };
const NOT_VIDEO = { ok: false, reason: 'not_video', local_path: 'D:\\AV\\A.txt', server_path: '/srv/av/A.txt' };
const UNCOVERED = { ok: false, reason: 'uncovered', local_path: null, server_path: '/srv/other/A.mp4' };

for (const kind of ['file', 'folder']) {
    test(`not_found 與 uncovered 用不同 key (${kind})`, () => {
        const a = run(NOT_FOUND, kind);
        assert.equal(a.ret, false);
        assert.deepEqual(a.calls, [['common.bridge.file_not_found|D:\\AV\\A.mp4', 'error']]);
        const b = run(UNCOVERED, kind);
        assert.equal(b.ret, false);
        assert.deepEqual(b.calls, [['common.bridge.path_uncovered_local|/srv/other/A.mp4', 'error']]);
    });

    test(`not_video 顯示 local_path (${kind})`, () => {
        assert.deepEqual(run(NOT_VIDEO, kind).calls, [['common.bridge.not_video|D:\\AV\\A.txt', 'error']]);
    });

    const fb = kind === 'file' ? 'showcase.video.play_failed' : 'common.open_local.folder_open_failed';
    for (const [name, r] of [
        ['failed', { ok: false, reason: 'failed', local_path: 'x', server_path: 'y' }],
        ['untrusted', { ok: false, reason: 'untrusted', local_path: null, server_path: null }],
        ['null reason', { ok: false, reason: null, local_path: 'x', server_path: 'y' }],
        ['undefined', undefined],
        ['null', null],
        ['舊 bool true', true],
        ['舊 bool false', false],
        ['空物件', {}],
        ['not_found 缺 local_path', { ok: false, reason: 'not_found', local_path: null, server_path: 's' }],
        ['not_video 缺 local_path', { ok: false, reason: 'not_video', local_path: null }],
        ['uncovered 缺 server_path', { ok: false, reason: 'uncovered', local_path: 'l', server_path: null }],
    ]) {
        test(`fallback: ${name} (${kind})`, () => {
            const { ret, calls } = run(r, kind);
            assert.equal(ret, false);
            assert.deepEqual(calls, [[fb, 'error']]);
        });
    }
}

test('ok:true 不顯示 toast 且回傳 true', () => {
    const { ret, calls } = run({ ok: true, reason: null, local_path: 'a', server_path: 'b' }, 'file');
    assert.equal(ret, true);
    assert.deepEqual(calls, []);
});

test('uncovered 顯示 server_path', () => {
    for (const kind of ['file', 'folder']) {
        const { calls } = run(UNCOVERED, kind);
        assert.equal(calls.length, 1);
        assert.equal(calls[0][0], 'common.bridge.path_uncovered_local|/srv/other/A.mp4');
        assert.ok(calls[0][0].includes(UNCOVERED.server_path));
    }
});

test('bridgeReasonMessage 只對具名原因回字串', () => {
    assert.equal(bridgeReasonMessage(NOT_FOUND), 'common.bridge.file_not_found|D:\\AV\\A.mp4');
    assert.equal(bridgeReasonMessage({ ok: false, reason: 'failed' }), null);
    assert.equal(bridgeReasonMessage(true), null);
    assert.equal(bridgeReasonMessage(null), null);
});

test('handleBridgeUncovered 空／非陣列不動作', () => {
    toastCalls.length = 0;
    handleBridgeUncovered([]);
    handleBridgeUncovered(null);
    handleBridgeUncovered('x');
    handleBridgeUncovered(undefined);
    assert.equal(toastCalls.length, 0);
});

test('handleBridgeUncovered 單筆一則、三筆仍一則（、連接）', () => {
    toastCalls.length = 0;
    handleBridgeUncovered(['\\\\nas\\x']);
    assert.deepEqual(toastCalls, [['common.bridge.path_uncovered_server|\\\\nas\\x', 'error']]);
    toastCalls.length = 0;
    handleBridgeUncovered(['/a', '/b', '/c']);
    assert.deepEqual(toastCalls, [['common.bridge.path_uncovered_server|/a、/b、/c', 'error']]);
});

test('handleBridgeUncovered 用 server 方向的 key', () => {
    toastCalls.length = 0;
    handleBridgeUncovered(['/a']);
    assert.equal(toastCalls.length, 1);
    assert.ok(toastCalls[0][0].startsWith('common.bridge.path_uncovered_server|'));
    assert.ok(!toastCalls[0][0].startsWith('common.bridge.path_uncovered_local'));
});

test('handleBridgeUncovered Alpine 未就緒不拋錯', () => {
    const saved = globalThis.Alpine;
    globalThis.Alpine = undefined;
    const warn = console.warn;
    console.warn = () => {};
    try {
        assert.doesNotThrow(() => handleBridgeUncovered(['/a']));
    } finally {
        console.warn = warn;
        globalThis.Alpine = saved;
    }
});

test('載入時掛上 window.handleBridgeUncovered', () => {
    assert.equal(window.handleBridgeUncovered, handleBridgeUncovered);
});
