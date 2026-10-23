// TASK-146a-T4：空狀態四行說明 method 分支 ＋ loadAppConfig() 失敗隔離 oracle（CD-146a-17）
//
// 覆蓋：
//   - favoriteConfigured()：appConfig null／favorite_folder 空字串／只有空白／有值
//   - favoritePathDisplay()：window.pathToDisplay 存在與不存在
//   - namingPreviewExample()：createFolder 開/關、formatVariables 空/非空
//   - CD-146a-17 失敗隔離：format-variables reject／favorite-scanner-link reject／
//     favorite_folder 空時不呼叫 favorite-scanner-link

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {} };

if (typeof globalThis.requestAnimationFrame !== 'function') {
    globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
}

// state/__tests__ → 上一層 __tests__/alias-loader.mjs
register(new URL('../../__tests__/alias-loader.mjs', import.meta.url), import.meta.url);

const { searchStateEmptyExplainer } = await import('../empty-explainer.js');
const { searchStateSearchFlow } = await import('../search-flow.js');

function jsonResponse(data, { ok = true, status = 200 } = {}) {
    return {
        ok,
        status,
        json: async () => data,
    };
}

function mockFetch(handler) {
    const calls = [];
    globalThis.fetch = async (url, opts = {}) => {
        const u = String(url);
        calls.push(u);
        return handler(u, opts, calls);
    };
    return calls;
}

function makeExplainerThis(overrides = {}) {
    return {
        appConfig: null,
        formatVariables: [],
        favoriteScannerLinked: null,
        ...searchStateEmptyExplainer(),
        ...overrides,
    };
}

// ─── favoriteConfigured() ─────────────────────────────────────────────────


// ─── favoritePathDisplay() ────────────────────────────────────────────────


// ─── namingPreviewReady() ─────────────────────────────────────────────────
// CodeRabbit PR#187：這一列吃兩個各自獨立載入的輸入（CD-146a-17 失敗隔離），
// 四種組合在本次之前**零測試覆蓋**——`fc9667bc` 只擋了 appConfig 就是從這個縫掉出來的。
// 兩個輸入各自「未載入」時都必須 false，否則畫面會把沒替換的 `{num}`／`{actor}`
// 當成「你的檔案會被改成這樣」秀出來。


test('namingPreviewReady: 只有 appConfig 到（format-variables 失敗）→ false', () => {
    const state = makeExplainerThis({
        appConfig: { scraper: { filename_format: '{num} {title}', create_folder: false } },
        formatVariables: [],
    });
    assert.equal(
        state.namingPreviewReady.call(state), false,
        'formatVariables 空時若判成 ready，畫面會秀出未替換的 token 當作使用者的命名結果',
    );
});


// ─── namingPreviewExample() ───────────────────────────────────────────────


// ─── CD-146a-17 失敗隔離 oracle ───────────────────────────────────────────

test('loadAppConfig: format-variables reject → appConfig 仍設定、formatVariables 維持 []、不 reject', async () => {
    const calls = mockFetch((url) => {
        if (url === '/api/config') {
            return jsonResponse({
                success: true,
                data: { search: { favorite_folder: '/fav' }, scraper: {} },
            });
        }
        if (url === '/api/config/format-variables') {
            return Promise.reject(new Error('format-variables down'));
        }
        if (url.startsWith('/api/settings/favorite-scanner-link')) {
            return jsonResponse({ linked: true, matched_directory: '/fav' });
        }
        throw new Error('unexpected url: ' + url);
    });

    const state = {
        appConfig: null,
        formatVariables: [],
        favoriteScannerLinked: null,
        ...searchStateSearchFlow(),
    };

    await assert.doesNotReject(() => state.loadAppConfig.call(state));
    assert.ok(
        state.appConfig,
        'loadAppConfig() 在 format-variables 失敗時仍須設定 appConfig',
    );
    assert.equal(state.appConfig.search.favorite_folder, '/fav');
    assert.deepEqual(state.formatVariables, []);
    assert.ok(calls.some((u) => u === '/api/config'));
    assert.ok(calls.some((u) => u === '/api/config/format-variables'));
});


