// TASK-116a-T4: 女優空狀態三分支互斥 + footer 三段式 + 四個新 i18n key。
// 純文字解析 showcase.html / zh_TW.json，不 import 任何 state-*.js（FE-GUARD-11 不適用）。
// 比照 pill-status.test.mjs 手法：抽出 x-show / x-if 表達式，用 new Function 動態求值。

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
 * 抽出女優模式 loading / empty / search-empty / grid 區塊
 * （錨定 T3 既有 Jinja 註解，全檔恰好一次）。
 */
function extractActressModeBlock(html) {
    const startMarker = '<!-- 女優模式：loading / empty state / actress grid (T3) -->';
    const start = html.indexOf(startMarker);
    assert.ok(start !== -1, '找不到女優模式區塊起點註解');
    // 取到下一個頂層同層註解或 template 結束附近；用 actress-grid 後第一個 </template>
    // 的父 template x-if="showFavoriteActresses" 範圍即可
    const after = html.slice(start);
    // 找到該 x-if template 的閉合：第一個 </template> 在 actress-grid 之後會出現，
    // 但區塊內還有其他 template。改以 state-page + actress-grid 的固定字串窗口。
    const gridIdx = after.indexOf('class="actress-grid"');
    assert.ok(gridIdx !== -1, '找不到 actress-grid');
    // 從 grid 開標籤掃到匹配的 </div>
    const gridOpen = after.indexOf('<div', gridIdx - 20); // 往前找 <div
    // 更穩：從 start 取到 actress-grid 的 </div>
    const gridTagStart = after.indexOf('<div class="actress-grid"');
    assert.ok(gridTagStart !== -1, '找不到 <div class="actress-grid"');
    let i = gridTagStart + '<div class="actress-grid"'.length;
    let depth = 1;
    while (i < after.length && depth > 0) {
        const nextOpen = after.indexOf('<div', i);
        const nextClose = after.indexOf('</div>', i);
        if (nextClose === -1) break;
        if (nextOpen !== -1 && nextOpen < nextClose) {
            depth++;
            i = nextOpen + 4;
        } else {
            depth--;
            i = nextClose + 6;
        }
    }
    return after.slice(0, i);
}

const ACTRESS_BLOCK = extractActressModeBlock(SHOWCASE_HTML);

/**
 * 抽出開標籤：class 屬性含 token 時，用 x-show="..." 引號配對，
 * 避免 x-show 表達式內的 `>`（如 `actressCount > 0`）截斷 [^>]*。
 */
function extractOpenTagsWithClass(block, className) {
    // 掃 class="..." 再向前找 <div；引號內允許 `>`（x-show 含 actressCount > 0）
    const needle = `class="`;
    const tags = [];
    let from = 0;
    while (from < block.length) {
        const classIdx = block.indexOf(needle, from);
        if (classIdx === -1) break;
        // 往前找本 tag 的 <div
        const divStart = block.lastIndexOf('<div', classIdx);
        if (divStart === -1 || divStart < from) {
            from = classIdx + needle.length;
            continue;
        }
        // 從 class=" 後找閉合引號
        const classValStart = classIdx + needle.length;
        const classValEnd = block.indexOf('"', classValStart);
        if (classValEnd === -1) break;
        const classVal = block.slice(classValStart, classValEnd);
        const tokens = classVal.split(/\s+/);
        if (!tokens.includes(className)) {
            from = classValEnd + 1;
            continue;
        }
        // 從 class 閉合引號之後繼續找屬性，直到不在引號內的 >
        let i = classValEnd + 1;
        let inQuote = null;
        while (i < block.length) {
            const ch = block[i];
            if (inQuote) {
                if (ch === inQuote) inQuote = null;
            } else if (ch === '"' || ch === "'") {
                inQuote = ch;
            } else if (ch === '>') {
                tags.push(block.slice(divStart, i + 1));
                from = i + 1;
                break;
            }
            i++;
        }
        if (i >= block.length) break;
    }
    return tags;
}

