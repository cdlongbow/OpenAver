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

for (const kind of ['file']) {
    test(`not_found 與 uncovered 用不同 key (${kind})`, () => {
        const a = run(NOT_FOUND, kind);
        assert.equal(a.ret, false);
        assert.deepEqual(a.calls, [['common.bridge.file_not_found|D:\\AV\\A.mp4', 'error']]);
        const b = run(UNCOVERED, kind);
        assert.equal(b.ret, false);
        assert.deepEqual(b.calls, [['common.bridge.path_uncovered_local|/srv/other/A.mp4', 'error']]);
    });

    const fb = kind === 'file' ? 'showcase.video.play_failed' : 'common.open_local.folder_open_failed';
    for (const [name, r] of [
        ['failed', { ok: false, reason: 'failed', local_path: 'x', server_path: 'y' }],
    ]) {
        test(`fallback: ${name} (${kind})`, () => {
            const { ret, calls } = run(r, kind);
            assert.equal(ret, false);
            assert.deepEqual(calls, [[fb, 'error']]);
        });
    }
}


test('handleBridgeUncovered 單筆一則、三筆仍一則（、連接）', () => {
    toastCalls.length = 0;
    handleBridgeUncovered(['\\\\nas\\x']);
    assert.deepEqual(toastCalls, [['common.bridge.path_uncovered_server_any|\\\\nas\\x', 'error']]);
    toastCalls.length = 0;
    handleBridgeUncovered(['/a', '/b', '/c']);
    assert.deepEqual(toastCalls, [['common.bridge.path_uncovered_server_any|/a、/b、/c', 'error']]);
});


