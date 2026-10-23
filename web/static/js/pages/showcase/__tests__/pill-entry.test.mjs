// TASK-115-T4: 入口改道（十個 searchFromMetadata call site 補齊維度）＋
// searchFromMetadata 降格為 addPill adapter 的契約鎖。
//
// state-videos.js / state-lightbox.js / state-base.js 用瀏覽器 importmap 別名
// `@/showcase/...` 與 `@/shared/...`，plain `node --test` 不認得。既有
// search/__tests__/alias-loader.mjs 只做 `@/` → `web/static/js/` 字首轉譯，對
// `@/showcase/` 會解成錯誤路徑（importmap 實際指到 `pages/showcase/`）。比照
// settings/save-access-auth.test.mjs / T1 的 pill-state.test.mjs，本檔自帶與
// base.html importmap 對齊的 resolve hook（不改共用 loader，見 gotcha FE-GUARD-11）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// 比照 pill-state.test.mjs 先 stub window，在任何 state-*.js import 之前完成。
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

const { stateVideos } = await import('../state-videos.js');
const { stateLightbox } = await import('../state-lightbox.js');
const { stateActress } = await import('../state-actress.js');
const { stateBase, _setActresses } = await import('../state-base.js');
const { buildPillPredicate } = await import('../../../shared/pill-filter.js');

// TASK-115-T8：_reconcileHeroCard() 從 no-op stub 填成真身後，addPill() 內部會呼叫
// _clearPreciseMatch()/_checkPreciseActressMatch()（定義在 state-actress.js）。本檔
// 既有 harness（T4 時代）只合併了 stateBase/stateVideos/stateLightbox，缺 stateActress，
// 會在 addPill 內部 TypeError。补上合併，並預先灌入 fixture 避免 dim==='actress' 案例
// 因 _actresses 為空觸發真正的 loadActresses() 網路呼叫（該函式非本檔測試標的）。
// is_favorite 刻意設 false：is_favorite:true 會排 $nextTick(requestAnimationFrame(...))
// 播 hero card 進場動畫，本檔 $nextTick 是同步呼叫（見 makeComponent），而
// requestAnimationFrame 在零-DOM node:test 環境不存在，會炸出 unhandledRejection——
// 這條動畫路徑與本檔要驗證的 pill 契約無關，用 is_favorite:false 讓它天然跳過。
_setActresses([{ name: 'Yui Hatano', is_favorite: false }]);

// ===== window / document stub（saveState 讀 location/history；searchFromMetadata
// 讀 document.querySelector + document.body.classList，比照 pill-persist.test.mjs stubWindow）=====
globalThis.window.location = { pathname: '/showcase', search: '' };
globalThis.window.history = { replaceState() {} };
globalThis.document = {
    querySelector: () => null,
    body: { classList: { add() {}, remove() {} } },
};


function makeComponent(overrides) {
    const base = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    const c = Object.assign({}, base, stateVideos(), stateLightbox(), stateActress(), {
        pills: [],
        search: '',
        mode: 'table',   // 避開 grid 專屬 DOM 路徑（_getActiveGrid 只在 mode==='grid' 時被呼叫）
        sort: 'date',
        order: 'desc',
        page: 1,
    }, overrides);
    c.$nextTick = (fn) => fn();
    return c;
}


// ===== 十二個入口逐一核對（plan CD-2b / TASK-115-T4「現況分析」表，文件順序；
// #3／#11 是 TASK-124a-T3 新增的發售日入口）=====


// ===== card-info 與燈箱同片同維度產生相同 pill（#1 vs #6 女優、#5 vs #12 標籤）=====


// ===== 全庫 grep：不存在 `this.search = ` 接 metadata 值的寫法 =====


// ===== D4/D8: adapter body（brace-matched，非整檔）不含四個禁止字面 + .focus( =====


// ===== D3（FE-ALPINE-05）: addPill 只定義在 state-videos.js =====


// ===== CD-2 步驟表唯一擁有權：一次點擊只觸發一次 _animateFilter/saveState/_reconcileHeroCard =====


// ===== addPill 呼叫參數順序：this.addPill(dim, value)，dim 在前 =====


// ===== 六個維度各自產生的 pill 透過 buildPillPredicate 實際命中對應影片
//       （這是唯一能抓到 addPill 參數順序寫反的斷言：順序反了會讓 pill.dim 變成
//       原始值、pill.value 變成維度 token，WHOLE_FIELD_DIMS/actress/tag 都查不到，
//       fail-closed 恆假，predicate 全部回傳 false）=====

test('六個維度各自產生的 pill，透過 buildPillPredicate 實際比對命中對應影片', () => {
    const cases = [
        { dim: 'actress', value: 'Yui Hatano', video: { actresses: 'Yui Hatano' } },
        { dim: 'tag', value: '痴女', video: { tags: '痴女' } },
        { dim: 'maker', value: 'Moodyz', video: { maker: 'Moodyz' } },
        { dim: 'director', value: 'Some Director', video: { director: 'Some Director' } },
        { dim: 'series', value: 'Madonna', video: { series: 'Madonna' } },
        { dim: 'label', value: 'S1', video: { label: 'S1' } },
    ];
    for (const { dim, value, video } of cases) {
        const c = makeComponent();
        c.searchFromMetadata(value, dim);
        assert.equal(c.pills.length, 1, `dim=${dim} 應恰好產生 1 枚 pill`);
        const predicate = buildPillPredicate(c.pills, {}, {});
        assert.equal(predicate(video), true, `dim=${dim} 的 pill 應命中對應影片 ${JSON.stringify(video)}`);
    }
});
