// TASK-138-T5: confirmMask 成功後 by-name 回寫 _matchedActress（CD-E3／CD-E6）。
// 接線（applyCellFocal）由 [lint-guard 138-T5] 守；本檔只守脫鉤回寫行為。
//
// FE-GUARD-11：import 頁面 state 模組之前必須先 stub window。
// FE-GUARD-13：fetch stub／物件狀態每支 test 自備，避免 module 單例跨測污染。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;
globalThis.window.innerWidth = 1200;
globalThis.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
globalThis.window.addEventListener = () => {};
globalThis.window.removeEventListener = () => {};
globalThis.document = globalThis.document || {
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return null; },
    body: { classList: { add() {}, remove() {}, contains() { return false; } } },
};
globalThis.localStorage = globalThis.localStorage || {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
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

const { stateLightbox } = await import('../state-lightbox.js');

const SAVED_FOCAL = '0.2500,0.5000';

function okFocalResponse() {
    return {
        ok: true,
        status: 200,
        json: async () => ({ success: true, auto_focal: SAVED_FOCAL }),
    };
}

/**
 * 組一顆可直接呼叫 confirmMask() 的 actress 分支元件。
 * 預設模擬 _fetchLiveAliases 的 Object.assign 脫鉤：
 * currentLightboxActress 與 _matchedActress 是兩顆不同物件、同名。
 */
function makeActressConfirmComponent(overrides = {}) {
    const wallActress = {
        name: '宇野みれい',
        auto_focal: '',
        crop_mode: 'auto',
        is_favorite: true,
        photo_url: '/photo.jpg',
    };
    const matched = Object.assign({}, wallActress);
    const lightboxActress = Object.assign({}, matched, { aliases: ['みれい'] });

    const c = Object.assign({}, stateLightbox(), {
        _maskFocalX: 0.25,
        _maskKind: 'actress',
        _maskSession: 1,
        _maskVisible: true,
        _maskExpectedCoverPath: null,
        _maskResizeHandler: null,
        _maskDragMoveHandler: null,
        _maskDragUpHandler: null,
        _maskWaitTl: null,
        _maskSettleTl: null,
        currentLightboxActress: lightboxActress,
        _matchedActress: matched,
        paginatedActresses: [wallActress],
        showToast() {},
        $refs: {},
    }, overrides);
    return c;
}

async function withFetch(fetchImpl, fn) {
    const prev = globalThis.fetch;
    globalThis.fetch = fetchImpl;
    try {
        return await fn();
    } finally {
        globalThis.fetch = prev;
    }
}

// ── 138-T5-02 靶：脫鉤後仍 by-name 回寫 _matchedActress ──────────────────

test('138-T5-02：confirmMask 存檔成功後即使 currentLightboxActress 已 Object.assign 脫鉤，仍 by-name 回寫 _matchedActress 的 auto_focal／crop_mode', async () => {
    await withFetch(async () => okFocalResponse(), async () => {
        const c = makeActressConfirmComponent();
        assert.notEqual(c.currentLightboxActress, c._matchedActress, '前置：兩顆必須是不同物件（模擬脫鉤）');
        assert.equal(c._matchedActress.auto_focal, '');
        assert.equal(c._matchedActress.crop_mode, 'auto');

        await c.confirmMask();

        assert.equal(c._matchedActress.auto_focal, SAVED_FOCAL,
            '脫鉤後 _matchedActress 必須被 by-name 回寫 auto_focal');
        assert.equal(c._matchedActress.crop_mode, 'manual',
            '脫鉤後 _matchedActress 必須被 by-name 回寫 crop_mode');
        // 脫鉤副本本身也應被 targetObj 寫入（既有行為）
        assert.equal(c.currentLightboxActress.auto_focal, SAVED_FOCAL);
        assert.equal(c.currentLightboxActress.crop_mode, 'manual');
    });
});

// ── 名字不相符時不得誤寫 ────────────────────────────────────────────────

test('confirmMask 存檔成功但 _matchedActress.name 與存檔目標不同 → _matchedActress 一個欄位都不能被改', async () => {
    await withFetch(async () => okFocalResponse(), async () => {
        const c = makeActressConfirmComponent({
            _matchedActress: {
                name: '別人',
                auto_focal: '0.1111,0.5000',
                crop_mode: 'manual',
                is_favorite: true,
            },
        });
        const before = {
            auto_focal: c._matchedActress.auto_focal,
            crop_mode: c._matchedActress.crop_mode,
            name: c._matchedActress.name,
        };

        await c.confirmMask();

        assert.equal(c._matchedActress.auto_focal, before.auto_focal);
        assert.equal(c._matchedActress.crop_mode, before.crop_mode);
        assert.equal(c._matchedActress.name, before.name);
    });
});

// ── _matchedActress 為 null 時不得丟錯 ──────────────────────────────────

test('confirmMask 存檔成功且 _matchedActress 為 null → 不丟錯', async () => {
    await withFetch(async () => okFocalResponse(), async () => {
        const c = makeActressConfirmComponent({ _matchedActress: null });
        await assert.doesNotReject(() => c.confirmMask());
        assert.equal(c._matchedActress, null);
    });
});

// ── 存檔失敗不得寫入 ────────────────────────────────────────────────────

test('confirmMask 存檔失敗（非 2xx）時不得寫入 _matchedActress', async () => {
    await withFetch(async () => ({
        ok: false,
        status: 500,
        json: async () => ({ success: false, error: 'boom' }),
    }), async () => {
        const c = makeActressConfirmComponent();
        await c.confirmMask();
        assert.equal(c._matchedActress.auto_focal, '');
        assert.equal(c._matchedActress.crop_mode, 'auto');
    });
});

test('confirmMask fetch reject 時不得寫入 _matchedActress', async () => {
    await withFetch(async () => { throw new Error('network down'); }, async () => {
        const c = makeActressConfirmComponent();
        await c.confirmMask();
        assert.equal(c._matchedActress.auto_focal, '');
        assert.equal(c._matchedActress.crop_mode, 'auto');
    });
});

// ── 遷移等價：既有 paginatedActresses 同步仍生效 ────────────────────────

test('confirmMask 存檔成功後既有 _syncActressesArray（paginatedActresses）同步仍然照舊生效', async () => {
    await withFetch(async () => okFocalResponse(), async () => {
        const c = makeActressConfirmComponent();
        const wall = c.paginatedActresses[0];
        assert.equal(wall.auto_focal, '');
        assert.equal(wall.crop_mode, 'auto');

        await c.confirmMask();

        assert.equal(wall.auto_focal, SAVED_FOCAL);
        assert.equal(wall.crop_mode, 'manual');
    });
});
