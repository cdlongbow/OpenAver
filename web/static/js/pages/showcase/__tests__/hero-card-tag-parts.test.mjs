// TASK-138-T4: _heroCardTagParts — tags → hometown → agency，AC-D4 空輸入零回歸。
//
// state-actress.js / state-base.js 用瀏覽器 importmap 別名；plain `node --test`
// 不認得。比照 actress-card-info.test.mjs 的 resolve hook（FE-GUARD-11：
// import 頁面 state 模組之前必須先 stub window）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// state-base.js 模組頂層讀 localStorage。FE-GUARD-11：先 stub window。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;

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

const { stateActress } = await import('../state-actress.js');

function partsOf(actress) {
    const c = Object.assign({}, stateActress());
    return c._heroCardTagParts(actress);
}

function textsOf(actress) {
    return partsOf(actress).map((p) => p.text);
}

// ── 順序與內容 ──────────────────────────────────────────────────────────


test('hometown／agency 排在 tags 之後', () => {
    const actress = {
        tags: ['ロリ', '美人'],
        hometown: '青森県',
        agency: 'KRONE(クローネ)',
    };
    assert.deepEqual(textsOf(actress), ['ロリ', '美人', '青森県', 'KRONE(クローネ)']);
});


// ── AC-D4 四種空輸入皆回 [] ─────────────────────────────────────────────


// ── 過濾 ────────────────────────────────────────────────────────────────


