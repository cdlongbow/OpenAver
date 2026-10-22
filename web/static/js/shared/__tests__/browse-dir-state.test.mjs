// TASK-128-T2：browseDirState() — 麵包屑／錯誤碼／localStorage／race guard／select 分流
//
// 三個 mutation 閘字串（卡片定死，不得改名）：
//   - stale navigate response is dropped
//   - cannot select the windows drive-list node
//   - remembers last path per trigger point

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
globalThis.window.t = (k) => k;

const { browseDirState } = await import('../state-browse-dir.js');

function makeState(overrides = {}) {
    return Object.assign(browseDirState(), overrides);
}

function mockFetch(impl) {
    const prev = globalThis.fetch;
    globalThis.fetch = impl;
    return () => { globalThis.fetch = prev; };
}

function mockLocalStorage(store = {}) {
    const prev = globalThis.localStorage;
    globalThis.localStorage = {
        getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
        setItem(k, v) { store[k] = String(v); },
        removeItem(k) { delete store[k]; },
    };
    return { store, restore: () => { globalThis.localStorage = prev; } };
}

function okJson(body) {
    return {
        ok: true,
        status: 200,
        json: async () => body,
    };
}

function errJson(status, error) {
    return {
        ok: false,
        status,
        json: async () => ({ success: false, error }),
    };
}

function flush() {
    return new Promise((r) => setImmediate(r));
}

// ── factory shape ──────────────────────────────────────────────────────────

// ── race guard ─────────────────────────────────────────────────────────────

test('stale navigate response is dropped', async () => {
    let resolveFirst;
    let resolveSecond;
    const firstBody = {
        current_path: '/old',
        parent_path: '/',
        entries: [{ name: 'old', path: '/old/a' }],
    };
    const secondBody = {
        current_path: '/new',
        parent_path: '/',
        entries: [{ name: 'new', path: '/new/b' }],
    };
    let call = 0;
    const restore = mockFetch(async () => {
        call++;
        if (call === 1) {
            return new Promise((resolve) => {
                resolveFirst = () => resolve(okJson(firstBody));
            });
        }
        return new Promise((resolve) => {
            resolveSecond = () => resolve(okJson(secondBody));
        });
    });
    try {
        const s = makeState();
        const p1 = s.navigateBrowseDir('/old');
        const p2 = s.navigateBrowseDir('/new');
        // 後點的先回來
        resolveSecond();
        await p2;
        assert.equal(s.browseDirCurrentPath, '/new');
        assert.deepEqual(s.browseDirEntries, secondBody.entries);
        // 慢的那個後到 → 必須丟棄，不得蓋回 /old
        resolveFirst();
        await p1;
        assert.equal(s.browseDirCurrentPath, '/new');
        assert.deepEqual(s.browseDirEntries, secondBody.entries);
    } finally {
        restore();
    }
});

// ── Windows drive-list node ────────────────────────────────────────────────

test('cannot select the windows drive-list node', () => {
    // 162a：真實資料夾可選、載入中／錯誤不可選併入同一支（同一 getter browseDirCanSelect）
    const cases = [
        { label: 'windows drive-list node', state: { browseDirLoading: false, browseDirCurrentPath: '', browseDirError: '' }, expected: false },
        { label: 'real folder path', state: { browseDirLoading: false, browseDirCurrentPath: '/home/videos', browseDirError: '' }, expected: true },
        { label: 'loading', state: { browseDirLoading: true, browseDirCurrentPath: '/home', browseDirError: '' }, expected: false },
        { label: 'error', state: { browseDirLoading: false, browseDirCurrentPath: '/home', browseDirError: 'common.browse_dir.err_not_found' }, expected: false },
    ];
    for (const c of cases) {
        assert.equal(makeState(c.state).browseDirCanSelect(), c.expected, c.label);
    }
});

// ── localStorage per trigger point ─────────────────────────────────────────


// ── error handling keeps entries ───────────────────────────────────────────


