// TASK-D4: openMask SSR skip + reason → toast（CD-152d-4b）
// harness 照抄 lb-tag-readonly-toast.test.mjs；另 stub DOM 幾何 API（假綠陷阱②③）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;
// openMask 在 detect 路徑會掛 resize listener；node:test 無 DOM EventTarget。
if (typeof globalThis.window.addEventListener !== 'function') {
    globalThis.window.addEventListener = () => {};
}
if (typeof globalThis.window.removeEventListener !== 'function') {
    globalThis.window.removeEventListener = () => {};
}

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
const STATIC_JS_ROOT = pathToFileURL(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../') + '/',
).href;

const loaderCode = `
const IMPORTMAP = ${JSON.stringify(IMPORTMAP)};
const STATIC_JS_ROOT = ${JSON.stringify(STATIC_JS_ROOT)};
export async function resolve(specifier, context, nextResolve) {
    for (const [prefix, rel] of Object.entries(IMPORTMAP)) {
        if (specifier.startsWith(prefix)) {
            return nextResolve(STATIC_JS_ROOT + rel + specifier.slice(prefix.length), context);
        }
    }
    if (specifier.startsWith('@/')) {
        return nextResolve(STATIC_JS_ROOT + specifier.slice(2), context);
    }
    return nextResolve(specifier, context);
}
`;
register(`data:text/javascript,${encodeURIComponent(loaderCode)}`, import.meta.url);

const { stateLightboxMask } = await import('../state-lightbox-mask.js');

const AUTO_DISABLED_KEY = 'showcase.lightbox.mask_focal_too_slow_auto_disabled';
const HINT_KEY = 'showcase.lightbox.mask_focal_too_slow_hint';
const FAILED_KEY = 'showcase.lightbox.mask_detect_failed';

function mockFetch(payload) {
    const calls = [];
    const prev = globalThis.fetch;
    globalThis.fetch = async (...args) => {
        calls.push(args);
        return {
            ok: true,
            status: 200,
            json: async () => payload,
        };
    };
    return {
        calls,
        restore() { globalThis.fetch = prev; },
    };
}

function makeComponent(overrides = {}) {
    const toasts = [];
    const imgEl = {
        naturalWidth: 100,
        getBoundingClientRect: () => ({ width: 100, height: 150 }),
        closest: () => null,
    };
    const c = Object.assign({}, stateLightboxMask(), {
        _lbFullLoaded: true,
        currentLightboxVideo: { path: 'file:///test.mp4' },
        currentLightboxActress: null,
        $refs: { lightboxCoverFull: imgEl },
        toasts,
        showToast(msg, kind) { toasts.push({ msg, kind }); },
    }, overrides);
    return c;
}

function withGeometryStub(fn) {
    const prev = globalThis.getComputedStyle;
    globalThis.getComputedStyle = () => ({ getPropertyValue: () => '0.667' });
    return (async () => {
        try {
            return await fn();
        } finally {
            if (prev === undefined) {
                delete globalThis.getComputedStyle;
            } else {
                globalThis.getComputedStyle = prev;
            }
        }
    })();
}

test('openMask: SSR focal_auto_enabled=false skips fetch entirely', async () => {
    await withGeometryStub(async () => {
        const prevFlag = globalThis.window.__FOCAL_AUTO_ENABLED__;
        const prevFetch = globalThis.fetch;
        let fetchCalled = false;
        globalThis.window.__FOCAL_AUTO_ENABLED__ = false;
        globalThis.fetch = async () => {
            fetchCalled = true;
            assert.fail('fetch must not be called when __FOCAL_AUTO_ENABLED__ === false');
        };
        try {
            const c = makeComponent();
            await c.openMask();
            assert.equal(fetchCalled, false, 'fetch must not be called');
            assert.equal(c._maskVisible, true, 'mask must still open for manual drag');
        } finally {
            globalThis.fetch = prevFetch;
            if (prevFlag === undefined) {
                delete globalThis.window.__FOCAL_AUTO_ENABLED__;
            } else {
                globalThis.window.__FOCAL_AUTO_ENABLED__ = prevFlag;
            }
        }
    });
});

test('openMask: reason=too_slow_auto_disabled shows auto-disabled toast', async () => {
    await withGeometryStub(async () => {
        const mock = mockFetch({
            success: true,
            auto_focal: '',
            reason: 'too_slow_auto_disabled',
            cover_path: 'file:///cover.jpg',
        });
        try {
            const c = makeComponent();
            await c.openMask();
            assert.ok(
                c.toasts.some((t) => t.msg === AUTO_DISABLED_KEY && t.kind === 'info'),
                `expected ${AUTO_DISABLED_KEY}/info, got ${JSON.stringify(c.toasts)}`,
            );
            assert.equal(
                c.toasts.filter((t) => t.msg === HINT_KEY).length,
                0,
                'must not also show the suggestion toast',
            );
        } finally {
            mock.restore();
        }
    });
});

test('openMask: reason=too_slow shows suggestion toast (different text than auto_disabled)', async () => {
    await withGeometryStub(async () => {
        const mock = mockFetch({
            success: true,
            auto_focal: '',
            reason: 'too_slow',
            cover_path: 'file:///cover.jpg',
        });
        try {
            const c = makeComponent();
            await c.openMask();
            assert.ok(
                c.toasts.some((t) => t.msg === HINT_KEY && t.kind === 'info'),
                `expected ${HINT_KEY}/info, got ${JSON.stringify(c.toasts)}`,
            );
            assert.equal(
                c.toasts.filter((t) => t.msg === AUTO_DISABLED_KEY).length,
                0,
                'must not show the auto-disabled toast for too_slow',
            );
            assert.notEqual(HINT_KEY, AUTO_DISABLED_KEY);
        } finally {
            mock.restore();
        }
    });
});

test('openMask: reason=failed shows existing mask_detect_failed toast in success branch', async () => {
    await withGeometryStub(async () => {
        const mock = mockFetch({
            success: true,
            auto_focal: '',
            reason: 'failed',
            cover_path: 'file:///cover.jpg',
        });
        try {
            const c = makeComponent();
            await c.openMask();
            assert.ok(
                c.toasts.some((t) => t.msg === FAILED_KEY && t.kind === 'error'),
                `expected ${FAILED_KEY}/error, got ${JSON.stringify(c.toasts)}`,
            );
        } finally {
            mock.restore();
        }
    });
});

test('openMask: reason=device_disabled stays silent (no toast)', async () => {
    await withGeometryStub(async () => {
        const mock = mockFetch({
            success: true,
            auto_focal: '',
            reason: 'device_disabled',
            cover_path: 'file:///cover.jpg',
        });
        try {
            const c = makeComponent();
            await c.openMask();
            assert.equal(
                c.toasts.length,
                0,
                `device_disabled must not toast, got ${JSON.stringify(c.toasts)}`,
            );
            assert.ok(mock.calls.length >= 1, 'fetch should still be sent when SSR flag is unset');
        } finally {
            mock.restore();
        }
    });
});
