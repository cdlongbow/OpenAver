// TASK-116b-T3: 女優 pill 浮層 markup 結構契約。
// 技術比照 actress-pill-shell.test.mjs：以文字解析 showcase.html / zh_TW.json，
// 不跑 CDP、不動 Alpine runtime、不需要 window/importmap（純文字讀取，FE-GUARD-11 不適用本檔）。
// 可互動 / 視覺幾何（真 click 開關、360/481px 斷點行為、溢出量測）交給 CDP 驗收，見
// feature/116-actress-attribute-filter/TASK-116b-T3.md「CDP 驗收清單」，本檔不重複驗。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// 本檔：web/static/js/pages/showcase/__tests__/ → 上六層 = repo root
const REPO_ROOT = path.resolve(__dirname, '../../../../../..');
const SHOWCASE_HTML = readFileSync(
    path.join(REPO_ROOT, 'web/templates/showcase.html'),
    'utf8',
);
const ZH_TW = JSON.parse(
    readFileSync(path.join(REPO_ROOT, 'locales/zh_TW.json'), 'utf8'),
);

function lookupNested(obj, dotted) {
    return dotted.split('.').reduce(
        (acc, part) => (acc && typeof acc === 'object' ? acc[part] : undefined),
        obj,
    );
}

/**
 * Depth-aware 抽出「開頭 tag 內含指定字面」到匹配 </div> 為止的整段 markup。
 * 仿 actress-pill-shell.test.mjs 的 extractActressFilterPillGroup()。
 */
function extractDivContaining(html, openTagLiteral, label) {
    const idx = html.indexOf(openTagLiteral);
    assert.ok(idx !== -1, `showcase.html 應含 ${label}（找不到字面：${openTagLiteral}）`);
    // 回頭找這段字面所在的 <div 開始位置
    const divStart = html.lastIndexOf('<div', idx);
    assert.ok(divStart !== -1, `${label} 字面前找不到對應的 <div 開始標籤`);
    const tagEnd = html.indexOf('>', idx);
    assert.ok(tagEnd !== -1, `${label} 的開始標籤未正常結束`);
    let i = tagEnd + 1;
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
                return html.slice(divStart, i);
            }
        }
    }
    throw new Error(`${label} 未找到匹配的 </div>`);
}

function extractActressFilterPillGroup(html) {
    return extractDivContaining(
        html,
        'class="filter-pill-group actress-filter-pill-group"',
        '.actress-filter-pill-group 容器',
    );
}

function extractPillEditorPopover(html) {
    return extractDivContaining(html, 'class="pill-editor-popover"', '.pill-editor-popover 浮層');
}

const ACTRESS_GROUP = extractActressFilterPillGroup(SHOWCASE_HTML);
const POPOVER = extractPillEditorPopover(SHOWCASE_HTML);

// ===== 容器唯一性 =====

test('showcase.html 恰有一個 .pill-editor-popover 容器', () => {
    const matches = SHOWCASE_HTML.match(/class="pill-editor-popover"/g) || [];
    assert.equal(matches.length, 1, `預期恰好 1 個，實際 ${matches.length}`);
});

// ===== pill 本體：兩個 <template x-if> 分流（button/span），非 :disabled ／ pointer-events =====

test('pill 本體用兩個互斥 <template x-if> 分流成 button（啟用）／span（停用）', () => {
    assert.ok(
        /<template x-if="_pillPopoverEnabled">\s*<button[^>]*class="filter-pill-value"/.test(ACTRESS_GROUP),
        '_pillPopoverEnabled 為真時應渲染 <button class="filter-pill-value">',
    );
    assert.ok(
        /<template x-if="!_pillPopoverEnabled">\s*<span[^>]*class="filter-pill-value"/.test(ACTRESS_GROUP),
        '_pillPopoverEnabled 為假時應渲染 <span class="filter-pill-value">（非 button）',
    );
});

test('pill 本體不得用 :disabled 或 pointer-events 做手機不可點（結構層換元素型別）', () => {
    assert.ok(
        !/filter-pill-value[\s\S]{0,200}:disabled/.test(ACTRESS_GROUP),
        '.filter-pill-value 不應綁 :disabled',
    );
    assert.ok(
        !/filter-pill-value[\s\S]{0,200}pointer-events/.test(ACTRESS_GROUP),
        '.filter-pill-value 不應靠 pointer-events 停用',
    );
});

