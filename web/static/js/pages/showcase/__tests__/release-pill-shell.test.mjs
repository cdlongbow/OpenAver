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

// ===== 表格模式 / 清單模式：零改動（AC22 反面對照） =====

test('表格模式 .table-cell-date 維持純文字，不含 _isReleaseClickable / searchFromMetadata', () => {
    const m = SHOWCASE_HTML.match(/<td class="table-cell-date"[^>]*><\/td>/);
    assert.ok(m, '應有 <td class="table-cell-date" ...></td>');
    assert.ok(
        m[0].includes("video.release_date || '-'"),
        '表格模式應維持 x-text="video.release_date || \'-\'"，逐字不變',
    );
    assert.ok(
        !/_isReleaseClickable|searchFromMetadata/.test(m[0]),
        '表格模式不得引入可點判斷（spec §6 第 8 條）',
    );
});

// ===== 影片 pill：可點分流（button/span） =====

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

test('影片 pill：外層 .filter-pill 的 :class 綁 is-editing，含 _releaseEditor 與 pill.dim === \'release\'', () => {
    assert.ok(
        /<span class="filter-pill" role="listitem"[\s\S]{0,200}:class="\{\s*'is-editing':\s*!!_releaseEditor\s*&&\s*pill\.dim\s*===\s*'release'\s*\}"/.test(VIDEO_GROUP),
        '外層 .filter-pill 應綁 :class="{ \'is-editing\': !!_releaseEditor && pill.dim === \'release\' }"',
    );
});

test('影片 pill：x-for 的 :key 一個字元都未改（複合鍵 pill.dim + \'::\' + normalizePillValue(pill.value)）', () => {
    const keyAttr = VIDEO_GROUP.match(/:key="([^"]+)"/);
    assert.ok(keyAttr, 'x-for template 應有 :key 綁定');
    assert.equal(
        keyAttr[1],
        "pill.dim + '::' + normalizePillValue(pill.value)",
        ':key 表達式必須逐字不變',
    );
});

test('影片 pill：:title / :aria-label 的 value 已改用 pillLabel(pill)（非 pill.value）', () => {
    const titleAttr = VIDEO_GROUP.match(/:title="([^"]+)"/);
    assert.ok(titleAttr, '應有 :title 綁定');
    assert.ok(
        titleAttr[1].includes('value: pillLabel(pill)'),
        `:title 應含 value: pillLabel(pill)，實際：${titleAttr[1]}`,
    );
    assert.ok(
        !/showcase\.pill\.title'.*value:\s*pill\.value/.test(titleAttr[1]),
        ':title 不得再用裸 pill.value',
    );

    const ariaAttr = VIDEO_GROUP.match(/:aria-label="([^"]+)"/);
    assert.ok(ariaAttr, '應有 :aria-label 綁定');
    assert.ok(
        ariaAttr[1].includes('value: pillLabel(pill)'),
        `:aria-label 應含 value: pillLabel(pill)，實際：${ariaAttr[1]}`,
    );
});

test('影片 pill：pillLabel(pill) 綁定不只服務 release——非 pick/release 維度仍走同一個 :title 表達式（結構斷言）', () => {
    // 恆等替換的訊號：:title 綁定式本身只有一份，release/actress/tag 等維度共用同一條表達式，
    // 不是為 release 另開一支分支。若未來有人替 release 開一條獨立 :title 綁定，這條測試會因
    // 「只找到一個 :title 屬性」的前提被打破而需要更新（見「本 task 新增」陷阱條目）。
    const titleAttrs = VIDEO_GROUP.match(/:title="[^"]+"/g) || [];
    assert.equal(titleAttrs.length, 1, '.filter-pill 應恰有一個 :title 綁定（非 release 專屬分支）');
});

// ===== 女優 markup 零 diff（結構層自證：不得出現 release 符號） =====

test('女優 .actress-filter-pill-group 容器零污染：不含任何 release / 124a 新符號', () => {
    const actressGroup = extractDivContaining(
        SHOWCASE_HTML,
        'class="filter-pill-group actress-filter-pill-group"',
        '.actress-filter-pill-group 容器',
    );
    for (const forbidden of ['_toggleReleaseEditor', '_releaseEditor', 'pillLabel', "pill.dim === 'release'"]) {
        assert.ok(
            !actressGroup.includes(forbidden),
            `.actress-filter-pill-group 不應出現 124a 符號 "${forbidden}"`,
        );
    }
});

