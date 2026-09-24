// TASK-155a-T1: card-actor-age-refresh.test.mjs
// _recomputeCardActorAges 單元行為、updatePagination() 兩分支寫入、refreshVideoData() 同步更新卡片年齡

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;

globalThis.document = {
    querySelector() { return null; },
    body: {
        classList: {
            remove() {},
            add() {},
            contains() { return false; },
        },
    },
};

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
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

const { _recomputeCardActorAges, _setActresses, _setFilteredVideos } = await import('@/showcase/state-base.js');
const { stateVideos } = await import('../state-videos.js');
const { stateLightbox } = await import('../state-lightbox.js');

test('_recomputeCardActorAges 單元行為：falsy 安全退出、正確為 video 寫入 _cardActorAges', () => {
    // 1. falsy 不拋錯
    assert.doesNotThrow(() => _recomputeCardActorAges(null));
    assert.doesNotThrow(() => _recomputeCardActorAges(undefined));

    // 2. 設置收藏女優
    _setActresses([
        { name: '柚木ティナ', birth: '1986-10-29' },
    ]);

    const video = {
        actresses: '柚木ティナ',
        release_date: '2020-01-15',
        duration: 120,
    };
    _recomputeCardActorAges(video);
    assert.deepStrictEqual(video._cardActorAges, {
        '柚木ティナ': 33,
    });
});

test('updatePagination() 對 paginatedVideos 每一筆寫入 _cardActorAges', () => {
    _setActresses([
        { name: '柚木ティナ', birth: '1986-10-29' },
        { name: '安齋らら', birth: '1993-12-03' },
    ]);

    const v1 = { id: 1, actresses: '柚木ティナ', release_date: '2020-01-15', duration: 120 };
    const v2 = { id: 2, actresses: '安齋らら', release_date: '2020-01-15', duration: 120 };
    const v3 = { id: 3, actresses: '柚木ティナ, 安齋らら', release_date: '2020-01-15', duration: 120 };

    _setFilteredVideos([v1, v2, v3]);

    const comp = stateVideos();
    comp.mode = 'grid';

    // 1. perPage > 0（一般分頁，例如 perPage = 2）
    comp.perPage = 2;
    comp.page = 1;
    comp.updatePagination();

    assert.strictEqual(comp.paginatedVideos.length, 2);
    assert.deepStrictEqual(comp.paginatedVideos[0]._cardActorAges, { '柚木ティナ': 33 });
    assert.deepStrictEqual(comp.paginatedVideos[1]._cardActorAges, { '安齋らら': 26 });

    // 2. perPage = 0 分支（非 grid 模式下 perPage=0 為顯示全部）
    comp.mode = 'list';
    comp.perPage = 0;
    comp.updatePagination();

    assert.strictEqual(comp.paginatedVideos.length, 3);
    assert.deepStrictEqual(comp.paginatedVideos[0]._cardActorAges, { '柚木ティナ': 33 });
    assert.deepStrictEqual(comp.paginatedVideos[1]._cardActorAges, { '安齋らら': 26 });
    assert.deepStrictEqual(comp.paginatedVideos[2]._cardActorAges, {
        '柚木ティナ': 33,
        '安齋らら': 26,
    });
});

test('refreshVideoData 補資料後同步更新卡片年齡', async () => {
    _setActresses([
        { name: '柚木ティナ', birth: '1986-10-29' },
    ]);

    const video = {
        path: '/media/video1.mp4',
        actresses: '',
        release_date: '2020-01-15',
        duration: 120,
    };
    _recomputeCardActorAges(video);
    assert.deepStrictEqual(video._cardActorAges, {});

    // Mock fetch 回傳更新後的 video 資料
    const originalFetch = globalThis.fetch;
    try {
        globalThis.fetch = async (url) => {
            if (String(url).includes('/api/showcase/video')) {
                return {
                    ok: true,
                    json: async () => ({
                        success: true,
                        video: {
                            actresses: '柚木ティナ',
                            release_date: '2020-01-15',
                            duration: 120,
                        },
                    }),
                };
            }
            return { ok: false };
        };

        const comp = stateLightbox();
        // 刻意讓 currentLightboxVideo 不是 video，驗證燈箱不在該片時仍同步更新卡片年齡
        comp.currentLightboxVideo = null;

        await comp.refreshVideoData(video);

        // video._cardActorAges 必須被更新
        assert.deepStrictEqual(video._cardActorAges, {
            '柚木ティナ': 33,
        });
    } finally {
        globalThis.fetch = originalFetch;
    }
});
