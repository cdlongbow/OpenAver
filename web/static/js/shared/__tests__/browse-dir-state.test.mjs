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

test('browseDirState declares all contract stubs and has no init()', () => {
    const s = browseDirState();
    assert.equal(s.browseDirOpen, false);
    assert.equal(s.browseDirLoading, false);
    assert.equal(s.browseDirCurrentPath, '');
    assert.equal(s.browseDirParentPath, null);
    assert.deepEqual(s.browseDirEntries, []);
    assert.equal(s.browseDirError, '');
    assert.equal(s.browseDirTargetKey, null);
    assert.equal(s.browseDirExpandVideos, false);
    assert.equal(s._browseDirOnSelect, null);
    assert.equal(s._browseDirNavGen, 0);
    assert.equal(typeof s.openBrowseDir, 'function');
    assert.equal(typeof s.closeBrowseDir, 'function');
    assert.equal(typeof s.navigateBrowseDir, 'function');
    assert.equal(typeof s.browseDirUp, 'function');
    assert.equal(typeof s.selectBrowseDir, 'function');
    assert.equal(typeof s.browseDirCanSelect, 'function');
    assert.equal(typeof s.browseDirCrumbs, 'function');
    assert.equal('init' in s, false);
});

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
    const s = makeState({
        browseDirLoading: false,
        browseDirCurrentPath: '',
        browseDirError: '',
    });
    assert.equal(s.browseDirCanSelect(), false);
});

test('browseDirCanSelect is true for a real folder path', () => {
    const s = makeState({
        browseDirLoading: false,
        browseDirCurrentPath: '/home/videos',
        browseDirError: '',
    });
    assert.equal(s.browseDirCanSelect(), true);
});

test('browseDirCanSelect is false while loading or on error', () => {
    assert.equal(makeState({
        browseDirLoading: true,
        browseDirCurrentPath: '/home',
        browseDirError: '',
    }).browseDirCanSelect(), false);
    assert.equal(makeState({
        browseDirLoading: false,
        browseDirCurrentPath: '/home',
        browseDirError: 'common.browse_dir.err_not_found',
    }).browseDirCanSelect(), false);
});

// ── localStorage per trigger point ─────────────────────────────────────────

test('remembers last path per trigger point', async () => {
    const { store, restore: restoreLs } = mockLocalStorage();
    const restoreFetch = mockFetch(async (url) => {
        const u = String(url);
        if (u.includes('expand=videos')) {
            return okJson({
                current_path: '/search/picked',
                parent_path: '/search',
                entries: [],
                files: ['/search/picked/a.mp4'],
            });
        }
        if (u.includes(encodeURIComponent('/scanner/picked'))) {
            return okJson({
                current_path: '/scanner/picked',
                parent_path: '/scanner',
                entries: [],
            });
        }
        if (u.includes(encodeURIComponent('/settings/picked'))) {
            return okJson({
                current_path: '/settings/picked',
                parent_path: '/settings',
                entries: [],
            });
        }
        if (u.includes(encodeURIComponent('/search/picked'))) {
            return okJson({
                current_path: '/search/picked',
                parent_path: '/search',
                entries: [],
            });
        }
        // open without memory → omit path
        return okJson({
            current_path: '/',
            parent_path: null,
            entries: [{ name: 'tmp', path: '/tmp' }],
        });
    });
    try {
        const s = makeState();

        // scanner 選定
        let scannerPicked = null;
        s.openBrowseDir('scanner', (p) => { scannerPicked = p; });
        await flush();
        s.browseDirCurrentPath = '/scanner/picked';
        s.browseDirError = '';
        s.browseDirLoading = false;
        await s.selectBrowseDir();
        assert.equal(scannerPicked, '/scanner/picked');
        assert.equal(store['browse_dir_last_path_scanner'], '/scanner/picked');

        // settings 選定（不同 key）
        let settingsPicked = null;
        s.openBrowseDir('settings', (p) => { settingsPicked = p; });
        await flush();
        s.browseDirCurrentPath = '/settings/picked';
        s.browseDirError = '';
        s.browseDirLoading = false;
        await s.selectBrowseDir();
        assert.equal(settingsPicked, '/settings/picked');
        assert.equal(store['browse_dir_last_path_settings'], '/settings/picked');
        assert.equal(store['browse_dir_last_path_scanner'], '/scanner/picked');

        // search 選定（expandVideos）
        let searchPicked = null;
        s.openBrowseDir('search', (files) => { searchPicked = files; }, { expandVideos: true });
        await flush();
        s.browseDirCurrentPath = '/search/picked';
        s.browseDirError = '';
        s.browseDirLoading = false;
        await s.selectBrowseDir();
        assert.deepEqual(searchPicked, ['/search/picked/a.mp4']);
        assert.equal(store['browse_dir_last_path_search'], '/search/picked');
        assert.equal(store['browse_dir_last_path_scanner'], '/scanner/picked');
        assert.equal(store['browse_dir_last_path_settings'], '/settings/picked');
    } finally {
        restoreFetch();
        restoreLs();
    }
});

