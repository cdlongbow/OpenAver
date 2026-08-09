// TASK-115-T2: pill 精準比對層契約。
//
// 分兩部分：
// Part A — buildPillPredicate 純函式（直接 import shared/pill-filter.js，零 DOM，
//          不需 resolve hook），涵蓋六個維度、alias 展開、正規化順序、fail-closed、
//          null 欄位、空 pill 列表，以及 CD-7 的兩條 oracle。
// Part B — applyFilterAndSort() 接線測試（比照 T1 pill-state.test.mjs 的
//          resolve hook + globalThis.window stub，import 真正的 state-videos.js /
//          state-base.js），涵蓋 pill+自由文字 AND、filteredCount 不變式、
//          自由文字既有行為零回歸（DoD ②）。
//
// state-videos.js 用瀏覽器 importmap 別名 `@/showcase/...` 與 `@/shared/...`，
// plain `node --test` 不認得。既有 search/__tests__/alias-loader.mjs 只做
// `@/` → `web/static/js/` 字首轉譯，對 `@/showcase/` 會解成錯誤路徑
// （importmap 實際指到 `pages/showcase/`）。比照 settings/save-access-auth.test.mjs /
// T1 的 pill-state.test.mjs，本檔自帶與 base.html importmap 對齊的 resolve hook
// （不改共用 loader，見 gotcha FE-GUARD-11）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// ===== Part A の純函式 import（無 window 依賴，可靜態 import） =====
import { buildPillPredicate } from '../../../shared/pill-filter.js';

// ===== Part B 的 resolve hook + window stub（FE-GUARD-11，照抄 T1 pill-state.test.mjs） =====

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
const {
    _setVideos,
    _filteredVideos,
    _loadAliasMap,
    _loadTagAliasMap,
} = await import('../state-base.js');

// ===== Part B 用的 alias map 種子資料：以 stub fetch 呼叫真正的 _loadAliasMap/_loadTagAliasMap =====
// _nameToGroup/_tagToGroup 是 state-base.js 的模組層級變數，_loadAliasMap()/_loadTagAliasMap()
// 內部整個重新指派（非 mutate），test 端 import binding 是 live binding，呼叫後即可反映新值。
// applyFilterAndSort() 內讀的是同一個 module singleton，故這裡種子的資料對 Part B 的自由文字
// alias 展開回歸測試（DoD ②）與 pill 層皆生效。
// 頂層 await（非 async IIFE 的 dangling promise）：確保在任何 test() 執行之前，
// alias map 已用種子資料填好——node:test 的 test() 只是註冊，真正執行在模組
// 評估完成之後，但若用不 await 的 IIFE，填表與模組評估完成之間仍有 race window。
{
    const ORIGINAL_FETCH = globalThis.fetch;
    globalThis.fetch = async (url) => {
        if (url === '/api/actress-aliases') {
            return {
                ok: true,
                json: async () => ({ groups: [{ primary_name: 'AliasActressA', aliases: ['AliasActressB'] }] }),
            };
        }
        if (url === '/api/tag-aliases') {
            return {
                ok: true,
                json: async () => ({ groups: [{ primary_name: '女僕', aliases: ['メイド'] }] }),
            };
        }
        throw new Error('pill-match.test.mjs: unexpected fetch url ' + url);
    };
    await _loadAliasMap();
    await _loadTagAliasMap();
    globalThis.fetch = ORIGINAL_FETCH;
}

function makeComponent(overrides) {
    return Object.assign({}, stateVideos(), {
        pills: [],
        search: '',
        sort: 'title',
        order: 'asc',
        page: 1,
        perPage: 0,
        mode: 'list',
        filteredCount: 0,
    }, overrides);
}

// =====================================================================
// Part A — buildPillPredicate 純函式
// =====================================================================

test('spec AC11：片商 pill S1 → 標題含 "S1" 但 maker 不等於 S1 的影片不在結果中', () => {
    const predicate = buildPillPredicate([{ dim: 'maker', value: 'S1' }], {}, {});
    assert.equal(predicate({ title: 'S1 NO.1 STYLE 精選', maker: 'Some Other Maker' }), false);
    assert.equal(predicate({ title: 'random', maker: 'S1' }), true);
});

test('spec AC12：標籤 pill 痴女 → 只有 tags 含 痴女系（不含 痴女）的影片不 match', () => {
    const predicate = buildPillPredicate([{ dim: 'tag', value: '痴女' }], {}, {});
    assert.equal(predicate({ tags: '痴女系' }), false);
    assert.equal(predicate({ tags: '痴女, 中出' }), true);
});

test('alias 正向命中：pill 值為別名 A，影片 actresses 含同 group 的別名 B（A≠B）→ match', () => {
    const nameToGroup = { 'a': ['A', 'B'] };
    const predicate = buildPillPredicate([{ dim: 'actress', value: 'A' }], nameToGroup, {});
    assert.equal(predicate({ actresses: 'B' }), true);
});

