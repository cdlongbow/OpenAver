import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import fs from 'node:fs';

globalThis.window = globalThis;
window.t = (k) => k;
globalThis.document = {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
};

register(new URL('./alias-loader.mjs', import.meta.url), import.meta.url);
const { searchStateResultCard } = await import('../state/result-card.js');
const { searchStateBatch } = await import('../state/batch.js');
const provider = await import('../../../shared/translate-provider.js');

const zh = JSON.parse(fs.readFileSync(new URL('../../../../../../locales/zh_TW.json', import.meta.url), 'utf8'));

// 真實 zh_TW 展開；缺 key 回 key 本身（斷言會紅）
function realT(key, params) {
    let v = key.split('.').reduce((o, k) => (o == null ? undefined : o[k]), zh);
    if (typeof v !== 'string') return key;
    for (const [k, val] of Object.entries(params || {})) v = v.replaceAll(`{${k}}`, String(val));
    return v;
}

async function withGlobals(fn) {
    const origT = window.t;
    const origFetch = globalThis.fetch;
    window.t = realT;
    try { return await fn(); } finally {
        window.t = origT;
        globalThis.fetch = origFetch;
    }
}

function makeCardState(reason) {
    const toasts = [];
    const state = {
        ...searchStateResultCard(),
        appConfig: { translate: { provider: 'gemini' } },
        listMode: 'search',
        currentIndex: 0,
        searchResults: [{ title: '日本語タイトル' }],
        isTranslating: false,
        hasJapanese: (t) => /[\u3040-\u30ff]/.test(t),
        saveState() {},
        showToast(msg, type) { toasts.push([msg, type]); },
        async translateWithOllama() {
            const r = { success: false, error: 'x' };
            if (reason !== undefined) r.reason = reason;
            return r;
        },
    };
    return { state, toasts };
}

test('test_failure_toast_key_by_reason', async () => {
    assert.equal(provider.translateFailureToastKey('blocked'), 'search.toast.translate_blocked');
    assert.equal(provider.translateFailureToastKey('rate_limited'), 'search.toast.translate_rate_limited');
    for (const r of ['other', undefined, null, 5, 'weird']) {
        assert.equal(provider.translateFailureToastKey(r), 'search.toast.translate_failed');
    }
    await withGlobals(async () => {
        const origErr = console.error;
        console.error = () => {};
        try {
            const cases = [
                ['blocked', 'search.toast.translate_blocked', 'error'],
                ['rate_limited', 'search.toast.translate_rate_limited', 'warning'],
                ['other', 'search.toast.translate_failed', 'error'],
                [undefined, 'search.toast.translate_failed', 'error'],
            ];
            for (const [reason, key, type] of cases) {
                const { state, toasts } = makeCardState(reason);
                await state.translateWithAI();
                assert.equal(toasts.length, 1);
                assert.equal(toasts[0][0], realT(key), `reason=${reason} 文案`);
                assert.notEqual(toasts[0][0], key, `${key} 必須存在於 zh_TW`);
                assert.equal(toasts[0][1], type, `reason=${reason} 型別`);
            }
        } finally { console.error = origErr; }
    });
});


function makeBatch(provider = 'ollama') {
    const toasts = [];
    const state = {
        ...searchStateBatch(),
        appConfig: { translate: { provider } },
        searchResults: [{ title: 'タイトルA' }, { title: 'タイトルB' }, { title: 'タイトルC' }],
        translateState: { isProcessing: false, isPaused: false, total: 0, processed: 0, success: 0, failed: 0 },
        hasJapanese: (t) => /[\u3040-\u30ff]/.test(t),
        showToast(msg, type) { toasts.push([msg, type]); },
        _getAbortSignal: () => undefined,
        _clearAbort() {},
    };
    return { state, toasts };
}

function fakeFetch(responses) {
    let i = 0;
    return async () => ({ json: async () => responses[i++] });
}

