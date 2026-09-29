import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateBatch } from '../state/batch.js';

globalThis.window = globalThis;
globalThis.document = globalThis.document || { querySelectorAll: () => [] };

async function scrapeWithResult(payload) {
    const file = {
        filename: 'ABC-123.mp4',
        searchResults: [{ number: 'ABC-123', title: 'Title' }],
        selectedCandidateIndex: 0,
        chineseTitle: '',
    };
    const toasts = [];
    const translations = [];
    globalThis.fetch = async () => ({ json: async () => payload });
    window.SearchFile = { scrapeFile: async () => (await fetch('/api/scrape-single')).json() };
    window.t = (key, params) => {
        translations.push({ key, params });
        return key;
    };
    const state = {
        ...searchStateBatch(),
        fileList: [file],
        listMode: 'file',
        currentFileIndex: 0,
        currentIndex: 0,
        appConfig: null,
        showToast(message, type) { toasts.push({ message, type }); },
        $nextTick() {},
    };

    await state.scrapeSingle(0);
    return { file, toasts, translations };
}

test('scrapeSingle: 後端失敗原因出現在單檔整理 toast', async () => {
    const { file, toasts, translations } = await scrapeWithResult({ success: false, error: 'X' });

    assert.deepEqual(translations, [{
        key: 'search.toast.scrape_failed_reason',
        params: { filename: 'ABC-123.mp4', reason: 'X' },
    }]);
    assert.deepEqual(toasts, [{ message: 'search.toast.scrape_failed_reason', type: 'error' }]);
    assert.equal(file.scrapeStatus, 'failed');
});

test('scrapeSingle: 後端未提供原因時維持原 toast', async () => {
    const { toasts, translations } = await scrapeWithResult({ success: false });

    assert.deepEqual(translations, [{
        key: 'search.toast.scrape_failed',
        params: { filename: 'ABC-123.mp4' },
    }]);
    assert.deepEqual(toasts, [{ message: 'search.toast.scrape_failed', type: 'error' }]);
});
