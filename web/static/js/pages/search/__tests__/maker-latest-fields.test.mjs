// TASK-173-T8：片商最新作品——前端共享欄位語意（CD-173-9 oracle 1–5、CD-173-12）
//
// 守住的行為：
//   - activeMaker() 只在 currentMode==='maker' 時回 currentMaker（惰性靠模式閘）
//   - progressQueryText()：片商模式顯示片商名，其餘顯示 currentQuery
//   - saveState 兩條分支（live／搜尋中 snapshot）都帶 currentMaker，queryValue 維持空字串
//   - restoreState：存→還原後搜尋框仍空、activeMaker().key 不變；舊存檔缺欄位 ⇒ null
//   - cancelSearch 還原 snapshot 的 currentMaker；clearAll 清掉它
//   - hasContent：片商錯誤頁有 ✕、關鍵字錯誤頁沒有、載入中沒有

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {} };
window.t = (key) => key;

register(new URL('./alias-loader.mjs', import.meta.url), import.meta.url);

const { searchStateBase } = await import('../state/base.js');
const { searchStateSearchFlow } = await import('../state/search-flow.js');
const { searchStatePersistence } = await import('../state/persistence.js');
const { searchPage } = await import('../main.js');

const MAKER_A = { key: 'moodyz', label: 'MOODYZ', spellings: ['MOODYZ', 'Moodyz'] };
const MAKER_B = { key: 's1', label: 'S1', spellings: ['S1'] };

// 合併時保留 getter（Object.assign／spread 會在合併當下把 hasContent 求值凍結）
function merge(...parts) {
    const target = {};
    for (const part of parts) {
        Object.defineProperties(target, Object.getOwnPropertyDescriptors(part));
    }
    return target;
}

function flowThis(overrides = {}) {
    return merge(searchStateBase(), searchStateSearchFlow(), overrides);
}

function mockSessionStorage(initial = {}) {
    const store = { ...initial };
    globalThis.sessionStorage = {
        setItem: (k, v) => { store[k] = v; },
        getItem: (k) => store[k] ?? null,
        removeItem: (k) => { delete store[k]; },
    };
    return store;
}

// persistence 分片＋activeMaker（只供測試端斷言用；saveState／restoreState 本身不得呼叫它）
function persistThis(STATE_KEY, overrides = {}) {
    return merge(
        searchStatePersistence(),
        { activeMaker: searchStateSearchFlow().activeMaker },
        {
            STATE_KEY,
            searchResults: [],
            currentIndex: 0,
            currentQuery: '',
            currentOffset: 0,
            hasMoreResults: false,
            fileList: [],
            currentFileIndex: 0,
            listMode: null,
            searchQuery: '',
            displayMode: 'detail',
            _preWishlistDisplayMode: null,
            _preWishlistListMode: null,
            currentMode: '',
            currentMaker: null,
            actressProfile: null,
            pageState: 'result',
            _searchSnapshot: null,
            lightboxOpen: false,
            lightboxIndex: 0,
            _heroCardImageError: false,
            _heroLightboxImageError: false,
            _resetCoverState: () => {},
            switchToWishlist: () => {},
        },
        overrides,
    );
}

// maker 結果態：currentQuery／searchQuery 皆空（CD-173-9 不變式）
function makerResultFields(maker = MAKER_A) {
    return {
        pageState: 'result',
        listMode: 'search',
        currentMode: 'maker',
        currentMaker: maker,
        currentQuery: '',
        searchQuery: '',
        searchResults: [{ number: 'MIDV-001' }, { number: 'MIDV-002' }],
        currentOffset: 0,
        hasMoreResults: true,
    };
}

// ─── oracle 1：惰性 ────────────────────────────────────────────────────────

test('activeMaker: inert-when-mode-not-maker（模式不是 maker 時恆為 null）', () => {
    const exact = flowThis({ currentMode: 'exact', currentMaker: MAKER_A });
    assert.equal(exact.activeMaker(), null, 'currentMode=exact 時殘留的 currentMaker 必須被視為不存在');

    const noMaker = flowThis({ currentMode: 'maker', currentMaker: null });
    assert.equal(noMaker.activeMaker(), null);

    const maker = flowThis({ currentMode: 'maker', currentMaker: MAKER_A });
    assert.equal(maker.activeMaker()?.key, 'moodyz');
});

