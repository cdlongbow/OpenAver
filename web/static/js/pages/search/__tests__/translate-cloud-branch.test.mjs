import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

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

function makeResultCardState(overrides = {}) {
    const translateWithOllamaCalls = [];
    const translateBatchCalls = [];

    const state = {
        ...searchStateResultCard(),
        listMode: 'search',
        currentIndex: 0,
        hasJapanese: (t) => /[-ゟ゠-ヿ]/.test(t),
        saveState() {},
        _addBatchTranslatingIndex() {},
        _deleteBatchTranslatingIndex() {},
        async translateWithOllama(text, mode, currentResult) {
            translateWithOllamaCalls.push({ text, mode, currentResult });
            return { success: true, result: '譯' };
        },
        async translateBatch(titles) {
            translateBatchCalls.push({ titles });
            return ['譯'];
        },
        ...overrides,
    };

    return { state, translateWithOllamaCalls, translateBatchCalls };
}

function makeBatchState(overrides = {}) {
    return {
        ...searchStateBatch(),
        translateState: {
            isPaused: false,
            isProcessing: false,
            total: 0,
            processed: 0,
            success: 0,
            failed: 0,
        },
        hasJapanese: (t) => /[-ゟ゠-ヿ]/.test(t),
        showToast() {},
        _getAbortSignal: () => undefined,
        _clearAbort() {},
        ...overrides,
    };
}

test('cloud providers translate only the current slice', async () => {
    for (const provider of ['gemini', 'openai', 'claude']) {
        const searchResults = [
            { title: 'テストA', translated_title: '已翻' },
            { title: 'テストB', translated_title: '' },
            { title: 'テストC', translated_title: '' },
        ];
        const { state, translateWithOllamaCalls, translateBatchCalls } = makeResultCardState({
            appConfig: { translate: { provider } },
            searchResults,
            currentIndex: 0,
        });

        await state._translateWithAILogic();

        assert.equal(translateWithOllamaCalls.length, 1, `provider ${provider} should call translateWithOllama once`);
        assert.equal(translateWithOllamaCalls[0].text, 'テストA', `provider ${provider} should translate current slice title`);
        assert.equal(translateBatchCalls.length, 0, `provider ${provider} should not call translateBatch`);
        assert.equal(searchResults[0].translated_title, '譯', `provider ${provider} should update current slice translated_title`);
        assert.equal(searchResults[1].translated_title, '', `provider ${provider} should not touch slice 1`);
    }
});

test('cloud providers wait 300ms between slices', async () => {
    const originalFetch = globalThis.fetch;
    const originalSetTimeout = globalThis.setTimeout;

    try {
        globalThis.fetch = async () => ({
            ok: true,
            json: async () => ({ success: true, result: '譯' }),
        });

        for (const provider of ['gemini', 'openai', 'claude']) {
            const delays = [];
            globalThis.setTimeout = (fn, ms) => {
                delays.push(ms);
                fn();
                return 0;
            };

            const searchResults = [
                { title: 'テストA', actors: [], number: 'A' },
                { title: 'テストB', actors: [], number: 'B' },
                { title: 'テストC', actors: [], number: 'C' },
            ];
            const state = makeBatchState({
                appConfig: { translate: { provider } },
                searchResults,
            });

            await state.translateAll();

            const delays300 = delays.filter(ms => ms === 300);
            assert.equal(delays300.length, 2, `provider ${provider} should wait 300ms exactly 2 times across 3 slices`);
        }
    } finally {
        globalThis.fetch = originalFetch;
        globalThis.setTimeout = originalSetTimeout;
    }
});

test('ollama or missing provider uses batch translation and skips translated items', async () => {
    const configs = [
        { translate: { provider: 'ollama' } },
        { translate: {} },
        undefined,
    ];

    for (const appConfig of configs) {
        const searchResults = [
            { title: 'テストA', translated_title: '已翻' },
            { title: 'テストB', translated_title: '' },
            { title: 'テストC', translated_title: '' },
        ];
        const { state, translateWithOllamaCalls, translateBatchCalls } = makeResultCardState({
            appConfig,
            searchResults,
            currentIndex: 0,
        });

        await state._translateWithAILogic();

        assert.equal(translateWithOllamaCalls.length, 0, 'should not call translateWithOllama in ollama/missing provider mode');
        assert.equal(translateBatchCalls.length, 1, 'should call translateBatch in ollama/missing provider mode');
        assert.deepEqual(translateBatchCalls[0].titles, ['テストB'], 'should translate first untranslated slice');
        assert.equal(searchResults[0].translated_title, '已翻', 'slice 0 should remain unchanged');
        assert.equal(searchResults[1].translated_title, '譯', 'slice 1 should be translated');
    }

    const originalFetch = globalThis.fetch;
    const originalSetTimeout = globalThis.setTimeout;
    try {
        globalThis.fetch = async () => ({
            ok: true,
            json: async () => ({ success: true, result: '譯' }),
        });

        for (const appConfig of configs) {
            const delays = [];
            globalThis.setTimeout = (fn, ms) => {
                delays.push(ms);
                fn();
                return 0;
            };

            const searchResults = [
                { title: 'テストA', actors: [], number: 'A' },
                { title: 'テストB', actors: [], number: 'B' },
                { title: 'テストC', actors: [], number: 'C' },
            ];
            const state = makeBatchState({
                appConfig,
                searchResults,
            });

            await state.translateAll();

            const delays300 = delays.filter(ms => ms === 300);
            assert.equal(delays300.length, 0, 'ollama or missing provider should have 0 300ms delays');
        }
    } finally {
        globalThis.fetch = originalFetch;
        globalThis.setTimeout = originalSetTimeout;
    }
});

test('all items already translated throws no_japanese_title in ollama mode', async () => {
    const searchResults = [
        { title: 'テストA', translated_title: '已翻A' },
        { title: 'テストB', translated_title: '已翻B' },
        { title: 'テストC', translated_title: '已翻C' },
    ];
    const { state } = makeResultCardState({
        appConfig: { translate: { provider: 'ollama' } },
        searchResults,
        currentIndex: 0,
    });

    await assert.rejects(
        async () => {
            await state._translateWithAILogic();
        },
        (err) => {
            assert.equal(err.message, 'search.error.no_japanese_title');
            return true;
        }
    );
});
