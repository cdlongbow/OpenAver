// TASK-116c-T3: 女優 pill 浮層 markup 結構契約（116c 重設計）。
// 技術比照 actress-pill-shell.test.mjs：以文字解析 showcase.html / zh_TW.json，
// 不跑 CDP、不動 Alpine runtime、不需要 window/importmap（純文字讀取，FE-GUARD-11 不適用本檔）。
// 可互動 / 視覺幾何（真 click 開關、360/481px 斷點行為、content box 量測）交給 T4 CDP，本檔不重複驗。

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

// TASK-124a-T3 起 .pill-editor-popover 這個 class 有兩個實例（女優 ＋ 發售日）——
// 不能再用 bare class 字面去抓「第一個」，那只是碰巧文件順序在前，換了順序就會抓錯
// 區塊。改用 aria-labelledby="pill-editor-title" 精準錨定女優那個浮層（發售日浮層是
// aria-labelledby="release-editor-title"，兩者互斥，字面不會混淆）。
function extractPillEditorPopover(html) {
    return extractDivContaining(html, 'aria-labelledby="pill-editor-title"', '女優 .pill-editor-popover 浮層');
}

const ACTRESS_GROUP = extractActressFilterPillGroup(SHOWCASE_HTML);
const POPOVER = extractPillEditorPopover(SHOWCASE_HTML);

// ===== 容器唯一性 =====
// TASK-124a-T3 起 .pill-editor-popover 這個 class 有兩個實例（女優 ＋ 發售日各一）——
// 唯一性不再數 class 出現次數，改由各自的 title id 保證：女優浮層錨定
// id="pill-editor-title" / aria-labelledby="pill-editor-title"，恰各出現一次即可證明
// 「女優浮層恰一個」，不受另一個同 class 浮層存在與否影響。

