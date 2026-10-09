// TASK-124a-T3: 發售日 pill / 浮層 markup 結構契約（跨切面收尾）。
// 技術比照 pill-shell.test.mjs / actress-pill-popover-shell.test.mjs：以文字解析
// showcase.html / zh_TW.json，不跑 CDP、不動 Alpine runtime。
// 本檔只驗「接線對不對」（靜態結構是否照契約接線），不驗「按下去視覺上動不動」
// ——視覺／互動最終確認交 owner 真機 hard-gate（plan-124a §6/§9 明文不跑 CDP）。

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
 * 逐字比照 actress-pill-popover-shell.test.mjs 的 extractDivContaining()。
 */
function extractDivContaining(html, openTagLiteral, label, fromIndex) {
    const idx = html.indexOf(openTagLiteral, fromIndex || 0);
    assert.ok(idx !== -1, `showcase.html 應含 ${label}（找不到字面：${openTagLiteral}）`);
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

function extractSpanContaining(html, openTagLiteral, label, fromIndex) {
    const idx = html.indexOf(openTagLiteral, fromIndex || 0);
    assert.ok(idx !== -1, `showcase.html 應含 ${label}（找不到字面：${openTagLiteral}）`);
    const spanStart = html.lastIndexOf('<span', idx);
    assert.ok(spanStart !== -1, `${label} 字面前找不到對應的 <span 開始標籤`);
    const tagEnd = html.indexOf('>', idx);
    assert.ok(tagEnd !== -1, `${label} 的開始標籤未正常結束`);
    let i = tagEnd + 1;
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
                return html.slice(spanStart, i);
            }
        }
    }
    throw new Error(`${label} 未找到匹配的 </span>`);
}

function extractVideoFilterPillGroup(html) {
    return extractDivContaining(html, 'class="filter-pill-group" x-show="!showFavoriteActresses"', '影片 .filter-pill-group');
}

function extractReleaseEditorPopover(html) {
    return extractDivContaining(html, 'id="release-editor-title"', '發售日浮層', 0);
}

const VIDEO_GROUP = extractVideoFilterPillGroup(SHOWCASE_HTML);
// 發售日浮層外層 tag 起點在 id="release-editor-title" 之前很遠，改用 class="pill-editor-popover"
// 第二次出現的位置往回抓 <div（女優浮層第一個、release 第二個，逐字比照現況分析已驗證順序）。
function extractSecondPillEditorPopover(html) {
    const first = html.indexOf('class="pill-editor-popover"');
    assert.ok(first !== -1, '應至少有一個 .pill-editor-popover');
    const second = html.indexOf('class="pill-editor-popover"', first + 1);
    assert.ok(second !== -1, '應恰有第二個 .pill-editor-popover（release 浮層）');
    return extractDivContaining(html, 'class="pill-editor-popover"', 'release 浮層（第二個 .pill-editor-popover）', second);
}
const RELEASE_POPOVER = extractSecondPillEditorPopover(SHOWCASE_HTML);

// ===== 燈箱入口：兩支 <template x-if> 分流 =====

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope（配對 </span> 取整段 770 字元），只有 {anchor,window:N}，required 會吃到鄰居
test('燈箱發售日入口：兩支 <template x-if> 分流，判準 _isReleaseClickable(currentLightboxVideo)', () => {
    const section = extractSpanContaining(SHOWCASE_HTML, 'currentLightboxVideo?.release_date">', '燈箱發售日 <span x-show>');
    assert.ok(
        /<template x-if="_isReleaseClickable\(currentLightboxVideo\)">/.test(section),
        '應有正向 <template x-if="_isReleaseClickable(currentLightboxVideo)">',
    );
    assert.ok(
        /<template x-if="!_isReleaseClickable\(currentLightboxVideo\)">/.test(section),
        '應有反向 <template x-if="!_isReleaseClickable(currentLightboxVideo)">',
    );
    assert.ok(
        /class="lb-link"/.test(section),
        '可點分支應帶 class="lb-link"（鏡射同列 director/series/label 連結）',
    );
    assert.ok(
        /@click\.prevent="searchFromMetadata\(currentLightboxVideo\?\.release_date,\s*'release'\)"/.test(section),
        '可點分支應綁 @click.prevent="searchFromMetadata(currentLightboxVideo?.release_date, \'release\')"（不帶 .stop）',
    );
    assert.ok(
        !/@click\.prevent\.stop="searchFromMetadata\(currentLightboxVideo\?\.release_date/.test(section),
        '燈箱入口不得帶 .stop（同列 director/series/label 連結今天就沒有 .stop）',
    );
});