/** 從女優區塊抽出所有 class="state-page" 的 x-show 條件。 */
function extractStatePageShows(block) {
    const tags = extractOpenTagsWithClass(block, 'state-page');
    const shows = [];
    for (const tag of tags) {
        const showM = tag.match(/\bx-show="([^"]+)"/);
        assert.ok(showM, `state-page 開標籤應含 x-show：${tag}`);
        assert.ok(/\bx-cloak\b/.test(tag), `state-page 開標籤應含 x-cloak：${tag}`);
        shows.push(showM[1]);
    }
    return shows;
}

/** 抽出 actress-grid 的 x-show 條件。 */
function extractGridShow(block) {
    const tags = extractOpenTagsWithClass(block, 'actress-grid');
    assert.ok(tags.length >= 1, 'actress-grid 應存在');
    const showM = tags[0].match(/\bx-show="([^"]+)"/);
    assert.ok(showM, 'actress-grid 應含 x-show');
    return showM[1];
}

const STATE_PAGE_SHOWS = extractStatePageShows(ACTRESS_BLOCK);
const GRID_SHOW = extractGridShow(ACTRESS_BLOCK);

// 期望字面（契約鎖）——互斥性求值用的是下方從 HTML 抽出的實際條件，
// 這樣拿掉 actressCount > 0 時互斥表會真的轉紅（mutation 可證偽）。
const LOADING_SHOW_EXPECTED = 'actressLoading';
const EMPTY_SHOW_EXPECTED = '!actressLoading && actressCount === 0';
const SEARCH_EMPTY_SHOW_EXPECTED = '!actressLoading && actressCount > 0 && filteredActressCount === 0';
const GRID_SHOW_EXPECTED = '!actressLoading && filteredActressCount > 0';

// 實際抽出的條件（互斥求值以此為準）
assert.equal(STATE_PAGE_SHOWS.length, 3, `預期 3 個 state-page，實際：${JSON.stringify(STATE_PAGE_SHOWS)}`);
const LOADING_SHOW = STATE_PAGE_SHOWS[0];
const EMPTY_SHOW = STATE_PAGE_SHOWS[1];
const SEARCH_EMPTY_SHOW = STATE_PAGE_SHOWS[2];

test('女優區塊恰有三個 state-page，條件字面符合 loading / empty / searchEmpty', () => {
    assert.equal(STATE_PAGE_SHOWS.length, 3, `預期 3 個 state-page，實際：${JSON.stringify(STATE_PAGE_SHOWS)}`);
    assert.equal(LOADING_SHOW, LOADING_SHOW_EXPECTED);
    assert.equal(EMPTY_SHOW, EMPTY_SHOW_EXPECTED);
    assert.equal(SEARCH_EMPTY_SHOW, SEARCH_EMPTY_SHOW_EXPECTED);
    assert.equal(GRID_SHOW, GRID_SHOW_EXPECTED);
});

test('新 searchEmpty 分支引用 showcase.actress.searchEmpty 且 icon 為 bi-search', () => {
    // 以第三個 state-page 的實際 x-show 定位，再取到匹配的 </div>
    const showNeedle = `x-show="${SEARCH_EMPTY_SHOW}"`;
    const showIdx = ACTRESS_BLOCK.indexOf(showNeedle);
    assert.ok(showIdx !== -1, `應能找到 searchEmpty 的 x-show 字面：${SEARCH_EMPTY_SHOW}`);
    // 從開標籤結尾後掃 depth-aware 內容
    let i = showIdx + showNeedle.length;
    while (i < ACTRESS_BLOCK.length && ACTRESS_BLOCK[i] !== '>') i++;
    assert.ok(i < ACTRESS_BLOCK.length, 'searchEmpty 開標籤未閉合');
    const contentStart = i + 1;
    let depth = 1;
    i = contentStart;
    while (i < ACTRESS_BLOCK.length && depth > 0) {
        const nextOpen = ACTRESS_BLOCK.indexOf('<div', i);
        const nextClose = ACTRESS_BLOCK.indexOf('</div>', i);
        if (nextClose === -1) break;
        if (nextOpen !== -1 && nextOpen < nextClose) {
            depth++;
            i = nextOpen + 4;
        } else {
            depth--;
            if (depth === 0) {
                const body = ACTRESS_BLOCK.slice(contentStart, nextClose);
                assert.ok(
                    body.includes("t('showcase.actress.searchEmpty')"),
                    '新分支應引用 showcase.actress.searchEmpty',
                );
                assert.ok(
                    /class="bi bi-search state-page-icon"/.test(body),
                    '新分支 icon 應為 bi-search',
                );
                return;
            }
            i = nextClose + 6;
        }
    }
    assert.fail('searchEmpty state-page 未找到匹配的 </div>');
});

