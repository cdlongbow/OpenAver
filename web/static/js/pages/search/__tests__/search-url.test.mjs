// TASK-173-T9：buildSearchUrl 純函式（CD-173-10 URL 單一出口）
//
// 守住的行為：
//   - 關鍵字／片商 × stream／REST 四種形狀逐字
//   - 關鍵字 REST 的 offset／limit 未給就省略（不改既有模糊搜尋 URL）
//   - 片商名與寫法一律 encodeURIComponent，往返還原相等；spellings 順序＝輸入順序
//   - MAKER_PAGE_SIZE === 30

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildSearchUrl, MAKER_PAGE_SIZE } from '../search-url.js';

const MOODYZ = { key: 'moodyz', label: 'MOODYZ', spellings: ['MOODYZ', 'Moodyz'] };

test('keyword stream URL', () => {
    assert.equal(buildSearchUrl({ stream: true, query: 'SONE-205' }), '/api/search/stream?q=SONE-205');
});

test('maker stream URL', () => {
    assert.equal(
        buildSearchUrl({ stream: true, maker: MOODYZ }),
        '/api/search/stream?maker_key=moodyz&maker=MOODYZ&spellings=MOODYZ&spellings=Moodyz'
    );
});

test('keyword REST URL: offset/limit given vs omitted', () => {
    assert.equal(
        buildSearchUrl({ query: 'SONE-205', offset: 20, limit: 20 }),
        '/api/search?q=SONE-205&offset=20&limit=20'
    );
    assert.equal(buildSearchUrl({ query: 'SONE-205' }), '/api/search?q=SONE-205');
});

test('maker REST URL: offset always present', () => {
    assert.equal(
        buildSearchUrl({ maker: MOODYZ, offset: 30 }),
        '/api/search?maker_key=moodyz&maker=MOODYZ&spellings=MOODYZ&spellings=Moodyz&offset=30'
    );
    assert.equal(
        buildSearchUrl({ maker: MOODYZ }),
        '/api/search?maker_key=moodyz&maker=MOODYZ&spellings=MOODYZ&spellings=Moodyz&offset=0'
    );
    assert.match(buildSearchUrl({ maker: MOODYZ, offset: 30, limit: 30 }), /&offset=30&limit=30$/);
});

test('url-maker-encoded: special chars round-trip through searchParams', () => {
    const maker = {
        key: 'a&b/c#d',
        label: 'A&B/C#D 日本語　全形',
        spellings: ['X&Y', 'p/q#r', 'ＳＯＮＥ　１', '日本'],
    };
    for (const url of [
        buildSearchUrl({ stream: true, maker }),
        buildSearchUrl({ maker, offset: 0 }),
    ]) {
        const sp = new URL(url, 'http://x').searchParams;
        assert.equal(sp.get('maker_key'), maker.key);
        assert.equal(sp.get('maker'), maker.label);
        assert.deepEqual(sp.getAll('spellings'), maker.spellings);
    }
    const kw = new URL(buildSearchUrl({ stream: true, query: 'a&b#c 日本' }), 'http://x').searchParams;
    assert.equal(kw.get('q'), 'a&b#c 日本');
});

test('MAKER_PAGE_SIZE is 30', () => {
    assert.equal(MAKER_PAGE_SIZE, 30);
});

// ─── 175d-T7：cursor（不透明續頁 token；只在 REST 附加、附在所有既有參數之後）────────
test('url-cursor: keyword REST 附加在 offset／limit 之後；沒有 offset／limit 也附加', () => {
    assert.equal(
        buildSearchUrl({ query: 'SONE-205', offset: 20, limit: 20, cursor: 'tok' }),
        '/api/search?q=SONE-205&offset=20&limit=20&cursor=tok'
    );
    assert.equal(buildSearchUrl({ query: 'x', cursor: 'tok' }), '/api/search?q=x&cursor=tok');
});

test('url-cursor: maker REST 附加在 offset 之後', () => {
    assert.equal(
        buildSearchUrl({ maker: MOODYZ, offset: 30, cursor: 'tok' }),
        '/api/search?maker_key=moodyz&maker=MOODYZ&spellings=MOODYZ&spellings=Moodyz&offset=30&cursor=tok'
    );
});

test('url-cursor: stream 即使給 cursor 也不附加', () => {
    assert.equal(buildSearchUrl({ stream: true, query: 'SONE-205', cursor: 'tok' }), '/api/search/stream?q=SONE-205');
    assert.equal(
        buildSearchUrl({ stream: true, maker: MOODYZ, cursor: 'tok' }),
        '/api/search/stream?maker_key=moodyz&maker=MOODYZ&spellings=MOODYZ&spellings=Moodyz'
    );
});

test('url-cursor: null／undefined／空字串都不附加（URL 與沒給 cursor 逐字相同）', () => {
    const base = { query: 'SONE-205', offset: 20, limit: 20 };
    const plain = buildSearchUrl(base);
    for (const cursor of [null, undefined, '']) {
        assert.equal(buildSearchUrl({ ...base, cursor }), plain);
        assert.ok(!buildSearchUrl({ maker: MOODYZ, offset: 30, cursor }).includes('cursor='));
    }
});

test('url-cursor: 含 = & 空白 # % + 非 ASCII 的 token 經 searchParams 往返相等', () => {
    for (const raw of ['a=b&c d', '日本語/トークン#1', 'x+y%20z?', 'eyJ2IjoxfQ==']) {
        for (const url of [
            buildSearchUrl({ query: 'q', offset: 20, limit: 20, cursor: raw }),
            buildSearchUrl({ maker: MOODYZ, offset: 30, cursor: raw }),
        ]) {
            const sp = new URL(url, 'http://x').searchParams;
            assert.equal(sp.get('cursor'), raw);
            assert.equal(sp.getAll('cursor').length, 1);
        }
    }
});
