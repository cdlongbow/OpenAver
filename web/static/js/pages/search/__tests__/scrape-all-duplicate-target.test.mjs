// TASK-122-T6 AC-13：scrapeAll() 撞名時必須把後端 duplicate_target 寫進該 file
// 物件的 duplicateTarget，列表標記點開既有 modal 才顯示「撞到哪個檔」。
// 缺這行時 scrapeStatus 仍是 'duplicate'，但點開彈窗是空字串。
//
// batch.js 無 `@/` 別名 import，可直接靜態 import（不必掛 alias-loader）。
// 慣例同 remove-file-candidate-pollution.test.mjs：spread factory → 補 mock state
// → 直接呼叫方法 → 斷言。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateBatch } from '../state/batch.js';

globalThis.window = globalThis;
globalThis.document = globalThis.document || {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
};
globalThis.window.t = globalThis.window.t || ((k) => k);

function makeFile(overrides = {}) {
    return {
        filename: 'ABC-123-part1.mp4',
        path: '/lib/ABC-123-part1.mp4',
        searched: true,
        scraped: false,
        searchResults: [{ number: 'ABC-123', title: 'Title' }],
        selectedCandidateIndex: 0,
        chineseTitle: '',
        ...overrides,
    };
}

function makeState(fileList, scrapeFileImpl) {
    window.SearchFile = {
        scrapeFile: scrapeFileImpl,
    };
    return {
        ...searchStateBatch(),
        fileList,
        listMode: 'file',
        currentFileIndex: 0,
        currentIndex: 0,
        searchResults: [],
        isScrapeAllProcessing: false,
        scrapeProgress: { total: 0, processed: 0, isProcessing: false },
        appConfig: {},
        showToast() {},
        $nextTick(fn) { fn(); },
        scrapePercent() { return 0; },
        _resetCoverState() {},
    };
}

test('scrapeAll: 後端回 duplicate + duplicate_target → scrapeStatus 與 duplicateTarget 都寫上該 file', async () => {
    const file = makeFile();
    const state = makeState(
        [file],
        async () => ({ duplicate: true, duplicate_target: 'ABC-123.mp4' }),
    );

    await state.scrapeAll();

    assert.equal(file.scrapeStatus, 'duplicate');
    assert.equal(file.duplicateTarget, 'ABC-123.mp4');
});

test('scrapeAll: duplicate_target 缺席 → duplicateTarget 是空字串（不是 undefined、不炸）', async () => {
    const file = makeFile();
    const state = makeState(
        [file],
        async () => ({ duplicate: true }),
    );

    await state.scrapeAll();

    assert.equal(file.scrapeStatus, 'duplicate');
    assert.equal(file.duplicateTarget, '');
});

// ── T6 review P1：單片路徑也必須寫 file.duplicateTarget ──────────────────
// scrapeSingle() 本來就會設 file.scrapeStatus='duplicate'，而 T6 讓列表對這個值
// 長出持久標記。若只寫單例 this.duplicateTarget（關彈窗時會被清空），使用者關掉
// 彈窗後再點那顆標記，會看到「undefined」而不是撞到的檔名。
function makeSingleState(file, scrapeResult) {
    globalThis.window.SearchFile = {
        scrapeFile: async () => scrapeResult,
    };
    return {
        ...searchStateBatch(),
        fileList: [file],
        listMode: 'file',
        currentFileIndex: 0,
        currentIndex: 0,
        searchResults: [],
        duplicateModalOpen: false,
        duplicateTarget: '',
        appConfig: null,
        showToast() {},
        $nextTick(fn) { fn(); },
        _resetCoverState() {},
    };
}

test('scrapeSingle: 撞名時 file.duplicateTarget 與單例 duplicateTarget 都要寫入（兩條路對稱）', async () => {
    const file = makeFile();
    const state = makeSingleState(file, { duplicate: true, duplicate_target: 'Y' });

    await state.scrapeSingle(0);

    assert.equal(file.scrapeStatus, 'duplicate');
    assert.equal(state.duplicateTarget, 'Y', '單片路徑仍然立刻開彈窗（既有行為，不改）');
    assert.equal(state.duplicateModalOpen, true);
    assert.equal(
        file.duplicateTarget, 'Y',
        '缺這個欄位 → 關掉彈窗後點列表標記會顯示 undefined',
    );
});