// ===== 卡片 info 入口：兩支 <template x-if> 分流 =====

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope（配對 </span> 取整段 678 字元），只有 {anchor,window:N}，required 會吃到鄰居
test('卡片 info 發售日入口：兩支 <template x-if> 分流，判準 _isReleaseClickable(video)', () => {
    const section = extractSpanContaining(SHOWCASE_HTML, 'video.release_date">', '卡片 info 發售日 <span x-show>');
    assert.ok(
        /<template x-if="_isReleaseClickable\(video\)">/.test(section),
        '應有正向 <template x-if="_isReleaseClickable(video)">',
    );
    assert.ok(
        /<template x-if="!_isReleaseClickable\(video\)">/.test(section),
        '應有反向 <template x-if="!_isReleaseClickable(video)">',
    );
    assert.ok(
        /class="info-link"/.test(section),
        '可點分支應帶 class="info-link"（鏡射同列 maker 連結）',
    );
    assert.ok(
        /@click\.prevent\.stop="searchFromMetadata\(video\.release_date,\s*'release'\)"/.test(section),
        '可點分支應綁 @click.prevent.stop="searchFromMetadata(video.release_date, \'release\')"',
    );
});

// ===== 影片 pill：可點分流（button/span） =====

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope（VIDEO_GROUP 配對 </div>），required 只能全檔掃＝子區塊放寬為全檔
test('影片 pill：兩支互斥 <template x-if> 分流，判準 pill.dim === \'release\' && _pillPopoverEnabled', () => {
    assert.ok(
        /<template x-if="pill\.dim === 'release' && _pillPopoverEnabled">\s*<button[^>]*class="filter-pill-value"/.test(VIDEO_GROUP),
        '正向應渲染 <button class="filter-pill-value">',
    );
    assert.ok(
        /<template x-if="!\(pill\.dim === 'release' && _pillPopoverEnabled\)">\s*<span[^>]*class="filter-pill-value"/.test(VIDEO_GROUP),
        '反向應渲染 <span class="filter-pill-value">（非 button）',
    );
});

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope（VIDEO_GROUP 內鄰近比對 required），全檔會被別處 filter-pill-value 按鈕餵飽
test('影片 pill：button 分支綁 @click.stop="_toggleReleaseEditor(pill)"，不使用 :disabled / pointer-events', () => {
    assert.ok(
        /<button[^>]*class="filter-pill-value"[\s\S]{0,200}@click\.stop="_toggleReleaseEditor\(\s*pill\s*\)"/.test(VIDEO_GROUP),
        'button 態 .filter-pill-value 應綁 @click.stop="_toggleReleaseEditor(pill)"',
    );
    assert.ok(
        !/filter-pill-value[\s\S]{0,200}:disabled/.test(VIDEO_GROUP),
        '.filter-pill-value 不應綁 :disabled',
    );
    assert.ok(
        !/filter-pill-value[\s\S]{0,200}pointer-events/.test(VIDEO_GROUP),
        '.filter-pill-value 不應靠 pointer-events 停用',
    );
});

// [lint-guard: node-justified] 162e 暫留：缺「VIDEO_GROUP 內第一個 :key」語意的 scope，全檔 required 只驗存在性，撞鍵保護流失
test('影片 pill：x-for 的 :key 一個字元都未改（複合鍵 pill.dim + \'::\' + normalizePillValue(pill.value)）', () => {
    const keyAttr = VIDEO_GROUP.match(/:key="([^"]+)"/);
    assert.ok(keyAttr, 'x-for template 應有 :key 綁定');
    assert.equal(
        keyAttr[1],
        "pill.dim + '::' + normalizePillValue(pill.value)",
        ':key 表達式必須逐字不變',
    );
});

// ===== 三顆運算子鈕 =====

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope（RELEASE_POPOVER 取整個浮層），6 條 required 全檔掃＝子區塊放寬為全檔
test('release 浮層三顆運算子鈕：@click 綁 _applyReleaseOp(...)，:class 判準 _releaseEditor?.op === ...', () => {
    for (const op of ["'='", "'<='", "'>='"]) {
        assert.ok(
            RELEASE_POPOVER.includes(`@click="_applyReleaseOp(${op})"`),
            `應有 @click="_applyReleaseOp(${op})"`,
        );
        const re = new RegExp(
            `class="pill-editor-mode"[^>]*:class="\\{\\s*'is-active':\\s*_releaseEditor\\?\\.op\\s*===\\s*${op}\\s*\\}"`,
        );
        assert.ok(re.test(RELEASE_POPOVER), `.pill-editor-mode 應有 op===${op} 的 .is-active 綁定`);
    }
});

// ===== 四格所在的 <template x-if> 必須是裸判斷 =====

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope（RELEASE_POPOVER），required 半邊須同粒度，全檔 required 會放寬
test('四格所在 <template x-if="_releaseEditor"> 是裸判斷（不得是 optional chaining）', () => {
    assert.ok(
        /<template x-if="_releaseEditor">\s*<div class="pill-editor-custom">/.test(RELEASE_POPOVER),
        '必須是字面 <template x-if="_releaseEditor">，根元素 .pill-editor-custom',
    );
    assert.ok(
        !/<template x-if="_releaseEditor\?\./.test(RELEASE_POPOVER),
        '不得用 <template x-if="_releaseEditor?.xxx">（浮層關閉時 _releaseEditor 為 null，optional chaining 條件為 false 沒問題，但為 undefined 屬性存取仍是危險寫法且偏離契約定案的裸判斷）',
    );
});