test('女優浮層（第一個 .pill-editor-popover）零污染：不含 release 符號，id 仍是 pill-editor-title', () => {
    const first = SHOWCASE_HTML.indexOf('class="pill-editor-popover"');
    const actressPopover = extractDivContaining(SHOWCASE_HTML, 'class="pill-editor-popover"', '女優浮層', first);
    assert.ok(actressPopover.includes('id="pill-editor-title"'), '女優浮層標題 id 應維持 pill-editor-title');
    for (const forbidden of ['_releaseEditor', '_toggleReleaseEditor', '_applyReleaseOp', '_commitReleaseEditor', '_cancelReleaseEditor', 'pe-ym-']) {
        assert.ok(
            !actressPopover.includes(forbidden),
            `女優浮層不應出現 release 符號 "${forbidden}"`,
        );
    }
});

// ===== 第二個浮層：恰一個，容器屬性齊備 =====

test('showcase.html 恰有兩個 .pill-editor-popover（女優 + release）', () => {
    const matches = SHOWCASE_HTML.match(/class="pill-editor-popover"/g) || [];
    assert.equal(matches.length, 2, `預期恰好 2 個 .pill-editor-popover，實際 ${matches.length}`);
});

test('release 浮層恰有一個 id="release-editor-title"', () => {
    const matches = SHOWCASE_HTML.match(/id="release-editor-title"/g) || [];
    assert.equal(matches.length, 1, `預期恰好 1 個 id="release-editor-title"，實際 ${matches.length}`);
});

test('release 浮層 x-show 三合取項字面：_releaseEditor && !showFavoriteActresses && _pillPopoverEnabled', () => {
    const openTagEnd = RELEASE_POPOVER.indexOf('>');
    const openTag = RELEASE_POPOVER.slice(0, openTagEnd + 1);
    assert.ok(
        /x-show="_releaseEditor && !showFavoriteActresses && _pillPopoverEnabled"/.test(openTag),
        `.pill-editor-popover（release）應綁三合取項 x-show，實際開始標籤：${openTag}`,
    );
});

test('release 浮層：x-trap="!!_releaseEditor"、@click.outside、@click.stop、role/aria 齊備', () => {
    const openTagEnd = RELEASE_POPOVER.indexOf('>');
    const openTag = RELEASE_POPOVER.slice(0, openTagEnd + 1);
    assert.ok(/x-cloak/.test(openTag), '應有 x-cloak');
    assert.ok(/x-transition\.opacity\.duration\.150ms/.test(openTag), '應有 x-transition.opacity.duration.150ms');
    assert.ok(/x-trap="!!_releaseEditor"/.test(openTag), '應有 x-trap="!!_releaseEditor"');
    assert.ok(
        /@click\.outside="_releaseEditor && _cancelReleaseEditor\(\)"/.test(openTag),
        '應有 @click.outside="_releaseEditor && _cancelReleaseEditor()"',
    );
    assert.ok(/@click\.stop/.test(openTag), '應有 @click.stop');
    assert.ok(/role="dialog"/.test(openTag), '應有 role="dialog"');
    assert.ok(/aria-modal="false"/.test(openTag), '應有 aria-modal="false"');
    assert.ok(/aria-labelledby="release-editor-title"/.test(openTag), '應有 aria-labelledby="release-editor-title"');
});

test('release 浮層標題綁 t(\'showcase.pill.dim_label.release\')，id="release-editor-title"', () => {
    assert.ok(
        /class="pill-editor-title" id="release-editor-title" x-text="t\('showcase\.pill\.dim_label\.release'\)"/.test(RELEASE_POPOVER),
        '.pill-editor-title 應綁 x-text="t(\'showcase.pill.dim_label.release\')" 且 id="release-editor-title"',
    );
});

// ===== 三顆運算子鈕 =====

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

