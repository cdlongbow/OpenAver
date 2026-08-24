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
import { buildPillPredicate, mergeTagTokens } from '../../../shared/pill-filter.js';

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
const stateBaseMod = await import('../state-base.js');
const {
    _setVideos,
    _filteredVideos,
    _loadAliasMap,
    _loadTagAliasMap,
    stateBase,
} = stateBaseMod;

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
        // 121b-T2：cover-badge manifest 端點。這個 seed 區塊只呼叫 _loadAliasMap()/
        // _loadTagAliasMap()，目前不會打到這個 URL——留著是 fail-safe：日後若有人在此
        // seed manifest（或既有 loader 多打一次 fetch），才不會撞上下面那行 throw。
        // 刻意回空陣列：seed 階段不消耗 _coverBadgeManifestLoaded 冪等 guard，
        // 讓下面各 loader 測試自己決定要載入什麼。
        if (url === '/api/cover-badges/manifest') {
            return { ok: true, json: async () => [] };
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

test('user_tags 參與：tags 不含 X、user_tags 含 X → tag pill X match 該影片（D7 反轉）', () => {
    // 這裡曾經鎖 user_tags 不參與的舊行為（spec-115 §4.3），121b 刻意行為升級
    const predicate = buildPillPredicate([{ dim: 'tag', value: 'X' }], {}, {});
    assert.equal(predicate({ tags: 'Y', user_tags: ['X'] }), true);
});

test('mergeTagTokens：tags 空、user_tags 陣列含 中字 → 結果含 中字；tag pill 中字 match（邊界 1）', () => {
    const video = { tags: '', user_tags: ['中字'] };
    assert.ok(mergeTagTokens(video).includes('中字'));
    const predicate = buildPillPredicate([{ dim: 'tag', value: '中字' }], {}, {});
    assert.equal(predicate(video), true);
});

test('mergeTagTokens：user_tags 非陣列（undefined / null / 數字）不拋例外，結果等同只有 tags（邊界 3）', () => {
    const tagsOnly = mergeTagTokens({ tags: 'Y' });
    assert.doesNotThrow(() => {
        assert.deepEqual(mergeTagTokens({ tags: 'Y', user_tags: undefined }), tagsOnly);
        assert.deepEqual(mergeTagTokens({ tags: 'Y', user_tags: null }), tagsOnly);
        assert.deepEqual(mergeTagTokens({ tags: 'Y', user_tags: 42 }), tagsOnly);
        assert.deepEqual(mergeTagTokens({ tags: 'Y', user_tags: { X: true } }), tagsOnly);
    });
});

test('mergeTagTokens：user_tags 為字串 X 不拋例外，結果等同只有 tags（邊界 3 字串格）', () => {
    const tagsOnly = mergeTagTokens({ tags: 'Y' });
    assert.doesNotThrow(() => {
        assert.deepEqual(mergeTagTokens({ tags: 'Y', user_tags: 'X' }), tagsOnly);
    });
    const predicate = buildPillPredicate([{ dim: 'tag', value: 'X' }], {}, {});
    assert.equal(predicate({ tags: 'Y', user_tags: 'X' }), false);
});

test('mergeTagTokens：user_tags 空值成員被濾掉，不產生假的空 token 命中（邊界 4）', () => {
    const tokens = mergeTagTokens({ tags: 'Y', user_tags: ['', '   ', null] });
    assert.ok(!tokens.includes(''));
    const predicate = buildPillPredicate([{ dim: 'tag', value: '' }], {}, {});
    assert.equal(predicate({ tags: 'Y', user_tags: ['', '   ', null] }), false);
});

test('CD-4 疊加不縮小：tags 含 痴女、user_tags 含無關的 重看 → tag pill 痴女仍 match（邊界 5）', () => {
    const predicate = buildPillPredicate([{ dim: 'tag', value: '痴女' }], {}, {});
    assert.equal(predicate({ tags: '痴女', user_tags: ['重看'] }), true);
});

test('actress 路徑不受 user_tags 影響：actresses 為 A、user_tags 含 B → actress pill B 不 match（邊界 6）', () => {
    const predicate = buildPillPredicate([{ dim: 'actress', value: 'B' }], {}, {});
    assert.equal(predicate({ actresses: 'A', user_tags: ['B'] }), false);
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

test('TASK-124a-T1：release pill 與既有維度混用取交集（AND）', () => {
    const predicate = buildPillPredicate(
        [{ dim: 'release', op: '=', value: '2024-09' }, { dim: 'maker', value: 'S1' }],
        {},
        {},
    );
    assert.equal(predicate({ release_date: '2024-09-09', maker: 'S1' }), true);
    assert.equal(predicate({ release_date: '2024-09-09', maker: 'Other' }), false);
    assert.equal(predicate({ release_date: '2024-08-01', maker: 'S1' }), false);
});

test('TASK-124a-T1：release pill 的 expandPill 回 null 時 fail-closed（不是 fail-open）', () => {
    // op 不在四值白名單內 → expandPill 回 null → matcher 對任何影片皆回 false，
    // 不是讓這枚 pill 形同虛設變相回 true。
    const predicate = buildPillPredicate([{ dim: 'release', op: '!=', value: '2024' }], {}, {});
    assert.equal(predicate({ release_date: '2024-01-01' }), false);
    assert.equal(predicate({}), false);
    assert.equal(predicate({ release_date: null }), false);
});

test('TASK-124a-T1：release pill 的 value 形狀不合法 → expandPill 回 null → fail-closed', () => {
    const predicate = buildPillPredicate([{ dim: 'release', op: '=', value: 'garbage' }], {}, {});
    assert.equal(predicate({ release_date: '2024-01-01' }), false);
});

test('TASK-124a-T1：release pill range 命中／不命中邊界（含端點）', () => {
    const predicate = buildPillPredicate(
        [{ dim: 'release', op: 'range', value: '2023', value2: '2024-06' }],
        {},
        {},
    );
    assert.equal(predicate({ release_date: '2023-01-01' }), true);
    assert.equal(predicate({ release_date: '2024-06-30' }), true);
    assert.equal(predicate({ release_date: '2022-12-31' }), false);
    assert.equal(predicate({ release_date: '2024-07-01' }), false);
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

// =====================================================================
// TASK-121b-T3 — B1／B4 端到端（真正的 applyFilterAndSort 接線）
// =====================================================================
//
// 假設（測試順序敏感）：本區塊註冊在 Part B、早於檔尾 121b-T2 的
// CoverBadgeManifest 測試。跑到這裡時：
//   - `_tagToGroup` 只有頂層 seed 的 女僕/メイド（不得覆寫）
//   - `_coverBadgeManifestLoaded` 仍為 false
// 因此就地改屬性併入短名對，不呼叫 `_loadCoverBadgeManifest()`——
// 若改走 loader 會吃掉冪等 guard，T2 cold/warm 的 init() 就變成 no-op。

test('B1 端到端：燈箱手貼 user_tags 中字 → 瀏覽頁標籤篩 中文字幕 命中', () => {
    // 就地 seed：T2 併入 manifest 短名對之後的狀態（中字 ↔ 中文字幕 同組）。
    // 先把「這兩個 key 在我寫入前是空的」這個隱含假設變成可執行斷言——下面的 finally
    // 是無條件 delete，若哪天有人把本區塊搬到已經載入過 manifest 的測試之後，
    // delete 會砍掉別人載入的真值而不是還原，這條斷言會先一步紅給你看。
    assert.equal(stateBaseMod._tagToGroup['中文字幕'], undefined, '本區塊必須是第一個寫入這兩個 key 的測試');
    assert.equal(stateBaseMod._tagToGroup['中字'], undefined, '本區塊必須是第一個寫入這兩個 key 的測試');
    const b1ShortPair = ['中文字幕', '中字'];
    stateBaseMod._tagToGroup['中文字幕'] = b1ShortPair;
    stateBaseMod._tagToGroup['中字'] = b1ShortPair;

    // ⚠ 用完必須清掉（Opus 復驗抓到）：這兩個 key 若留在共享 _tagToGroup 裡，
    // 檔尾 121b-T2 的 cold/warm 測試就會在 init() 根本沒合併 manifest 的情況下也綠
    // ——實測：拿掉 init() 內那行 await 時，原本轉紅的 cold/warm 會退化成綠，
    // 只剩字面錨點那條抓得到。清掉才維持「測試順序無關」。
    try {
        _setVideos([
            { number: 'B1-HAND', title: 'HandTagged', maker: '', tags: '', actresses: '', user_tags: ['中字'] },
            { number: 'B1-MISS', title: 'NoTags', maker: '', tags: '', actresses: '', user_tags: [] },
            { number: 'B1-OTHER', title: 'Unrelated', maker: '', tags: '痴女', actresses: '', user_tags: ['重看'] },
        ]);
        const c = makeComponent({ pills: [{ dim: 'tag', value: '中文字幕' }] });
        c.applyFilterAndSort(true);
        const numbers = _filteredVideos.map((v) => v.number);
        assert.ok(numbers.includes('B1-HAND'), '手貼 中字 的片必須命中 中文字幕 pill');
        assert.ok(!numbers.includes('B1-MISS'), '無標籤對照片不得命中');
        assert.ok(!numbers.includes('B1-OTHER'), '無關標籤對照片不得命中');
        assert.equal(numbers.length, 1);
        assert.equal(_filteredVideos[0].number, 'B1-HAND');
    } finally {
        delete stateBaseMod._tagToGroup['中文字幕'];
        delete stateBaseMod._tagToGroup['中字'];
    }
});

test('B4 端到端：清空 user_tags 版結果集 ⊆ 保留版（既有 tag 篩選不因 121b 縮小）', () => {
    const pill = [{ dim: 'tag', value: '痴女' }];
    const clearVideos = [
        { number: 'B4-TAGS', title: 'TagsHit', maker: '', tags: '痴女', actresses: '', user_tags: [] },
        { number: 'B4-USER', title: 'UserOnly', maker: '', tags: '', actresses: '', user_tags: [] },
        { number: 'B4-MISS', title: 'NoHit', maker: '', tags: '中出', actresses: '', user_tags: [] },
    ];
    const keptVideos = [
        { number: 'B4-TAGS', title: 'TagsHit', maker: '', tags: '痴女', actresses: '', user_tags: ['重看'] },
        { number: 'B4-USER', title: 'UserOnly', maker: '', tags: '', actresses: '', user_tags: ['痴女'] },
        { number: 'B4-MISS', title: 'NoHit', maker: '', tags: '中出', actresses: '', user_tags: ['重看'] },
    ];

    _setVideos(clearVideos);
    const cClear = makeComponent({ pills: pill });
    cClear.applyFilterAndSort(true);
    const filteredClearIds = _filteredVideos.map((v) => v.number);

    _setVideos(keptVideos);
    const cKept = makeComponent({ pills: pill });
    cKept.applyFilterAndSort(true);
    const filteredKeptIds = _filteredVideos.map((v) => v.number);

    for (const id of filteredClearIds) {
        assert.ok(filteredKeptIds.includes(id), `number ${id} 在保留 user_tags 後消失（篩選不得變窄）`);
    }
    assert.ok(filteredClearIds.includes('B4-TAGS'), '靠 tags 命中的片兩份都應在結果裡');
    assert.ok(filteredKeptIds.includes('B4-TAGS'));
    assert.ok(filteredKeptIds.includes('B4-USER'), '只靠 user_tags 命中的片必須只在 kept 版');
    assert.ok(!filteredClearIds.includes('B4-USER'), '清空版不得因 user_tags 命中（子集斷言才有內容）');
    assert.ok(!filteredClearIds.includes('B4-MISS'));
    assert.ok(!filteredKeptIds.includes('B4-MISS'));
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

// =====================================================================
// TASK-121b-T2 — CoverBadgeManifest / mergeAliasPair
// =====================================================================
//
// 冪等 guard `_coverBadgeManifestLoaded` 是 module-level 的：一旦某條測試把它
// 設為 true，同 module instance 後續再呼叫 loader 就是 no-op。失敗分支必須能
// 在成功分支之前真正跑到 catch，而 cold/warm 又要走 shared module 的 init()。
// 因此 loader 的成功／失敗／空陣列測試用 query-string 獨立 instance（不依賴
// 重複呼叫 shared loader）；cold/warm 才打 shared 的 init()。

const COVER_BADGE_MANIFEST_FIVE = [
    { id: 'zh-sub', canonical_tag: '中文字幕', display_name: '中字', match_aliases: ['中文字幕', '中字', '字幕'], display_order: 1, i18n_key: 'cover.zh_sub' },
    { id: 'uncen-crack', canonical_tag: '無碼破解', display_name: '破解', match_aliases: ['無碼破解', '破解', '克破', 'AI'], display_order: 2, i18n_key: 'cover.crack' },
    { id: 'uncen-leak', canonical_tag: '無碼流出', display_name: '流出', match_aliases: ['無碼流出', '流出', 'leak'], display_order: 3, i18n_key: 'cover.leak' },
    { id: '4k', canonical_tag: '4K', display_name: '4K', match_aliases: ['4K'], display_order: 4, i18n_key: 'cover.4k' },
    { id: 'vr', canonical_tag: 'VR', display_name: 'VR', match_aliases: ['VR'], display_order: 5, i18n_key: 'cover.vr' },
];

async function importFreshStateBase(tag) {
    return import(`../state-base.js?coverBadge=${encodeURIComponent(tag)}`);
}

async function withStubFetch(handler, fn) {
    const orig = globalThis.fetch;
    globalThis.fetch = handler;
    try {
        return await fn();
    } finally {
        globalThis.fetch = orig;
    }
}

function manifestFetch(payload, { ok = true, throwError = null } = {}) {
    return async (url) => {
        if (url !== '/api/cover-badges/manifest') {
            throw new Error('pill-match.test.mjs: unexpected fetch url ' + url);
        }
        if (throwError) throw throwError;
        return { ok, json: async () => payload };
    };
}

test('CoverBadgeManifest 成功分支：五筆 stub 後 中字 與 中文字幕 同組', async () => {
    const fresh = await importFreshStateBase('success');
    assert.equal(typeof fresh._loadCoverBadgeManifest, 'function', '_loadCoverBadgeManifest 必須存在');
    await withStubFetch(manifestFetch(COVER_BADGE_MANIFEST_FIVE), () => fresh._loadCoverBadgeManifest());
    const byShort = fresh._tagToGroup['中字'];
    const byCanonical = fresh._tagToGroup['中文字幕'];
    assert.ok(Array.isArray(byShort), '_tagToGroup[中字] 應為陣列');
    assert.ok(Array.isArray(byCanonical), '_tagToGroup[中文字幕] 應為陣列');
    assert.ok(byShort.includes('中字') && byShort.includes('中文字幕'));
    assert.ok(byCanonical.includes('中字') && byCanonical.includes('中文字幕'));
    assert.equal(byShort, byCanonical, '兩個 key 必須指到同一組陣列');
});

test('CoverBadgeManifest 失敗分支：fetch 拋錯時既有 DB alias 群組原封不動', async () => {
    const fresh = await importFreshStateBase('fail');
    assert.equal(typeof fresh._loadCoverBadgeManifest, 'function', '_loadCoverBadgeManifest 必須存在');
    fresh._tagToGroup['女僕'] = ['女僕', 'メイド'];
    await assert.doesNotReject(() =>
        withStubFetch(
            manifestFetch(null, { throwError: new Error('network down') }),
            () => fresh._loadCoverBadgeManifest(),
        ),
    );
    assert.deepEqual(fresh._tagToGroup['女僕'], ['女僕', 'メイド']);
});

test('mergeAliasPair 三方群組合併：繁中/簡中 也能查到 中字', async () => {
    const { _mergeAliasPair } = await import('../state-base.js');
    assert.equal(typeof _mergeAliasPair, 'function', '_mergeAliasPair 必須存在');
    const map = {};
    const group = ['中文字幕', '繁中', '簡中'];
    for (const member of group) map[member.toLowerCase()] = group;
    _mergeAliasPair(map, '中文字幕', '中字');
    for (const key of ['中文字幕', '繁中', '簡中', '中字']) {
        const got = map[key.toLowerCase()];
        assert.ok(Array.isArray(got), `${key} 必須仍是陣列`);
        assert.ok(got.includes('中字'), `${key} 必須查得到 中字`);
        assert.ok(got.includes('中文字幕') && got.includes('繁中') && got.includes('簡中'));
    }
});

test('mergeAliasPair canonical 與 display_name 相同（4K/VR）不重複不拋例外', async () => {
    const { _mergeAliasPair } = await import('../state-base.js');
    assert.equal(typeof _mergeAliasPair, 'function', '_mergeAliasPair 必須存在');
    const map = {};
    assert.doesNotThrow(() => {
        _mergeAliasPair(map, '4K', '4K');
        _mergeAliasPair(map, 'VR', 'VR');
    });
    assert.ok(Array.isArray(map['4k']));
    assert.equal(map['4k'].length, 1);
    assert.equal(map['4k'][0], '4K');
    assert.ok(Array.isArray(map['vr']));
    assert.equal(map['vr'].length, 1);
    assert.equal(map['vr'][0], 'VR');
});

test('CoverBadgeManifest 空陣列 manifest：_tagToGroup 不變、不拋例外', async () => {
    const fresh = await importFreshStateBase('empty');
    assert.equal(typeof fresh._loadCoverBadgeManifest, 'function', '_loadCoverBadgeManifest 必須存在');
    fresh._tagToGroup['女僕'] = ['女僕', 'メイド'];
    await assert.doesNotReject(() =>
        withStubFetch(manifestFetch([]), () => fresh._loadCoverBadgeManifest()),
    );
    assert.deepEqual(fresh._tagToGroup['女僕'], ['女僕', 'メイド']);
    assert.equal(Object.keys(fresh._tagToGroup).length, 1);
});

test('CoverBadgeManifest cold/warm：pill 中文字幕 vs user_tags 中字（B1）', async () => {
    const videos = [{ tags: '', user_tags: ['中字'] }];
    const pills = [{ dim: 'tag', value: '中文字幕' }];
    const cold = videos.filter(buildPillPredicate(pills, {}, {}));
    assert.equal(cold.length, 0);

    // warm 必須走 init() 才鎖得住「第一次 applyFilterAndSort 前已併入短名」。
    // 若只餵本地 loaded map，init 漏 await 這條仍會綠——mutation A 就測不紅。
    const c = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    c.restoreState = () => {};
    c.fetchVideos = async () => {};
    c.applyFilterAndSort = () => {};
    c.updatePagination = () => {};
    c.loadActresses = () => {};
    // 129-T3：init() 新增了一個 _reconcileHeroCard() 呼叫，而它定義在 state-videos.js。
    // 本 harness 刻意只建 stateBase（不 merge stateVideos）以縮小 cold/warm 的變因，
    // 所以比照上面每一條 init 依賴的既有做法，補一個 stub。
    c._reconcileHeroCard = () => {};
    c.$watch = () => {};
    c.$nextTick = () => {};
    c.mode = 'list';
    const origAlpine = globalThis.Alpine;
    const origAddEventListener = globalThis.window.addEventListener;
    globalThis.Alpine = { store: () => ({ toolbarOpen: false, showcaseHasSearch: false }) };
    globalThis.window.__registerPage = () => {};
    globalThis.window.addEventListener = () => {};
    try {
        await withStubFetch(async (url) => {
            if (url === '/api/cover-badges/manifest') {
                return { ok: true, json: async () => COVER_BADGE_MANIFEST_FIVE };
            }
            return { ok: true, json: async () => ({ groups: [] }) };
        }, () => c.init());
    } finally {
        // 全域 stub 必須無條件還原：init() 若因未來的回歸拋例外，殘留的 Alpine /
        // addEventListener stub 會污染同檔後續測試，讓失敗訊息指向錯誤的地方。
        globalThis.Alpine = origAlpine;
        globalThis.window.addEventListener = origAddEventListener;
        delete globalThis.window.__registerPage;
    }

    const warm = videos.filter(buildPillPredicate(pills, {}, stateBaseMod._tagToGroup));
    assert.equal(warm.length, 1);
});

test('CoverBadgeManifest 順序錨點：await _loadCoverBadgeManifest 早於 applyFilterAndSort(true)', () => {
    const src = readFileSync(new URL('../state-base.js', import.meta.url), 'utf8');
    // 剝註解：mutation A 把 await 整行註解掉時必須轉 RED（裸 indexOf 會命中註解）。
    const stripped = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
    const idxCover = stripped.indexOf('await _loadCoverBadgeManifest()');
    const idxApply = stripped.indexOf('applyFilterAndSort(true)');
    assert.ok(idxCover !== -1 && idxApply !== -1, '兩個錨點字面必須存在');
    assert.ok(idxCover < idxApply, 'cover badge manifest 必須在第一次 applyFilterAndSort 之前載入');
});

test('CoverBadgeManifest 自由文字搜尋只會變寬：併入前命中 ⊆ 併入後命中', async () => {
    const { _mergeAliasPair } = await import('../state-base.js');
    assert.equal(typeof _mergeAliasPair, 'function', '_mergeAliasPair 必須存在');
    _setVideos([
        { id: 'w-exact', number: 'W-EXACT', title: '', maker: '', tags: 'WidenShort', actresses: '' },
        { id: 'w-alias', number: 'W-ALIAS', title: '', maker: '', tags: 'WidenCanonical', actresses: '' },
        { id: 'w-never', number: 'W-NEVER', title: '', maker: '', tags: 'UnrelatedTag', actresses: '' },
    ]);
    const c = makeComponent({ search: 'widenshort' });
    c.applyFilterAndSort(true);
    const beforeIds = _filteredVideos.map((v) => v.id);
    _mergeAliasPair(stateBaseMod._tagToGroup, 'WidenCanonical', 'WidenShort');
    c.applyFilterAndSort(true);
    const afterIds = _filteredVideos.map((v) => v.id);
    for (const id of beforeIds) {
        assert.ok(afterIds.includes(id), `id ${id} 在 manifest 併入後消失（搜尋不得變窄）`);
    }
});

// =====================================================================
// TASK-121c-T2 — mergeAliasGroup / loader 併整組 / _coverBadgeRules
// =====================================================================

test('mergeAliasGroup N 元：四個 key 同組含四成員且重複呼叫冪等', async () => {
    const { _mergeAliasGroup } = await import('../state-base.js');
    assert.equal(typeof _mergeAliasGroup, 'function', '_mergeAliasGroup 必須存在');
    const map = {};
    const members = ['無碼破解', '破解', '克破', 'AI'];
    _mergeAliasGroup(map, members);
    const first = map['無碼破解'.toLowerCase()];
    assert.ok(Array.isArray(first), 'canonical key 必須是陣列');
    assert.equal(first.length, 4, '該組必須含四個成員');
    for (const key of members) {
        const got = map[key.toLowerCase()];
        assert.equal(got, first, `${key} 必須指到同一組陣列`);
        for (const m of members) {
            assert.ok(got.includes(m), `${key} 必須含 ${m}`);
        }
    }
    _mergeAliasGroup(map, members);
    assert.equal(map['無碼破解'.toLowerCase()].length, 4, '重複呼叫不得長出重複值');
    assert.doesNotThrow(() => {
        _mergeAliasGroup(map, []);
        _mergeAliasGroup(map, ['單獨']);
        _mergeAliasGroup(map, ['破解', '破解', '克破']);
        _mergeAliasGroup(map, ['無碼破解', null, undefined, '', '克破']);
    });
});

test('mergeAliasGroup 與既有 DB alias 群組相交時取聯集', async () => {
    const { _mergeAliasGroup } = await import('../state-base.js');
    assert.equal(typeof _mergeAliasGroup, 'function', '_mergeAliasGroup 必須存在');
    const map = {};
    const dbGroup = ['無碼破解', '裏'];
    for (const member of dbGroup) map[member.toLowerCase()] = dbGroup;
    _mergeAliasGroup(map, ['無碼破解', '破解', '克破', 'AI']);
    const got = map['裏'.toLowerCase()];
    assert.ok(Array.isArray(got), '裏 必須仍是陣列');
    assert.ok(got.includes('克破'), '裏 必須查得到 克破');
    assert.ok(got.includes('無碼破解') && got.includes('破解') && got.includes('AI'));
    assert.equal(map['克破'.toLowerCase()], got, '克破 與 裏 必須指到同一組陣列');
});

test('CoverBadgeManifest 接線：loader 讀 match_aliases 後 破解 與 無碼破解 同組', async () => {
    const fresh = await importFreshStateBase('wiring-match-aliases');
    assert.equal(typeof fresh._loadCoverBadgeManifest, 'function', '_loadCoverBadgeManifest 必須存在');
    // display_name 用 T1 真值 AI，讓 破解 只出現在 match_aliases——
    // 這樣 loader 若只併 canonical + display_name，_tagToGroup['破解'] 就查不到 無碼破解。
    const payload = COVER_BADGE_MANIFEST_FIVE.map((item) => (
        item.id === 'uncen-crack' ? { ...item, display_name: 'AI' } : item
    ));
    await withStubFetch(manifestFetch(payload), () => fresh._loadCoverBadgeManifest());
    const byCrack = fresh._tagToGroup['破解'];
    const byCanonical = fresh._tagToGroup['無碼破解'];
    assert.ok(Array.isArray(byCrack), '_tagToGroup[破解] 應為陣列');
    assert.ok(Array.isArray(byCanonical), '_tagToGroup[無碼破解] 應為陣列');
    assert.ok(byCrack.includes('破解') && byCrack.includes('無碼破解'));
    assert.ok(byCanonical.includes('破解') && byCanonical.includes('無碼破解'));
    assert.equal(byCrack, byCanonical, '兩個 key 必須指到同一組陣列');
    assert.equal(fresh._coverBadgeRules.length, 5);
    assert.equal(fresh._coverBadgeRules[0].display_name, '中字');
});

test('CoverBadgeManifest 失敗分支：fetch 拋錯時 _coverBadgeRules 維持空陣列', async () => {
    const fresh = await importFreshStateBase('fail-rules');
    assert.equal(typeof fresh._loadCoverBadgeManifest, 'function', '_loadCoverBadgeManifest 必須存在');
    fresh._tagToGroup['女僕'] = ['女僕', 'メイド'];
    await assert.doesNotReject(() =>
        withStubFetch(
            manifestFetch(null, { throwError: new Error('network down') }),
            () => fresh._loadCoverBadgeManifest(),
        ),
    );
    assert.deepEqual(fresh._coverBadgeRules, []);
    assert.deepEqual(fresh._tagToGroup['女僕'], ['女僕', 'メイド']);
});
