// TASK-116a-T3: 燈箱三格可點——_actressCoreMetadataParts() 取代 _actressCoreMetadata()（CD-116a-6）。
//
// state-actress.js 用瀏覽器 importmap 別名；plain node --test 不認得。
// 比照 actress-pill-state.test.mjs，本檔自帶 resolve hook（FE-GUARD-11）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import { readFileSync } from 'node:fs';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// state-base.js 模組頂層讀 localStorage（清壞值）。
globalThis.window = globalThis;
// identity mock：測試只驗證「呼叫了哪個 key」與「join 順序/分隔符」，不驗真正翻譯字串
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

const { stateActress } = await import('../state-actress.js');

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '../../../../../..');

/**
 * 合併 harness——本檔只需要 stateActress()（_actressCoreMetadataParts /
 * _onActressMetadataClick / _actressPillDisplayText 都定義在其上），
 * closeLightbox/addActressPill 用 spy 取代（前者屬 state-lightbox.js，
 * 依卡片「不准碰」清單本檔不 import 它）。
 */
function makeComponent(overrides) {
    const actress = stateActress();
    const calls = [];
    const c = Object.assign({}, actress, {
        currentLightboxActress: null,
        actressLightboxSource: 'grid',
        closeLightbox() { calls.push(['closeLightbox']); },
        addActressPill(dim, value) { calls.push(['addActressPill', dim, value]); },
    }, overrides);
    c.__calls = calls;
    return c;
}

// ── 舊版演算法手抄對照（不 import 舊函式，它已被整段取代刪除）──────────────
// 逐字抄自 T3 之前的 state-actress.js:499-511（TASK-116a-T3.md B 項已核對）。
function legacyActressCoreMetadata(a) {
    if (!a) return '';
    const parts = [];
    if (typeof a.video_count === 'number') {
        parts.push(a.video_count + window.t('showcase.unit.films'));
    }
    if (a.age) parts.push(a.age + window.t('search.unit.age'));
    if (a.birth) parts.push(a.birth);
    if (a.height) parts.push(a.height);
    if (a.cup) parts.push(a.cup + window.t('search.unit.cup'));
    if (a.bust && a.waist && a.hip) parts.push(a.bust + '-' + a.waist + '-' + a.hip);
    return parts.join(' · ');
}

function joinParts(parts) {
    return parts.map((p) => p.text).join(' · ');
}

// ── AC1：六格白名單，grid 路徑逐格驗證（不是抽樣）──────────────────────────

const FULL_ACTRESS = {
    video_count: 12,
    age: 28,
    birth: '1997-01-01',
    height: '160cm',
    cup: 'C',
    bust: 88, waist: 58, hip: 90,
};

test('grid 路徑：六格逐一驗證 clickable 白名單（作品數/生日/三圍恆 false，年齡/身高/罩杯 true）', () => {
    const c = makeComponent({ currentLightboxActress: FULL_ACTRESS, actressLightboxSource: 'grid' });
    const parts = c._actressCoreMetadataParts();
    const byKey = Object.fromEntries(parts.map((p) => [p.key, p]));

    assert.equal(parts.length, 6, `預期 6 格，實際 ${parts.length}`);

    assert.equal(byKey.count.clickable, false, '作品數不可點');
    assert.ok(!('dim' in byKey.count), '作品數不應帶 dim');

    assert.equal(byKey.age.clickable, true, '年齡（grid 路徑）應可點');
    assert.equal(byKey.age.dim, 'age');
    assert.equal(byKey.age.value, FULL_ACTRESS.age);

    assert.equal(byKey.birth.clickable, false, '生日不可點');
    assert.ok(!('dim' in byKey.birth), '生日不應帶 dim');

    assert.equal(byKey.height.clickable, true, '身高（grid 路徑）應可點');
    assert.equal(byKey.height.dim, 'height');
    assert.equal(byKey.height.value, FULL_ACTRESS.height);

    assert.equal(byKey.cup.clickable, true, '罩杯（grid 路徑）應可點');
    assert.equal(byKey.cup.dim, 'cup');
    assert.equal(byKey.cup.value, FULL_ACTRESS.cup);

    assert.equal(byKey.bwh.clickable, false, '三圍不可點');
    assert.ok(!('dim' in byKey.bwh), '三圍不應帶 dim');
});

// ── AC2：hero 路徑，全部 part 皆不可點 ──────────────────────────────────────