// ── error handling keeps entries ───────────────────────────────────────────

test('non-2xx maps error code and keeps previous entries', async () => {
    const restore = mockFetch(async () => errJson(404, 'not_found'));
    try {
        const s = makeState({
            browseDirEntries: [{ name: 'keep', path: '/keep' }],
            browseDirCurrentPath: '/keep',
        });
        await s.navigateBrowseDir('/missing');
        assert.equal(s.browseDirError, 'common.browse_dir.err_not_found');
        assert.deepEqual(s.browseDirEntries, [{ name: 'keep', path: '/keep' }]);
        assert.equal(s.browseDirLoading, false);
        assert.equal(s.browseDirCanSelect(), false);
    } finally {
        restore();
    }
});

test('unknown error code and fetch throw both map to err_generic', async () => {
    {
        const restore = mockFetch(async () => errJson(500, 'weird_code'));
        try {
            const s = makeState({ browseDirEntries: [{ name: 'a', path: '/a' }] });
            await s.navigateBrowseDir('/x');
            assert.equal(s.browseDirError, 'common.browse_dir.err_generic');
            assert.deepEqual(s.browseDirEntries, [{ name: 'a', path: '/a' }]);
        } finally {
            restore();
        }
    }
    {
        const restore = mockFetch(async () => { throw new Error('offline'); });
        try {
            const s = makeState({ browseDirEntries: [{ name: 'b', path: '/b' }] });
            await s.navigateBrowseDir('/y');
            assert.equal(s.browseDirError, 'common.browse_dir.err_generic');
            assert.deepEqual(s.browseDirEntries, [{ name: 'b', path: '/b' }]);
            assert.equal(s.browseDirLoading, false);
        } finally {
            restore();
        }
    }
});

test('permission_denied and not_a_directory map to their keys', async () => {
    {
        const restore = mockFetch(async () => errJson(403, 'permission_denied'));
        try {
            const s = makeState();
            await s.navigateBrowseDir('/nope');
            assert.equal(s.browseDirError, 'common.browse_dir.err_permission_denied');
        } finally {
            restore();
        }
    }
    {
        const restore = mockFetch(async () => errJson(400, 'not_a_directory'));
        try {
            const s = makeState();
            await s.navigateBrowseDir('/file');
            assert.equal(s.browseDirError, 'common.browse_dir.err_not_a_directory');
        } finally {
            restore();
        }
    }
});

// ── crumbs ─────────────────────────────────────────────────────────────────

test('browseDirCrumbs for empty path is drives-only', () => {
    const s = makeState({ browseDirCurrentPath: '' });
    assert.deepEqual(s.browseDirCrumbs(), [
        { label: 'common.browse_dir.drives', path: '' },
    ]);
});

test('browseDirCrumbs for POSIX root and nested paths', () => {
    assert.deepEqual(makeState({ browseDirCurrentPath: '/' }).browseDirCrumbs(), [
        { label: '/', path: '/' },
    ]);
    assert.deepEqual(makeState({ browseDirCurrentPath: '/home/videos' }).browseDirCrumbs(), [
        { label: '/', path: '/' },
        { label: 'home', path: '/home' },
        { label: 'videos', path: '/home/videos' },
    ]);
});