test('全形寫法的 alias 成員仍命中：靠 D5 雙 key 查表 + 值正規化命中', () => {
    // _nameToGroup/_tagToGroup 的 key 只做 .toLowerCase()，無 NFKC（state-base.js:65/93 現況），
    // 若 pill 值本身是全形字元，normalizePillValue() 折出的 key（半形小寫）查不到表裡的全形小寫 key，
    // 必須靠第二把 candidateKey（純 .toLowerCase()，不做 NFKC）才查得到。
    //
    // 刻意讓 pill 值與命中影片的 token 不同字面（'Ｂ' vs 'A'）——若兩者本就折疊成同一個
    // normalizePillValue() 結果，「pill 自身正規化值恆在 Set 內」那條 D5 保底規則會讓這條測試
    // 在完全不查 alias group 的情況下也綠燈，測不出雙 key 查表本身是否有效（green shell）。
    const fullWidthPillValue = 'Ｂ';                          // norm = 'b'
    const fullWidthLowerKey = fullWidthPillValue.toLowerCase(); // 'ｂ'（全形小寫，非 norm 的 'b'）
    const nameToGroup = {};
    nameToGroup[fullWidthLowerKey] = [fullWidthPillValue, 'A'];  // 只掛在全形 key 下，半形 key 'b' 查無此表
    const predicate = buildPillPredicate([{ dim: 'actress', value: fullWidthPillValue }], nameToGroup, {});
    assert.equal(predicate({ actresses: 'A' }), true);
});

test('"A, B" 形式的 actresses 欄位，pill 值 B 命中（trim 驗證，D4）', () => {
    const predicate = buildPillPredicate([{ dim: 'actress', value: 'B' }], {}, {});
    assert.equal(predicate({ actresses: 'A, B' }), true);
});

test('全形逗號欄位（"A，B"）正確切成兩個 token（D4 normalize-then-split 順序驗證，spec §4.2 第 2 條）', () => {
    const predicate = buildPillPredicate([{ dim: 'actress', value: 'B' }], {}, {});
    assert.equal(predicate({ actresses: 'A，B' }), true);
});

test('未知 dim（如 typo）→ predicate 對任何影片皆回傳 false（fail closed，D3）', () => {
    const predicate = buildPillPredicate([{ dim: 'typo', value: 'anything' }], {}, {});
    assert.equal(predicate({ maker: 'anything', actresses: 'anything', tags: 'anything' }), false);
    assert.equal(predicate({}), false);
});

test('user_tags 不參與：tags 不含 X、user_tags 含 X → tag pill X 不 match 該影片（D7，spec §4.3）', () => {
    const predicate = buildPillPredicate([{ dim: 'tag', value: 'X' }], {}, {});
    assert.equal(predicate({ tags: 'Y', user_tags: 'X' }), false);
});

test('空 pill 列表（pills: []）→ buildPillPredicate 對任何影片皆回傳 true，不過濾任何影片（D2）', () => {
    const predicate = buildPillPredicate([], {}, {});
    assert.equal(predicate({}), true);
    assert.equal(predicate({ maker: null, actresses: undefined, tags: '' }), true);

    const predicateNoPillsArg = buildPillPredicate(undefined, {}, {});
    assert.equal(predicateNoPillsArg({}), true);
});

test('video.maker 為 null 的影片，對任何非空片商 pill 皆不 match、不拋例外（Extra 3 finding）', () => {
    const predicate = buildPillPredicate([{ dim: 'maker', value: 'S1' }], {}, {});
    assert.doesNotThrow(() => {
        assert.equal(predicate({ maker: null }), false);
    });
});

test('CD-7：alias map 未載入時 pill 結果會少於載入後——證明順序鎖是有意義的，不是巧合', () => {
    const videos = [{ actresses: '別名B' }];
    const pills = [{ dim: 'actress', value: '別名A' }];
    const loaded = { '別名a': ['別名A', '別名B'] };
    const cold = videos.filter(buildPillPredicate(pills, {}, {}));        // map 未載入
    const warm = videos.filter(buildPillPredicate(pills, loaded, {}));    // map 已載入
    assert.equal(cold.length, 0);
    assert.equal(warm.length, 1);   // 冷載真的會少 → 順序鎖是承重的
});

test('CD-7 regression lock：state-base.js init() 的 alias map await 必須排在 applyFilterAndSort(true) 之前', () => {
    const src = readFileSync(new URL('../state-base.js', import.meta.url), 'utf8');
    const idxAlias = src.indexOf('await _loadAliasMap()');
    const idxTagAlias = src.indexOf('await _loadTagAliasMap()');
    const idxApply = src.indexOf('applyFilterAndSort(true)');
    assert.ok(idxAlias !== -1 && idxTagAlias !== -1 && idxApply !== -1, '三個錨點字面必須存在');
    assert.ok(idxAlias < idxApply, 'alias map 必須在第一次 applyFilterAndSort 之前載入');
    assert.ok(idxTagAlias < idxApply, 'tag alias map 必須在第一次 applyFilterAndSort 之前載入');
});

// =====================================================================
// Part B — 透過真正的 applyFilterAndSort() 接線測試
// =====================================================================