test('pill 本體的 button 分支綁 @click.stop="_togglePillEditor(pill)"（CD-116b-7 承重）', () => {
    assert.ok(
        /<button[^>]*class="filter-pill-value"[\s\S]{0,300}@click\.stop="_togglePillEditor\(\s*pill\s*\)"/.test(ACTRESS_GROUP),
        'button 態 .filter-pill-value 應綁 @click.stop="_togglePillEditor(pill)"',
    );
});

test('.is-editing 綁在外層 .filter-pill 上（CD-116b-12b 逐字：掛在既有 .filter-pill、不新開元素）', () => {
    assert.ok(
        /<span class="filter-pill" role="listitem"[\s\S]{0,200}:class="\{\s*'is-editing':\s*_pillEditor\s*&&\s*_pillEditor\.dim\s*===\s*pill\.dim\s*\}"/.test(ACTRESS_GROUP),
        '外層 .filter-pill 應綁 :class="{ \'is-editing\': _pillEditor && _pillEditor.dim === pill.dim }"',
    );
    // 反向：不得改掛回 .filter-pill-value（浮層不黏著 pill，訊號必須落在整枚 pill 上——CD-116b-4 的補償義務）
    assert.ok(
        !/<button[^>]*class="filter-pill-value"[^>]*:class=/.test(ACTRESS_GROUP),
        'button 態 .filter-pill-value 不應自帶 :class（.is-editing 的所有者是外層 .filter-pill）',
    );
});

test('影片 .filter-pill-group（bare class）零污染：不含任何 pill-editor / 116b 新符號', () => {
    const videoGroup = extractDivContaining(SHOWCASE_HTML, 'class="filter-pill-group"', '影片 .filter-pill-group（bare）');
    for (const forbidden of ['pill-editor', '_pillPopoverEnabled', '_togglePillEditor', '_pillEditor', 'is-editing']) {
        assert.ok(
            !videoGroup.includes(forbidden),
            `影片 .filter-pill-group 不應出現 116b 符號 "${forbidden}"（AC11 逐位元組不變）`,
        );
    }
});

// ===== 浮層四段順序 ＝ CD-116b-12b（class 命名逐字）=====

test('浮層四段順序：title → modes → range(僅 range 模式) → actions', () => {
    const titleIdx = POPOVER.indexOf('class="pill-editor-title"');
    const modesIdx = POPOVER.indexOf('class="pill-editor-modes"');
    const rangeIdx = POPOVER.indexOf('class="pill-editor-range"');
    const actionsIdx = POPOVER.indexOf('class="pill-editor-actions"');
    assert.ok(titleIdx !== -1, '應有 .pill-editor-title');
    assert.ok(modesIdx !== -1, '應有 .pill-editor-modes');
    assert.ok(rangeIdx !== -1, '應有 .pill-editor-range');
    assert.ok(actionsIdx !== -1, '應有 .pill-editor-actions');
    assert.ok(titleIdx < modesIdx, 'title 應在 modes 之前');
    assert.ok(modesIdx < rangeIdx, 'modes 應在 range 之前');
    assert.ok(rangeIdx < actionsIdx, 'range 應在 actions 之前');
});

test('.pill-editor-title 用 t(\'showcase.pill.dim_label.\' + (_pillEditor?.dim || \'\'))', () => {
    assert.ok(
        /class="pill-editor-title"[^>]*x-text="t\('showcase\.pill\.dim_label\.'\s*\+\s*\(_pillEditor\?\.dim\s*\|\|\s*''\)\)"/.test(POPOVER),
        '.pill-editor-title 應動態綁定當前維度名稱',
    );
});

test('.pill-editor-modes 含四顆模式鈕（=/≤/≥/區間），選中態綁 .is-active', () => {
    for (const op of ["'='", "'<='", "'>='", "'range'"]) {
        const re = new RegExp(
            `class="pill-editor-mode"[^>]*:class="\\{\\s*'is-active':\\s*_pillEditor\\?\\.op\\s*===\\s*${op}\\s*\\}"`,
        );
        assert.ok(re.test(POPOVER), `.pill-editor-mode 應有 op===${op} 的 .is-active 綁定`);
    }
});

test('.pill-editor-modes 的四顆鈕 @click 分別綁 _setEditorMode(\'=\'|\'<=\'|\'>=\'|\'range\')', () => {
    for (const op of ["'='", "'<='", "'>='", "'range'"]) {
        assert.ok(
            POPOVER.includes(`@click="_setEditorMode(${op})"`),
            `應有 @click="_setEditorMode(${op})"`,
        );
    }
});