test('browseDirCrumbs for Windows paths prepends drives', () => {
    assert.deepEqual(makeState({ browseDirCurrentPath: 'C:\\' }).browseDirCrumbs(), [
        { label: 'common.browse_dir.drives', path: '' },
        { label: 'C:\\', path: 'C:\\' },
    ]);
    assert.deepEqual(makeState({ browseDirCurrentPath: 'C:\\Users\\foo' }).browseDirCrumbs(), [
        { label: 'common.browse_dir.drives', path: '' },
        { label: 'C:\\', path: 'C:\\' },
        { label: 'Users', path: 'C:\\Users' },
        { label: 'foo', path: 'C:\\Users\\foo' },
    ]);
});

// ── up / navigate null ─────────────────────────────────────────────────────

test('browseDirUp does nothing when parent_path is null', async () => {
    let called = 0;
    const restore = mockFetch(async () => {
        called++;
        return okJson({ current_path: '/', parent_path: null, entries: [] });
    });
    try {
        const s = makeState({ browseDirParentPath: null, browseDirCurrentPath: '/' });
        s.browseDirUp();
        await flush();
        assert.equal(called, 0);
    } finally {
        restore();
    }
});

test('browseDirUp navigates to empty-string parent (Windows drive list)', async () => {
    const urls = [];
    const restore = mockFetch(async (url) => {
        urls.push(String(url));
        return okJson({ current_path: '', parent_path: null, entries: [{ name: 'C:', path: 'C:\\' }] });
    });
    try {
        const s = makeState({ browseDirParentPath: '', browseDirCurrentPath: 'C:\\' });
        s.browseDirUp();
        await flush();
        assert.equal(urls.length, 1);
        assert.match(urls[0], /[?&]path=/);
        assert.equal(s.browseDirCurrentPath, '');
    } finally {
        restore();
    }
});

test('navigateBrowseDir(null) omits path param so backend picks start', async () => {
    const urls = [];
    const restore = mockFetch(async (url) => {
        urls.push(String(url));
        return okJson({ current_path: '/', parent_path: null, entries: [] });
    });
    try {
        const s = makeState();
        await s.navigateBrowseDir(null);
        assert.equal(urls.length, 1);
        assert.equal(urls[0].includes('path='), false);
        assert.equal(s.browseDirCurrentPath, '/');
    } finally {
        restore();
    }
});

// ── open / close symmetry ──────────────────────────────────────────────────

test('openBrowseDir resets expandVideos every time', async () => {
    const restore = mockFetch(async () => okJson({
        current_path: '/', parent_path: null, entries: [],
    }));
    const { restore: restoreLs } = mockLocalStorage();
    try {
        const s = makeState();
        s.openBrowseDir('search', () => {}, { expandVideos: true });
        await flush();
        assert.equal(s.browseDirExpandVideos, true);
        s.closeBrowseDir();
        assert.equal(s.browseDirExpandVideos, false);

        s.openBrowseDir('scanner', () => {});
        await flush();
        assert.equal(s.browseDirExpandVideos, false);
        assert.equal(s.browseDirTargetKey, 'scanner');
    } finally {
        restore();
        restoreLs();
    }
});

test('closeBrowseDir clears callback, error, entries, expandVideos', () => {
    const s = makeState({
        browseDirOpen: true,
        browseDirError: 'common.browse_dir.err_generic',
        browseDirEntries: [{ name: 'x', path: '/x' }],
        browseDirExpandVideos: true,
        _browseDirOnSelect: () => {},
    });
    s.closeBrowseDir();
    assert.equal(s.browseDirOpen, false);
    assert.equal(s._browseDirOnSelect, null);
    assert.equal(s.browseDirError, '');
    assert.deepEqual(s.browseDirEntries, []);
    assert.equal(s.browseDirExpandVideos, false);
});

test('openBrowseDir reads remembered path for that trigger point', async () => {
    const { restore: restoreLs } = mockLocalStorage();
    const urls = [];
    const restore = mockFetch(async (url) => {
        urls.push(String(url));
        if (String(url).includes(encodeURIComponent('/remembered/scanner'))) {
            return okJson({
                current_path: '/remembered/scanner',
                parent_path: '/remembered',
                entries: [],
            });
        }
        return okJson({ current_path: '/', parent_path: null, entries: [] });
    });
    try {
        const s = makeState();
        // 先選定寫入記憶，再開啟應帶出同一路徑（不硬編碼 storage key 字面）
        s.openBrowseDir('scanner', () => {});
        await flush();
        s.browseDirCurrentPath = '/remembered/scanner';
        s.browseDirError = '';
        s.browseDirLoading = false;
        await s.selectBrowseDir();
        urls.length = 0;
        s.openBrowseDir('scanner', () => {});
        await flush();
        assert.equal(s.browseDirOpen, true);
        assert.ok(urls.some((u) => u.includes(encodeURIComponent('/remembered/scanner'))));
    } finally {
        restore();
        restoreLs();
    }
});