test('progressQueryText: progress-text-maker（片商模式顯示片商名）', () => {
    const page = flowThis({ currentMode: 'maker', currentMaker: MAKER_A, currentQuery: '' });
    assert.equal(page.progressQueryText(), 'MOODYZ');
});

test('progressQueryText: 非片商模式顯示 currentQuery（殘留 currentMaker 不影響）', () => {
    const page = flowThis({ currentMode: 'exact', currentMaker: MAKER_A, currentQuery: 'SONE-205' });
    assert.equal(page.progressQueryText(), 'SONE-205');
});

// ─── oracle 2：兩條存檔分支 ────────────────────────────────────────────────

test('saveState: save-live（結果態存出 currentMaker）', () => {
    const KEY = 'test-173-save-live';
    const store = mockSessionStorage();
    const page = persistThis(KEY, makerResultFields(MAKER_A));

    searchStatePersistence().saveState.call(page);
    const saved = JSON.parse(store[KEY]);
    assert.equal(saved.currentMaker?.key, 'moodyz');
    assert.equal(saved.currentMode, 'maker');
});

test('saveState: save-snapshot（搜尋中存的是上一輪 snapshot 的 currentMaker，不是 live 的）', () => {
    const KEY = 'test-173-save-snapshot';
    const store = mockSessionStorage();
    const page = persistThis(KEY, {
        pageState: 'loading',
        listMode: 'search',
        currentMode: '',
        currentMaker: MAKER_B,  // live：正在載入片商 B
        _searchSnapshot: {
            searchResults: [{ number: 'MIDV-001' }],
            currentIndex: 0,
            currentQuery: '',
            currentOffset: 0,
            hasMoreResults: true,
            fileList: [],
            currentFileIndex: 0,
            listMode: 'search',
            displayMode: 'grid',
            currentMode: 'maker',
            currentMaker: MAKER_A,  // 上一輪：片商 A 的結果
            actressProfile: null,
        },
    });

    searchStatePersistence().saveState.call(page);
    const saved = JSON.parse(store[KEY]);
    assert.equal(saved.currentMaker?.key, 'moodyz', 'loading 分支必須寫 snapshot 的 currentMaker');
    assert.equal(saved.queryValue, '', '上一輪是片商結果，搜尋框還原值必須是空字串');
});

test('saveState→restoreState: query-value-empty（片商結果存檔後搜尋框仍空）', () => {
    const KEY = 'test-173-query-value';
    const store = mockSessionStorage();
    const before = persistThis(KEY, makerResultFields(MAKER_A));
    searchStatePersistence().saveState.call(before);
    const saved = JSON.parse(store[KEY]);
    assert.equal(saved.queryValue, '', '存出的搜尋框值不得帶入片商名');

    const after = persistThis(KEY);
    searchStatePersistence().restoreState.call(after);
    assert.equal(after.searchQuery, '', '還原後搜尋框必須是空的');
});

test('saveState→restoreState: restore-roundtrip（還原後仍是同一家片商）', () => {
    const KEY = 'test-173-roundtrip';
    mockSessionStorage();
    const before = persistThis(KEY, makerResultFields(MAKER_A));
    searchStatePersistence().saveState.call(before);

    const after = persistThis(KEY);
    searchStatePersistence().restoreState.call(after);
    assert.equal(after.pageState, 'result');
    assert.equal(after.currentMode, 'maker');
    assert.equal(after.activeMaker()?.key, before.activeMaker()?.key);
    assert.equal(after.activeMaker()?.key, 'moodyz');
});

// ─── oracle 4：舊存檔 ──────────────────────────────────────────────────────

test('restoreState: 舊存檔沒有 currentMaker 欄位 ⇒ null，其他欄位照舊還原', () => {
    const KEY = 'test-173-legacy';
    const legacy = {
        searchResults: [{ number: 'SONE-205' }],
        currentIndex: 0,
        currentQuery: 'SONE',
        currentOffset: 0,
        hasMoreResults: true,
        fileList: [],
        currentFileIndex: 0,
        listMode: 'search',
        queryValue: 'SONE',
        displayMode: 'detail',
        currentMode: 'prefix',
        actressProfile: null,
    };
    const store = mockSessionStorage({ [KEY]: JSON.stringify(legacy) });
    assert.equal('currentMaker' in JSON.parse(store[KEY]), false, '前提：舊存檔真的沒有這個欄位');

    const errors = [];
    const origError = console.error;
    console.error = (...args) => { errors.push(args); };
    try {
        const page = persistThis(KEY, { currentMaker: MAKER_B });
        searchStatePersistence().restoreState.call(page);
        assert.equal(page.currentMaker, null);
        assert.equal(page.currentQuery, 'SONE');
        assert.equal(page.searchQuery, 'SONE');
        assert.equal(page.currentMode, 'prefix');
        assert.equal(page.pageState, 'result');
    } finally {
        console.error = origError;
    }
    assert.equal(errors.length, 0, 'restoreState 不得走進 catch');
    assert.ok(store[KEY], 'restoreState 不得清掉存檔（catch 分支才會清）');
});

