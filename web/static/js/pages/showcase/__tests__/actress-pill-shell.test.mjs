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


// ===== role="list" 落點（只包 pill，不包 input）=====


// ===== x-for + 單一 :key（CD-116a-4：只用 pill.dim，非複合鍵）=====


// ===== placeholder 收合（有 pill 時收起提示字，不補靜態 fallback）=====


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
