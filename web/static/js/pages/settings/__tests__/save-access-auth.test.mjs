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
        accessAuthEnabled: true,       // 草稿：使用者已勾選「需要密碼」
        accessAuthEnabledSaved: false, // 後端真實狀態：還沒有任何保護
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

// ── Codex PR#129 P2：安全宣稱不得跟著未提交草稿走 ────────────────────────────
//
// 畫面上有兩處會對使用者說「其他裝置需要輸入密碼才能連入」（「?」說明與伺服器模式
// 切換確認框）。它們讀 `accessAuthEnabledSaved`，不讀草稿 `accessAuthEnabled`。
// 下面四支鎖住「只有真的存成功才准推進已生效值」——破了的後果不是顯示瑕疵：
// 使用者勾了密碼、存檔失敗（磁碟寫入失敗，或從手機按存檔吃到 403），畫面卻一路
// 宣稱「已設定密碼保護」直到重新整理，而區網其實整個是開的。
//
// 對應模板側的兩條 [lint-guard:114a-T7fix] 靜態守衛（那兩條管「誰在讀」，
// 這四支管「什麼時候可以寫」）。

test('saveAccessAuth 成功 → accessAuthEnabledSaved 推進到草稿值', async () => {
    globalThis.fetch = async () => ({ json: async () => ({ success: true }) });
    const fakeThis = makeFakeThis();
    await fakeThis.saveAccessAuth.call(fakeThis);
    assert.equal(fakeThis.accessAuthEnabledSaved, true);
});

test('saveAccessAuth 400 invalid_pin → accessAuthEnabledSaved 不動（草稿保留）', async () => {
    globalThis.fetch = async () => ({ json: async () => ({ success: false, reason: 'invalid_pin' }) });
    const fakeThis = makeFakeThis();
    await fakeThis.saveAccessAuth.call(fakeThis);
    assert.equal(fakeThis.accessAuthEnabledSaved, false);
    // 草稿刻意不還原：使用者剛打的東西不該因為一次失敗就被清掉。
    assert.equal(fakeThis.accessAuthEnabled, true);
    assert.equal(fakeThis.accessAuthPin, '1234');
});

test('saveAccessAuth 403 remote_forbidden → accessAuthEnabledSaved 不動', async () => {
    globalThis.fetch = async () => ({ json: async () => ({ success: false, reason: 'remote_forbidden' }) });
    const fakeThis = makeFakeThis();
    await fakeThis.saveAccessAuth.call(fakeThis);
    assert.equal(fakeThis.accessAuthEnabledSaved, false);
});

test('saveAccessAuth network error → accessAuthEnabledSaved 不動', async () => {
    globalThis.fetch = async () => { throw new Error('offline'); };
    const fakeThis = makeFakeThis();
    await fakeThis.saveAccessAuth.call(fakeThis);
    assert.equal(fakeThis.accessAuthEnabledSaved, false);
});
