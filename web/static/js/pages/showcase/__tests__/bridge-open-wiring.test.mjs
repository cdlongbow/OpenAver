// 168a-T4: playVideo / openLocal 吃 bridge dict 的接線測試（真的走方法，this 綁假物件）。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.window.t = (key, params) => (params && params.path !== undefined ? `${key}|${params.path}` : key);
globalThis.Alpine = globalThis.Alpine || { store: () => ({ toolbarOpen: false, showcaseHasSearch: false }) };

const STATIC_JS_ROOT = pathToFileURL(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../') + '/',
).href;
const IMPORTMAP = {
    '@/settings/': 'pages/settings/', '@/shared/': 'shared/', '@/components/': 'components/',
    '@/search/': 'pages/search/', '@/showcase/': 'pages/showcase/', '@/scanner/': 'pages/scanner/',
};
const loaderCode = `
const IMPORTMAP = ${JSON.stringify(IMPORTMAP)};
const STATIC_JS_ROOT = ${JSON.stringify(STATIC_JS_ROOT)};
export async function resolve(specifier, context, nextResolve) {
    for (const [prefix, rel] of Object.entries(IMPORTMAP)) {
        if (specifier.startsWith(prefix)) {
            return nextResolve(STATIC_JS_ROOT + rel + specifier.slice(prefix.length), context);
        }
    }
    if (specifier.startsWith('@/')) return nextResolve(STATIC_JS_ROOT + specifier.slice(2), context);
    return nextResolve(specifier, context);
}
`;
register(`data:text/javascript,${encodeURIComponent(loaderCode)}`, import.meta.url);

const { stateVideos } = await import('../state-videos.js');
const { openLocal } = await import('@/shared/open-local.js');

const tick = () => new Promise((r) => setTimeout(r, 0));

function fakeThis() {
    const toasts = [];
    return { toasts, showToast: (m, t) => toasts.push([m, t]) };
}
function setApi(fn, name) {
    globalThis.window.pywebview = { api: { [name]: fn } };
}

const NF = { ok: false, reason: 'not_found', local_path: 'D:\\AV\\A.mp4', server_path: '/srv/A.mp4' };

test('playVideo 失敗 dict 顯示 toast', async () => {
    setApi(() => Promise.resolve(NF), 'open_file');
    const self = fakeThis();
    stateVideos().playVideo.call(self, 'x');
    await tick();
    assert.deepEqual(self.toasts, [['common.bridge.file_not_found|D:\\AV\\A.mp4', 'error']]);
});

test('playVideo ok:true 無 toast', async () => {
    setApi(() => Promise.resolve({ ok: true, reason: null }), 'open_file');
    const self = fakeThis();
    stateVideos().playVideo.call(self, 'x');
    await tick();
    assert.deepEqual(self.toasts, []);
});

test('playVideo reject 走既有 catch', async () => {
    setApi(() => Promise.reject(new Error('boom')), 'open_file');
    const err = console.error;
    console.error = () => {};
    const self = fakeThis();
    stateVideos().playVideo.call(self, 'x');
    await tick();
    console.error = err;
    assert.deepEqual(self.toasts, [['showcase.video.play_failed', 'error']]);
});

test('openLocal 具名原因贏（error toast 帶路徑）', async () => {
    setApi(() => Promise.resolve(NF), 'open_folder');
    const self = fakeThis();
    openLocal.call(self, 'D:\\AV\\A.mp4');
    await tick();
    assert.deepEqual(self.toasts, [['common.bridge.file_not_found|D:\\AV\\A.mp4', 'error']]);
});

test('openLocal ok:true 沿用成功分支', async () => {
    setApi(() => Promise.resolve({ ok: true, reason: null }), 'open_folder');
    const self = fakeThis();
    openLocal.call(self, 'D:\\AV\\A.mp4');
    await tick();
    assert.deepEqual(self.toasts, [['common.open_local.folder_opened', 'success']]);
});

test('openLocal failed 維持既有失敗文案', async () => {
    setApi(() => Promise.resolve({ ok: false, reason: 'failed' }), 'open_folder');
    const self = fakeThis();
    openLocal.call(self, 'D:\\AV\\A.mp4');
    await tick();
    assert.deepEqual(self.toasts, [['common.open_local.folder_open_failed', 'error']]);
});

test('openLocal reject 走既有 catch', async () => {
    setApi(() => Promise.reject(new Error('boom')), 'open_folder');
    const self = fakeThis();
    openLocal.call(self, 'D:\\AV\\A.mp4');
    await tick();
    assert.deepEqual(self.toasts, [['common.open_local.folder_open_failed', 'error']]);
});

function withClipboard(fn) {
    return async () => {
        Object.defineProperty(globalThis, 'navigator', {
            value: { clipboard: { writeText: () => Promise.resolve() } }, configurable: true, writable: true,
        });
        try { await fn(); } finally { delete globalThis.navigator; }
    };
}

test('openLocal 剪貼簿成功＋not_found：只有帶路徑 error toast、無「已複製」', withClipboard(async () => {
    setApi(() => Promise.resolve(NF), 'open_folder');
    const self = fakeThis();
    openLocal.call(self, 'D:\\AV\\A.mp4');
    await tick();
    assert.deepEqual(self.toasts, [['common.bridge.file_not_found|D:\\AV\\A.mp4', 'error']]);
}));

test('openLocal 剪貼簿成功＋ok:true：沿用既有成功文案', withClipboard(async () => {
    setApi(() => Promise.resolve({ ok: true, reason: null }), 'open_folder');
    const self = fakeThis();
    openLocal.call(self, 'D:\\AV\\A.mp4');
    await tick();
    assert.deepEqual(self.toasts, [['common.open_local.folder_opened_copied', 'success']]);
}));
