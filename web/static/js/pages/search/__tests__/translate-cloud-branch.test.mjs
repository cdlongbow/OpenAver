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


