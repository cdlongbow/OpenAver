// TASK-116a-T3: 女優工具列 pill 視覺殼（markup + bindings）結構契約。
// 技術比照 pill-shell.test.mjs：以文字解析 showcase.html / zh_TW.json，
// 不跑 CDP、不動 Alpine runtime、不需要 window/importmap（純文字讀取，FE-GUARD-11 後者不適用本檔）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// 本檔：web/static/js/pages/showcase/__tests__/ → 上五層 = repo root
const REPO_ROOT = path.resolve(__dirname, '../../../../../..');
const SHOWCASE_HTML = readFileSync(
    path.join(REPO_ROOT, 'web/templates/showcase.html'),
    'utf8',
);
const ZH_TW = JSON.parse(
    readFileSync(path.join(REPO_ROOT, 'locales/zh_TW.json'), 'utf8'),
);

/**
 * 抽出 class="filter-pill-group actress-filter-pill-group" 起的那一個元素 markup
 * （含內層，depth-aware）。仿 pill-shell.test.mjs 的 extractFilterPillGroup()，
 * 但錨定女優容器獨有的複合 class 字面（含順序）——TASK-116a-T3.md E 項的建議：
 * 若順序寫反（"actress-filter-pill-group filter-pill-group"）這個 regex 抓不到，
 * 這是期望行為，class 屬性值的字面順序也是契約的一部分（plan CD-116a-4）。
 */
function extractActressFilterPillGroup(html) {
    const openRe = /<div\b[^>]*\bclass="filter-pill-group actress-filter-pill-group"[^>]*>/;
    const m = openRe.exec(html);
    assert.ok(m, 'showcase.html 應含 class="filter-pill-group actress-filter-pill-group" 的容器');
    const start = m.index;
    let i = start + m[0].length;
    let depth = 1;
    while (i < html.length && depth > 0) {
        const nextOpen = html.indexOf('<div', i);
        const nextClose = html.indexOf('</div>', i);
        if (nextClose === -1) break;
        if (nextOpen !== -1 && nextOpen < nextClose) {
            depth++;
            i = nextOpen + 4;
        } else {
            depth--;
            i = nextClose + 6;
            if (depth === 0) {
                return html.slice(start, i);
            }
        }
    }
    throw new Error('actress-filter-pill-group 未找到匹配的 </div>');
}

const GROUP = extractActressFilterPillGroup(SHOWCASE_HTML);

// ===== 容器唯一性（複合 class，不撞既有「恰有一個 filter-pill-group」守衛）=====

test('showcase.html 恰有一個 filter-pill-group actress-filter-pill-group 容器', () => {
    const matches = SHOWCASE_HTML.match(/class="filter-pill-group actress-filter-pill-group"/g) || [];
    assert.equal(matches.length, 1, `預期恰好 1 個，實際 ${matches.length}`);
});

test('裸 class="filter-pill-group" 的計數仍是 1（女優容器不撞既有 pill-shell.test.mjs 守衛）', () => {
    // 這條與 pill-shell.test.mjs 的「恰有一個 filter-pill-group 容器」同一件事，
    // 在本檔重複驗證是為了讓 CD-116a-4 的可證偽承諾在女優這支測試檔內也自成立，
    // 不依賴讀者去跳讀另一個檔案。
    const matches = SHOWCASE_HTML.match(/class="filter-pill-group"/g) || [];
    assert.equal(matches.length, 1, `裸 filter-pill-group 應仍為 1（影片版），實際 ${matches.length}`);
});

