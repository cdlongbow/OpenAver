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


test('openLocal 具名原因贏（error toast 帶路徑）', async () => {
    setApi(() => Promise.resolve(NF), 'open_folder');
    const self = fakeThis();
    openLocal.call(self, 'D:\\AV\\A.mp4');
    await tick();
    assert.deepEqual(self.toasts, [['common.bridge.file_not_found|D:\\AV\\A.mp4', 'error']]);
});


// 168e-T4：剪貼簿 spy 會記錄每次寫入的內容
function withClipboardSpy(fn) {
    return async () => {
        const writes = [];
        Object.defineProperty(globalThis, 'navigator', {
            value: { clipboard: { writeText: (s) => { writes.push(s); return Promise.resolve(); } } },
            configurable: true, writable: true,
        });
        try { await fn(writes); } finally { delete globalThis.navigator; delete globalThis.window.pywebview; }
    };
}

test('openLocal bridge ok：剪貼簿是這台電腦的資料夾路徑', withClipboardSpy(async (writes) => {
    const cases = [
        ['D:\\av\\a\\b.mp4', 'D:\\av\\a'],
        ['/Volumes/av/a/b.mp4', '/Volumes/av/a'],
    ];
    for (const [localPath, expected] of cases) {
        writes.length = 0;
        setApi(() => Promise.resolve({ ok: true, reason: null, local_path: localPath, server_path: '/mnt/av/a/b.mp4' }), 'open_folder');
        const self = fakeThis();
        openLocal.call(self, '/mnt/av/a/b.mp4');
        await tick();
        assert.deepEqual(self.toasts, [['common.open_local.folder_opened_copied', 'success']]);
        assert.deepEqual(writes, [expected]);
    }
}));


test('openLocal 無 bridge：複製 pathToDisplay 後的資料夾', withClipboardSpy(async (writes) => {
    delete globalThis.window.pywebview;
    const self = fakeThis();
    openLocal.call(self, 'file:///C:/AV/A.mp4');
    await tick();
    assert.deepEqual(writes, ['C:\\AV']);
    assert.deepEqual(self.toasts, [['common.open_local.path_copied|C:\\AV', 'success']]);
}));
