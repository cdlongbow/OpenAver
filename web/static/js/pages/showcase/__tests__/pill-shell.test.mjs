// TASK-115-T5: pill UI 殼（markup + bindings）結構契約。
// 技術比照 pill-entry.test.mjs：以文字解析 showcase.html / zh_TW.json，
// 不跑 CDP、不動 Alpine runtime。

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

/** 抽出 class="filter-pill-group" 起的那一個元素 markup（含內層，depth-aware）。 */
function extractFilterPillGroup(html) {
    const openRe = /<div\b[^>]*\bclass="filter-pill-group"[^>]*>/;
    const m = openRe.exec(html);
    assert.ok(m, 'showcase.html 應含 class="filter-pill-group" 的容器');
    const start = m.index;
    // 從 open tag 的 `>` 之後開始 brace-match 元素深度（用 tag open/close 計數）
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
    throw new Error('filter-pill-group 未找到匹配的 </div>');
}

const GROUP = extractFilterPillGroup(SHOWCASE_HTML);

// ===== 容器唯一性 + list 語意 =====

test('showcase.html 恰有一個 filter-pill-group 容器', () => {
    const matches = SHOWCASE_HTML.match(/class="filter-pill-group"/g) || [];
    assert.equal(matches.length, 1, `預期恰好 1 個 filter-pill-group，實際 ${matches.length}`);
});

test('role="list" 只包 pill、不包 input（list 的合法子元素只有 listitem）', () => {
    // Opus review 修正：原版把 role="list" 放在 .filter-pill-group 上，而該容器同時裝著
    // 搜尋 <input>。ARIA 規定 list 的 owned element 只能是 listitem，把輸入框圈進去會讓
    // 螢幕閱讀器數不對「目前有幾個條件」——那正是 spec §6.7 要這條語意的唯一理由。
    assert.ok(
        !/class="filter-pill-group"[^>]*\brole="list"/.test(SHOWCASE_HTML)
            && !/role="list"[^>]*\bclass="filter-pill-group"/.test(SHOWCASE_HTML),
        'filter-pill-group（含 input）不得直接帶 role="list"',
    );
    assert.ok(
        /class="filter-pill-list"[^>]*\brole="list"/.test(SHOWCASE_HTML),
        'role="list" 應落在只包 pill 的 .filter-pill-list 上',
    );
    assert.ok(
        /class="filter-pill-list"[^>]*x-show="pills\.length"/.test(SHOWCASE_HTML),
        'pills 為空時應收起清單，避免報出「0 個項目的清單」',
    );
});

test('每枚 pill 帶 role="listitem"', () => {
    assert.ok(
        /class="filter-pill"[^>]*\brole="listitem"/.test(GROUP)
            || /role="listitem"[^>]*\bclass="filter-pill"/.test(GROUP),
        '.filter-pill 應帶 role="listitem"',
    );
});

// ===== x-for + 複合 :key（CD-4）=====

test('x-for 遍歷 pills，:key 是複合鍵 dim + \'::\' + normalizePillValue(...)', () => {
    assert.ok(
        /x-for="pill in pills"/.test(GROUP),
        '應有 x-for="pill in pills"',
    );
    // 逐字要求複合鍵形狀，不是子字串偶然命中 pill.value
    const keyAttr = GROUP.match(/:key="([^"]+)"/);
    assert.ok(keyAttr, 'x-for template 應有 :key 綁定');
    const keyExpr = keyAttr[1];
    assert.ok(
        keyExpr.includes("pill.dim"),
        `:key 必須含 pill.dim，實際：${keyExpr}`,
    );
    assert.ok(
        keyExpr.includes("'::'") || keyExpr.includes('"::"'),
        `:key 必須含維度分隔符 '::'，實際：${keyExpr}`,
    );
    assert.ok(
        /normalizePillValue\s*\(\s*pill\.value\s*\)/.test(keyExpr),
        `:key 必須呼叫 normalizePillValue(pill.value)，實際：${keyExpr}`,
    );
    // 明確拒絕只 key 在 pill.value 的寫法（mutation self-check 目標）
    assert.notEqual(
        keyExpr.trim(),
        'pill.value',
        ':key 不得只是 pill.value（複合鍵契約）',
    );
});

// ===== 移除鈕契約（D3 / D4 / D5）=====

test('✕ 綁 removePill(pill.dim, pill.value)，含 dim 參數', () => {
    assert.ok(
        /@click="removePill\(\s*pill\.dim\s*,\s*pill\.value\s*\)"/.test(GROUP),
        '✕ 應綁 @click="removePill(pill.dim, pill.value)"',
    );
});

test('✕ 的 @click 不含 .stop 修飾符', () => {
    // 抓 filter-pill-remove 附近的 @click 屬性
    const btnChunk = GROUP.match(/class="filter-pill-remove"[\s\S]{0,200}/);
    assert.ok(btnChunk, '應有 .filter-pill-remove 按鈕');
    assert.ok(
        !/@click\.stop\b/.test(btnChunk[0]),
        '✕ 的 @click 不應帶 .stop（搜尋框作用域無 @click.outside）',
    );
});