/**
 * 以 new Function 求值 x-show / x-if 表達式。
 * 傳入 fixture 物件的鍵作為區域變數。
 */
function evalExpr(expr, ctx) {
    const keys = Object.keys(ctx);
    const vals = keys.map((k) => ctx[k]);
    const fn = new Function(...keys, `return !!(${expr});`);
    return fn(...vals);
}

/**
 * 空狀態互斥性真值表（TASK-116a-T4 鎖定 4 組合法組合）。
 * filteredActressCount <= actressCount 是結構不變式。
 *
 * 每個組合恰好命中 loading / empty / searchEmpty / grid 中 0 或 1 個。
 */
const EMPTY_STATE_CASES = [
    {
        name: '#1 loading=true → 只命中 Loading',
        ctx: { actressLoading: true, actressCount: 5, filteredActressCount: 2 },
        expect: { loading: true, empty: false, searchEmpty: false, grid: false },
    },
    {
        name: '#1b loading=true（count=0）→ 只命中 Loading',
        ctx: { actressLoading: true, actressCount: 0, filteredActressCount: 0 },
        expect: { loading: true, empty: false, searchEmpty: false, grid: false },
    },
    {
        name: '#2 loading=false, count=0 → 只命中 Empty',
        ctx: { actressLoading: false, actressCount: 0, filteredActressCount: 0 },
        expect: { loading: false, empty: true, searchEmpty: false, grid: false },
    },
    {
        name: '#3 loading=false, count>0, filtered=0 → 只命中 Search Empty',
        ctx: { actressLoading: false, actressCount: 3, filteredActressCount: 0 },
        expect: { loading: false, empty: false, searchEmpty: true, grid: false },
    },
    {
        name: '#4 loading=false, count>0, filtered>0 → 只命中 Grid',
        ctx: { actressLoading: false, actressCount: 5, filteredActressCount: 2 },
        expect: { loading: false, empty: false, searchEmpty: false, grid: true },
    },
];

for (const tc of EMPTY_STATE_CASES) {
    test(`空狀態互斥：${tc.name}`, () => {
        // 求值用 HTML 實際抽出的條件（非硬編碼期望字面）
        const hits = {
            loading: evalExpr(LOADING_SHOW, tc.ctx),
            empty: evalExpr(EMPTY_SHOW, tc.ctx),
            searchEmpty: evalExpr(SEARCH_EMPTY_SHOW, tc.ctx),
            grid: evalExpr(GRID_SHOW, tc.ctx),
        };
        assert.deepEqual(hits, tc.expect, `ctx=${JSON.stringify(tc.ctx)}`);
        // 恰好 0 或 1 個命中（本表每組恰 1 個）
        const hitCount = Object.values(hits).filter(Boolean).length;
        assert.equal(hitCount, 1, `應恰好命中 1 個分支，實際 ${hitCount}：${JSON.stringify(hits)}`);
    });
}

// 額外：對整張表再做一次「任意合法組合不得同時命中兩個 state-page」的總掃描
// （用 HTML 實際條件——拿掉 actressCount > 0 後 #2 會同時命中 empty + searchEmpty）
test('空狀態：任意合法 (loading, count, filtered) 組合 state-page 分支至多命中 1 個', () => {
    const loadings = [true, false];
    const counts = [0, 1, 5];
    for (const actressLoading of loadings) {
        for (const actressCount of counts) {
            // 合法 filtered：0..actressCount
            for (let filteredActressCount = 0; filteredActressCount <= actressCount; filteredActressCount++) {
                const ctx = { actressLoading, actressCount, filteredActressCount };
                const spHits = [
                    evalExpr(LOADING_SHOW, ctx),
                    evalExpr(EMPTY_SHOW, ctx),
                    evalExpr(SEARCH_EMPTY_SHOW, ctx),
                ].filter(Boolean).length;
                assert.ok(
                    spHits <= 1,
                    `state-page 同時命中 ${spHits} 個：${JSON.stringify(ctx)}`,
                );
            }
        }
    }
});

