// TASK-172-T5：燈箱翻譯鈕的時序／失敗／復原／跳過／6 秒 oracle（CD-172-8 oracle 1、2、2b、3、4、5）。
// 組合 component 用 mergeState（保留 getter descriptor），不用 Object.assign（會把 getter 求值凍結）。
// _filteredVideos 是 state-base 的 module singleton，每支測試 try/finally 清乾淨（FE-GUARD-13）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
globalThis.Alpine = globalThis.Alpine || {
    store: () => ({ toolbarOpen: false, showcaseHasSearch: false }),
};
globalThis.document = globalThis.document || {
    querySelector() { return null; },
    body: { classList: { add() {}, remove() {}, contains() { return false; } } },
};

register(new URL('../../search/__tests__/alias-loader.mjs', import.meta.url), import.meta.url);

const { stateLightbox } = await import('../state-lightbox.js');
const { stateLightboxPicker } = await import('../state-lightbox-picker.js');
const { stateLightboxMask } = await import('../state-lightbox-mask.js');
const { stateLightboxTranslate } = await import('../state-lightbox-translate.js');
const { mergeState } = await import('@/shared/merge-state.js');
const { _setFilteredVideos } = await import('../state-base.js');

function makeVideos() {
    return [
        { path: 'file:///C:/a.mp4', number: 'AAA-001', title: 'あいう', original_title: '', actresses: 'X, Y', needs_translate: true },
        { path: 'file:///C:/b.mp4', number: 'BBB-002', title: 'えおか', original_title: '', actresses: '', needs_translate: true },
    ];
}

function makeComponent(toasts) {
    return mergeState(stateLightbox(), stateLightboxPicker(), stateLightboxMask(), stateLightboxTranslate(), {
        lightboxOpen: true,
        showFavoriteActresses: false,
        currentLightboxActress: null,
        lightboxIndex: 0,
        actressLightboxIndex: 0,
        similarModeOpen: false,
        similarModeMobileOpen: false,
        removeActressModalOpen: false,
        _pickerOpen: false,
        rescrapeOpen: false,
        deleteVideoModalOpen: false,
        sampleGalleryOpen: false,
        _pillEditor: null,
        _releaseEditor: null,
        _maskVisible: false,
        $nextTick() {},
        $refs: {},
        _fetchLiveAliases() {},
        showToast(...args) { toasts.push(args); },
    });
}

// 依 URL 分流的假 fetch：每個請求回一個可手動放行的 Promise
function installFetch() {
    const calls = [];
    const pending = { translate: [], title: [] };
    const original = globalThis.fetch;
    globalThis.fetch = (url, opts) => {
        const body = JSON.parse(opts.body);
        const kind = url === '/api/translate' ? 'translate' : 'title';
        calls.push({ url, kind, body });
        return new Promise((resolve) => {
            pending[kind].push((payload, ok = true) => resolve({ ok, status: ok ? 200 : 500, json: async () => payload }));
        });
    };
    return {
        calls,
        pending,
        flush() { for (const k of Object.keys(pending)) for (const r of pending[k]) r({ success: true, skipped: true }); },
        count: (kind) => calls.filter((c) => c.kind === kind).length,
        restore() { globalThis.fetch = original; },
    };
}

const tick = () => new Promise((r) => setImmediate(r));
const WB_OK = (title, original_title) => ({ success: true, title, original_title, needs_translate: false });

async function withEnv(fn) {
    const [A, B] = makeVideos();
    _setFilteredVideos([A, B]);
    const toasts = [];
    const c = makeComponent(toasts);
    c._setLightboxIndex(0);
    const f = installFetch();
    try {
        await fn({ A, B, c, f, toasts });
    } finally {
        f.flush();
        f.restore();
        _setFilteredVideos([]);
    }
}

test('切片後翻譯結果只寫回按下當下那一片', async () => {
    await withEnv(async ({ A, B, c, f }) => {
        const p = c.lbTranslate();
        assert.equal(c.lbTrIsBusy(), true);
        c.nextLightboxVideo();
        assert.equal(c.currentLightboxVideo, B);
        assert.equal(c.lbTrIsBusy(), false, '切到 B：B 不在 in-flight');
        f.pending.translate[0]({ success: true, result: '譯文A' });
        await tick();
        f.pending.title[0](WB_OK('譯文A', 'あいう'));
        await p;
        assert.equal(A.title, '譯文A');
        assert.equal(A.original_title, 'あいう');
        assert.equal(A.needs_translate, false);
        assert.equal(B.title, 'えおか');
        assert.equal(B.original_title, '');
        c._setLightboxIndex(0);
        assert.equal(c.lbTrIsBusy(), false, '放行後鎖已清');
    });
});

