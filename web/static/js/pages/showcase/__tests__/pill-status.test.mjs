// TASK-115-T10: 狀態列文案（有 pill 時顯示「符合 N 個條件的 M 部」）結構契約。
// 技術比照 pill-shell.test.mjs：以文字解析 showcase.html / zh_TW.json，
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

/** 抽出 class="footer-count" 起的那一個元素 markup（影片模式；depth-aware）。 */
function extractFooterCount(html) {
    // 影片模式 footer-count 在 !showFavoriteActresses 之下；取第一個 .footer-count
    // （女優模式是 footer-count footer-count--actress，不在此範圍）
    const openRe = /<span\b[^>]*\bclass="footer-count"(?![^>]*footer-count--actress)[^>]*>/;
    const m = openRe.exec(html);
    assert.ok(m, 'showcase.html 應含 class="footer-count" 的影片模式計數容器');
    const start = m.index;
    let i = start + m[0].length;
    let depth = 1;
    while (i < html.length && depth > 0) {
        const nextOpen = html.indexOf('<span', i);
        const nextClose = html.indexOf('</span>', i);
        if (nextClose === -1) break;
        if (nextOpen !== -1 && nextOpen < nextClose) {
            depth++;
            i = nextOpen + 5;
        } else {
            depth--;
            i = nextClose + 7;
            if (depth === 0) {
                return html.slice(start, i);
            }
        }
    }
    throw new Error('footer-count 未找到匹配的 </span>');
}

const FOOTER = extractFooterCount(SHOWCASE_HTML);

/** 從 footer-count 區塊抽出所有 <template x-if="..."> 的條件字串。 */
function extractXIfConditions(markup) {
    const re = /<template\s+x-if="([^"]+)"/g;
    const conds = [];
    let m;
    while ((m = re.exec(markup)) !== null) {
        conds.push(m[1]);
    }
    return conds;
}

const CONDITIONS = extractXIfConditions(FOOTER);

function lookupNested(obj, dotted) {
    return dotted.split('.').reduce(
        (acc, part) => (acc && typeof acc === 'object' ? acc[part] : undefined),
        obj,
    );
}

// ===== 四個分支的 x-if 條件 =====

test('footer 有 pills.length > 0 分支，並渲染三個新 pill status key', () => {
    assert.ok(
        CONDITIONS.some((c) => c === 'pills.length > 0' || c.trim() === 'pills.length > 0'),
        `應有 x-if="pills.length > 0" 分支，實際條件：${JSON.stringify(CONDITIONS)}`,
    );
    // 抽出該分支內容
    const branchRe = /<template\s+x-if="pills\.length\s*>\s*0">([\s\S]*?)<\/template>/;
    const m = FOOTER.match(branchRe);
    assert.ok(m, '應能抽出 pills.length > 0 分支內容');
    const body = m[1];
    assert.ok(
        body.includes("t('showcase.status.pill_prefix')"),
        '新分支應含 showcase.status.pill_prefix',
    );
    assert.ok(
        body.includes("t('showcase.status.pill_middle')"),
        '新分支應含 showcase.status.pill_middle',
    );
    assert.ok(
        body.includes("t('showcase.status.pill_suffix')"),
        '新分支應含 showcase.status.pill_suffix',
    );
    // N = pills.length，M = filteredCount
    assert.ok(
        /x-text="pills\.length"/.test(body),
        '新分支應以 x-text="pills.length" 綁定 N',
    );
    assert.ok(
        /x-text="filteredCount"/.test(body),
        '新分支應以 x-text="filteredCount" 綁定 M',
    );
});

test('既有 total 分支（!search）現含 !pills.length 守衛', () => {
    const total = CONDITIONS.find(
        (c) => c.includes('!search') && !c.includes('filteredCount'),
    );
    assert.ok(total, `應有 total 分支（含 !search），實際：${JSON.stringify(CONDITIONS)}`);
    assert.ok(
        total.includes('!pills.length'),
        `total 分支條件應含 !pills.length，實際：${total}`,
    );
});

test('既有 search-with-hits 分支現含 !pills.length 守衛', () => {
    const hits = CONDITIONS.find(
        (c) => c.includes('search') && c.includes('filteredCount > 0'),
    );
    assert.ok(hits, `應有 search-with-hits 分支，實際：${JSON.stringify(CONDITIONS)}`);
    assert.ok(
        hits.includes('!pills.length'),
        `search-with-hits 分支條件應含 !pills.length，實際：${hits}`,
    );
});

test('既有 zero-results 分支現含 !pills.length 守衛', () => {
    const empty = CONDITIONS.find(
        (c) => c.includes('filteredCount === 0') || c.includes('filteredCount ===0'),
    );
    assert.ok(empty, `應有 zero-results 分支，實際：${JSON.stringify(CONDITIONS)}`);
    assert.ok(
        empty.includes('!pills.length'),
        `zero-results 分支條件應含 !pills.length，實際：${empty}`,
    );
});