// ===== footer 三段式 =====

/** 抽出 class="footer-count footer-count--actress" 元素 markup（depth-aware）。 */
function extractActressFooter(html) {
    const openRe = /<span\b[^>]*\bclass="footer-count footer-count--actress"[^>]*>/;
    const m = openRe.exec(html);
    assert.ok(m, 'showcase.html 應含 footer-count footer-count--actress');
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
    throw new Error('footer-count--actress 未找到匹配的 </span>');
}

/** 抽出女優 footer 外層 template x-if 條件。 */
function extractActressFooterOuterIf(html) {
    const m = html.match(
        /<template\s+x-if="(showFavoriteActresses && \(!actressSearch \|\| filteredActressCount > 0\))">/,
    );
    assert.ok(m, '應找到女優 footer 外層 x-if');
    return m[1];
}

const ACTRESS_FOOTER = extractActressFooter(SHOWCASE_HTML);
const OUTER_IF = extractActressFooterOuterIf(SHOWCASE_HTML);

function extractXIfConditions(markup) {
    const re = /<template\s+x-if="([^"]+)"/g;
    const conds = [];
    let m;
    while ((m = re.exec(markup)) !== null) {
        conds.push(m[1]);
    }
    return conds;
}

// 內層三個 x-if 在 footer-count 內部（不包含外層 template，因為 extractActressFooter 從 span 起）
const INNER_CONDS = extractXIfConditions(ACTRESS_FOOTER);

const FOOTER_TOTAL = '!actressSearch && !actressPills.length';
const FOOTER_SEARCH = 'actressSearch && filteredActressCount > 0 && !actressPills.length';
const FOOTER_PILL = 'actressPills.length > 0';

test('女優 footer 恰有三個內層 x-if，條件字面符合 total / search / pill', () => {
    assert.equal(INNER_CONDS.length, 3, `實際：${JSON.stringify(INNER_CONDS)}`);
    assert.equal(INNER_CONDS[0], FOOTER_TOTAL);
    assert.equal(INNER_CONDS[1], FOOTER_SEARCH);
    assert.equal(INNER_CONDS[2], FOOTER_PILL);
});

test('女優 footer pill 分支渲染三個 pill_actresses_* key 並綁 N/M', () => {
    const branchRe = /<template\s+x-if="actressPills\.length\s*>\s*0">([\s\S]*?)<\/template>/;
    const m = ACTRESS_FOOTER.match(branchRe);
    assert.ok(m, '應能抽出 actressPills.length > 0 分支內容');
    const body = m[1];
    assert.ok(body.includes("t('showcase.status.pill_actresses_prefix')"));
    assert.ok(body.includes("t('showcase.status.pill_actresses_middle')"));
    assert.ok(body.includes("t('showcase.status.pill_actresses_suffix')"));
    assert.ok(/x-text="actressPills\.length"/.test(body), 'N = actressPills.length');
    assert.ok(/x-text="filteredActressCount"/.test(body), 'M = filteredActressCount');
});

/**
 * footer 互斥真值表 5 組。
 * actressSearch 用 truthy/falsy 字串模擬 Alpine 的 truthiness（空字串 falsy）。
 * actressPills 用陣列，條件用 .length。
 */
const FOOTER_CASES = [
    {
        name: '#1 空搜尋 + 零 pill → 分支 1（total）',
        ctx: { actressSearch: '', actressPills: [], filteredActressCount: 5 },
        expectInner: { total: true, search: false, pill: false },
        expectOuter: true,
    },
    {
        name: '#2 非空搜尋 + 零 pill + filtered>0 → 分支 2（search）',
        ctx: { actressSearch: 'yua', actressPills: [], filteredActressCount: 2 },
        expectInner: { total: false, search: true, pill: false },
        expectOuter: true,
    },
    {
        name: '#3 空搜尋 + 有 pill → 分支 3（pill）',
        ctx: { actressSearch: '', actressPills: [{ dim: 'age', value: '37' }], filteredActressCount: 0 },
        expectInner: { total: false, search: false, pill: true },
        expectOuter: true,
    },
    {
        name: '#4 非空搜尋 + 有 pill → 分支 3（pill 優先）',
        ctx: { actressSearch: 'yua', actressPills: [{ dim: 'cup', value: 'B' }], filteredActressCount: 1 },
        expectInner: { total: false, search: false, pill: true },
        expectOuter: true,
    },
    {
        name: '#5 非空搜尋 + 零 pill + filtered=0 → 外層隱藏、零內層命中',
        ctx: { actressSearch: 'zzz', actressPills: [], filteredActressCount: 0 },
        expectInner: { total: false, search: false, pill: false },
        expectOuter: false,
    },
];