test('切片後切回仍是 busy（未放行前）', async () => {
    await withEnv(async ({ A, c, f }) => {
        const p = c.lbTranslate();
        c.nextLightboxVideo();
        c._setLightboxIndex(0);
        assert.equal(c.currentLightboxVideo, A);
        assert.equal(c.lbTrIsBusy(), true);
        f.pending.translate[0]({ success: true, skipped: true, reason: 'no_japanese' });
        await p;
    });
});

test('同一片連按兩次只送出一次翻譯', async () => {
    await withEnv(async ({ c, f }) => {
        const p1 = c.lbTranslate();
        c.lbTranslate();
        await tick();
        assert.equal(f.count('translate'), 1);
        f.pending.translate[0]({ success: true, skipped: true, reason: 'no_japanese' });
        await p1;
    });
});

test('寫回掛起時再按：翻譯與寫回各只送一次、仍 busy、放行後鎖已清（2b）', async () => {
    await withEnv(async ({ c, f }) => {
        const p = c.lbTranslate();
        f.pending.translate[0]({ success: true, result: '譯文' });
        await tick();
        assert.equal(f.count('title'), 1);
        c.lbTranslate();
        await tick();
        assert.equal(f.count('translate'), 1);
        assert.equal(f.count('title'), 1);
        assert.equal(c.lbTrIsBusy(), true);
        f.pending.title[0](WB_OK('譯文', 'あいう'));
        await p;
        assert.equal(c.lbTrIsBusy(), false);
    });
});

test('翻譯失敗後鎖會釋放', async () => {
    await withEnv(async ({ A, c, f }) => {
        const p = c.lbTranslate();
        f.pending.translate[0]({ success: false, reason: 'rate_limited' });
        await p;
        assert.equal(c.lbTrIsBusy(), false);
        assert.equal(A.title, 'あいう');
        c.lbTranslate();
        assert.equal(f.count('translate'), 2, '鎖釋放後可再送');
    });
});

test('失敗三種原因各對應各自的 toast key', async () => {
    const cases = [
        ['blocked', 'search.toast.translate_blocked'],
        ['rate_limited', 'search.toast.translate_rate_limited'],
        ['other', 'search.toast.translate_failed'],
    ];
    for (const [reason, key] of cases) {
        await withEnv(async ({ A, c, f, toasts }) => {
            const p = c.lbTranslate();
            f.pending.translate[0]({ success: false, reason });
            await p;
            assert.deepEqual(toasts.map((t) => [t[0], t[1]]), [[key, 'error']], reason);
            assert.equal(A.title, 'あいう');
            assert.equal(A.original_title, '');
            assert.equal(f.count('title'), 0);
            assert.equal(c.lbTrIsBusy(), false);
        });
    }
});

test('翻譯請求 HTTP 非 ok 或丟例外：通用失敗 toast、鎖已清', async () => {
    await withEnv(async ({ c, f, toasts }) => {
        const p = c.lbTranslate();
        f.pending.translate[0]({}, false);
        await p;
        assert.equal(toasts[0][0], 'search.toast.translate_failed');
        assert.equal(c.lbTrIsBusy(), false);
    });
});

test('跳過時不呼叫寫回端點', async () => {
    await withEnv(async ({ A, c, f, toasts }) => {
        const p = c.lbTranslate();
        f.pending.translate[0]({ success: true, skipped: true, reason: 'no_japanese' });
        await p;
        assert.equal(f.count('title'), 0);
        assert.deepEqual(toasts.map((t) => [t[0], t[1]]), [['showcase.lightbox.translate_skipped', 'info']]);
        assert.equal(A.title, 'あいう');
        assert.equal(c.lbTrIsBusy(), false);
    });
});

test('寫回失敗：no_nfo 與其他錯誤各自 toast，標題不變、鎖已清', async () => {
    const cases = [
        [{ success: false, error: 'no_nfo' }, 'showcase.lightbox.translate_no_nfo'],
        [{ success: false, error: 'write_failed' }, 'showcase.lightbox.translate_write_failed'],
    ];
    for (const [resp, key] of cases) {
        await withEnv(async ({ A, c, f, toasts }) => {
            const p = c.lbTranslate();
            f.pending.translate[0]({ success: true, result: '譯文' });
            await tick();
            f.pending.title[0](resp);
            await p;
            assert.deepEqual(toasts.map((t) => [t[0], t[1]]), [[key, 'error']]);
            assert.equal(A.title, 'あいう');
            assert.equal(c.lbTrIsBusy(), false);
        });
    }
    await withEnv(async ({ c, f, toasts }) => {
        const p = c.lbTranslate();
        f.pending.translate[0]({ success: true, result: '譯文' });
        await tick();
        f.pending.title[0]({}, false);
        await p;
        assert.equal(toasts[0][0], 'showcase.lightbox.translate_write_failed');
        assert.equal(c.lbTrIsBusy(), false);
    });
});

