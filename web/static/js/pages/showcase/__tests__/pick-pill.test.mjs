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

const { stateVideos } = await import('../state-videos.js');

function makeComponent(overrides) {
    const c = Object.assign({}, stateVideos(), {
        pills: [],
        search: '',
        actressSearch: '',
        sort: 'title',
        order: 'asc',
        animateCalls: 0,
        heroCalls: 0,
        _clearPreciseMatch() {},
        _checkPreciseActressMatch() {},
        applyActressFilterAndSort() {},
    }, overrides);
    c._animateFilter = function () { c.animateCalls++; };
    c._reconcileHeroCard = function () { c.heroCalls++; };
    return c;
}

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

test('pick 分支：video.user_rating 為 undefined → 不 match（|| 兜底）', () => {
    const predicate = buildPillPredicate([{ dim: 'pick', value: '1' }], {}, {});
    assert.equal(predicate({}), false);
    assert.equal(predicate({ user_rating: undefined }), false);
});

test('pick 分支：video.user_rating 為 null → 不 match（|| 兜底）', () => {
    const predicate = buildPillPredicate([{ dim: 'pick', value: '1' }], {}, {});
    assert.equal(predicate({ user_rating: null }), false);
});

test('AC-9：pick pill 與 actress pill 同時掛 → 取交集', () => {
    const nameToGroup = {};
    const predicate = buildPillPredicate(
        [{ dim: 'pick', value: '1' }, { dim: 'actress', value: 'A' }],
        nameToGroup, {},
    );
    // 精選但女優不符 → 不 match
    assert.equal(predicate({ user_rating: 1, actresses: 'B' }), false);
    // 女優符合但未精選 → 不 match
    assert.equal(predicate({ user_rating: 0, actresses: 'A' }), false);
    // 兩者皆符合 → match
    assert.equal(predicate({ user_rating: 1, actresses: 'A' }), true);
});

test('末尾 fail-closed 出口不受 pick 分支影響：未知 dim 仍回 false', () => {
    const predicate = buildPillPredicate([{ dim: 'typo', value: 'x' }], {}, {});
    assert.equal(predicate({ user_rating: 1 }), false);
});

// =====================================================================
// Part B — togglePickPill() / _hasPickPill() / pillLabel()
// =====================================================================

test('_hasPickPill：pills 不含 pick → false；含 pick → true', () => {
    const c1 = makeComponent();
    assert.equal(c1._hasPickPill(), false);

    const c2 = makeComponent({ pills: [{ dim: 'pick', value: '1' }] });
    assert.equal(c2._hasPickPill(), true);
});

test('togglePickPill：未掛精選時呼叫 → addPill 進去，pills 含恰好一枚 {dim:"pick", value:"1"}', () => {
    const c = makeComponent();
    c.togglePickPill();
    assert.equal(c.pills.length, 1);
    assert.deepEqual(c.pills[0], { dim: 'pick', value: '1' });
    assert.equal(c._hasPickPill(), true);
});

test('togglePickPill：已掛精選時呼叫 → removePill 拿掉，pills 不再含 pick', () => {
    const c = makeComponent({ pills: [{ dim: 'pick', value: '1' }] });
    c.togglePickPill();
    assert.equal(c.pills.length, 0);
    assert.equal(c._hasPickPill(), false);
});

test('邊界條件 1：連點兩次「只看精選」→ 第一次 add、第二次 remove，pills 回到不含 pick 的狀態', () => {
    const c = makeComponent();
    c.togglePickPill();
    assert.equal(c._hasPickPill(), true);
    c.togglePickPill();
    assert.equal(c._hasPickPill(), false);
    assert.equal(c.pills.length, 0);
});

test('AC-10：pill 的 × 與選單那條等價 —— removePill 直接呼叫 與 togglePickPill（已掛狀態）結果相同', () => {
    const cViaChip = makeComponent({ pills: [{ dim: 'pick', value: '1' }] });
    cViaChip.removePill('pick', '1');

    const cViaMenu = makeComponent({ pills: [{ dim: 'pick', value: '1' }] });
    cViaMenu.togglePickPill();

    assert.deepEqual(cViaChip.pills, cViaMenu.pills);
    assert.equal(cViaChip._hasPickPill(), false);
    assert.equal(cViaMenu._hasPickPill(), false);
});

test('AC-8：togglePickPill() 呼叫前後 this.sort 與 this.order 逐位元組不變（精選是篩選不是排序，兩者正交）', () => {
    const c = makeComponent({ sort: 'mdate', order: 'desc' });
    c.togglePickPill();
    assert.equal(c.sort, 'mdate');
    assert.equal(c.order, 'desc');
    // 再次呼叫（remove 分支）也不變
    c.togglePickPill();
    assert.equal(c.sort, 'mdate');
    assert.equal(c.order, 'desc');
});

test('togglePickPill 複用既有 addPill/removePill 的副作用鏈：_animateFilter/_reconcileHeroCard 各呼叫一次', () => {
    const cAdd = makeComponent();
    cAdd.togglePickPill();
    assert.equal(cAdd.animateCalls, 1);
    assert.equal(cAdd.heroCalls, 1);

    const cRemove = makeComponent({ pills: [{ dim: 'pick', value: '1' }] });
    cRemove.togglePickPill();
    assert.equal(cRemove.animateCalls, 1);
    assert.equal(cRemove.heroCalls, 1);
});

test('pillLabel：pick dim → 走 i18n key showcase.pick.chip_label（非直接顯示 value "1"）', () => {
    const c = makeComponent();
    assert.equal(c.pillLabel({ dim: 'pick', value: '1' }), 'showcase.pick.chip_label');
});

test('pillLabel：非 pick dim → 逐字回傳 pill.value（其餘 dim 不特判）', () => {
    const c = makeComponent();
    assert.equal(c.pillLabel({ dim: 'actress', value: 'AliasActressA' }), 'AliasActressA');
    assert.equal(c.pillLabel({ dim: 'maker', value: 'S1' }), 'S1');
    assert.equal(c.pillLabel({ dim: 'tag', value: '痴女' }), '痴女');
});