test('hero 路徑：_actressCoreMetadataParts() 全部 part 的 clickable 為 false', () => {
    const c = makeComponent({ currentLightboxActress: FULL_ACTRESS, actressLightboxSource: 'hero' });
    const parts = c._actressCoreMetadataParts();
    assert.equal(parts.length, 6);
    for (const p of parts) {
        assert.equal(p.clickable, false, `hero 路徑下 ${p.key} 不應可點`);
    }
});

// ── 呼叫序列：closeLightbox() 先於 addActressPill(dim, value) ──────────────

test('_onActressMetadataClick：先 closeLightbox() 再 addActressPill(dim, value)（FE-ALPINE-04）', () => {
    const c = makeComponent({ currentLightboxActress: FULL_ACTRESS, actressLightboxSource: 'grid' });
    c._onActressMetadataClick('height', '160cm');
    assert.deepEqual(c.__calls, [
        ['closeLightbox'],
        ['addActressPill', 'height', '160cm'],
    ]);
});

test('_onActressMetadataClick：hero 路徑（防禦性 gate）不呼叫任何函式', () => {
    const c = makeComponent({ currentLightboxActress: FULL_ACTRESS, actressLightboxSource: 'hero' });
    c._onActressMetadataClick('height', '160cm');
    assert.deepEqual(c.__calls, [], '防禦性 gate 應擋下呼叫，無副作用');
});

// ── 視覺零回歸：多組缺值組合下，join 輸出與舊版逐字相同（至少 5 組）────────

const REGRESSION_FIXTURES = [
    { name: '全有值', actress: FULL_ACTRESS },
    { name: '缺身高', actress: { video_count: 5, age: 30, birth: '1995-05-05', height: '', cup: 'D', bust: 85, waist: 60, hip: 88 } },
    { name: '缺罩杯', actress: { video_count: 3, age: 22, birth: '2003-03-03', height: '158cm', cup: '', bust: 80, waist: 55, hip: 82 } },
    { name: '缺三圍（僅 bust）', actress: { video_count: 8, age: 26, birth: '1999-09-09', height: '165cm', cup: 'B', bust: 86, waist: 0, hip: 0 } },
    { name: '只有作品數', actress: { video_count: 40, age: 0, birth: '', height: '', cup: '', bust: 0, waist: 0, hip: 0 } },
    { name: '缺年齡與生日', actress: { video_count: 1, age: 0, birth: '', height: '150cm', cup: 'A', bust: 78, waist: 54, hip: 80 } },
    { name: '完全空（無任何欄位）', actress: {} },
];

for (const { name, actress } of REGRESSION_FIXTURES) {
    test(`視覺零回歸（${name}）：_actressCoreMetadataParts() join 與舊版逐字相同`, () => {
        const c = makeComponent({ currentLightboxActress: actress, actressLightboxSource: 'grid' });
        const parts = c._actressCoreMetadataParts();
        assert.equal(joinParts(parts), legacyActressCoreMetadata(actress));
    });
}

test('currentLightboxActress 為 null 時回傳空陣列（比照舊版回傳空字串）', () => {
    const c = makeComponent({ currentLightboxActress: null, actressLightboxSource: 'grid' });
    assert.deepEqual(c._actressCoreMetadataParts(), []);
    assert.equal(legacyActressCoreMetadata(null), '');
});

// ── _actressPillDisplayText（CD-116a-6b）───────────────────────────────────

test('_actressPillDisplayText：age 附加單位、height 不附加（值已含 cm）、cup 附加單位', () => {
    const c = makeComponent();
    assert.equal(c._actressPillDisplayText({ dim: 'age', op: '=', value: '28' }), '=28search.unit.age');
    assert.equal(c._actressPillDisplayText({ dim: 'height', op: '=', value: '160cm' }), '=160cm');
    assert.equal(c._actressPillDisplayText({ dim: 'cup', op: '=', value: 'C' }), '=Csearch.unit.cup');
});

// ── `.lb-actress-core-value` 是原生 <button type="button">（機械證明，非 <span>）──

test('showcase.html：.lb-actress-core-value 是原生 <button type="button">，非 <span>', () => {
    const SHOWCASE_HTML = readFileSync(
        path.join(REPO_ROOT, 'web/templates/showcase.html'),
        'utf8',
    );
    assert.ok(
        /<button\s+type="button"\s+class="lb-actress-core-value"/.test(SHOWCASE_HTML),
        '.lb-actress-core-value 應是 <button type="button">',
    );
    assert.ok(
        !/<span\b[^>]*\bclass="lb-actress-core-value"/.test(SHOWCASE_HTML),
        '.lb-actress-core-value 不得是 <span>',
    );
});