test('四格之間只有一個 ~ 分隔符，位於第 2 格（loMonth）與第 3 格（hiYear）之間', () => {
    const rangeSection = extractDivContaining(RELEASE_POPOVER, 'class="pill-editor-range"', '.pill-editor-range（release）');
    const sepMatches = rangeSection.match(/class="pill-editor-range-sep"/g) || [];
    assert.equal(sepMatches.length, 1, `應恰有一個 .pill-editor-range-sep，實際 ${sepMatches.length}`);
    const loMonthIdx = rangeSection.indexOf('_releaseEditor.loMonth');
    const sepIdx = rangeSection.indexOf('class="pill-editor-range-sep"');
    const hiYearIdx = rangeSection.indexOf('_releaseEditor.hiYear');
    assert.ok(loMonthIdx !== -1 && sepIdx !== -1 && hiYearIdx !== -1);
    assert.ok(loMonthIdx < sepIdx, 'loMonth 應在 ~ 之前');
    assert.ok(sepIdx < hiYearIdx, '~ 應在 hiYear 之前');
});

// ===== ✓✗ 動作列 =====

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

test('release 浮層 hint 綁 _releaseYearHint()，label 綁 t(\'showcase.pill.op.range\')', () => {
    assert.ok(
        /class="pill-editor-hint" x-text="_releaseYearHint\(\)"/.test(RELEASE_POPOVER),
        '.pill-editor-hint 應綁 x-text="_releaseYearHint()"',
    );
    assert.ok(
        /class="pill-editor-custom-label"/.test(RELEASE_POPOVER) && RELEASE_POPOVER.includes("t('showcase.pill.op.range')"),
        '.pill-editor-custom-label 應引用 t(\'showcase.pill.op.range\')',
    );
});

// ===== CSS：.pe-ym-year / .pe-ym-month 兩條新增 + :3569 selector 改動 =====

const SHOWCASE_CSS = readFileSync(
    path.join(REPO_ROOT, 'web/static/css/pages/showcase.css'),
    'utf8',
);

test('showcase.css 新增 .pe-ym-year（5ch）與 .pe-ym-month（4ch）', () => {
    assert.ok(
        /\.pill-editor-range\s+\.pe-ym-year\s*\{\s*width:\s*5ch;\s*\}/.test(SHOWCASE_CSS),
        '應有 .pill-editor-range .pe-ym-year { width: 5ch; }',
    );
    assert.ok(
        /\.pill-editor-range\s+\.pe-ym-month\s*\{\s*width:\s*4ch;\s*\}/.test(SHOWCASE_CSS),
        '應有 .pill-editor-range .pe-ym-month { width: 4ch; }',
    );
});

test('showcase.css：button chrome reset selector 改為 .filter-pill-group（不再限定 .actress-filter-pill-group）', () => {
    assert.ok(
        !SHOWCASE_CSS.includes('.actress-filter-pill-group button.filter-pill-value'),
        '.actress-filter-pill-group button.filter-pill-value 選擇器不應再存在',
    );
    assert.ok(
        /\.filter-pill-group button\.filter-pill-value\s*\{/.test(SHOWCASE_CSS),
        '應有 .filter-pill-group button.filter-pill-value { ... }',
    );
});

// ===== i18n：5 個新 key =====

const EXPECTED_KEYS = {
    'showcase.pill.dim_label.release': '發售日',
    'showcase.pill.editor.from_year': '起始年',
    'showcase.pill.editor.from_month': '起始月',
    'showcase.pill.editor.to_year': '結束年',
    'showcase.pill.editor.to_month': '結束月',
};

test('zh_TW.json 含 5 個新 key，值與契約一致', () => {
    for (const [key, expected] of Object.entries(EXPECTED_KEYS)) {
        const actual = lookupNested(ZH_TW, key);
        assert.equal(
            actual,
            expected,
            `zh_TW 缺/錯 key ${key}：期望 ${JSON.stringify(expected)}，實際 ${JSON.stringify(actual)}`,
        );
    }
});

test('markup 確有引用全部 5 個新 key（浮層標題 1 次 + 四格 aria-label 各 1 次）', () => {
    assert.ok(
        SHOWCASE_HTML.includes("t('showcase.pill.dim_label.release')"),
        '浮層標題應引用 t(\'showcase.pill.dim_label.release\')',
    );
    for (const key of ['showcase.pill.editor.from_year', 'showcase.pill.editor.from_month', 'showcase.pill.editor.to_year', 'showcase.pill.editor.to_month']) {
        assert.ok(
            SHOWCASE_HTML.includes(`t('${key}')`),
            `markup 應引用 t('${key}')`,
        );
    }
});
