/**
 * mask-kill-mechanism.test.mjs — Showcase ESM（149a-T4a）
 *
 * I-149a-2b/2c 窄 oracle：
 * 驗證 _maskStopSettleAnim() / _maskStopWaitAnim() 的 kill/stop 機制本身正確（純函式層級）。
 * 確保 kill/stop 被呼叫恰一次且內部 handle 歸零為 null。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;

register(new URL('../../search/__tests__/alias-loader.mjs', import.meta.url), import.meta.url);

const { stateLightboxMask } = await import('../state-lightbox-mask.js');

function makeComponent(overrides = {}) {
    return Object.assign({}, stateLightboxMask(), {
        $refs: {},
        currentLightboxVideo: { path: 'file:///test.mp4' },
        ...overrides,
    });
}

test('_maskStopSettleAnim: kill 被呼叫恰一次，_maskSettleTl 歸零', () => {
    let killCalls = 0;
    const fakeTl = {
        kill() {
            killCalls++;
        },
    };
    const c = makeComponent();
    c._maskSettleTl = fakeTl;

    c._maskStopSettleAnim();

    assert.equal(killCalls, 1, 'kill() 必須被呼叫恰一次');
    assert.equal(c._maskSettleTl, null, '_maskSettleTl 必須歸零為 null');
});

test('_maskStopWaitAnim: stopFocalDetectWait 被呼叫恰一次，_maskWaitTl 歸零', () => {
    let stopCalls = 0;
    let passedHandle = null;
    const fakeHandle = { id: 'wait_handle_1' };
    const prevGhostFly = globalThis.window.GhostFly;
    globalThis.window.GhostFly = {
        stopFocalDetectWait(handle) {
            stopCalls++;
            passedHandle = handle;
        },
    };
    try {
        const c = makeComponent();
        c._maskWaitTl = fakeHandle;

        c._maskStopWaitAnim();

        assert.equal(stopCalls, 1, 'stopFocalDetectWait 必須被呼叫恰一次');
        assert.equal(passedHandle, fakeHandle, '傳入 handle 必須一致');
        assert.equal(c._maskWaitTl, null, '_maskWaitTl 必須歸零為 null');
    } finally {
        if (prevGhostFly !== undefined) {
            globalThis.window.GhostFly = prevGhostFly;
        } else {
            delete globalThis.window.GhostFly;
        }
    }
});
