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
import { readFileSync } from 'node:fs';
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

const SHOWCASE_HTML = readFileSync(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../../templates/showcase.html'),
    'utf8',
);
const LIGHTBOX_SRC = readFileSync(new URL('../state-lightbox.js', import.meta.url), 'utf8');

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

// 抽「<sig> 起的下一個 `{` 開始 brace-match 到對應 `}`」的函式 body（比照
// readonly-action-intent.test.mjs 的 extractFnBody）。
function extractFnBody(code, sig, label) {
    const sigIdx = code.indexOf(sig);
    assert.ok(sigIdx >= 0, `原始碼應含 \`${sig}\`（${label}）`);
    const open = code.indexOf('{', sigIdx);
    assert.ok(open >= 0, `${label} 應有 {`);
    let depth = 0;
    for (let i = open; i < code.length; i++) {
        const ch = code[i];
        if (ch === '{') depth++;
        else if (ch === '}') {
            depth--;
            if (depth === 0) return code.slice(open + 1, i);
        }
    }
    throw new Error(`${label} 大括號未閉合（brace-match 失敗）`);
}

// 抽出 showcase.html 全部 `searchFromMetadata(...)` call 的參數字串（depth-aware，
// 容納參數本身含 `.trim()` 這類巢狀括號）。
function extractSearchFromMetadataCalls(html) {
    const marker = 'searchFromMetadata(';
    const calls = [];
    let idx = 0;
    for (;;) {
        const found = html.indexOf(marker, idx);
        if (found === -1) break;
        const argStart = found + marker.length;
        let depth = 1;
        let i = argStart;
        for (; i < html.length; i++) {
            const ch = html[i];
            if (ch === '(') depth++;
            else if (ch === ')') {
                depth--;
                if (depth === 0) break;
            }
        }
        assert.ok(depth === 0, `searchFromMetadata( 未找到匹配的收尾括號（offset ${found}）`);
        calls.push(html.slice(argStart, i));
        idx = i + 1;
    }
    return calls;
}

// ===== 十二個入口逐一核對（plan CD-2b / TASK-115-T4「現況分析」表，文件順序；
// #3／#11 是 TASK-124a-T3 新增的發售日入口）=====

const EXPECTED_DIMS = [
    'actress',   // #1 卡片 · 女優
    'maker',     // #2 卡片 · 片商
    'release',   // #3 卡片 · 發售日（TASK-124a-T3 新增）
    'series',    // #4 卡片 · 系列
    'tag',       // #5 卡片 · 標籤
    'actress',   // #6 燈箱 · 女優
    'maker',     // #7 燈箱 · 片商
    'director',  // #8 燈箱 · 導演
    'series',    // #9 燈箱 · 系列
    'label',     // #10 燈箱 · 廠牌
    'release',   // #11 燈箱 · 發售日（TASK-124a-T3 新增）
    'tag',       // #12 燈箱 · 標籤
];

test('showcase.html 恰有十二個 searchFromMetadata call site，逐一帶正確維度 token（非抽樣）', () => {
    const calls = extractSearchFromMetadataCalls(SHOWCASE_HTML);
    assert.equal(calls.length, 12, `預期恰好 12 個 searchFromMetadata call site，實際 ${calls.length}`);
    EXPECTED_DIMS.forEach((dim, i) => {
        const args = calls[i];
        assert.ok(args.includes(','), `#${i + 1} 缺少第二個維度參數：${args}`);
        assert.ok(
            args.includes(`'${dim}'`),
            `#${i + 1} 預期維度 token '${dim}'，實際參數：${args}`,
        );
    });
});

// ===== card-info 與燈箱同片同維度產生相同 pill（#1 vs #6 女優、#5 vs #12 標籤）=====

test('card-info 與燈箱點擊同片同維度（女優，#1 vs #6）產生完全相同的 pill', () => {
    const c1 = makeComponent();
    c1.searchFromMetadata('Yui Hatano', 'actress');
    const c2 = makeComponent();
    c2.searchFromMetadata('Yui Hatano', 'actress');
    assert.deepEqual(c1.pills, c2.pills);
});

test('card-info 與燈箱點擊同片同維度（標籤，#5 vs #12）產生完全相同的 pill', () => {
    const c1 = makeComponent();
    c1.searchFromMetadata('痴女', 'tag');
    const c2 = makeComponent();
    c2.searchFromMetadata('痴女', 'tag');
    assert.deepEqual(c1.pills, c2.pills);
});

// ===== 全庫 grep：不存在 `this.search = ` 接 metadata 值的寫法 =====