// ── crumbs ─────────────────────────────────────────────────────────────────


// ── up / navigate null ─────────────────────────────────────────────────────


// ── open / close symmetry ──────────────────────────────────────────────────


test('stale expand=videos response cannot apply after cancel and reopen', async () => {
    // Codex PR review P2（2026-08-24）：selectBrowseDir 的 expand=videos 二次請求
    // 沒有納入任何 generation guard —— 使用者在慢儲存（NAS／9p 掛載）上選了大資料夾，
    // 等不及按取消／重開，舊回應回來時仍會塞舊清單、寫舊記憶路徑、關掉新彈窗。
    const ls = mockLocalStorage({});
    let resolveExpand = null;
    const restoreFetch = mockFetch(async (url) => {
        if (String(url).includes('expand=videos')) {
            return new Promise((resolve) => {
                resolveExpand = () => resolve(okJson({
                    current_path: '/old/folder',
                    parent_path: '/old',
                    entries: [],
                    files: ['/old/folder/stale.mp4'],
                }));
            });
        }
        return okJson({
            current_path: String(url).includes('new') ? '/new/folder' : '/old/folder',
            parent_path: '/old',
            entries: [],
        });
    });
    try {
        const s = makeState();
        let oldPicked = null;
        let newPicked = null;

        // ① 第一次開窗 → 停在 /old/folder → 按「選取此資料夾」（請求卡住不回）
        s.openBrowseDir('search', (files) => { oldPicked = files; }, { expandVideos: true });
        await flush();
        assert.equal(s.browseDirCurrentPath, '/old/folder');
        const selectPromise = s.selectBrowseDir();
        await flush();
        assert.equal(oldPicked, null, 'fetch 還沒回來，callback 不該先被呼叫');

        // ② 使用者按取消（Escape／X／取消鈕都走這支），然後重開一個新的選擇器
        s.closeBrowseDir();
        s.openBrowseDir('search', (files) => { newPicked = files; }, { expandVideos: true });
        await s.navigateBrowseDir('/new/folder');
        await flush();
        assert.equal(s.browseDirOpen, true);

        // ③ 舊請求現在才回來
        resolveExpand();
        await selectPromise;
        await flush();

        assert.equal(oldPicked, null, '舊 callback 不得被延遲回應觸發');
        assert.equal(newPicked, null, '也不得誤觸新 session 的 callback');
        assert.equal(ls.store['browse_dir_last_path_search'], undefined,
            '不得用已取消的那次選取覆寫記憶路徑');
        assert.equal(s.browseDirOpen, true, '新開的彈窗不得被舊請求關掉');
        assert.equal(s.browseDirCurrentPath, '/new/folder', '新 session 的路徑不得被舊回應覆蓋');
    } finally {
        restoreFetch();
        ls.restore();
    }
});

test('a normal expand=videos select still applies within the same session', async () => {
    // 反向鎖：上面那條 guard 不得把正常流程也擋掉
    const ls = mockLocalStorage({});
    const restoreFetch = mockFetch(async (url) => {
        if (String(url).includes('expand=videos')) {
            return okJson({ current_path: '/lib/a', parent_path: '/lib', entries: [], files: ['/lib/a/1.mp4'] });
        }
        return okJson({ current_path: '/lib/a', parent_path: '/lib', entries: [] });
    });
    try {
        const s = makeState();
        let picked = null;
        s.openBrowseDir('search', (files) => { picked = files; }, { expandVideos: true });
        await flush();
        await s.selectBrowseDir();
        await flush();
        assert.deepEqual(picked, ['/lib/a/1.mp4']);
        assert.equal(ls.store['browse_dir_last_path_search'], '/lib/a');
        assert.equal(s.browseDirOpen, false);
        assert.equal(s.browseDirLoading, false, 'select 成功後 loading 必須回到 false');
    } finally {
        restoreFetch();
        ls.restore();
    }
});

