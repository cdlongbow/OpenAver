// TASK-D7：setFocalDeviceDisabled() 失敗 toast + await 前快照回滾。
//
// 對照契約：
//   success true            → 無 toast；checkbox 維持送出後狀態；body.value = !checked
//   success false           → settings.scraper.focal_toggle_failed (error) + 回滾到按之前
//   fetch reject            → 同上
//   await 中途再點一下失敗  → 仍回滾到「這一次送出前」的狀態（不是回應當下的 DOM）
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
        showToast: (msg, type) => toasts.push({ msg, type }),
        _toasts: toasts,
    };
}

function makeCheckbox(checked) {
    return { checked };
}

test('setFocalDeviceDisabled 成功（關掉開關）→ body.value=true、無 toast、不回滾', async () => {
    // 使用者把開關關掉：click 後 checked=false → disabled=true
    let sentBody = null;
    globalThis.fetch = async (_url, opts) => {
        sentBody = opts.body;
        return { json: async () => ({ success: true }) };
    };
    const fakeThis = makeFakeThis();
    const checkbox = makeCheckbox(false);
    await fakeThis.setFocalDeviceDisabled.call(fakeThis, { target: checkbox });
    assert.equal(sentBody, JSON.stringify({ value: true }));
    assert.deepEqual(fakeThis._toasts, []);
    assert.equal(checkbox.checked, false);
});

test('setFocalDeviceDisabled success:false → error toast + checkbox 回到按之前', async () => {
    // 使用者關掉（click 後 false）；失敗應退回按之前的 true
    globalThis.fetch = async () => ({ json: async () => ({ success: false, error: 'disk' }) });
    const fakeThis = makeFakeThis();
    const checkbox = makeCheckbox(false);
    await fakeThis.setFocalDeviceDisabled.call(fakeThis, { target: checkbox });
    assert.deepEqual(fakeThis._toasts, [
        { msg: 'settings.scraper.focal_toggle_failed', type: 'error' },
    ]);
    assert.equal(checkbox.checked, true);
});

test('setFocalDeviceDisabled fetch reject → error toast + checkbox 回到按之前', async () => {
    globalThis.fetch = async () => { throw new Error('offline'); };
    const fakeThis = makeFakeThis();
    const checkbox = makeCheckbox(false);
    await fakeThis.setFocalDeviceDisabled.call(fakeThis, { target: checkbox });
    assert.deepEqual(fakeThis._toasts, [
        { msg: 'settings.scraper.focal_toggle_failed', type: 'error' },
    ]);
    assert.equal(checkbox.checked, true);
});

// ── await 前快照：飛行途中再點一下，失敗仍回滾到送出前 ───────────────────────
//
// 不修的話：回滾讀的是回應到達當下的 DOM（!event.target.checked），飛行途中再點
// 一次會把開關撥到錯的位置，與 server 不一致。

test('setFocalDeviceDisabled 飛行途中再點、失敗 → checkbox 落在送出前狀態', async () => {
    // 送出：關掉（click 後 false）；飛行中使用者又點回 true；失敗應仍回到送出前的 true
    const fakeThis = makeFakeThis();
    const checkbox = makeCheckbox(false);
    globalThis.fetch = async () => {
        checkbox.checked = true;  // 回應抵達前，使用者又點了一下
        return { json: async () => ({ success: false, error: 'disk' }) };
    };
    await fakeThis.setFocalDeviceDisabled.call(fakeThis, { target: checkbox });
    assert.deepEqual(fakeThis._toasts, [
        { msg: 'settings.scraper.focal_toggle_failed', type: 'error' },
    ]);
    assert.equal(checkbox.checked, true,
        '應回到送出前（按關掉之前）的 true，不是 !回應當下');
});