test('女優 .pill-editor-popover 浮層唯一（由 pill-editor-title 這組 id 保證，不再數 class）', () => {
    const idMatches = SHOWCASE_HTML.match(/id="pill-editor-title"/g) || [];
    assert.equal(idMatches.length, 1, `預期恰好 1 個 id="pill-editor-title"，實際 ${idMatches.length}`);
    const labelledbyMatches = SHOWCASE_HTML.match(/aria-labelledby="pill-editor-title"/g) || [];
    assert.equal(labelledbyMatches.length, 1, `預期恰好 1 個 aria-labelledby="pill-editor-title"，實際 ${labelledbyMatches.length}`);
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

// TASK-124a-T3 起 spec-124a 前言明文解除 spec-116 §7「影片模式的 pill 行為與 markup
// 逐位元組不變」這條自我約束（124a 就是那個「之後」）——_pillPopoverEnabled（斷點閘門）
// 與 is-editing（正在編輯中標記）本來就是通用機制，release pill 走同一套手勢，出現在
// 影片 pill 區塊是預期行為，不再是污染。
// 保留的是「不得混用女優編輯器 slot」：pill-editor / _togglePillEditor / _pillEditor
// 是 CD-124a-4 指定的女優專屬符號（release 走獨立的 _releaseEditor slot），影片 pill
// 區塊出現這三者代表兩個 slot 被接混了，仍然是 bug。
test('影片 .filter-pill-group（bare class）不得混用女優編輯器 slot（pill-editor / _pillEditor 系列符號）', () => {
    const videoGroup = extractDivContaining(SHOWCASE_HTML, 'class="filter-pill-group"', '影片 .filter-pill-group（bare）');
    for (const forbidden of ['pill-editor', '_togglePillEditor', '_pillEditor']) {
        assert.ok(
            !videoGroup.includes(forbidden),
            `影片 .filter-pill-group 不應出現女優編輯器專屬符號 "${forbidden}"（CD-124a-4 slot 隔離）`,
        );
    }
});

// ===== 浮層段落順序 ＝ CD-116c-5（title → modes → custom）=====

test('浮層段落順序：title → modes → custom（含 range ＋ actions）', () => {
    const titleIdx = POPOVER.indexOf('class="pill-editor-title"');
    const modesIdx = POPOVER.indexOf('class="pill-editor-modes"');
    const customIdx = POPOVER.indexOf('class="pill-editor-custom"');
    const rangeIdx = POPOVER.indexOf('class="pill-editor-range"');
    const actionsIdx = POPOVER.indexOf('class="pill-editor-actions"');
    assert.ok(titleIdx !== -1, '應有 .pill-editor-title');
    assert.ok(modesIdx !== -1, '應有 .pill-editor-modes');
    assert.ok(customIdx !== -1, '應有 .pill-editor-custom');
    assert.ok(rangeIdx !== -1, '應有 .pill-editor-range');
    assert.ok(actionsIdx !== -1, '應有 .pill-editor-actions');
    assert.ok(titleIdx < modesIdx, 'title 應在 modes 之前');
    assert.ok(modesIdx < customIdx, 'modes 應在 custom 之前');
    assert.ok(customIdx < rangeIdx, 'custom 應包住 range');
    assert.ok(rangeIdx < actionsIdx, 'range 應在 actions 之前');
});

test('.pill-editor-title 用 t(\'showcase.pill.dim_label.\' + (_pillEditor?.dim || \'\'))', () => {
    assert.ok(
        /class="pill-editor-title"[^>]*x-text="t\('showcase\.pill\.dim_label\.'\s*\+\s*\(_pillEditor\?\.dim\s*\|\|\s*''\)\)"/.test(POPOVER),
        '.pill-editor-title 應動態綁定當前維度名稱',
    );
});

// ===== 三顆運算子鈕（116c：第四顆「區間」刪除，@click 改 _applyPillOp）=====

test('.pill-editor-modes 恰有三顆鈕，@click 分別綁 _applyPillOp(\'=\'|\'<=\'|\'>=\')', () => {
    const modesStart = POPOVER.indexOf('class="pill-editor-modes"');
    const modesEnd = POPOVER.indexOf('</div>', modesStart);
    const modesSection = POPOVER.slice(modesStart, modesEnd);
    const buttons = modesSection.match(/class="pill-editor-mode"/g) || [];
    assert.equal(buttons.length, 3, `.pill-editor-modes 應恰有三顆 .pill-editor-mode，實際 ${buttons.length}`);
    for (const op of ["'='", "'<='", "'>='"]) {
        assert.ok(
            POPOVER.includes(`@click="_applyPillOp(${op})"`),
            `應有 @click="_applyPillOp(${op})"`,
        );
    }
    // 舊契約殘留不得存在
    assert.ok(!POPOVER.includes('_setEditorMode'), '浮層不得再引用已刪的 _setEditorMode');
    assert.ok(!POPOVER.includes("@click=\"_applyPillOp('range')\""), '不得有第四顆 range 運算子鈕');
});

test('三顆鈕的 :class="{ \'is-active\': _pillEditor?.op === … }" 維持原樣（AC-C7b）', () => {
    for (const op of ["'='", "'<='", "'>='"]) {
        const re = new RegExp(
            `class="pill-editor-mode"[^>]*:class="\\{\\s*'is-active':\\s*_pillEditor\\?\\.op\\s*===\\s*${op}\\s*\\}"`,
        );
        assert.ok(re.test(POPOVER), `.pill-editor-mode 應有 op===${op} 的 .is-active 綁定`);
    }
    // range 不再是鈕，不得有 is-active 綁 op==='range'
    assert.ok(
        !/:class="\{\s*'is-active':\s*_pillEditor\?\.op\s*===\s*'range'\s*\}"/.test(POPOVER),
        '不得有 op===\'range\' 的 .is-active 綁定（區間不再是模式鈕）',
    );
});

// ===== 罩杯：第 3–5 段在結構層 <template x-if> 分流內（條件字面硬鎖）=====

test('第 3–5 段包在 <template x-if="_pillEditor && _pillEditor.dim !== \'cup\'"> 內（條件字面硬鎖）', () => {
    // ⚠ 本 task 第一風險：不得寫成 _pillEditor?.dim !== 'cup'
    // （浮層關著時 _pillEditor 為 null，optional chaining 條件為 true → x-model 炸 null）
    assert.ok(
        /<template x-if="_pillEditor && _pillEditor\.dim !== 'cup'">/.test(POPOVER),
        '必須是字面 <template x-if="_pillEditor && _pillEditor.dim !== \'cup\'">',
    );
    // 反向：?. 版本是本 task 最容易犯的錯，守衛必須擋得住
    assert.ok(
        !/<template x-if="_pillEditor\?\.dim !== 'cup'">/.test(POPOVER),
        '不得用 <template x-if="_pillEditor?.dim !== \'cup\'">（關閉時會炸 x-model）',
    );
    // 根元素必須是 .pill-editor-custom
    const xIfIdx = POPOVER.indexOf('<template x-if="_pillEditor && _pillEditor.dim !== \'cup\'">');
    assert.ok(xIfIdx !== -1);
    const afterXIf = POPOVER.slice(xIfIdx, xIfIdx + 200);
    assert.ok(
        /class="pill-editor-custom"/.test(afterXIf),
        'x-if 的單一根元素應是 .pill-editor-custom',
    );
    // range + actions 都在 custom 裡面
    const custom = extractDivContaining(POPOVER, 'class="pill-editor-custom"', '.pill-editor-custom');
    assert.ok(custom.includes('class="pill-editor-range"'), '.pill-editor-range 應在 .pill-editor-custom 內');
    assert.ok(custom.includes('class="pill-editor-actions"'), '.pill-editor-actions 應在 .pill-editor-custom 內');
    assert.ok(custom.includes('class="pill-editor-custom-label"'), '.pill-editor-custom-label 應在 .pill-editor-custom 內');
    // 罩杯排除不得用 x-show
    assert.ok(
        !/x-show="[^"]*dim[^"]*!==\s*'cup'/.test(POPOVER),
        '罩杯排除不得用 x-show（必須是結構層 <template x-if>）',
    );
});

// ===== 自訂區間列：常駐、無 :min/:max、inputmode、~ 分隔 =====

test('兩個 range input：inputmode=numeric、無 :min/:max、無 x-model.number、aria-label 沿用既有 key', () => {
    const rangeSection = extractDivContaining(POPOVER, 'class="pill-editor-range"', '.pill-editor-range');
    const inputs = rangeSection.match(/<input\b[^>]*>/g) || [];
    assert.equal(inputs.length, 2, `.pill-editor-range 應恰有兩個 <input>，實際 ${inputs.length}`);
    for (const input of inputs) {
        assert.ok(
            /inputmode="numeric"/.test(input),
            `input 應有 inputmode="numeric"：${input}`,
        );
        assert.ok(
            !/:min=/.test(input),
            `input 不得有 :min（§3.6 不做範圍驗證）：${input}`,
        );
        assert.ok(
            !/:max=/.test(input),
            `input 不得有 :max（§3.6 不做範圍驗證）：${input}`,
        );
        // 反面先例守則：settings.html 的 x-model.number 不准抄（CD-116b-1）
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
    // 舊契約殘留
    assert.ok(!POPOVER.includes('_pillRangeBounds'), '浮層不得再引用已刪的 _pillRangeBounds');
    assert.ok(
        !POPOVER.includes("_pillEditor?.op === 'range'"),
        '區間列不再包在 op===\'range\' 的 x-if 裡（常駐）',
    );
});

// ===== Codex PR review P2-2：兩個 range input 都要回報 badInput 給狀態層 =====

test('兩個 range input 都綁 @input，把 $event.target.validity.badInput 寫進對應的 badLo/badHi（不是別的東西）', () => {
    const rangeSection = extractDivContaining(POPOVER, 'class="pill-editor-range"', '.pill-editor-range');
    const inputs = rangeSection.match(/<input\b[^>]*>/g) || [];
    assert.equal(inputs.length, 2, `.pill-editor-range 應恰有兩個 <input>，實際 ${inputs.length}`);
    assert.ok(
        /@input="_pillEditor\.badLo\s*=\s*\$event\.target\.validity\.badInput"/.test(inputs[0]),
        `下限 input 應綁 @input 寫入 _pillEditor.badLo＝$event.target.validity.badInput：${inputs[0]}`,
    );
    assert.ok(
        /@input="_pillEditor\.badHi\s*=\s*\$event\.target\.validity\.badInput"/.test(inputs[1]),
        `上限 input 應綁 @input 寫入 _pillEditor.badHi＝$event.target.validity.badInput：${inputs[1]}`,
    );
});

test('兩框之間有 ~ 分隔（.pill-editor-range-sep，aria-hidden）', () => {
    const rangeSection = extractDivContaining(POPOVER, 'class="pill-editor-range"', '.pill-editor-range');
    assert.ok(
        /class="pill-editor-range-sep"[^>]*aria-hidden="true"/.test(rangeSection)
        || /aria-hidden="true"[^>]*class="pill-editor-range-sep"/.test(rangeSection),
        '應有 .pill-editor-range-sep 且 aria-hidden="true"',
    );
    assert.ok(
        /class="pill-editor-range-sep"[^>]*>~</.test(rangeSection)
        || />~<\/span>/.test(rangeSection),
        '分隔符可見文字應為 ~',
    );
});

test('自訂區間標籤用 t(\'showcase.pill.op.range\') ＋ hint 綁 _pillDimRangeHint()', () => {
    const custom = extractDivContaining(POPOVER, 'class="pill-editor-custom"', '.pill-editor-custom');
    assert.ok(
        /class="pill-editor-custom-label"[\s\S]*x-text="t\('showcase\.pill\.op\.range'\)"/.test(custom),
        '標籤應綁 t(\'showcase.pill.op.range\')',
    );
    assert.ok(
        /class="pill-editor-hint"[^>]*x-text="_pillDimRangeHint\(\)"/.test(custom),
        '.pill-editor-hint 應綁 x-text="_pillDimRangeHint()"',
    );
});

test('整個浮層（含 range input 之外）不含任何 x-model.number（CD-116b-1 反面先例）', () => {
    assert.ok(
        !POPOVER.includes('x-model.number'),
        '.pill-editor-popover 內任何欄位都不得用 x-model.number',
    );
});

// ===== ✓/✗ 動作列：x-show 條件 + 方法綁定 =====

test('.pill-editor-actions 綁 x-show="_pillEditorHasRangeInput()"，且含 cancel/confirm', () => {
    assert.ok(
        /class="pill-editor-actions"[^>]*x-show="_pillEditorHasRangeInput\(\)"/.test(POPOVER)
        || /x-show="_pillEditorHasRangeInput\(\)"[^>]*class="pill-editor-actions"/.test(POPOVER),
        '.pill-editor-actions 應綁 x-show="_pillEditorHasRangeInput()"',
    );
    assert.ok(
        /class="pill-editor-btn cancel"[^>]*@click="_cancelPillEditor\(\)"/.test(POPOVER),
        '.pill-editor-btn.cancel 應綁 @click="_cancelPillEditor()"',
    );
    assert.ok(
        /class="pill-editor-btn confirm"[^>]*@click="_commitPillEditor\(\)"/.test(POPOVER),
        '.pill-editor-btn.confirm 應綁 @click="_commitPillEditor()"',
    );
});

test('✓/✗ 的 aria-label 重用既有 common.action.confirm/cancel（不新增 key）', () => {
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

test('浮層帶 @click.stop（不得把點擊冒泡出去，供 @click.outside 銜接）', () => {
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

test('浮層帶 x-trap="!!_pillEditor"（不加 .inert）與 @click.outside（CD-116b-9）', () => {
    const openTagEnd = POPOVER.indexOf('>');
    const openTag = POPOVER.slice(0, openTagEnd + 1);
    assert.ok(
        /x-trap="!!_pillEditor"/.test(openTag),
        '.pill-editor-popover 應綁 x-trap="!!_pillEditor"',
    );
    assert.ok(
        !/x-trap\.inert/.test(openTag),
        'x-trap 不得帶 .inert（CD-116b-9：modal 級語意與點外面關閉矛盾）',
    );
    assert.ok(
        /@click\.outside="_pillEditor && _cancelPillEditor\(\)"/.test(openTag),
        '.pill-editor-popover 應綁 @click.outside="_pillEditor && _cancelPillEditor()"',
    );
});

test('浮層 role/aria：dialog + aria-modal=false + aria-labelledby=pill-editor-title', () => {
    const openTagEnd = POPOVER.indexOf('>');
    const openTag = POPOVER.slice(0, openTagEnd + 1);
    assert.ok(/role="dialog"/.test(openTag), '應有 role="dialog"');
    assert.ok(/aria-modal="false"/.test(openTag), '應有 aria-modal="false"（non-modal）');
    assert.ok(
        /aria-labelledby="pill-editor-title"/.test(openTag),
        '應有 aria-labelledby="pill-editor-title"',
    );
    assert.ok(
        /class="pill-editor-title"[^>]*id="pill-editor-title"/.test(POPOVER)
        || /id="pill-editor-title"[^>]*class="pill-editor-title"/.test(POPOVER),
        '.pill-editor-title 應有 id="pill-editor-title"',
    );
});

// ===== i18n key：用途沿用／改值，模板確有引用 =====

const EXPECTED_KEYS = {
    'showcase.pill.op.eq': '等於',
    'showcase.pill.op.lte': '小於等於',
    'showcase.pill.op.gte': '大於等於',
    'showcase.pill.op.range': '自訂區間',
    'showcase.pill.editor.range_min': '下限',
    'showcase.pill.editor.range_max': '上限',
};

test('zh_TW.json 六個 pill.op / pill.editor key 值正確（range 改為「自訂區間」）', () => {
    for (const [key, expected] of Object.entries(EXPECTED_KEYS)) {
        const actual = lookupNested(ZH_TW, key);
        assert.equal(actual, expected, `zh_TW 缺/錯 key ${key}：期望 ${JSON.stringify(expected)}，實際 ${JSON.stringify(actual)}`);
    }
});

test('浮層 markup 確有綁定全部六個 key', () => {
    for (const key of Object.keys(EXPECTED_KEYS)) {
        assert.ok(
            POPOVER.includes(`t('${key}')`),
            `.pill-editor-popover 應引用 t('${key}')`,
        );
    }
});

test('六個 key 只寫 zh_TW（本檔不驗其餘三語，milestone 才補齊）', () => {
    // 僅確認 zh_TW 檔內確實存在，不對 zh_CN/en/ja 做任何斷言——依 CLAUDE.md
    // 「i18n 新增 key 只寫 zh_TW」，其餘三語留空靠 fallback是本 branch 刻意行為。
    assert.ok(lookupNested(ZH_TW, 'showcase.pill.op.eq') !== undefined);
});
