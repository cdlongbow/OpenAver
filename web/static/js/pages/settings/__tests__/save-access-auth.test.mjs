// TASK-114a-T5：saveAccessAuth() 四條 reason 分流回歸鎖。
//
// 對照 T4 契約：
//   200 success            → settings.access_auth.saved (success)
//   400 invalid_pin        → settings.access_auth.pin_invalid (error)
//   403 remote_forbidden   → settings.server_info.remote_only (error)  // 複用既有 key
//   其他 / network throw   → settings.access_auth.save_failed (error)  // finally 還原 saving
//
// state-config.js 匯入瀏覽器 importmap 別名 `@/settings/...`（base.html 把
// `@/settings/` 指到 `/static/js/pages/settings/`，不是 `/static/js/settings/`）。
// 既有 alias-loader.mjs 只做 `@/` → `web/static/js/` 字首轉譯，對 `@/settings/`
// 會解成錯誤路徑；此檔自帶與 importmap 對齊的 resolve hook（不改共用 loader）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.t = (key) => key;  // identity mock：斷言時比對 key 字面即可

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
// 本檔：web/static/js/pages/settings/__tests__/ → 上三層 = web/static/js/
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

const { stateConfig } = await import('../state-config.js');

function makeFakeThis() {
    const toasts = [];
    return {
        ...stateConfig(),
        accessAuthEnabled: true,
        accessAuthPin: '1234',
        accessAuthSaving: false,
        showToast: (msg, type) => toasts.push({ msg, type }),
        _toasts: toasts,
    };
}

test('saveAccessAuth 成功 → .saved success toast', async () => {
    globalThis.fetch = async () => ({ json: async () => ({ success: true }) });
    const fakeThis = makeFakeThis();
    await fakeThis.saveAccessAuth.call(fakeThis);
    assert.deepEqual(fakeThis._toasts, [{ msg: 'settings.access_auth.saved', type: 'success' }]);
    assert.equal(fakeThis.accessAuthSaving, false);
});

test('saveAccessAuth PIN 格式錯誤（400 invalid_pin）→ .pin_invalid error toast', async () => {
    globalThis.fetch = async () => ({ json: async () => ({ success: false, reason: 'invalid_pin' }) });
    const fakeThis = makeFakeThis();
    await fakeThis.saveAccessAuth.call(fakeThis);
    assert.deepEqual(fakeThis._toasts, [{ msg: 'settings.access_auth.pin_invalid', type: 'error' }]);
    // 這條不是重複「成功路徑也驗過了」——`accessAuthSaving` 只在 finally 還原，
    // 而「resp 成功回傳但 result.success 為 false」是唯一**不經過 catch** 的失敗路徑。
    // 少了它，把 finally 拆成「成功分支 + catch 分支各還原一次」的重構會全綠通過，
    // 而使用者實際會遇到的是：PIN 打錯一次之後儲存鈕永久 disabled，只能重整頁面。
    assert.equal(fakeThis.accessAuthSaving, false);
});

test('saveAccessAuth 非本機（403 remote_forbidden）→ 複用 server_info.remote_only', async () => {
    globalThis.fetch = async () => ({ json: async () => ({ success: false, reason: 'remote_forbidden' }) });
    const fakeThis = makeFakeThis();
    await fakeThis.saveAccessAuth.call(fakeThis);
    assert.deepEqual(fakeThis._toasts, [{ msg: 'settings.server_info.remote_only', type: 'error' }]);
});

test('saveAccessAuth 未知 reason / network error → .save_failed error toast', async () => {
    globalThis.fetch = async () => { throw new Error('offline'); };
    const fakeThis = makeFakeThis();
    await fakeThis.saveAccessAuth.call(fakeThis);
    assert.deepEqual(fakeThis._toasts, [{ msg: 'settings.access_auth.save_failed', type: 'error' }]);
    assert.equal(fakeThis.accessAuthSaving, false);  // finally 區塊必須還原，即使 catch 路徑
});