test('state-lightbox.js 全檔 grep this.search = 結果為零筆（舊行為已徹底移除）', () => {
    assert.equal(
        (LIGHTBOX_SRC.match(/this\.search = /g) || []).length,
        0,
        'state-lightbox.js 不應再出現 this.search = 字面',
    );
});

// ===== D4/D8: adapter body（brace-matched，非整檔）不含四個禁止字面 + .focus( =====

test('searchFromMetadata body（brace-matched）不含 D4 四個禁止字面與 .focus(（D8 regression lock）', () => {
    const body = extractFnBody(LIGHTBOX_SRC, 'searchFromMetadata(value, dim) {', 'searchFromMetadata');
    for (const forbidden of ['this.search =', '_animateFilter', '_checkPreciseActressMatch', '_clearPreciseMatch', '.focus(']) {
        assert.ok(!body.includes(forbidden), `searchFromMetadata body 不應含 ${JSON.stringify(forbidden)}`);
    }
    assert.ok(body.includes('addPill('), 'searchFromMetadata body 必須委派給 addPill(');
});

// ===== D3（FE-ALPINE-05）: addPill 只定義在 state-videos.js =====

test('D3: addPill 只定義在 state-videos.js，state-lightbox.js 不得定義同名成員（FE-ALPINE-05）', () => {
    // 比對「定義形狀」而非「出現過 addPill(」。第一版寫的是後者（扣掉 this.addPill( 之後
    // 任何 `addPill(` 都算定義），結果**實作端自己的 CD-2 註解**寫了 `addPill()` 就把這支打紅——
    // 那是 fail-red-fragile：未來任何人在本檔寫一句提到 `addPill(dim, value)` 的英文註解都會
    // 誤紅，而功能毫無問題。改成必須是「名稱 + 參數列 + 緊接 `{`」的定義頭，散文寫不出這個形狀；
    // 另外先剝掉註解，雙保險。（FE-GUARD-03 的反向版本：註解同樣會參與字串守衛。）
    const srcNoComments = LIGHTBOX_SRC
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\/\/[^\n]*/g, '');
    assert.ok(
        !/\baddPill\s*\([^)]*\)\s*\{/.test(srcNoComments),
        'state-lightbox.js 不得定義 addPill（會被 mergeState 靜默覆蓋 T1 的 core，FE-ALPINE-05）',
    );
    assert.equal(typeof stateVideos().addPill, 'function', 'stateVideos() 應有 addPill');
    assert.equal(stateLightbox().addPill, undefined, 'stateLightbox() 不應有 addPill');
});

// ===== CD-2 步驟表唯一擁有權：一次點擊只觸發一次 _animateFilter/saveState/_reconcileHeroCard =====

test('一次 searchFromMetadata 呼叫，_animateFilter/saveState/_reconcileHeroCard 各恰好 1 次', () => {
    const c = makeComponent();
    let animateCalls = 0;
    let saveCalls = 0;
    let heroCalls = 0;

    const origAnimate = c._animateFilter.bind(c);
    c._animateFilter = function (...args) { animateCalls++; return origAnimate(...args); };
    const origSave = c.saveState.bind(c);
    c.saveState = function (...args) { saveCalls++; return origSave(...args); };
    const origHero = c._reconcileHeroCard.bind(c);
    c._reconcileHeroCard = function (...args) { heroCalls++; return origHero(...args); };

    c.searchFromMetadata('Moodyz', 'maker');

    assert.equal(animateCalls, 1, `_animateFilter 應恰好呼叫 1 次，實際 ${animateCalls}`);
    assert.equal(saveCalls, 1, `saveState 應恰好呼叫 1 次，實際 ${saveCalls}`);
    assert.equal(heroCalls, 1, `_reconcileHeroCard 應恰好呼叫 1 次，實際 ${heroCalls}`);
});

// ===== addPill 呼叫參數順序：this.addPill(dim, value)，dim 在前 =====

test('adapter 呼叫 addPill 時參數順序正確：this.addPill(dim, value)，非 this.addPill(value, dim)', () => {
    const c = makeComponent();
    let capturedArgs = null;
    const origAddPill = c.addPill.bind(c);
    c.addPill = function (a, b) { capturedArgs = [a, b]; return origAddPill(a, b); };

    c.searchFromMetadata('Moodyz', 'maker');   // value='Moodyz', dim='maker'（template 呼叫慣例）

    assert.deepEqual(
        capturedArgs,
        ['maker', 'Moodyz'],
        'addPill 應收到 (dim, value)＝(\'maker\', \'Moodyz\')，不是 (value, dim)',
    );
});

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