test('女優容器帶 x-show="showFavoriteActresses"（掛在外層 div，不留在 input 上）', () => {
    assert.ok(
        /class="filter-pill-group actress-filter-pill-group"[^>]*x-show="showFavoriteActresses"/.test(SHOWCASE_HTML)
            || /x-show="showFavoriteActresses"[^>]*class="filter-pill-group actress-filter-pill-group"/.test(SHOWCASE_HTML),
        'x-show="showFavoriteActresses" 應掛在 .actress-filter-pill-group 外層 div',
    );
    // input 本身不應再帶 x-show（留在 input 上會讓 wrapper 在影片模式也佔版面）
    const inputTag = GROUP.match(/<input\b[^>]*>/);
    assert.ok(inputTag, '容器內應有 <input>');
    assert.ok(
        !/x-show=/.test(inputTag[0]),
        `input 本身不應帶 x-show（應搬到外層 div）：${inputTag[0]}`,
    );
});

// ===== role="list" 落點（只包 pill，不包 input）=====

test('role="list" 只包 pill、不包 input（list 的合法子元素只有 listitem）', () => {
    assert.ok(
        !/class="filter-pill-group actress-filter-pill-group"[^>]*\brole="list"/.test(SHOWCASE_HTML),
        'actress-filter-pill-group（含 input）不得直接帶 role="list"',
    );
    assert.ok(
        /class="filter-pill-list"[^>]*\brole="list"/.test(GROUP),
        'role="list" 應落在只包 pill 的 .filter-pill-list 上',
    );
    assert.ok(
        /class="filter-pill-list"[^>]*x-show="actressPills\.length"/.test(GROUP),
        'actressPills 為空時應收起清單，避免報出「0 個項目的清單」',
    );
});

test('每枚女優 pill 帶 role="listitem"', () => {
    assert.ok(
        /class="filter-pill"[^>]*\brole="listitem"/.test(GROUP)
            || /role="listitem"[^>]*\bclass="filter-pill"/.test(GROUP),
        '.filter-pill（女優）應帶 role="listitem"',
    );
});

// ===== x-for + 單一 :key（CD-116a-4：只用 pill.dim，非複合鍵）=====

test('x-for 遍歷 actressPills，:key="pill.dim"（單一鍵，同維度只允許一枚）', () => {
    assert.ok(
        /x-for="pill in actressPills"/.test(GROUP),
        '應有 x-for="pill in actressPills"',
    );
    const keyAttr = GROUP.match(/:key="([^"]+)"/);
    assert.ok(keyAttr, 'x-for template 應有 :key 綁定');
    assert.equal(
        keyAttr[1].trim(),
        'pill.dim',
        `:key 應恰為 "pill.dim"（CD-116a-4：不需要複合鍵），實際：${keyAttr[1]}`,
    );
});

// ===== pill 顯示文字：_actressPillDisplayText(pill)，非裸 pill.value =====

test('pill 顯示文字綁 _actressPillDisplayText(pill)（CD-116a-6b，非影片版的裸 pill.value）', () => {
    assert.ok(
        /class="filter-pill-value"[^>]*x-text="_actressPillDisplayText\(\s*pill\s*\)"/.test(GROUP),
        '.filter-pill-value 應綁 x-text="_actressPillDisplayText(pill)"',
    );
});

// ===== ✕ 移除鈕契約 =====

test('✕ 綁 removeActressPill(pill.dim, pill.value)，參數順序與 addActressPill(dim, value) 一致', () => {
    assert.ok(
        /@click="removeActressPill\(\s*pill\.dim\s*,\s*pill\.value\s*\)"/.test(GROUP),
        '✕ 應綁 @click="removeActressPill(pill.dim, pill.value)"',
    );
});

test('✕ 有 :aria-label 綁定，沿用既有 showcase.pill.remove_aria（不需新 key）', () => {
    assert.ok(
        /:aria-label="t\('showcase\.pill\.remove_aria'/.test(GROUP),
        '✕ 應以 :aria-label="t(\'showcase.pill.remove_aria\', ...)" 綁定',
    );
});

// ===== placeholder 收合（有 pill 時收起提示字，不補靜態 fallback）=====

