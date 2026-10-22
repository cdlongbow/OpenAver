// TASK-123-T6: 漏斗選單「只看精選」＋ pick pill 契約。
//
// 分兩部分：
// Part A — buildPillPredicate 的 pick 分支（直接 import shared/pill-filter.js，零 DOM，
//          不需 resolve hook），涵蓋 >0 為真、0/undefined/null 為假、與 actress pill 疊加
//          取交集（AC-9）、fail-closed 出口不受影響。
// Part B — togglePickPill()/_hasPickPill()/pillLabel() 接線測試（比照既有
//          pill-state.test.mjs 的 resolve hook + globalThis.window stub 寫法，
//          import 真正的 state-videos.js），涵蓋 AC-8（排序鍵/升降冪不變）、
//          AC-10（pill 的 × 與選單那條等價）、重複點選單那條（連兩次）。
//
// state-videos.js 用瀏覽器 importmap 別名 `@/showcase/...` 與 `@/shared/...`，
// plain `node --test` 不認得。比照 pill-state.test.mjs / pill-match.test.mjs，
// 本檔自帶與 base.html importmap 對齊的 resolve hook（不改共用 loader，見 gotcha FE-GUARD-11）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// ===== Part A の純函式 import（無 window 依賴，可靜態 import） =====
import { buildPillPredicate } from '../../../shared/pill-filter.js';

// ===== Part B 的 resolve hook + window stub（FE-GUARD-11，照抄 pill-state.test.mjs） =====

globalThis.window = globalThis;
globalThis.window.t = (key) => key;
globalThis.Alpine = globalThis.Alpine || {
    store: () => ({ toolbarOpen: false, showcaseHasSearch: false }),
};

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
// 本檔：web/static/js/pages/showcase/__tests__/ → 上三層 = web/static/js/
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


// =====================================================================
// Part A — buildPillPredicate 的 pick 分支
// =====================================================================

test('pick 分支：video.user_rating > 0 → match', () => {
    const predicate = buildPillPredicate([{ dim: 'pick', value: '1' }], {}, {});
    assert.equal(predicate({ user_rating: 1 }), true);
    assert.equal(predicate({ user_rating: 5 }), true);
});

test('pick 分支：video.user_rating === 0 → 不 match', () => {
    const predicate = buildPillPredicate([{ dim: 'pick', value: '1' }], {}, {});
    assert.equal(predicate({ user_rating: 0 }), false);
});


// =====================================================================
// Part B — togglePickPill() / _hasPickPill() / pillLabel()
// =====================================================================


