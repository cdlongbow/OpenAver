// TASK-115-T6: pill 視覺契約（靜態文字掃描）。
// 技術比照 pill-shell.test.mjs：讀 showcase.css / ui-conventions.md 文字解析。
// 誠實邊界：可證明 resting ✕ 規則沒有 opacity:0 等隱藏宣告，
// 不能證明渲染後命中區真的 ≥24×24（那是 CDP batch）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// 本檔：web/static/js/pages/showcase/__tests__/ → 上五層 = repo root
const REPO_ROOT = path.resolve(__dirname, '../../../../../..');
const SHOWCASE_CSS = readFileSync(
    path.join(REPO_ROOT, 'web/static/css/pages/showcase.css'),
    'utf8',
);
const UI_CONVENTIONS = readFileSync(
    path.join(REPO_ROOT, 'feature/AI_COLLABORATION/ui-conventions.md'),
    'utf8',
);

/**
 * Extract a CSS rule body for an exact selector (first match).
 * Strips block comments first so comment text cannot pollute assertions.
 */
function extractRuleBody(css, selector) {
    const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
    // Escape selector for regex, then match `selector { ... }`
    const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(`${esc}\\s*\\{([^}]*)\\}`);
    const m = stripped.match(re);
    return m ? m[1] : null;
}

/**
 * Slice the contiguous `.filter-pill*` authoring block from showcase.css
 * (T5/T6 section through the next major section comment).
 */
function extractFilterPillBlock(css) {
    const startMarkers = [
        '/* ==================== Filter pills',
        '/* ==================== Filter pills shell',
    ];
    let start = -1;
    for (const marker of startMarkers) {
        start = css.indexOf(marker);
        if (start !== -1) break;
    }
    assert.ok(start !== -1, 'showcase.css 應含 Filter pills 區塊註解');
    // Next top-level section comment after start
    const after = css.slice(start + 10);
    const nextSection = after.search(/\n\/\* ={5,}/);
    const end = nextSection === -1 ? css.length : start + 10 + nextSection;
    return css.slice(start, end);
}

const PILL_BLOCK = extractFilterPillBlock(SHOWCASE_CSS);
const REMOVE_BODY = extractRuleBody(SHOWCASE_CSS, '.filter-pill-remove');
const PILL_BODY = extractRuleBody(SHOWCASE_CSS, '.filter-pill');
const LB_TAG_BODY = extractRuleBody(SHOWCASE_CSS, '.lb-user-tag');

// ===== ✕ always visible (no hover-reveal) =====

test('resting .filter-pill-remove 規則存在且不含隱藏宣告', () => {
    assert.ok(REMOVE_BODY !== null, '應有 .filter-pill-remove { ... } 規則');
    const body = REMOVE_BODY;
    // Forbidden hiding patterns on the resting (non-hover) rule
    assert.ok(
        !/(?:^|[;\s{])width\s*:\s*0(?:px|rem|em)?\s*[;}]/.test(`{${body}}`)
            && !/(?:^|[;\s{])width\s*:\s*0\s*[;}]/.test(body),
        'resting .filter-pill-remove 不得 width: 0',
    );
    // Explicit checks for the four forbidden hide techniques
    for (const decl of [
        /opacity\s*:\s*0\s*[;}]/,
        /display\s*:\s*none\s*[;}]/,
        /visibility\s*:\s*hidden\s*[;}]/,
        /width\s*:\s*0(?:px)?\s*[;}]/,
    ]) {
        assert.ok(
            !decl.test(body),
            `resting .filter-pill-remove 不得含 ${decl}：${body.trim()}`,
        );
    }
});