// ===== 罩杯：range 鈕在結構層 <template x-if> 分流內（非 CSS 隱藏）=====

test('罩杯不渲染 range 鈕：range 鈕包在 <template x-if="_pillEditor?.dim !== \'cup\'"> 內', () => {
    const modesStart = POPOVER.indexOf('class="pill-editor-modes"');
    const rangeStart = POPOVER.indexOf('class="pill-editor-range"');
    const modesSection = POPOVER.slice(modesStart, rangeStart);
    assert.ok(
        /<template x-if="_pillEditor\?\.dim !== 'cup'">[\s\S]*_setEditorMode\('range'\)[\s\S]*<\/template>/.test(modesSection),
        'range 模式鈕應包在 <template x-if="_pillEditor?.dim !== \'cup\'"> 內（結構層不渲染，非 x-show/display:none）',
    );
    assert.ok(
        !/x-show="[^"]*dim[^"]*!==\s*'cup'/.test(modesSection),
        '罩杯排除不得用 x-show（必須是結構層 <template x-if>）',
    );
});

// ===== range 輸入框：僅 range 模式渲染、:min/:max 走 _pillRangeBounds()、x-model 無 .number =====

test('.pill-editor-range 整段包在 <template x-if="_pillEditor?.op === \'range\'"> 內', () => {
    const rangeBlockIdx = POPOVER.indexOf('<template x-if="_pillEditor?.op === \'range\'">');
    assert.ok(rangeBlockIdx !== -1, '應有 <template x-if="_pillEditor?.op === \'range\'">');
    const classIdx = POPOVER.indexOf('class="pill-editor-range"');
    assert.ok(
        classIdx > rangeBlockIdx && classIdx < rangeBlockIdx + 200,
        '.pill-editor-range 應緊接在該 <template x-if> 之後（僅 range 模式渲染）',
    );
});

test('兩個 range input 的 :min/:max 綁 _pillRangeBounds()（單一所有者，不得手寫數字）', () => {
    const rangeSection = extractDivContaining(POPOVER, 'class="pill-editor-range"', '.pill-editor-range');
    const inputs = rangeSection.match(/<input\b[^>]*>/g) || [];
    assert.equal(inputs.length, 2, `.pill-editor-range 應恰有兩個 <input>，實際 ${inputs.length}`);
    for (const input of inputs) {
        assert.ok(
            /:min="_pillRangeBounds\(\)\?\.min"/.test(input),
            `input 的 :min 應綁 _pillRangeBounds()?.min：${input}`,
        );
        assert.ok(
            /:max="_pillRangeBounds\(\)\?\.max"/.test(input),
            `input 的 :max 應綁 _pillRangeBounds()?.max：${input}`,
        );
        // 反面先例守則：settings.html:1000 的 x-model.number 不准抄（CD-116b-1）
        assert.ok(
            !/x-model\.number/.test(input),
            `input 不得用 x-model.number（草稿邊界值必須維持字串）：${input}`,
        );
    }
    assert.ok(
        /x-model="_pillEditor\.rangeLo"/.test(rangeSection),
        '下限 input 應綁 x-model="_pillEditor.rangeLo"',
    );
    assert.ok(
        /x-model="_pillEditor\.rangeHi"/.test(rangeSection),
        '上限 input 應綁 x-model="_pillEditor.rangeHi"',
    );
    assert.ok(
        /:aria-label="t\('showcase\.pill\.editor\.range_min'\)"/.test(rangeSection),
        '下限 input 應綁 :aria-label="t(\'showcase.pill.editor.range_min\')"',
    );
    assert.ok(
        /:aria-label="t\('showcase\.pill\.editor\.range_max'\)"/.test(rangeSection),
        '上限 input 應綁 :aria-label="t(\'showcase.pill.editor.range_max\')"',
    );
});

test('整個浮層（含 range input 之外）不含任何 x-model.number（CD-116b-1 反面先例）', () => {
    assert.ok(
        !POPOVER.includes('x-model.number'),
        '.pill-editor-popover 內任何欄位都不得用 x-model.number',
    );
});

// ===== ✓/✗ 動作列 =====

test('.pill-editor-actions 含 .pill-editor-btn.cancel 與 .pill-editor-btn.confirm，各綁對應方法', () => {
    assert.ok(
        /class="pill-editor-btn cancel"[^>]*@click="_cancelPillEditor\(\)"/.test(POPOVER),
        '.pill-editor-btn.cancel 應綁 @click="_cancelPillEditor()"',
    );
    assert.ok(
        /class="pill-editor-btn confirm"[^>]*@click="_commitPillEditor\(\)"/.test(POPOVER),
        '.pill-editor-btn.confirm 應綁 @click="_commitPillEditor()"',
    );
});