test('pill 本體（.filter-pill）不掛任何 @click 移除綁定', () => {
    // 抽出每個 .filter-pill 開標籤（不含內層 button）
    const openTags = GROUP.match(/<span\b[^>]*\bclass="filter-pill"[^>]*>/g) || [];
    assert.ok(openTags.length >= 1, '應至少有一個 .filter-pill 開標籤');
    for (const tag of openTags) {
        assert.ok(
            !/@click\b/.test(tag),
            `.filter-pill 開標籤不得含 @click：${tag}`,
        );
    }
    // 值 span 也不該掛 click
    const valueSpans = GROUP.match(/<span\b[^>]*\bclass="filter-pill-value"[^>]*>/g) || [];
    for (const tag of valueSpans) {
        assert.ok(
            !/@click\b/.test(tag),
            `.filter-pill-value 不得含 @click：${tag}`,
        );
    }
});

test('✕ handler 不使用 $el.querySelector', () => {
    assert.ok(
        !/\$el\.querySelector/.test(GROUP),
        'pill 容器 markup 不得使用 $el.querySelector（x-for 內 $el 是自身）',
    );
});

test('✕ 有 :aria-label 綁定（非裸 × 字面充當唯一標籤）', () => {
    // TASK-123-T6：pick pill 的 remove_aria 走條件式分流（'移除篩選：1' 語意很怪，
    // 改用 showcase.pick.remove_aria），非 pick 維度仍走 showcase.pill.remove_aria——
    // 斷言鬆綁成「:aria-label 綁定值含 t('showcase.pill.remove_aria'」，不再要求它是
    // 值的最前綴。
    const m = GROUP.match(/:aria-label="([^"]*)"/);
    assert.ok(m, '✕ 應有 :aria-label 綁定');
    assert.ok(
        m[1].includes("t('showcase.pill.remove_aria'"),
        '✕ 的 :aria-label 綁定應含 t(\'showcase.pill.remove_aria\', ...) 分支，實際：' + m[1],
    );
});

// ===== placeholder 收合（D8）=====

test('影片搜尋框 :placeholder 條件綁定含 pills.length', () => {
    // 容器內 input 的 :placeholder
    const ph = GROUP.match(/:placeholder="([^"]+)"/);
    assert.ok(ph, '影片搜尋框應有 :placeholder 綁定（非 Jinja 靜態 placeholder）');
    const expr = ph[1];
    assert.ok(
        expr.includes('pills.length'),
        `:placeholder 應條件於 pills.length，實際：${expr}`,
    );
    assert.ok(
        expr.includes("t('showcase.placeholder.search')")
            || expr.includes('t("showcase.placeholder.search")'),
        `:placeholder 無 pill 時應回落 showcase.placeholder.search，實際：${expr}`,
    );
});

// ===== i18n key 存在性（防 typo 渲染成 raw key）=====

const EXPECTED_PILL_KEYS = {
    'showcase.pill.dim_label.actress': '女優',
    'showcase.pill.dim_label.tag': '標籤',
    'showcase.pill.dim_label.maker': '片商',
    'showcase.pill.dim_label.director': '導演',
    'showcase.pill.dim_label.series': '系列',
    'showcase.pill.dim_label.label': '廠牌',
    'showcase.pill.title': '{dim}：{value}',
    'showcase.pill.remove_aria': '移除篩選：{value}',
};

function lookupNested(obj, dotted) {
    return dotted.split('.').reduce(
        (acc, part) => (acc && typeof acc === 'object' ? acc[part] : undefined),
        obj,
    );
}

test('locales/zh_TW.json 含全部 8 個 showcase.pill.* key，值與契約一致', () => {
    for (const [key, expected] of Object.entries(EXPECTED_PILL_KEYS)) {
        const actual = lookupNested(ZH_TW, key);
        assert.equal(
            actual,
            expected,
            `zh_TW 缺/錯 key ${key}：期望 ${JSON.stringify(expected)}，實際 ${JSON.stringify(actual)}`,
        );
    }
});

test('模板用到的每一個 t(\'showcase.pill...\') key 都存在於 zh_TW.json', () => {
    // 抓字面 key；動態串接 dim_label. 前綴另驗六個維度
    const literalKeys = new Set();
    const re = /t\(\s*'((?:showcase\.pill)[^']*)'/g;
    let m;
    while ((m = re.exec(GROUP)) !== null) {
        const k = m[1];
        // 動態前綴：'showcase.pill.dim_label.' + pill.dim
        if (k.endsWith('.')) {
            // 由 EXPECTED 的六個維度覆蓋
            continue;
        }
        literalKeys.add(k);
    }
    // 至少 title / remove_aria 必須被模板引用
    assert.ok(literalKeys.has('showcase.pill.title'), '模板應引用 showcase.pill.title');
    assert.ok(literalKeys.has('showcase.pill.remove_aria'), '模板應引用 showcase.pill.remove_aria');

    for (const key of literalKeys) {
        const actual = lookupNested(ZH_TW, key);
        assert.notEqual(
            actual,
            undefined,
            `模板引用的 key 不存在於 zh_TW.json：${key}`,
        );
    }

    // 動態 dim_label 前綴：六個維度全部必須存在
    for (const dim of ['actress', 'tag', 'maker', 'director', 'series', 'label']) {
        const key = `showcase.pill.dim_label.${dim}`;
        assert.notEqual(
            lookupNested(ZH_TW, key),
            undefined,
            `動態 dim_label 維度 key 不存在：${key}`,
        );
    }
    // 模板必須使用動態串接形狀（防寫死單一維度）
    assert.ok(
        /t\(\s*'showcase\.pill\.dim_label\.'\s*\+\s*pill\.dim\s*\)/.test(GROUP),
        "模板應使用 t('showcase.pill.dim_label.' + pill.dim) 動態查表",
    );
});