/** 把 fixture 轉成 evalExpr 可用的扁平 ctx（actressPills.length 語意）。 */
function footerEvalCtx(ctx) {
    // 表達式用 actressSearch / actressPills.length / filteredActressCount
    // new Function 無法直接寫 .length 作為獨立變數名；改把陣列傳入，表達式照樣用
    return {
        actressSearch: ctx.actressSearch,
        actressPills: ctx.actressPills,
        filteredActressCount: ctx.filteredActressCount,
        showFavoriteActresses: true,
    };
}

for (const tc of FOOTER_CASES) {
    test(`footer 互斥：${tc.name}`, () => {
        const ctx = footerEvalCtx(tc.ctx);
        const outer = evalExpr(OUTER_IF, ctx);
        assert.equal(outer, tc.expectOuter, `外層 x-if 不符：${OUTER_IF}`);

        const hits = {
            total: evalExpr(FOOTER_TOTAL, ctx),
            search: evalExpr(FOOTER_SEARCH, ctx),
            pill: evalExpr(FOOTER_PILL, ctx),
        };
        assert.deepEqual(hits, tc.expectInner, `內層命中不符：ctx=${JSON.stringify(tc.ctx)}`);

        const hitCount = Object.values(hits).filter(Boolean).length;
        // 互斥：至多 1 個；#5 允許 0
        assert.ok(hitCount <= 1, `內層同時命中 ${hitCount} 個：${JSON.stringify(hits)}`);
        if (tc.expectOuter === false) {
            assert.equal(hitCount, 0, '外層隱藏時內層應零命中');
        } else {
            assert.equal(hitCount, 1, '外層顯示時內層應恰好命中 1 個');
        }
    });
}

// ===== i18n 四個新 key =====

function lookupNested(obj, dotted) {
    return dotted.split('.').reduce(
        (acc, part) => (acc && typeof acc === 'object' ? acc[part] : undefined),
        obj,
    );
}

const I18N_KEYS = [
    { key: 'showcase.status.pill_actresses_prefix', value: '符合' },
    { key: 'showcase.status.pill_actresses_middle', value: '個條件的' },
    { key: 'showcase.status.pill_actresses_suffix', value: '位' },
    { key: 'showcase.actress.searchEmpty', value: '沒有符合條件的女優' },
];

for (const { key, value } of I18N_KEYS) {
    test(`zh_TW.json 含 ${key} = "${value}"`, () => {
        const actual = lookupNested(ZH_TW, key);
        assert.equal(actual, value, `預期 "${value}"，實際 ${JSON.stringify(actual)}`);
    });
}

test('女優 footer / 空狀態模板引用的 showcase.* key 皆存在於 zh_TW', () => {
    // 從女優 footer + searchEmpty 分支抽出 t('showcase...')
    const chunks = [ACTRESS_FOOTER, ACTRESS_BLOCK];
    const keyRe = /t\('((?:showcase\.)[^']+)'\)/g;
    const missing = [];
    for (const chunk of chunks) {
        let m;
        while ((m = keyRe.exec(chunk)) !== null) {
            const k = m[1];
            if (lookupNested(ZH_TW, k) === undefined) missing.push(k);
        }
    }
    // Jinja {{ t('...') }} 形式
    const jinjaRe = /\{\{\s*t\('((?:showcase\.)[^']+)'\)/g;
    for (const chunk of chunks) {
        let m;
        while ((m = jinjaRe.exec(chunk)) !== null) {
            const k = m[1];
            if (lookupNested(ZH_TW, k) === undefined) missing.push(k);
        }
    }
    assert.deepEqual(missing, [], `模板引用但 zh_TW 缺失：${JSON.stringify(missing)}`);
});
