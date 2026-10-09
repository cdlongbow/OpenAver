// TASK-116c-T3: 女優 pill 浮層 markup 結構契約（116c 重設計）。
// 技術比照 actress-pill-shell.test.mjs：以文字解析 showcase.html，
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

// ===== pill 本體：兩個 <template x-if> 分流（button/span），非 :disabled ／ pointer-events =====

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope（ACTRESS_GROUP 配對 </div>），2 條 required 只能全檔掃＝子區塊放寬為全檔
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

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope（ACTRESS_GROUP 內 first-match 鄰近 required），全檔掃＝子區塊放寬為全檔
test('pill 本體的 button 分支綁 @click.stop="_togglePillEditor(pill)"（CD-116b-7 承重）', () => {
    assert.ok(
        /<button[^>]*class="filter-pill-value"[\s\S]{0,300}@click\.stop="_togglePillEditor\(\s*pill\s*\)"/.test(ACTRESS_GROUP),
        'button 態 .filter-pill-value 應綁 @click.stop="_togglePillEditor(pill)"',
    );
});

// ===== 三顆運算子鈕（116c：第四顆「區間」刪除，@click 改 _applyPillOp）=====

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope（POPOVER 內第 1 個 pill-editor-modes 計數切片），required 與計數須同切片
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

// ===== 罩杯：第 3–5 段在結構層 <template x-if> 分流內（條件字面硬鎖）=====

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope，.pill-editor-custom 配對取整塊，lazy capture 到 </template> 只是近似
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

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware 抽段的 structure-count（.pill-editor-range 內 <input> exact 2），tag-scan 只能逐顆認
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

// [lint-guard: node-justified] 162e 暫留：缺區塊內 exact 2 count＋inputs[0]=badLo／inputs[1]=badHi 順序，且 scope 需 depth-aware 抽段
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

// ===== ✓/✗ 動作列：x-show 條件 + 方法綁定 =====

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope（POPOVER），actions class＋x-show 共現與 cancel/confirm @click 全檔掃會放寬
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

// ===== 浮層開關條件：role/aria（dialog、aria-modal、aria-labelledby）=====

// [lint-guard: node-justified] 162e 暫留：title id 半邊（class/id 雙向屬性序）缺 depth-aware scope（POPOVER），required 半邊須同粒度
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