test('女優搜尋框 :placeholder 條件綁定含 actressPills.length，回落 showcase.search.actress', () => {
    const ph = GROUP.match(/:placeholder="([^"]+)"/);
    assert.ok(ph, '女優搜尋框應有 :placeholder 綁定');
    const expr = ph[1];
    assert.ok(
        expr.includes('actressPills.length'),
        `:placeholder 應條件於 actressPills.length，實際：${expr}`,
    );
    assert.ok(
        expr.includes("t('showcase.search.actress')") || expr.includes('t("showcase.search.actress")'),
        `:placeholder 無 pill 時應回落 showcase.search.actress，實際：${expr}`,
    );
});

test('女優搜尋框不補靜態 placeholder="..." fallback（現況既有不對稱，本 task 不順手補）', () => {
    const inputTag = GROUP.match(/<input\b[^>]*>/);
    assert.ok(inputTag, '容器內應有 <input>');
    assert.ok(
        !/\splaceholder="/.test(inputTag[0]),
        `女優 input 不應有靜態 placeholder="..." fallback（僅 :placeholder 動態綁定）：${inputTag[0]}`,
    );
});

// ===== i18n key 存在性：三個新 dim_label key =====

const EXPECTED_NEW_DIM_LABELS = {
    'showcase.pill.dim_label.age': '年齡',
    'showcase.pill.dim_label.height': '身高',
    'showcase.pill.dim_label.cup': '罩杯',
};

function lookupNested(obj, dotted) {
    return dotted.split('.').reduce(
        (acc, part) => (acc && typeof acc === 'object' ? acc[part] : undefined),
        obj,
    );
}

test('locales/zh_TW.json 新增 dim_label.age/height/cup 三個 key，值與既有 showcase.sort.actress 措辭一致', () => {
    for (const [key, expected] of Object.entries(EXPECTED_NEW_DIM_LABELS)) {
        const actual = lookupNested(ZH_TW, key);
        assert.equal(
            actual,
            expected,
            `zh_TW 缺/錯 key ${key}：期望 ${JSON.stringify(expected)}，實際 ${JSON.stringify(actual)}`,
        );
    }
});

test('既有六個 dim_label（actress/tag/maker/director/series/label）不受影響', () => {
    const EXISTING = {
        'showcase.pill.dim_label.actress': '女優',
        'showcase.pill.dim_label.tag': '標籤',
        'showcase.pill.dim_label.maker': '片商',
        'showcase.pill.dim_label.director': '導演',
        'showcase.pill.dim_label.series': '系列',
        'showcase.pill.dim_label.label': '廠牌',
    };
    for (const [key, expected] of Object.entries(EXISTING)) {
        assert.equal(lookupNested(ZH_TW, key), expected, `既有 key 不應被本 task 改動：${key}`);
    }
});

test('模板用到的每一個 t(\'showcase.pill...\') key 都存在於 zh_TW.json（含動態 dim_label）', () => {
    const literalKeys = new Set();
    const re = /t\(\s*'((?:showcase\.pill)[^']*)'/g;
    let m;
    while ((m = re.exec(GROUP)) !== null) {
        const k = m[1];
        if (k.endsWith('.')) continue;   // 動態前綴另驗
        literalKeys.add(k);
    }
    assert.ok(literalKeys.has('showcase.pill.remove_aria'), '模板應引用 showcase.pill.remove_aria');
    for (const key of literalKeys) {
        assert.notEqual(lookupNested(ZH_TW, key), undefined, `模板引用的 key 不存在於 zh_TW.json：${key}`);
    }

    // 動態 dim_label 前綴：本容器會用到的三個新維度全部必須存在
    for (const dim of ['age', 'height', 'cup']) {
        const key = `showcase.pill.dim_label.${dim}`;
        assert.notEqual(lookupNested(ZH_TW, key), undefined, `動態 dim_label 維度 key 不存在：${key}`);
    }
    assert.ok(
        /t\(\s*'showcase\.pill\.dim_label\.'\s*\+\s*pill\.dim\s*\)/.test(GROUP),
        "模板應使用 t('showcase.pill.dim_label.' + pill.dim) 動態查表",
    );
});
