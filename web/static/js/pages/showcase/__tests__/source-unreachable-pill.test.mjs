// TASK-142-T4: unreachableSources state ＋ footer pill ＋ i18n（DoD 1、2、4、9；DoD 3 已刪）
//
// 技術比照 pill-status.test.mjs（HTML／i18n 文字契約）與 card-shape-persist.test.mjs
// （importmap resolve hook ＋ stateBase factory）。不跑 CDP、不動 Alpine runtime。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.window.t = (key, params) => {
    params = params || {};
    const keys = key.split('.');
    let val = globalThis.window.__i18n;
    for (const k of keys) {
        if (val == null) break;
        val = val[k];
    }
    if (typeof val !== 'string') return '[' + key + ']';
    return val.replace(/\{(\w+)\}/g, (_, k) => (
        Object.prototype.hasOwnProperty.call(params, k) ? params[k] : '{' + k + '}'
    ));
};

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
const STATIC_JS_ROOT = pathToFileURL(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../') + '/',
).href;

const loaderCode = `
const IMPORTMAP = ${JSON.stringify(IMPORTMAP)};
const STATIC_JS_ROOT = ${JSON.stringify(STATIC_JS_ROOT)};
export async function resolve(specifier, context, nextResolve) {
    for (const [prefix, rel] of Object.entries(IMPORTMAP)) {
        if (specifier.startsWith(prefix)) {
            return nextResolve(STATIC_JS_ROOT + rel + specifier.slice(prefix.length), context);
        }
    }
    if (specifier.startsWith('@/')) {
        return nextResolve(STATIC_JS_ROOT + specifier.slice(2), context);
    }
    return nextResolve(specifier, context);
}
`;
register(`data:text/javascript,${encodeURIComponent(loaderCode)}`, import.meta.url);

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '../../../../../..');
const SHOWCASE_HTML = readFileSync(
    path.join(REPO_ROOT, 'web/templates/showcase.html'),
    'utf8',
);
const ZH_TW = JSON.parse(
    readFileSync(path.join(REPO_ROOT, 'locales/zh_TW.json'), 'utf8'),
);
globalThis.window.__i18n = ZH_TW;

const { stateBase } = await import('../state-base.js');

function makeComponent(overrides) {
    const c = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    return Object.assign(c, overrides);
}

/** 抽出包住 footer-count--unreachable 的外層 <template x-if="..."> 條件。 */
function extractUnreachablePillXIf(html) {
    const re = /<template\s+x-if="([^"]+)">\s*<span\b[^>]*\bfooter-count--unreachable\b/;
    const m = re.exec(html);
    assert.ok(m, 'showcase.html 應有 <template x-if="..."> 包住 .footer-count--unreachable');
    return m[1];
}

/** 抽出 unreachable pill 整段 markup（外層 template 起至對應 </template>）。 */
function extractUnreachablePillBlock(html) {
    const openRe = /<template\s+x-if="[^"]+">\s*<span\b[^>]*\bfooter-count--unreachable\b/;
    const m = openRe.exec(html);
    assert.ok(m, 'showcase.html 應含 footer-count--unreachable pill');
    const start = m.index;
    // 從外層 <template 起算，depth-aware 配對到對應 </template>
    let i = start + '<template'.length;
    let depth = 1;
    while (i < html.length && depth > 0) {
        const nextOpen = html.indexOf('<template', i);
        const nextClose = html.indexOf('</template>', i);
        if (nextClose === -1) break;
        if (nextOpen !== -1 && nextOpen < nextClose) {
            depth++;
            i = nextOpen + '<template'.length;
        } else {
            depth--;
            i = nextClose + '</template>'.length;
            if (depth === 0) {
                return html.slice(start, i);
            }
        }
    }
    throw new Error('unreachable pill 未找到匹配的 </template>');
}

function tKey(key, params) {
    return globalThis.window.t(key, params);
}