test('✓/✗ 的 aria-label 重用既有 common.action.confirm/cancel（CD-116b-12b：不新增 key）', () => {
    assert.ok(
        /class="pill-editor-btn cancel"[\s\S]{0,200}:aria-label="t\('common\.action\.cancel'\)"/.test(POPOVER),
        '.cancel 應綁 :aria-label="t(\'common.action.cancel\')"',
    );
    assert.ok(
        /class="pill-editor-btn confirm"[\s\S]{0,200}:aria-label="t\('common\.action\.confirm'\)"/.test(POPOVER),
        '.confirm 應綁 :aria-label="t(\'common.action.confirm\')"',
    );
});

// ===== 浮層開關條件：三合取項 x-show，@click.stop，x-cloak =====

test('浮層 x-show 為三合取項：_pillEditor && showFavoriteActresses && _pillPopoverEnabled', () => {
    assert.ok(
        /class="pill-editor-popover"[^>]*x-show="_pillEditor && showFavoriteActresses && _pillPopoverEnabled"/.test(SHOWCASE_HTML)
        || /x-show="_pillEditor && showFavoriteActresses && _pillPopoverEnabled"[^>]*class="pill-editor-popover"/.test(SHOWCASE_HTML),
        '.pill-editor-popover 應綁 x-show="_pillEditor && showFavoriteActresses && _pillPopoverEnabled"',
    );
});

test('浮層帶 @click.stop（不得把點擊冒泡出去，供 T4 的 @click.outside 銜接）', () => {
    const openTagEnd = POPOVER.indexOf('>');
    const openTag = POPOVER.slice(0, openTagEnd + 1);
    assert.ok(/@click\.stop/.test(openTag), '.pill-editor-popover 開始標籤應含 @click.stop');
});

test('浮層帶 x-transition.opacity.duration.150ms（照抄 .toolbar-dropdown 既有寫法，不自訂 ease）', () => {
    const openTagEnd = POPOVER.indexOf('>');
    const openTag = POPOVER.slice(0, openTagEnd + 1);
    assert.ok(
        /x-transition\.opacity\.duration\.150ms/.test(openTag),
        '.pill-editor-popover 應綁 x-transition.opacity.duration.150ms',
    );
});

test('浮層不含 x-trap 或 @click.outside（T4 範圍，本 task 只鋪骨架）', () => {
    assert.ok(!POPOVER.includes('x-trap'), '.pill-editor-popover 本 task 不應含 x-trap（留給 T4）');
    assert.ok(!POPOVER.includes('@click.outside'), '.pill-editor-popover 本 task 不應含 @click.outside（留給 T4）');
});

// ===== i18n key：六個新 key 存在且值正確、且模板確有引用 =====

const EXPECTED_NEW_KEYS = {
    'showcase.pill.op.eq': '等於',
    'showcase.pill.op.lte': '小於等於',
    'showcase.pill.op.gte': '大於等於',
    'showcase.pill.op.range': '區間',
    'showcase.pill.editor.range_min': '下限',
    'showcase.pill.editor.range_max': '上限',
};

test('zh_TW.json 新增六個 pill.op / pill.editor key，值與 CD-116b-12b 表逐字一致', () => {
    for (const [key, expected] of Object.entries(EXPECTED_NEW_KEYS)) {
        const actual = lookupNested(ZH_TW, key);
        assert.equal(actual, expected, `zh_TW 缺/錯 key ${key}：期望 ${JSON.stringify(expected)}，實際 ${JSON.stringify(actual)}`);
    }
});

test('浮層 markup 確有綁定全部六個新 key', () => {
    for (const key of Object.keys(EXPECTED_NEW_KEYS)) {
        assert.ok(
            POPOVER.includes(`t('${key}')`),
            `.pill-editor-popover 應引用 t('${key}')`,
        );
    }
});

test('六個新 key 只寫 zh_TW（本檔不驗其餘三語，milestone 才補齊）', () => {
    // 僅確認 zh_TW 檔內確實新增，不對 zh_CN/en/ja 做任何斷言——依 CLAUDE.md
    // 「i18n 新增 key 只寫 zh_TW」，其餘三語留空靠 fallback是本 branch 刻意行為。
    assert.ok(lookupNested(ZH_TW, 'showcase.pill.op.eq') !== undefined);
});
