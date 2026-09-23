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

test('stripNumPrefixes: 空格分隔 ABC-123 片名 剝除前綴', () => {
    assert.equal(stripNumPrefixes('ABC-123 片名', 'ABC-123'), '片名');
});

test('stripNumPrefixes: 邊界 guard ABC-1234片名 不誤剝 ABC-123', () => {
    assert.equal(stripNumPrefixes('ABC-1234片名', 'ABC-123'), 'ABC-1234片名');
});

test('stripNumPrefixes: 特殊符號 FC2-PPV-123 片名 剝除前綴', () => {
    assert.equal(stripNumPrefixes('FC2-PPV-123 片名', 'FC2-PPV-123'), '片名');
});

test('stripNumPrefixes: 多層 fixpoint [ABC-123][ABC-123]片名 剝除前綴', () => {
    assert.equal(stripNumPrefixes('[ABC-123][ABC-123]片名', 'ABC-123'), '片名');
});

// ── 2. rescrapeCurrentTitleStripped 方法 ──

test('rescrapeCurrentTitleStripped: 正確剝除當前影片標題的番號前綴', () => {
    const fakeThis = {
        ...rescrapeState(),
        _rescrapeVideo: { title: '[ABC-123]目前片名', number: 'ABC-123' },
    };
    assert.equal(fakeThis.rescrapeCurrentTitleStripped(), '目前片名');
});

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

test('rescrapeShowPreserveTitle: 目前標題剝完為空字串時回傳 false', () => {
    const fakeThis = {
        ...rescrapeState(),
        rescrapeEntryPoint: 'lightbox',
        rescrapeNumber: 'ABC-123',
        _rescrapeVideo: { title: '[ABC-123]', number: 'ABC-123' },
        rescrapePreview: { title: '日文片名', number: 'ABC-123' },
    };
    assert.equal(fakeThis.rescrapeShowPreserveTitle(), false);
});

test('rescrapeShowPreserveTitle: 番號僅大小寫不同時仍視為未改', () => {
    const fakeThis = {
        ...rescrapeState(),
        rescrapeEntryPoint: 'lightbox',
        rescrapeNumber: 'abc-123',
        _rescrapeVideo: { title: '[ABC-123]中文片名', number: 'ABC-123' },
        rescrapePreview: { title: '日文片名', number: 'ABC-123' },
    };
    assert.equal(fakeThis.rescrapeShowPreserveTitle(), true);
});

test('rescrapeShowPreserveTitle: entryPoint 非 lightbox 或缺少必要資料時一律回傳 false', () => {
    const base = {
        ...rescrapeState(),
        rescrapeEntryPoint: 'search',
        rescrapeNumber: 'ABC-123',
        _rescrapeVideo: { title: '[ABC-123]中文片名', number: 'ABC-123' },
        rescrapePreview: { title: '日文片名', number: 'ABC-123' },
    };
    assert.equal(base.rescrapeShowPreserveTitle(), false, 'search 入口應回傳 false');

    const switchSource = { ...base, rescrapeEntryPoint: 'switch-source' };
    assert.equal(switchSource.rescrapeShowPreserveTitle(), false, 'switch-source 入口應回傳 false');

    const noVideo = { ...base, rescrapeEntryPoint: 'lightbox', _rescrapeVideo: null };
    assert.equal(noVideo.rescrapeShowPreserveTitle(), false, '缺少 _rescrapeVideo 應回傳 false');

    const noPreview = { ...base, rescrapeEntryPoint: 'lightbox', rescrapePreview: null };
    assert.equal(noPreview.rescrapeShowPreserveTitle(), false, '缺少 rescrapePreview 應回傳 false');
});

test('rescrapeShowPreserveTitle: preview 標題自帶番號前綴且剝完與目前相同時回傳 false', () => {
    const fakeThis = {
        ...rescrapeState(),
        rescrapeEntryPoint: 'lightbox',
        rescrapeNumber: 'ABC-123',
        _rescrapeVideo: { title: '[ABC-123]片名', number: 'ABC-123' },
        rescrapePreview: { title: 'ABC-123 片名', number: 'ABC-123' },
    };
    assert.equal(fakeThis.rescrapeShowPreserveTitle(), false);

    fakeThis.rescrapePreview = { title: '[ABC-123]片名', number: 'ABC-123' };
    assert.equal(fakeThis.rescrapeShowPreserveTitle(), false);
});

test('rescrapeShowPreserveTitle: 前綴大小寫與番號不同仍會被剝除', () => {
    const fakeThis = {
        ...rescrapeState(),
        rescrapeEntryPoint: 'lightbox',
        rescrapeNumber: 'ABC-123',
        _rescrapeVideo: { title: '[abc-123]片名', number: 'ABC-123' },
        rescrapePreview: { title: '片名', number: 'ABC-123' },
    };
    assert.equal(fakeThis.rescrapeShowPreserveTitle(), false);
    assert.equal(stripNumPrefixes('[abc-123]片名', 'ABC-123'), '片名');
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

test('rescrapeConfirm payload: rescrapeShowPreserveTitle 為 true 且使用者取消勾選時為 false', async () => {
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
            rescrapePreserveTitle: false, // 使用者取消勾選
            refreshVideoData: async () => {},
            showToast: () => {},
            closeRescrape: () => {},
        };

        await rescrapeState().rescrapeConfirm.call(fakeThis);

        assert.ok(sentBody, 'fetch 應被呼叫');
        assert.equal(sentBody.preserve_title, false);
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

test('openRescrape: 呼叫後 rescrapePreserveTitle 恆重設為 true（含連續開窗）', () => {
    const instance = {
        ...rescrapeState(),
    };

    assert.equal(instance.rescrapePreserveTitle, true, '初始預設值為 true');

    // 第一次開窗
    instance.openRescrape({ number: 'ABC-123', path: '/test.mp4' });
    assert.equal(instance.rescrapePreserveTitle, true, 'openRescrape 後為 true');

    // 使用者取消勾選
    instance.rescrapePreserveTitle = false;
    assert.equal(instance.rescrapePreserveTitle, false);

    // 第二次開窗，再次重設為 true
    instance.openRescrape({ number: 'ABC-123', path: '/test.mp4' });
    assert.equal(instance.rescrapePreserveTitle, true, '再次 openRescrape 應恢復為 true');
});

test('rescrapePreserveTitle: 同窗換來源重新 preview 不重設勾選', async () => {
    const origFetch = globalThis.fetch;
    globalThis.fetch = async (_url, _opts) => ({
        json: async () => ({ success: true, title: '新來源片名', number: 'ABC-123' }),
    });

    try {
        const instance = {
            ...rescrapeState(),
        };
        const video = { number: 'ABC-123', path: '/test.mp4', title: '原片名' };
        instance.openRescrape(video);
        assert.equal(instance.rescrapePreserveTitle, true, '開窗預設為 true');

        // 使用者取消勾選
        instance.rescrapePreserveTitle = false;

        // 模擬換來源：呼叫 rescrapeBackToPick 並透過 rescrapeWithSource 取得新 preview
        instance.rescrapeBackToPick();
        await instance.rescrapeWithSource('fanza');

        assert.ok(instance.rescrapePreview, '應成功取得 preview');
        assert.equal(instance.rescrapePreview.title, '新來源片名');
        assert.equal(instance.rescrapePreserveTitle, false, '換來源重新 preview 後不重設勾選');
    } finally {
        globalThis.fetch = origFetch;
    }
});