// ===== 空狀態回歸鎖（DoD 第一優先）=====

test('zero-results / empty-state 分支仍存在且仍引用 search_empty key', () => {
    // 條件字串含 filteredCount === 0
    const empty = CONDITIONS.find((c) => c.includes('filteredCount === 0'));
    assert.ok(
        empty,
        `應有 filteredCount === 0 的 x-if 條件，實際：${JSON.stringify(CONDITIONS)}`,
    );
    // 內容逐字含 search_empty key（回歸紅線）
    assert.ok(
        FOOTER.includes("t('showcase.status.search_empty')"),
        "footer 應仍含 t('showcase.status.search_empty') 字面",
    );
    // 該 key 落在 zero-results 分支內
    const branchRe = /<template\s+x-if="[^"]*filteredCount\s*===\s*0">([\s\S]*?)<\/template>/;
    const m = FOOTER.match(branchRe);
    assert.ok(m, '應能抽出 zero-results 分支內容');
    assert.ok(
        m[1].includes("t('showcase.status.search_empty')"),
        'zero-results 分支內容應引用 showcase.status.search_empty',
    );
});

// ===== 新分支不列舉條件值 =====

test('pill 狀態分支不含 x-for 或 pill 值插值（不列舉條件）', () => {
    const branchRe = /<template\s+x-if="pills\.length\s*>\s*0">([\s\S]*?)<\/template>/;
    const m = FOOTER.match(branchRe);
    assert.ok(m, '應能抽出 pills.length > 0 分支');
    const body = m[1];
    assert.ok(!/\bx-for\b/.test(body), '新分支不得含 x-for');
    assert.ok(
        !/pill\.value/.test(body),
        '新分支不得插值 pill.value',
    );
    assert.ok(
        !/pill\.dim/.test(body),
        '新分支不得插值 pill.dim',
    );
});

// ===== D5 count 語意：N = pills.length，不含自由文字 =====

test('N 嚴格綁定 pills.length，不含 search 計入條件數', () => {
    const branchRe = /<template\s+x-if="pills\.length\s*>\s*0">([\s\S]*?)<\/template>/;
    const m = FOOTER.match(branchRe);
    assert.ok(m, '應能抽出 pills.length > 0 分支');
    const body = m[1];
    // 條件數綁 pills.length；不應出現 search ? 1 : 0 之類衍生計數
    assert.ok(
        /x-text="pills\.length"/.test(body),
        'N 應直接 x-text="pills.length"',
    );
    assert.ok(
        !/search\s*\?/.test(body),
        '新分支不得把 search 算進條件數',
    );
    // 分支條件本身也不依賴 search——有 pill 一律命中
    const cond = CONDITIONS.find((c) => /pills\.length\s*>\s*0/.test(c));
    assert.ok(cond, '應有 pills.length > 0 條件');
    assert.ok(
        !cond.includes('search'),
        `pill 分支條件不得依賴 search，實際：${cond}`,
    );
});

// ===== i18n key 存在性 =====

const EXPECTED_PILL_STATUS_KEYS = {
    'showcase.status.pill_prefix': '符合',
    'showcase.status.pill_middle': '個條件的',
    'showcase.status.pill_suffix': '部',
};

test('locales/zh_TW.json 含三個 showcase.status.pill_* key，值與契約一致', () => {
    for (const [key, expected] of Object.entries(EXPECTED_PILL_STATUS_KEYS)) {
        const actual = lookupNested(ZH_TW, key);
        assert.equal(
            actual,
            expected,
            `zh_TW 缺/錯 key ${key}：期望 ${JSON.stringify(expected)}，實際 ${JSON.stringify(actual)}`,
        );
    }
});

test("footer 內每一個 t('showcase.status.…') key 都存在於 zh_TW.json", () => {
    const re = /t\(\s*'((?:showcase\.status)[^']*)'/g;
    const keys = new Set();
    let m;
    while ((m = re.exec(FOOTER)) !== null) {
        keys.add(m[1]);
    }
    assert.ok(keys.size >= 1, 'footer 應至少引用一個 showcase.status.* key');
    for (const key of keys) {
        const actual = lookupNested(ZH_TW, key);
        assert.notEqual(
            actual,
            undefined,
            `模板引用的 key 不存在於 zh_TW.json：${key}`,
        );
    }
    // 三個新 key 必須被引用
    for (const key of Object.keys(EXPECTED_PILL_STATUS_KEYS)) {
        assert.ok(keys.has(key), `footer 應引用 ${key}`);
    }
});