test('navigate does not write localStorage; only select does', async () => {
    const { store, restore: restoreLs } = mockLocalStorage();
    const restore = mockFetch(async () => okJson({
        current_path: '/nav', parent_path: '/', entries: [],
    }));
    const memoryKeys = () => Object.keys(store).filter((k) => k.startsWith('browse_dir_last_path_'));
    try {
        const s = makeState();
        s.openBrowseDir('scanner', () => {});
        await flush();
        await s.navigateBrowseDir('/nav');
        assert.deepEqual(memoryKeys(), []);

        s.browseDirCurrentPath = '/nav';
        s.browseDirError = '';
        s.browseDirLoading = false;
        await s.selectBrowseDir();
        assert.ok(memoryKeys().length >= 1);
        assert.ok(memoryKeys().some((k) => store[k] === '/nav'));
    } finally {
        restore();
        restoreLs();
    }
});

test('localStorage unavailable is swallowed and feature still works', async () => {
    const prev = globalThis.localStorage;
    globalThis.localStorage = {
        getItem() { throw new Error('denied'); },
        setItem() { throw new Error('denied'); },
        removeItem() { throw new Error('denied'); },
    };
    const restore = mockFetch(async () => okJson({
        current_path: '/', parent_path: null, entries: [],
    }));
    try {
        const s = makeState();
        s.openBrowseDir('settings', () => {});
        await flush();
        assert.equal(s.browseDirOpen, true);
        s.browseDirCurrentPath = '/ok';
        s.browseDirError = '';
        s.browseDirLoading = false;
        await s.selectBrowseDir();
        assert.equal(s.browseDirOpen, false);
    } finally {
        restore();
        globalThis.localStorage = prev;
    }
});

test('deleted remembered path shows error but up still works', async () => {
    const { restore: restoreLs } = mockLocalStorage();
    let call = 0;
    const restore = mockFetch(async (url) => {
        call++;
        if (String(url).includes(encodeURIComponent('/gone'))) {
            return errJson(404, 'not_found');
        }
        return okJson({ current_path: '/', parent_path: null, entries: [{ name: 'home', path: '/home' }] });
    });
    try {
        const s = makeState();
        // 先寫入記憶路徑，再開啟觸發 404（不硬編碼 storage key）
        s.openBrowseDir('scanner', () => {});
        await flush();
        s.browseDirCurrentPath = '/gone';
        s.browseDirError = '';
        s.browseDirLoading = false;
        await s.selectBrowseDir();
        s.openBrowseDir('scanner', () => {});
        await flush();
        assert.equal(s.browseDirError, 'common.browse_dir.err_not_found');
        s.browseDirParentPath = '/';
        s.browseDirUp();
        await flush();
        assert.equal(s.browseDirCurrentPath, '/');
        assert.equal(s.browseDirError, '');
        assert.ok(call >= 2);
    } finally {
        restore();
        restoreLs();
    }
});

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

test('cancelled expand=videos select does not apply even without reopening', async () => {
    // 比「取消後重開」更常見的子情境：使用者只是按了取消，沒有再開。
    // 若只有 openBrowseDir 讓 session 失效，這條就會漏 —— 舊回應照樣把整夾塞進來。
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
        return okJson({ current_path: '/old/folder', parent_path: '/old', entries: [] });
    });
    try {
        const s = makeState();
        let picked = null;
        s.openBrowseDir('search', (files) => { picked = files; }, { expandVideos: true });
        await flush();
        const selectPromise = s.selectBrowseDir();
        await flush();

        s.closeBrowseDir();          // 使用者按取消，之後什麼都沒做
        resolveExpand();
        await selectPromise;
        await flush();

        assert.equal(picked, null, '按了取消之後，延遲回應不得再把檔案塞進來');
        assert.equal(ls.store['browse_dir_last_path_search'], undefined,
            '按了取消之後不得寫記憶路徑');
        assert.equal(s.browseDirOpen, false);
    } finally {
        restoreFetch();
        ls.restore();
    }
});