// ─── oracle 3：取消還原 ────────────────────────────────────────────────────

test('cancelSearch: cancel-restores（還原 snapshot 的 currentMaker）', () => {
    const page = flowThis({
        pageState: 'loading',
        currentMode: '',
        currentMaker: MAKER_B,
        _searchSnapshot: {
            searchResults: [{ number: 'MIDV-001' }],
            currentIndex: 0,
            fileList: [],
            currentFileIndex: 0,
            listMode: 'search',
            hasMoreResults: true,
            currentQuery: '',
            currentOffset: 0,
            pageState: 'result',
            actressProfile: null,
            displayMode: 'grid',
            currentMode: 'maker',
            currentMaker: MAKER_A,
            errorText: '',
            errorKind: '',
        },
    });

    page.cancelSearch();
    assert.equal(page.pageState, 'result');
    assert.equal(page.activeMaker()?.key, 'moodyz');
});

test('cancelSearch: snapshot 沒有 currentMaker 欄位 ⇒ null', () => {
    const page = flowThis({
        pageState: 'loading',
        currentMaker: MAKER_B,
        _searchSnapshot: {
            searchResults: [{ number: 'SONE-205' }],
            currentIndex: 0,
            fileList: [],
            currentFileIndex: 0,
            listMode: 'search',
            hasMoreResults: false,
            currentQuery: 'SONE-205',
            currentOffset: 0,
            pageState: 'result',
            actressProfile: null,
            displayMode: 'detail',
            currentMode: 'exact',
            errorText: '',
            errorKind: '',
        },
    });

    page.cancelSearch();
    assert.equal(page.currentMaker, null);
    assert.equal(page.currentQuery, 'SONE-205');
});

test('clearAll: 清掉 currentMaker', () => {
    const page = flowThis(makerResultFields(MAKER_A));
    page.clearAll();
    assert.equal(page.currentMaker, null);
    assert.equal(page.activeMaker(), null);
    assert.equal(page.pageState, 'empty');
});

// ─── oracle 5：hasContent ──────────────────────────────────────────────────

test('hasContent: has-content-maker-error（片商錯誤頁有 ✕）', () => {
    const page = flowThis({
        pageState: 'error',
        searchResults: [],
        fileList: [],
        currentMode: 'maker',
        currentMaker: MAKER_A,
    });
    assert.equal(page.hasContent, true);
});

test('hasContent: has-content-keyword-error-no-clear（關鍵字錯誤頁沒有 ✕）', () => {
    const page = flowThis({
        pageState: 'error',
        searchResults: [],
        fileList: [],
        currentMode: 'exact',
        currentMaker: MAKER_A,  // 殘留值也不得讓關鍵字錯誤頁出現 ✕
    });
    assert.equal(page.hasContent, false);
});

test('hasContent: 片商載入中沒有 ✕', () => {
    const page = flowThis({
        pageState: 'loading',
        searchResults: [],
        fileList: [],
        currentMode: 'maker',
        currentMaker: MAKER_A,
    });
    assert.equal(page.hasContent, false);
});

// ─── FE-ALPINE-06：真 searchPage() 合併物件的接線 ─────────────────────────

test('searchPage(): 合併物件上有 currentMaker／activeMaker()／progressQueryText()，初始無 ✕', () => {
    const page = searchPage();
    assert.ok('currentMaker' in page);
    assert.equal(page.currentMaker, null);
    assert.equal(typeof page.activeMaker, 'function');
    assert.equal(typeof page.progressQueryText, 'function');
    assert.equal(page.activeMaker(), null);
    assert.equal(page.hasContent, false);
});