test('成功 toast 帶 6000 毫秒與復原動作', async () => {
    await withEnv(async ({ c, f, toasts }) => {
        const p = c.lbTranslate();
        f.pending.translate[0]({ success: true, result: '譯文' });
        await tick();
        f.pending.title[0](WB_OK('譯文', 'あいう'));
        await p;
        assert.equal(toasts.length, 1);
        const [msg, type, ms, action] = toasts[0];
        assert.equal(msg, 'showcase.lightbox.translate_done');
        assert.equal(type, 'success');
        assert.equal(ms, 6000);
        assert.equal(action.label, 'showcase.lightbox.translate_undo');
        assert.equal(typeof action.onClick, 'function');
    });
});

test('首次與再翻的寫回只送 file_path 與 title', async () => {
    await withEnv(async ({ A, c, f }) => {
        // 首次
        let p = c.lbTranslate();
        assert.equal(f.calls[0].body.text, 'あいう');
        assert.equal(f.calls[0].body.mode, 'translate');
        assert.deepEqual(f.calls[0].body.actors, ['X', 'Y']);
        assert.equal(f.calls[0].body.number, 'AAA-001');
        f.pending.translate[0]({ success: true, result: '譯文1' });
        await tick();
        assert.deepEqual(Object.keys(f.calls[1].body).sort(), ['file_path', 'title']);
        assert.deepEqual(f.calls[1].body, { file_path: A.path, title: '譯文1' });
        f.pending.title[0](WB_OK('譯文1', 'あいう'));
        await p;
        // 再翻：從原文翻
        p = c.lbTranslate();
        assert.equal(f.calls[2].body.text, 'あいう');
        f.pending.translate[1]({ success: true, result: '譯文2' });
        await tick();
        assert.deepEqual(Object.keys(f.calls[3].body).sort(), ['file_path', 'title']);
        f.pending.title[1](WB_OK('譯文2', 'あいう'));
        await p;
        assert.equal(A.title, '譯文2');
    });
});

test('復原用按下當下的快照且只作用於當時那一片', async () => {
    await withEnv(async ({ A, B, c, f, toasts }) => {
        // 已有原文的片再翻 → snapshot.original_title 非空
        A.title = '舊譯文';
        A.original_title = 'あいう原文';
        const p = c.lbTranslate();
        f.pending.translate[0]({ success: true, result: '新譯文' });
        await tick();
        f.pending.title[0](WB_OK('新譯文', 'あいう原文'));
        await p;
        assert.equal(A.title, '新譯文');
        c.nextLightboxVideo();
        assert.equal(c.currentLightboxVideo, B);
        const undo = toasts[0][3].onClick();
        assert.deepEqual(f.calls[2].body, { file_path: A.path, title: '舊譯文', original_title: 'あいう原文' });
        f.pending.title[1]({ success: true, title: '舊譯文', original_title: 'あいう原文', needs_translate: false });
        await undo;
        assert.equal(A.title, '舊譯文');
        assert.equal(A.original_title, 'あいう原文');
        assert.equal(B.title, 'えおか');
        assert.equal(B.original_title, '');
        const last = toasts[toasts.length - 1];
        assert.equal(last[0], 'showcase.lightbox.translate_undone');
        assert.equal(last[3], undefined, '復原後的 toast 不帶 action');
    });
});

test('復原失敗：標題不變並顯示寫入失敗 toast', async () => {
    await withEnv(async ({ A, c, f, toasts }) => {
        const p = c.lbTranslate();
        f.pending.translate[0]({ success: true, result: '譯文' });
        await tick();
        f.pending.title[0](WB_OK('譯文', 'あいう'));
        await p;
        const undo = toasts[0][3].onClick();
        f.pending.title[1]({ success: false, error: 'no_nfo' });
        await undo;
        assert.equal(A.title, '譯文');
        assert.equal(toasts[toasts.length - 1][0], 'showcase.lightbox.translate_write_failed');
    });
});