test('無 :hover 門控展開 .filter-pill-remove 的可見性/尺寸', () => {
    const stripped = SHOWCASE_CSS.replace(/\/\*[\s\S]*?\*\//g, '');
    // Any selector that couples :hover with .filter-pill-remove
    const hoverRe =
        /\.filter-pill[^{\n]*:hover[^{\n]*\.filter-pill-remove[^{\n]*\{([^}]*)\}|\.filter-pill-remove:hover\s*\{([^}]*)\}/g;
    let m;
    while ((m = hoverRe.exec(stripped)) !== null) {
        const body = m[1] || m[2] || '';
        // Hover may change color/background; must NOT be a hide→show expand
        const isReveal =
            /opacity\s*:\s*1/.test(body)
            || /width\s*:\s*(?!0)\d/.test(body)
            || /display\s*:\s*(?!none)/.test(body) && /display\s*:/.test(body)
            || /visibility\s*:\s*visible/.test(body);
        // Only fail if the hover rule is the *reveal* half of a hide/show pair:
        // i.e. it sets opacity/width/display/visibility in a show direction
        // AND the resting rule also doesn't already have them permanently shown.
        // Practical oracle: hover rule must not set width or opacity at all
        // (color/background transitions are fine).
        assert.ok(
            !/\b(width|opacity|display|visibility)\s*:/.test(body),
            `.filter-pill-remove:hover 不得以 width/opacity/display/visibility 做展開：${body.trim()}`,
        );
        // silence unused
        void isReveal;
    }
});

test('resting .filter-pill-remove 宣告 min-width 與 min-height ≥24px 意圖', () => {
    assert.ok(REMOVE_BODY !== null, '應有 .filter-pill-remove 規則');
    assert.ok(
        /min-width\s*:\s*24px/.test(REMOVE_BODY),
        '應有 min-width: 24px（命中區意圖；渲染實測屬 CDP）',
    );
    assert.ok(
        /min-height\s*:\s*24px/.test(REMOVE_BODY),
        '應有 min-height: 24px（命中區意圖；渲染實測屬 CDP）',
    );
});

// ===== No accent / accent-pink on .filter-pill =====

test('.filter-pill 不使用 var(--accent) 或 var(--accent-pink)', () => {
    assert.ok(PILL_BODY !== null, '應有 .filter-pill { ... } 規則');
    assert.ok(
        !/var\(\s*--accent\s*\)/.test(PILL_BODY),
        '.filter-pill 不得使用 var(--accent)（那是 .lb-user-tag 的實心填色）',
    );
    assert.ok(
        !/var\(\s*--accent-pink\s*\)/.test(PILL_BODY),
        '.filter-pill 不得使用 var(--accent-pink)（女優模式情感色）',
    );
    // Whole pill block (including remove) also must not paint accent fill on the chip
    const pillOnlyRules = PILL_BLOCK.match(/\.filter-pill\s*\{[^}]*\}/g) || [];
    for (const rule of pillOnlyRules) {
        assert.ok(
            !/var\(\s*--accent(?:-pink)?\s*\)/.test(rule),
            `.filter-pill 規則不得含 accent：${rule}`,
        );
    }
});

// ===== Distinguishable from .lb-user-tag =====

test('.filter-pill 與 .lb-user-tag 在 fill/border 宣告上可區分', () => {
    assert.ok(PILL_BODY !== null, '應有 .filter-pill 規則');
    assert.ok(LB_TAG_BODY !== null, '應有 .lb-user-tag 規則（對照組）');

    // .lb-user-tag: solid accent fill, no border
    assert.ok(
        /background\s*:\s*var\(\s*--accent\s*\)/.test(LB_TAG_BODY),
        '.lb-user-tag 應對照為 background: var(--accent)',
    );
    assert.ok(
        !/\bborder\s*:/.test(LB_TAG_BODY),
        '.lb-user-tag 對照組不應有 border 宣告',
    );

    // .filter-pill: must NOT solid-fill accent; must have a border
    assert.ok(
        !/background\s*:\s*var\(\s*--accent\s*\)/.test(PILL_BODY),
        '.filter-pill 不得 background: var(--accent)',
    );
    assert.ok(
        /\bborder\s*:\s*1px\s+solid\s+var\(\s*--stroke-default\s*\)/.test(PILL_BODY)
            || /\bborder\s*:\s*1px\s+solid\s+var\(\s*--stroke-subtle\s*\)/.test(PILL_BODY),
        '.filter-pill 應有 1px solid stroke 邊框（與 .lb-user-tag 無邊框對照）',
    );
    // Background must be a neutral tint, not solid accent
    assert.ok(
        /background\s*:\s*color-mix\(/.test(PILL_BODY)
            || /background\s*:\s*var\(\s*--surface-[12]\s*\)/.test(PILL_BODY),
        '.filter-pill 背景應為 color-mix tint 或 --surface-1/--surface-2',
    );
});

// ===== No hardcoded colour literals in the new block =====

test('.filter-pill* 區塊無硬編碼 hex/rgb 色值', () => {
    // Strip comments so hex in comments (e.g. historical notes) does not trip us
    const code = PILL_BLOCK.replace(/\/\*[\s\S]*?\*\//g, '');
    assert.ok(
        !/#[0-9a-fA-F]{3,8}\b/.test(code),
        '.filter-pill* 區塊不得含 hex 色值',
    );
    assert.ok(
        !/\brgba?\(\s*\d/.test(code),
        '.filter-pill* 區塊不得含 rgb()/rgba() 數字色值',
    );
});

// ===== Component registration =====

test('ui-conventions.md §1 pill 白名單含 .filter-pill 列', () => {
    // Locate §1 pill table (between "### Pill 999px 白名單" and next ## heading)
    const sectionStart = UI_CONVENTIONS.indexOf('### Pill 999px 白名單');
    assert.ok(sectionStart !== -1, '應有 ### Pill 999px 白名單 小節');
    const after = UI_CONVENTIONS.slice(sectionStart);
    const nextH2 = after.search(/\n## /);
    const section = nextH2 === -1 ? after : after.slice(0, nextH2);
    assert.ok(
        /\|[^|\n]*\.filter-pill[^|\n]*\|/.test(section)
            || /`\.filter-pill`/.test(section),
        '§1 pill 白名單表應含 .filter-pill 列',
    );
    // Class number 8 row present
    assert.ok(
        /\|\s*8\s*\|/.test(section),
        '§1 pill 白名單應有類 8 列',
    );
});
