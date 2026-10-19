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

test('test_cloud_branch_attaches_reason', async () => {
    const { state } = makeCardState('blocked');
    await assert.rejects(() => state._translateWithAILogic(), (err) => {
        assert.equal(err.reason, 'blocked');
        return true;
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

test('test_translate_all_counts_blocked_and_limited', async () => {
    await withGlobals(async () => {
        globalThis.fetch = fakeFetch([
            { success: true, result: '譯' },
            { success: false, reason: 'blocked' },
            { success: false, reason: 'rate_limited' },
        ]);
        const { state, toasts } = makeBatch();
        await state.translateAll();
        const [msg, type] = toasts[toasts.length - 1];
        assert.match(msg, /成功 1/);
        assert.match(msg, /失敗 2/);
        assert.match(msg, /（其中 1 片被翻譯服務的內容審查擋下，可改用其他翻譯服務）/);
        assert.match(msg, /（1 片遇到額度或限流，請稍後再試）/);
        assert.ok(msg.indexOf('內容審查') < msg.indexOf('額度或限流'), 'blocked 在前');
        assert.equal(type, 'warning');

        // 無 reason 的失敗只算 failed
        globalThis.fetch = fakeFetch([
            { success: false }, { success: false, reason: 'other' }, { success: true, result: '譯' },
        ]);
        const b = makeBatch();
        await b.state.translateAll();
        const m2 = b.toasts[b.toasts.length - 1][0];
        assert.match(m2, /失敗 2/);
        assert.ok(!m2.includes('（'), '無 reason 不附後綴');

        // 全成功：與 translate_batch_done 逐字相同
        globalThis.fetch = fakeFetch([
            { success: true, result: '譯' }, { success: true, result: '譯' }, { success: true, result: '譯' },
        ]);
        const c = makeBatch();
        await c.state.translateAll();
        const [m3, t3] = c.toasts[c.toasts.length - 1];
        assert.equal(m3, realT('search.toast.translate_batch_done', { success: 3, failed: 0 }));
        assert.equal(t3, 'success');
    });

    // translateAllSummary 純函式
    const t = (k, p) => `${k}:${JSON.stringify(p)}`;
    const s = provider.translateAllSummary(t, { success: 1, failed: 0, blocked: 0, limited: 0 });
    assert.equal(s, t('search.toast.translate_batch_done', { success: 1, failed: 0 }));
});
