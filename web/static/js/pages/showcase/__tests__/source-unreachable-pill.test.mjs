// TASK-142-T4: unreachableSources state ＋ footer pill ＋ i18n（DoD 1–4）
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
const STATE_BASE_SRC = readFileSync(
    path.join(REPO_ROOT, 'web/static/js/pages/showcase/state-base.js'),
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

/**
 * 抽出 state-base.js 內 source-status 的 fire-and-forget fetch 鏈（含 .catch）。
 * 以括號深度掃描，避免寫死 catch 形狀——M1 改 catch 內容時仍能抽出並執行。
 */
function extractSourceStatusFetchChain(src) {
    const marker = "fetch('/api/showcase/source-status')";
    const start = src.indexOf(marker);
    assert.ok(start !== -1, "state-base.js 應含 fetch('/api/showcase/source-status')");
    let i = start + 'fetch'.length;
    assert.equal(src[i], '(', 'fetch 後應接 (');
    let depth = 0;
    // 吃掉 fetch(...) 本身
    for (; i < src.length; i++) {
        const ch = src[i];
        if (ch === '(') depth++;
        else if (ch === ')') {
            depth--;
            if (depth === 0) {
                i++;
                break;
            }
        }
    }
    // 繼續吃 .then(...) / .catch(...) 鏈
    while (true) {
        while (i < src.length && /\s/.test(src[i])) i++;
        if (src[i] !== '.') break;
        const idStart = i + 1;
        let idEnd = idStart;
        while (idEnd < src.length && /\w/.test(src[idEnd])) idEnd++;
        const id = src.slice(idStart, idEnd);
        assert.ok(id === 'then' || id === 'catch', `fetch 鏈只允許 .then/.catch，實際 .${id}`);
        i = idEnd;
        while (i < src.length && /\s/.test(src[i])) i++;
        assert.equal(src[i], '(', `.${id} 後應接 (`);
        depth = 0;
        for (; i < src.length; i++) {
            const ch = src[i];
            if (ch === '(') depth++;
            else if (ch === ')') {
                depth--;
                if (depth === 0) {
                    i++;
                    break;
                }
            } else if (ch === "'" || ch === '"' || ch === '`') {
                // 跳過字串（避免字串內括號干擾）
                const quote = ch;
                i++;
                while (i < src.length && src[i] !== quote) {
                    if (src[i] === '\\') i++;
                    i++;
                }
            }
        }
    }
    while (i < src.length && /\s/.test(src[i])) i++;
    assert.equal(src[i], ';', 'fetch 鏈應以 ; 結束');
    return src.slice(start, i + 1);
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

test('DoD1: unreachableSources=[] → footer pill x-if 條件為 false', () => {
    const cond = extractUnreachablePillXIf(SHOWCASE_HTML);
    const result = new Function('unreachableSources', `return Boolean(${cond});`)([]);
    assert.equal(result, false, `x-if="${cond}" 在 unreachableSources=[] 時應為 falsy`);
});

// ===== DoD 2：1／2／3 筆文案組出 =====

test('DoD2: 1／2／3 個來源 → 對應 i18n key、插值與 title', () => {
    assert.equal(
        ZH_TW.showcase?.status?.source_unreachable_list,
        '無法存取：{list}',
        'zh_TW 應有 source_unreachable_list',
    );
    assert.equal(
        ZH_TW.showcase?.status?.source_unreachable_count,
        '{n} 個位置無法存取',
        'zh_TW 應有 source_unreachable_count',
    );

    const block = extractUnreachablePillBlock(SHOWCASE_HTML);
    assert.ok(
        /x-if="unreachableSources\.length\s*<=\s*2"/.test(block),
        '≤2 分支應存在',
    );
    assert.ok(
        /x-if="unreachableSources\.length\s*>\s*2"/.test(block),
        '>2 分支應存在',
    );

    // ≤2 用 list key；>2 用 count key（M3 會把 count 改成 list → 本斷言轉紅）
    const le2 = block.match(
        /<template\s+x-if="unreachableSources\.length\s*<=\s*2">([\s\S]*?)<\/template>/,
    );
    assert.ok(le2, '應能抽出 ≤2 分支');
    assert.ok(
        le2[1].includes("t('showcase.status.source_unreachable_list'"),
        '≤2 應呼叫 source_unreachable_list',
    );
    assert.ok(
        !le2[1].includes("t('showcase.status.source_unreachable_count'"),
        '≤2 不得呼叫 source_unreachable_count',
    );

    const gt2 = block.match(
        /<template\s+x-if="unreachableSources\.length\s*>\s*2">([\s\S]*?)<\/template>/,
    );
    assert.ok(gt2, '應能抽出 >2 分支');
    assert.ok(
        gt2[1].includes("t('showcase.status.source_unreachable_count'"),
        '>2 應呼叫 source_unreachable_count',
    );
    assert.ok(
        !gt2[1].includes("t('showcase.status.source_unreachable_list'"),
        '>2 不得呼叫 source_unreachable_list',
    );
    assert.ok(
        /:title="unreachableSources\.map\(s\s*=>\s*s\.display\)\.join\('、'\)"/.test(gt2[1]),
        '>2 應把完整清單放 title',
    );

    const one = [{ path: 'a', display: '\\\\host-a', status: 'unreachable' }];
    const two = [
        { path: 'a', display: '\\\\host-a', status: 'unreachable' },
        { path: 'b', display: 'D:\\Videos', status: 'unreachable' },
    ];
    const three = [
        ...two,
        { path: 'c', display: '/mnt/nas', status: 'unreachable' },
    ];

    const c1 = composePillText(one);
    assert.equal(c1.key, 'showcase.status.source_unreachable_list');
    assert.equal(c1.text, '無法存取：\\\\host-a');
    assert.equal(c1.title, null);

    const c2 = composePillText(two);
    assert.equal(c2.key, 'showcase.status.source_unreachable_list');
    assert.equal(c2.text, '無法存取：\\\\host-a、D:\\Videos');
    assert.equal(c2.title, null);

    const c3 = composePillText(three);
    assert.equal(c3.key, 'showcase.status.source_unreachable_count');
    assert.equal(c3.text, '3 個位置無法存取');
    assert.equal(c3.title, '\\\\host-a、D:\\Videos、/mnt/nas');
});

// ===== DoD 3：fetch reject → 維持 []、不拋未捕捉例外 =====

test('DoD3: fetch reject → unreachableSources 維持 [] 且不拋未捕捉例外', async () => {
    const chain = extractSourceStatusFetchChain(STATE_BASE_SRC);
    // 必須是靜默空 catch；M1 移除整段或改成 throw e 都會讓本斷言轉紅。
    assert.ok(
        /\.catch\(\s*\(\s*\)\s*=>\s*\{\s*\}\s*\)/.test(chain),
        'source-status fetch 鏈必須 .catch(() => {}) 靜默；M1 破壞後本斷言轉紅',
    );

    const c = { unreachableSources: ['sentinel-should-be-cleared-only-on-success'] };
    // 初始值模擬 factory 的 []；若 then 誤跑會被覆蓋，reject 時應維持我們設的 []
    c.unreachableSources = [];

    const prevFetch = globalThis.fetch;
    globalThis.fetch = () => Promise.reject(new Error('network down'));

    const unhandled = [];
    const onUnhandled = (reason) => { unhandled.push(reason); };
    process.on('unhandledRejection', onUnhandled);

    try {
        const runner = new Function(`return (function () { ${chain} });`);
        runner.call(c);
        // 等 microtask + 一小段 macrotask，讓 reject／catch 落地
        await Promise.resolve();
        await Promise.resolve();
        await new Promise((r) => setImmediate(r));
        await new Promise((r) => setTimeout(r, 20));

        assert.deepEqual(c.unreachableSources, []);
        assert.equal(
            unhandled.length,
            0,
            `不得有未捕捉例外，實際：${unhandled.map(String).join('; ')}`,
        );
    } finally {
        process.off('unhandledRejection', onUnhandled);
        globalThis.fetch = prevFetch;
    }
});

// ===== DoD 4：🔴 不變式 — videoCount 不受 unreachableSources 影響 =====

test('DoD4: unreachableSources 非空時 videoCount 與主內容 x-show 仍為真', () => {
    const c = makeComponent();
    assert.ok(
        Object.prototype.hasOwnProperty.call(c, 'unreachableSources'),
        'state-base 頂層應宣告 unreachableSources',
    );
    assert.deepEqual(c.unreachableSources, []);

    c.videoCount = 42;
    c.error = '';
    c.showFavoriteActresses = false;
    c.unreachableSources = [
        { path: 'file:///x', display: '\\\\dead', status: 'unreachable' },
        { path: 'file:///y', display: 'E:\\Gone', status: 'unreachable' },
    ];

    assert.equal(c.videoCount, 42, '設 unreachableSources 不得改動 videoCount');

    const gateM = SHOWCASE_HTML.match(
        /x-show="(!error && \(videoCount > 0 \|\| showFavoriteActresses\))"/,
    );
    assert.ok(gateM, 'showcase.html 應保留主內容 x-show 閘門');
    const gate = new Function(
        'error',
        'videoCount',
        'showFavoriteActresses',
        `return (${gateM[1]});`,
    )(c.error, c.videoCount, c.showFavoriteActresses);
    assert.equal(gate, true, '全部來源斷線時主內容閘門仍應為真（不得退化成空狀態）');
});

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

test('DoD9: pill 掛在 .footer-left 直屬層，不在任一模式 template 內（女優牆也看得到）', () => {
    const inner = extractFooterLeftInner(SHOWCASE_HTML);
    const pillIdx = inner.search(/<template\s+x-if="[^"]+">\s*<span\b[^>]*\bfooter-count--unreachable\b/);
    assert.ok(pillIdx !== -1, '.footer-left 內應有 unreachable pill');

    // 走訪 pill 之前的所有 <template>／</template>，深度必須歸零 ——
    // 不歸零就代表 pill 被包在影片模式或女優模式的 template 裡面。
    const before = inner.slice(0, pillIdx);
    const opens = (before.match(/<template\b/g) || []).length;
    const closes = (before.match(/<\/template>/g) || []).length;
    assert.equal(
        opens - closes,
        0,
        `pill 前的 template 深度應為 0（實際 ${opens - closes}）——` +
        '它必須是 .footer-left 的直屬 sibling，不能包在 x-if="!showFavoriteActresses" 或女優模式那個 template 裡',
    );

    // 綁定條件本身不得摻入模式旗標：女優牆（showFavoriteActresses=true）也要為真。
    const cond = extractUnreachablePillXIf(SHOWCASE_HTML);
    const sources = [{ path: 'file:///x', display: '\\\\dead', status: 'unreachable' }];
    const inActressMode = new Function(
        'unreachableSources',
        'showFavoriteActresses',
        `return Boolean(${cond});`,
    )(sources, true);
    assert.equal(inActressMode, true, '女優牆模式下 pill 仍應顯示——位置連不到跟你在看哪一面牆無關');
});