test('pill 與自由文字同時作用：一枚片商 pill ＋ 自由文字關鍵字 → 結果同時滿足兩者（AND，CD-6）', () => {
    _setVideos([
        { title: 'Alpha', maker: 'Moodyz', tags: '', actresses: '', number: 'ABC-001' },
        { title: 'Beta', maker: 'Moodyz', tags: '', actresses: '', number: 'ABC-002' },
        { title: 'Alpha Extra', maker: 'S1', tags: '', actresses: '', number: 'XYZ-003' },
    ]);
    const c = makeComponent({
        pills: [{ dim: 'maker', value: 'Moodyz' }],
        search: 'alpha',
    });
    c.applyFilterAndSort(true);
    assert.equal(_filteredVideos.length, 1);
    assert.equal(_filteredVideos[0].title, 'Alpha');
});

test('this.filteredCount === _filteredVideos.length（pill 有/無 × 搜尋 有/無 四種組合）', () => {
    _setVideos([
        { title: 'Gamma', maker: 'Moodyz', tags: 'A', actresses: '', number: 'DEF-001' },
        { title: 'Delta', maker: 'S1', tags: 'B', actresses: '', number: 'DEF-002' },
    ]);
    const combos = [
        { pills: [], search: '' },
        { pills: [{ dim: 'maker', value: 'Moodyz' }], search: '' },
        { pills: [], search: 'gamma' },
        { pills: [{ dim: 'maker', value: 'Moodyz' }], search: 'gamma' },
    ];
    for (const combo of combos) {
        const c = makeComponent(combo);
        c.applyFilterAndSort(true);
        assert.equal(c.filteredCount, _filteredVideos.length);
    }
});

test('自由文字回歸（DoD ②）：番號模糊比對（ABC-123 打 abc123 命中），零 pill', () => {
    _setVideos([{ title: 'X', number: 'ABC-123', maker: '', tags: '', actresses: '' }]);
    const c = makeComponent({ search: 'abc123' });
    c.applyFilterAndSort(true);
    assert.equal(_filteredVideos.length, 1);
});

test('自由文字回歸（DoD ②）：多關鍵字 AND，零 pill', () => {
    _setVideos([
        { title: 'X', maker: 'Moodyz', tags: '痴女', actresses: '', number: 'A-1' },
        { title: 'Y', maker: 'Moodyz', tags: '中出', actresses: '', number: 'A-2' },
    ]);
    const c = makeComponent({ search: 'moodyz 痴女' });
    c.applyFilterAndSort(true);
    assert.equal(_filteredVideos.length, 1);
    assert.equal(_filteredVideos[0].title, 'X');
});

test('自由文字回歸（DoD ②）：女優 alias 展開，零 pill', () => {
    _setVideos([{ title: 'Z', maker: '', tags: '', actresses: 'AliasActressB', number: 'A-3' }]);
    const c = makeComponent({ search: 'aliasactressa' });
    c.applyFilterAndSort(true);
    assert.equal(_filteredVideos.length, 1);
});

test('自由文字回歸（DoD ②）：tag alias 展開，零 pill', () => {
    _setVideos([{ title: 'W', maker: '', tags: 'メイド', actresses: '', number: 'A-4' }]);
    const c = makeComponent({ search: '女僕' });
    c.applyFilterAndSort(true);
    assert.equal(_filteredVideos.length, 1);
});

// ===== Opus review 追加：alias map 的原型鏈污染 =====

// ⚠ 只有 `constructor` 真的會踩到守衛。查表 key 進去前已被 normalizePillValue 折成小寫，
// 而 Object.prototype 的成員名是 mixed-case（`toString`/`valueOf`/`hasOwnProperty`），折成
// `tostring`/`valueof`/`hasownproperty` 之後**不再與原型鏈上的任何 key 相等**——那三個即使
// 拿掉守衛也會通過。`constructor` 本來就全小寫，是唯一會取到繼承函式（→ `.forEach` TypeError）
// 的實例。三個非碰撞值留著當對照組（證明守衛沒有誤殺正常字串），但不得把它們算成守衛的證據。
test('alias 查表不得取到 Object.prototype 繼承來的成員（真正的實例是 constructor，其餘三個為對照組）', () => {
    const videos = [{ tags: 'toString', actresses: '' }];
    for (const evil of ['constructor', 'toString', 'valueOf', 'hasOwnProperty']) {
        const pred = buildPillPredicate([{ dim: 'tag', value: evil }], {}, {});
        // 不得拋例外；且只有欄位真的含該 token 時才命中
        assert.doesNotThrow(() => videos.filter(pred));
        assert.equal(videos.filter(pred).length, evil === 'toString' ? 1 : 0);
    }
});

test('alias group 值不是陣列時（壞掉的 map）視為查無 group，不拋例外', () => {
    const videos = [{ actresses: 'A', tags: '' }];
    const brokenMap = { a: 'not-an-array' };
    const pred = buildPillPredicate([{ dim: 'actress', value: 'A' }], brokenMap, {});
    assert.doesNotThrow(() => videos.filter(pred));
    assert.equal(videos.filter(pred).length, 1);  // 退化成只比字面值，仍命中自己
});