// ===== 四個 input：type/inputmode/x-model/@input/aria-label/class/無 min max =====

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope，exact 4 個 <input> 的 structure-count 與逐格 order 無法限定在 div.pill-editor-range
test('四個 <input> 逐一斷言：type/inputmode/x-model/@input/aria-label/class，且無 min/max', () => {
    const rangeSection = extractDivContaining(RELEASE_POPOVER, 'class="pill-editor-range"', '.pill-editor-range（release）');
    const inputs = rangeSection.match(/<input\b[^>]*>/g) || [];
    assert.equal(inputs.length, 4, `.pill-editor-range 應恰有四個 <input>，實際 ${inputs.length}`);

    const specs = [
        { field: 'loYear', bad: 'badLoY', ariaKey: 'showcase.pill.editor.from_year', cls: 'pe-ym-year' },
        { field: 'loMonth', bad: 'badLoM', ariaKey: 'showcase.pill.editor.from_month', cls: 'pe-ym-month' },
        { field: 'hiYear', bad: 'badHiY', ariaKey: 'showcase.pill.editor.to_year', cls: 'pe-ym-year' },
        { field: 'hiMonth', bad: 'badHiM', ariaKey: 'showcase.pill.editor.to_month', cls: 'pe-ym-month' },
    ];

    inputs.forEach((input, i) => {
        const spec = specs[i];
        assert.ok(/type="number"/.test(input), `第 ${i + 1} 個 input 應有 type="number"：${input}`);
        assert.ok(/inputmode="numeric"/.test(input), `第 ${i + 1} 個 input 應有 inputmode="numeric"：${input}`);
        assert.ok(
            !/\bmin=/.test(input) && !/:min=/.test(input),
            `第 ${i + 1} 個 input 不得有 min/:min：${input}`,
        );
        assert.ok(
            !/\bmax=/.test(input) && !/:max=/.test(input),
            `第 ${i + 1} 個 input 不得有 max/:max：${input}`,
        );
        assert.ok(
            new RegExp(`x-model="_releaseEditor\\.${spec.field}"`).test(input),
            `第 ${i + 1} 個 input 應綁 x-model="_releaseEditor.${spec.field}"：${input}`,
        );
        assert.ok(
            new RegExp(`@input="_releaseEditor\\.${spec.bad}\\s*=\\s*\\$event\\.target\\.validity\\.badInput"`).test(input),
            `第 ${i + 1} 個 input 應綁 @input 寫入 _releaseEditor.${spec.bad}：${input}`,
        );
        assert.ok(
            new RegExp(`:aria-label="t\\('${spec.ariaKey.replace(/\./g, '\\.')}'\\)"`).test(input),
            `第 ${i + 1} 個 input 應綁 :aria-label="t('${spec.ariaKey}')"：${input}`,
        );
        assert.ok(
            new RegExp(`class="input input-bordered input-sm ${spec.cls}"`).test(input),
            `第 ${i + 1} 個 input 應有 class 含 ${spec.cls}：${input}`,
        );
    });
});

// ===== ✓✗ 動作列 =====

// [lint-guard: node-justified] 162e 暫留：缺 depth-aware scope（RELEASE_POPOVER），cancel/confirm 鄰近比對全檔會被女優浮層同形按鈕餵飽
test('release 浮層 ✓✗：x-show="_releaseEditorHasInput()"，cancel/confirm 綁定正確', () => {
    assert.ok(
        /class="pill-editor-actions" x-show="_releaseEditorHasInput\(\)"/.test(RELEASE_POPOVER),
        '.pill-editor-actions 應綁 x-show="_releaseEditorHasInput()"',
    );
    assert.ok(
        /class="pill-editor-btn cancel"[^>]*@click="_cancelReleaseEditor\(\)"/.test(RELEASE_POPOVER),
        '.pill-editor-btn.cancel 應綁 @click="_cancelReleaseEditor()"',
    );
    assert.ok(
        /class="pill-editor-btn confirm"[^>]*@click="_commitReleaseEditor\(\)"/.test(RELEASE_POPOVER),
        '.pill-editor-btn.confirm 應綁 @click="_commitReleaseEditor()"',
    );
    assert.ok(
        /class="pill-editor-btn cancel"[\s\S]{0,200}:aria-label="t\('common\.action\.cancel'\)"/.test(RELEASE_POPOVER),
        '.cancel 應綁 :aria-label="t(\'common.action.cancel\')"（沿用既有 key，不新增）',
    );
    assert.ok(
        /class="pill-editor-btn confirm"[\s\S]{0,200}:aria-label="t\('common\.action\.confirm'\)"/.test(RELEASE_POPOVER),
        '.confirm 應綁 :aria-label="t(\'common.action.confirm\')"（沿用既有 key，不新增）',
    );
});
