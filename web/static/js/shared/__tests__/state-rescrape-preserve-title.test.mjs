import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
if (typeof globalThis.window.t !== 'function') {
    globalThis.window.t = (k) => k;
}

register(
    new URL('../../pages/search/__tests__/alias-loader.mjs', import.meta.url),
    import.meta.url,
);

const { rescrapeState, stripNumPrefixes } = await import('../state-rescrape.js');

// ── 1. stripNumPrefixes 邊界條件 ──

test('stripNumPrefixes: bracket 形式 [ABC-123]片名 剝除前綴', () => {
    assert.equal(stripNumPrefixes('[ABC-123]片名', 'ABC-123'), '片名');
});


// ── 2. rescrapeCurrentTitleStripped 方法 ──


// ── 3. rescrapeShowPreserveTitle 五組案例 ──

test('rescrapeShowPreserveTitle: 目前標題與 preview 標題不同且番號未變時回傳 true', () => {
    const fakeThis = {
        ...rescrapeState(),
        rescrapeEntryPoint: 'lightbox',
        rescrapeNumber: 'ABC-123',
        _rescrapeVideo: { title: '[ABC-123]中文片名', number: 'ABC-123' },
        rescrapePreview: { title: '日文片名', number: 'ABC-123' },
    };
    assert.equal(fakeThis.rescrapeShowPreserveTitle(), true);
});

test('rescrapeShowPreserveTitle: 目前標題與新標題剝完前綴相同時回傳 false', () => {
    const fakeThis = {
        ...rescrapeState(),
        rescrapeEntryPoint: 'lightbox',
        rescrapeNumber: 'ABC-123',
        _rescrapeVideo: { title: '[ABC-123]片名', number: 'ABC-123' },
        rescrapePreview: { title: '片名', number: 'ABC-123' },
    };
    assert.equal(fakeThis.rescrapeShowPreserveTitle(), false);
});


// ── 4. rescrapeConfirm payload 三種情境 ──

test('rescrapeConfirm payload: preserve_title 恆為 false 當 rescrapeShowPreserveTitle 為 false', async () => {
    let sentBody = null;
    const origFetch = globalThis.fetch;
    globalThis.fetch = async (_url, opts) => {
        sentBody = JSON.parse(opts.body);
        return { json: async () => ({ success: true }) };
    };

    try {
        const fakeThis = {
            ...rescrapeState(),
            _rescraping: false,
            rescrapeCfWaiting: false,
            rescrapeEntryPoint: 'lightbox',
            rescrapeNumber: 'XYZ-999', // 番號已改，rescrapeShowPreserveTitle() 為 false
            _rescrapeVideo: { path: '/media/test.mp4', number: 'ABC-123', title: '[ABC-123]片名' },
            rescrapePreview: { title: '新片名', url: 'http://test' },
            rescrapePreserveTitle: true, // 殘留或預設 true
            refreshVideoData: async () => {},
            showToast: () => {},
            closeRescrape: () => {},
        };

        await rescrapeState().rescrapeConfirm.call(fakeThis);

        assert.ok(sentBody, 'fetch 應被呼叫');
        assert.equal(sentBody.preserve_title, false, '可見條件為 false 時 preserve_title 必須為 false');
    } finally {
        globalThis.fetch = origFetch;
    }
});


test('rescrapeConfirm payload: rescrapeShowPreserveTitle 為 true 且勾選時為 true', async () => {
    let sentBody = null;
    const origFetch = globalThis.fetch;
    globalThis.fetch = async (_url, opts) => {
        sentBody = JSON.parse(opts.body);
        return { json: async () => ({ success: true }) };
    };

    try {
        const fakeThis = {
            ...rescrapeState(),
            _rescraping: false,
            rescrapeCfWaiting: false,
            rescrapeEntryPoint: 'lightbox',
            rescrapeNumber: 'ABC-123',
            _rescrapeVideo: { path: '/media/test.mp4', number: 'ABC-123', title: '[ABC-123]中文片名' },
            rescrapePreview: { title: '日文片名', url: 'http://test' },
            rescrapePreserveTitle: true, // 勾選
            refreshVideoData: async () => {},
            showToast: () => {},
            closeRescrape: () => {},
        };

        await rescrapeState().rescrapeConfirm.call(fakeThis);

        assert.ok(sentBody, 'fetch 應被呼叫');
        assert.equal(sentBody.preserve_title, true);
    } finally {
        globalThis.fetch = origFetch;
    }
});

// ── 5. openRescrape 狀態重設 ──