function composePillText(sources) {
    const list = sources.map((s) => s.display).join('、');
    if (sources.length <= 2) {
        return {
            key: 'showcase.status.source_unreachable_list',
            text: tKey('showcase.status.source_unreachable_list', { list }),
            title: null,
        };
    }
    return {
        key: 'showcase.status.source_unreachable_count',
        text: tKey('showcase.status.source_unreachable_count', { n: sources.length }),
        title: list,
    };
}

// ===== DoD 1：空陣列 → pill 綁定條件為 false =====

// [lint-guard: node-justified] 162e 暫留：求值型行為測試（lint 無 JS 求值能力）；R1：所有來源連得上時頁尾不得憑空顯示「無法存取」警告

// ===== DoD 2：1／2／3 筆文案組出 =====

// [lint-guard: node-justified] 162e 暫留：求值型行為測試（lint 無 JS 求值能力）；R1：1／2／3 個來源連不到時頁尾要顯示對的文案與完整清單 title

// [lint-guard: node-justified] 162e 暫留：求值型行為測試（lint 無 JS 求值能力）；R1：來源被拒絕讀取或連不到時頁尾文案與 DSM 授權指引不得算錯
test('permission footer renders new text only when every source lacks permission', () => {
    const block = extractUnreachablePillBlock(SHOWCASE_HTML);
    const small = block.match(/<template\s+x-if="unreachableSources\.length\s*<=\s*2">([\s\S]*?)<\/template>/);
    const large = block.match(/<template\s+x-if="unreachableSources\.length\s*>\s*2">([\s\S]*?)<\/template>/);
    assert.ok(small && large);
    const render = (branch, sources) => {
        const expression = branch.match(/x-text="([^"]+)"/)?.[1];
        assert.ok(expression, 'footer branch should contain x-text');
        return new Function('unreachableSources', 't', `return ${expression};`)(sources, tKey);
    };
    const denied = (display, dsm_hint = null) => ({ display, reason: 'no_permission', dsm_hint });
    const gone = (display) => ({ display, reason: 'unreachable', dsm_hint: null });
    assert.equal(render(small[1], [denied('/a')]), '沒有權限讀取：/a');
    assert.equal(render(small[1], [denied('/a', 'DSM 指引')]), '沒有權限讀取：/a DSM 指引');
    assert.equal(render(small[1], [denied('/a'), denied('/b')]), '沒有權限讀取：/a、/b');
    assert.equal(render(small[1], [denied('/a'), gone('/b')]), '無法存取：/a、/b');
    assert.equal(render(large[1], [denied('/a'), denied('/b'), denied('/c')]), '3 個位置沒有權限讀取');
    assert.equal(render(large[1], [denied('/a', 'DSM 指引'), denied('/b'), denied('/c')]), '3 個位置沒有權限讀取 DSM 指引');
    assert.equal(render(large[1], [denied('/a'), gone('/b'), denied('/c')]), '3 個位置無法存取');
    assert.equal(render(large[1], [gone('/a'), gone('/b'), gone('/c')]), '3 個位置無法存取');
});

// ===== DoD 4：🔴 不變式 — videoCount 不受 unreachableSources 影響 =====

// [lint-guard: node-justified] 162e 暫留：求值型行為測試（lint 無 JS 求值能力）；R1：所有來源連不到時瀏覽頁主內容仍要顯示本機已入庫影片

// ===== DoD 9：模式無關 — 女優牆也要看得到那句話 =====

/** 取 .footer-left 的內容（到對應 </div>），用 depth-aware 配對。 */
function extractFooterLeftInner(html) {
    const m = /<div class="footer-left">/.exec(html);
    assert.ok(m, 'showcase.html 應有 .footer-left');
    const start = m.index + m[0].length;
    let i = start;
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
            if (depth === 0) return html.slice(start, nextClose);
            i = nextClose + 6;
        }
    }
    throw new Error('.footer-left 未找到匹配的 </div>');
}

// [lint-guard: node-justified] 162e 暫留：求值型行為測試（lint 無 JS 求值能力）；R1：女優牆模式下來源連不到的警告仍要看得到
