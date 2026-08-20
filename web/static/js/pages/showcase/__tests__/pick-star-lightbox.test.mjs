// TASK-123-T3: 燈箱精選星 —— togglePickStar 飛行鎖／captured ref／_pickFilterStale／三層失敗判定
//
// 2026-08-21（自生洞立即停，換掉機制）：舊版用一個「dirty」旗標＋一個「這次是不是我設起來的」
// 輔助旗標代理「牆面是否過期」，在並發（兩個 path 同時在飛）與飛行中關燈箱下都會與真實狀態
// 脫鉤（已用腳本重現，非推理）。新機制不設旗標，改用直接觀察 _filteredVideos 的述詞
// `_pickFilterStale()`——本檔下方相關測試段落已全部改寫成驗這個述詞的行為。
//
// 零 DOM，mock global.fetch。state-lightbox.js 用瀏覽器 importmap 別名 `@/showcase/...`，
// plain `node --test` 不認得；比照 delete-modal-multipart.test.mjs／lb-full-error-pill.test.mjs
// 自帶與 base.html importmap 對齊的 resolve hook。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;

// closeLightbox / searchFromMetadata 會碰 document；給最小 stub。
globalThis.document = {
    querySelector() { return null; },
    body: {
        classList: {
            remove() {},
            add() {},
            contains() { return false; },
        },
    },
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
// _pickFilterStale() 讀的是 state-base.js 的模組級單例陣列（同一個 import specifier，
// 走同一支 resolve hook，跟 state-lightbox.js 內部 `@/showcase/state-base.js` 解析到同一份
// 模組實例）——測試用它直接佈置/清空「牆上目前顯示的清單」。
const { _filteredVideos } = await import('@/showcase/state-base.js');

const PATH_A = 'file:///m/ABC-123.mp4';
const PATH_B = 'file:///m/DEF-456.mp4';

/** 佈置 _filteredVideos（每個涉及 _pickFilterStale() 的測試都要先呼叫，避免吃到前一支測試殘留）。 */
function setFilteredVideos(arr) {
    _filteredVideos.length = 0;
    for (const v of arr) _filteredVideos.push(v);
}

/** 手動 resolve 的 fetch mock：可量測飛行中再呼叫、可精準控制落地時機。 */
function mockFetchManual() {
    const prev = globalThis.fetch;
    const calls = [];
    globalThis.fetch = (url, opts) => {
        const body = opts && opts.body ? JSON.parse(opts.body) : {};
        return new Promise((resolve, reject) => {
            calls.push({
                url,
                method: opts && opts.method,
                body,
                resolve: (respLike) => resolve(respLike),
                reject: (err) => reject(err),
            });
        });
    };
    return {
        restore() { globalThis.fetch = prev; },
        calls,
    };
}

/**
 * window.ShowcaseAnimations 的 spy：只記錄 playPickFill 呼叫、不做任何事。
 * 目前沒有任何既有測試碰 window.ShowcaseAnimations（togglePickStar 全走 `?.`，
 * undefined 時就是安靜的 no-op）——新增這支 spy 前務必 restore() 還原，避免外溢到其他測試。
 */
function mockAnimationsSpy() {
    const prev = globalThis.window.ShowcaseAnimations;
    const calls = [];
    globalThis.window.ShowcaseAnimations = {
        playPickFill(fillEl, outlineEl, fromPicked, toPicked) {
            calls.push({ fillEl, outlineEl, fromPicked, toPicked });
        },
    };
    return {
        restore() { globalThis.window.ShowcaseAnimations = prev; },
        calls,
    };
}

function okResp(results) {
    return {
        ok: true,
        status: 200,
        json: async () => ({
            success: true,
            results: results || [{ ok: true }],
        }),
    };
}

function makeComponent(overrides) {
    const c = Object.assign({}, stateLightbox(), {
        pills: [],
        lightboxOpen: true,
        applyFilterAndSortCalls: 0,
        applyFilterAndSort() { c.applyFilterAndSortCalls++; },
        addPillCalls: [],
        addPill(dim, value) { c.addPillCalls.push({ dim, value }); },
        toasts: [],
        showToast(msg, kind) { c.toasts.push({ msg, kind }); },
        _resetMask() {},
        _closePicker() {},
        $nextTick(fn) { if (typeof fn === 'function') fn(); },
    }, overrides);
    return c;
}

// ── 飛行鎖 ──────────────────────────────────────────────────────────

test('飛行鎖：飛行中再呼叫 togglePickStar 是 no-op（不發第二個 request）', async () => {
    const mock = mockFetchManual();
    try {
        const video = { path: PATH_A, user_rating: 0, number: 'ABC-123' };
        const c = makeComponent({ currentLightboxVideo: video });

        const p1 = c.togglePickStar();
        assert.equal(mock.calls.length, 1, '第一次呼叫應發一個 request');
        assert.equal(video.user_rating, 1, '樂觀更新應立刻生效');

        const p2 = c.togglePickStar();
        assert.equal(mock.calls.length, 1, '飛行中第二次呼叫不得再發 request');

        mock.calls[0].resolve(okResp());
        await p1;
        await p2;
    } finally {
        mock.restore();
    }
});

// ── CD-123-15 captured ref ───────────────────────────────────────────

test('captured ref：飛行中換片，失敗時回滾的是原本那一片，不是現在顯示的那片', async () => {
    const mock = mockFetchManual();
    try {
        const videoA = { path: PATH_A, user_rating: 0, number: 'ABC-123' };
        const videoB = { path: PATH_B, user_rating: 0, number: 'DEF-456' };
        const c = makeComponent({ currentLightboxVideo: videoA });

        const p = c.togglePickStar();
        assert.equal(videoA.user_rating, 1, '樂觀更新寫到 A');

        // 飛行中滾到下一片
        c.currentLightboxVideo = videoB;

        mock.calls[0].resolve({
            ok: true,
            status: 200,
            json: async () => ({
                success: true,
                results: [{ ok: false, reason: 'not_found' }],
            }),
        });
        await p;

        assert.equal(videoA.user_rating, 0, '失敗必須回滾 A（captured）');
        assert.equal(videoB.user_rating, 0, 'B 不該被碰');
        assert.equal(c.toasts.length, 1);
        assert.equal(c.toasts[0].msg, 'showcase.pick.save_failed');
        assert.equal(c.toasts[0].kind, 'error');
    } finally {
        mock.restore();
    }
});

// ── _pickFilterStale 述詞（CD-123-14a，取代舊版的旗標機制）─────────
// 直接觀察 _filteredVideos：掛精選 pill 時，牆上清單裡只要有一片不是精選（user_rating
// 為 0），就代表牆面已過期，需要重篩。沒掛 pill 時恆不重篩。每支測試各自
// setFilteredVideos()，不依賴前一支測試殘留的內容。

test('scenario 1：沒掛 pick pill → 切換星 → closeLightbox → applyFilterAndSort 一次都沒被呼叫', async () => {
    const mock = mockFetchManual();
    try {
        const video = { path: PATH_A, user_rating: 0 };
        // 沒掛 pick pill 時，牆上本來就會有未精選項目——這是正常狀態，不是「過期」。
        const otherUnpicked = { path: 'file:///m/OTHER-1.mp4', user_rating: 0 };
        const c = makeComponent({
            currentLightboxVideo: video,
            pills: [{ dim: 'maker', value: 'Moodyz' }],
            lightboxOpen: true,
        });
        setFilteredVideos([video, otherUnpicked]);

        const p = c.togglePickStar();
        mock.calls[0].resolve(okResp());
        await p;

        c.closeLightbox();
        assert.equal(c.applyFilterAndSortCalls, 0, '沒掛 pick pill，一次都不該重篩');
    } finally {
        mock.restore();
    }
});

test('scenario 2：掛 pick pill、取消某片的星 → 燈箱還開著時不重篩（§4.13）→ closeLightbox 剛好呼叫一次', async () => {
    const mock = mockFetchManual();
    try {
        const video = { path: PATH_A, user_rating: 1 };
        const c = makeComponent({
            currentLightboxVideo: video,
            pills: [{ dim: 'pick', value: '1' }],
            lightboxOpen: true,
        });
        setFilteredVideos([video]);

        const p = c.togglePickStar();
        assert.equal(video.user_rating, 0, '樂觀更新已生效');

        mock.calls[0].resolve(okResp());
        await p;
        assert.equal(c.applyFilterAndSortCalls, 0, '燈箱還開著，不能當場把這片從腳下抽走');

        c.closeLightbox();
        assert.equal(c.applyFilterAndSortCalls, 1, '關燈箱時牆面已過期，剛好重篩一次');
    } finally {
        mock.restore();
    }
});

test('scenario 5：淨變化為零（同一片取消又按回來）→ 關燈箱時不重篩', async () => {
    const mock = mockFetchManual();
    try {
        const video = { path: PATH_A, user_rating: 1 };
        const c = makeComponent({
            currentLightboxVideo: video,
            pills: [{ dim: 'pick', value: '1' }],
            lightboxOpen: true,
        });
        setFilteredVideos([video]);

        const p1 = c.togglePickStar();      // 取消
        mock.calls[0].resolve(okResp());
        await p1;
        assert.equal(video.user_rating, 0);

        const p2 = c.togglePickStar();      // 按回來
        mock.calls[1].resolve(okResp());
        await p2;
        assert.equal(video.user_rating, 1, '淨變化為零');

        c.closeLightbox();
        assert.equal(c.applyFilterAndSortCalls, 0, '牆面本來就一致，不必重篩');
    } finally {
        mock.restore();
    }
});

test('closeLightbox：無論如何都會把 lightboxOpen 收成 false（predicate 換掉旗標後其餘行為不變）', () => {
    const c = makeComponent({ pills: [], lightboxOpen: true });
    setFilteredVideos([]);
    c.closeLightbox();
    assert.equal(c.lightboxOpen, false);
    assert.equal(c.applyFilterAndSortCalls, 0);
});

test('searchFromMetadata：不呼叫 applyFilterAndSort（這條路徑本來就會經 addPill 重篩一次）', () => {
    const video = { path: PATH_A, user_rating: 0 };
    const c = makeComponent({
        lightboxOpen: true,
        pills: [{ dim: 'pick', value: '1' }],
    });
    setFilteredVideos([video]);
    c.searchFromMetadata('Moodyz', 'maker');
    assert.equal(c.applyFilterAndSortCalls, 0, '述詞式不需要事先清任何東西，也不可再跑一次');
    assert.deepEqual(c.addPillCalls, [{ dim: 'maker', value: 'Moodyz' }]);
});

// ── 三層失敗判定 ────────────────────────────────────────────────────

test('三層失敗：HTTP 200 + success:true + results[0].ok:false(not_found) 必須當失敗並回滾', async () => {
    const mock = mockFetchManual();
    try {
        const video = { path: PATH_A, user_rating: 0 };
        const c = makeComponent({ currentLightboxVideo: video });

        const p = c.togglePickStar();
        assert.equal(video.user_rating, 1);

        mock.calls[0].resolve({
            ok: true,
            status: 200,
            json: async () => ({
                success: true,
                results: [{ ok: false, reason: 'not_found' }],
            }),
        });
        await p;

        assert.equal(video.user_rating, 0, 'not_found 必須回滾');
        assert.equal(c.toasts.length, 1);
        assert.equal(c.toasts[0].msg, 'showcase.pick.save_failed');
    } finally {
        mock.restore();
    }
});

test('三層失敗：success:false（HTTP 仍 200）必須當失敗並回滾', async () => {
    const mock = mockFetchManual();
    try {
        const video = { path: PATH_A, user_rating: 1 };
        const c = makeComponent({ currentLightboxVideo: video });

        const p = c.togglePickStar();
        assert.equal(video.user_rating, 0);

        mock.calls[0].resolve({
            ok: true,
            status: 200,
            json: async () => ({ success: false }),
        });
        await p;

        assert.equal(video.user_rating, 1, 'success:false 必須回滾到 oldValue');
        assert.equal(c.toasts.length, 1);
    } finally {
        mock.restore();
    }
});

test('成功路徑：success:true + results[0].ok:true → 不 toast、不回滾', async () => {
    const mock = mockFetchManual();
    try {
        const video = { path: PATH_A, user_rating: 0 };
        const c = makeComponent({ currentLightboxVideo: video });

        const p = c.togglePickStar();
        mock.calls[0].resolve(okResp([{ ok: true }]));
        await p;

        assert.equal(video.user_rating, 1);
        assert.equal(c.toasts.length, 0);
        assert.equal(c._pickInFlight[PATH_A], undefined);
    } finally {
        mock.restore();
    }
});

test('初始 state：_pickInFlight 已宣告，舊版旗標機制已完全移除', () => {
    const s = stateLightbox();
    assert.deepEqual(s._pickInFlight, {});
    // 舊版的 dirty 旗標欄位不可再以任何形式殘留——刻意拼接字面值，讓本檔自己也不留下
    // 那個舊識別字的完整字面字串（不保留任何形式的「向後相容」殘跡）。
    var oldFlagName = 'pickFilter' + 'Dirty';
    assert.equal(oldFlagName in s, false, '舊版的 dirty 旗標不可再以任何形式殘留');
    assert.equal(typeof s._pickFilterStale, 'function');
});

// ── 飛行中關燈箱／並發（取代舊版那兩個旗標造成的 bug，見檔頭）───
// 這兩支是舊機制壞掉的地方：舊版用旗標代理「牆面過期了嗎」，在下面兩種時序下都會
// 與真實狀態脫鉤。新機制沒有旗標可以競爭，每次都直接觀察 _filteredVideos。

test('scenario 3：飛行中關燈箱＋請求失敗 → 關燈箱當下讀到的是還沒確認的樂觀值，事後落地才真正重篩一次', async () => {
    const mock = mockFetchManual();
    try {
        // video 本來未精選，但正被燈箱顯示（§4.13：開著時不因篩選被抽走）。
        const video = { path: PATH_A, user_rating: 0 };
        const c = makeComponent({
            currentLightboxVideo: video,
            pills: [{ dim: 'pick', value: '1' }],
            lightboxOpen: true,
        });
        setFilteredVideos([video]);

        const p = c.togglePickStar();          // 按下精選：樂觀值 0 → 1
        assert.equal(video.user_rating, 1);

        c.closeLightbox();                     // 飛行中就關燈箱（在 fetch resolve 之前）
        assert.equal(c.applyFilterAndSortCalls, 0,
            '關燈箱當下 _filteredVideos 只看得到樂觀值 1，看起來一致，不需要重篩——這正是「用還沒確認成功的樂觀值」判斷');

        mock.calls[0].reject(new Error('network down'));   // 請求之後才失敗
        await p;

        assert.equal(video.user_rating, 0, '樂觀更新必須回滾');
        assert.equal(c.toasts.length, 1);
        assert.equal(c.applyFilterAndSortCalls, 1,
            '請求落地時燈箱已經關了，述詞重新讀到真實資料（回滾後的 0）才發現過期，補一次重篩——把過早那次的錯誤結果修正回來');
    } finally {
        mock.restore();
    }
});

test('scenario 4：兩個不同 path 同時在飛，A 失敗 B 成功 → 兩者都落地後，關燈箱的重篩會讓牆面與真實資料一致（B 的改動不會被漏掉）', async () => {
    const mock = mockFetchManual();
    try {
        const videoA = { path: PATH_A, user_rating: 1 };
        const videoB = { path: PATH_B, user_rating: 1 };
        const c = makeComponent({
            currentLightboxVideo: videoA,
            pills: [{ dim: 'pick', value: '1' }],
            lightboxOpen: true,   // 兩個 path 的請求都在燈箱「還開著」時落地——刻意排在關燈箱之前，
                                  // 不靠請求落地當下的重篩，單獨驗證「舊機制的旗標算術」這個病灶本身
                                  // 已被拿掉：closeLightbox 不看任何歷史旗標，只看當下真實資料。
        });
        setFilteredVideos([videoA, videoB]);

        const pA = c.togglePickStar();         // A 開始飛（取消精選）
        assert.equal(videoA.user_rating, 0);

        c.currentLightboxVideo = videoB;
        const pB = c.togglePickStar();         // B 在 A 回來前開始飛（取消精選）
        assert.equal(videoB.user_rating, 0);

        // B 先落地：成功，不回滾。此時燈箱仍開著，不當場重篩（§4.13）。
        mock.calls[1].resolve(okResp());
        await pB;
        assert.equal(videoB.user_rating, 0);
        assert.equal(c.applyFilterAndSortCalls, 0, '燈箱還開著，B 落地也不當場重篩');

        // A 後落地：失敗，回滾。燈箱仍開著，同樣不當場重篩。
        mock.calls[0].reject(new Error('network down'));
        await pA;
        assert.equal(videoA.user_rating, 1, 'A 失敗必須回滾（等同沒變化）');
        assert.equal(c.applyFilterAndSortCalls, 0, '燈箱還開著，A 落地也不當場重篩');

        // 兩者都落地後才關燈箱：真實資料＝A 沒變（仍精選）、B 真的取消了。
        c.closeLightbox();
        assert.equal(c.applyFilterAndSortCalls, 1,
            '關燈箱時直接讀真實資料（B 已是 0），不看任何歷史旗標，B 的改動不會被漏掉重篩');
    } finally {
        mock.restore();
    }
});

// ── 123-T4：取消已精選片 ＋ 飛行中關燈箱（自生洞修正，見 state-lightbox.js
// _pickHasInFlight() 註解）───────────────────────────────────────────────
// 壞掉的序列：V 已精選（rating 1）→ 取消（樂觀 → 0）→ 請求還沒回來就關燈箱 →
// closeLightbox 的述詞讀到「牆上有一片不是精選的」→ 判定過期 → 若真的重篩，V 會被
// applyFilterAndSort 移出 _filteredVideos → 請求之後回滾成 1 → 但 V 已經不在陣列裡，
// 述詞掃不到它 → 卡回不來。修法：請求還在飛時兩個呼叫點都不篩，等最後一個請求落地
// （成功或已回滾）資料成定局，再篩一次。

test('scenario 6：取消已精選 ＋ 飛行中關燈箱 ＋ 請求失敗 → 關燈箱當下不篩，回滾後也不必篩（本來就一致）', async () => {
    const mock = mockFetchManual();
    try {
        const video = { path: PATH_A, user_rating: 1 };
        const otherPicked = { path: PATH_B, user_rating: 1 };
        const c = makeComponent({
            currentLightboxVideo: video,
            pills: [{ dim: 'pick', value: '1' }],
            lightboxOpen: true,
        });
        setFilteredVideos([video, otherPicked]);

        const p = c.togglePickStar();          // 取消精選：樂觀值 1 → 0
        assert.equal(video.user_rating, 0);

        c.closeLightbox();                     // 請求還沒回來就關燈箱
        assert.equal(c.applyFilterAndSortCalls, 0,
            '有精選請求在飛，即使述詞讀到「過期」也不能重篩——資料還沒定局');

        mock.calls[0].reject(new Error('network down'));   // 請求之後才失敗
        await p;

        assert.equal(video.user_rating, 1, '樂觀更新必須回滾');
        assert.equal(c.toasts.length, 1);
        assert.equal(c.applyFilterAndSortCalls, 0,
            '請求落地時已解鎖、燈箱已關、資料已回滾——述詞看到的是真相：牆上兩片都仍是精選，本來就一致，不必重篩');
    } finally {
        mock.restore();
    }
});

test('scenario 7：取消已精選 ＋ 飛行中關燈箱 ＋ 請求成功 → 關燈箱當下不篩，請求落地後剛好篩一次（V 確實該從精選牆消失）', async () => {
    const mock = mockFetchManual();
    try {
        const video = { path: PATH_A, user_rating: 1 };
        const otherPicked = { path: PATH_B, user_rating: 1 };
        const c = makeComponent({
            currentLightboxVideo: video,
            pills: [{ dim: 'pick', value: '1' }],
            lightboxOpen: true,
        });
        setFilteredVideos([video, otherPicked]);

        const p = c.togglePickStar();          // 取消精選：樂觀值 1 → 0
        assert.equal(video.user_rating, 0);

        c.closeLightbox();                     // 請求還沒回來就關燈箱
        assert.equal(c.applyFilterAndSortCalls, 0, '有精選請求在飛，關燈箱當下不篩');

        mock.calls[0].resolve(okResp());       // 請求之後才成功落地
        await p;

        assert.equal(video.user_rating, 0, '成功：樂觀值已是最終狀態');
        assert.equal(c.applyFilterAndSortCalls, 1,
            '請求落地時已解鎖、燈箱已關——述詞讀到 video 真的不再精選，補一次重篩，V 從精選牆消失');
    } finally {
        mock.restore();
    }
});

test('請求 body：file_path + picked 布林（冪等設值，非 toggle）', async () => {
    const mock = mockFetchManual();
    try {
        const video = { path: PATH_A, user_rating: 0 };
        const c = makeComponent({ currentLightboxVideo: video });
        const p = c.togglePickStar();
        assert.equal(mock.calls[0].url, '/api/user-rating');
        assert.equal(mock.calls[0].method, 'POST');
        assert.deepEqual(mock.calls[0].body, { file_path: PATH_A, picked: true });
        mock.calls[0].resolve(okResp());
        await p;
    } finally {
        mock.restore();
    }
});

// ── 123-T4：回滾動畫的 stale 檢查（CDP 實測重現後修正，見 state-lightbox.js
// togglePickStar() catch 區塊的 `if (this.currentLightboxVideo === video)` 註解）─────
// 燈箱裡的星是常駐 DOM 節點，不是每片各一顆。回滾發生在 await 之後：若飛行中已經滾到
// 別片，document.querySelector('.pick-star-fill') 抓到的是「現在顯示那片」的星，
// 沒有 stale 檢查就會把「已離場那片的回滾動畫」畫到「現在這片」的星上。

test('T4：飛行中換片後回滾 → 資料仍打在 captured 的 A 身上，但不得播動畫（stale 檢查擋下）', async () => {
    const mock = mockFetchManual();
    const anim = mockAnimationsSpy();
    try {
        const videoA = { path: PATH_A, user_rating: 1, number: 'ABC-123' };
        const videoB = { path: PATH_B, user_rating: 0, number: 'DEF-456' };
        const c = makeComponent({ currentLightboxVideo: videoA });

        const p = c.togglePickStar();
        assert.equal(videoA.user_rating, 0, '樂觀更新：取消精選');
        assert.equal(anim.calls.length, 1, '樂觀更新階段照常播一次動畫');

        // 飛行中滾到下一片（B 未精選，且 B 從未呼叫過 togglePickStar）
        c.currentLightboxVideo = videoB;

        mock.calls[0].reject(new Error('network down'));
        await p;

        assert.equal(videoA.user_rating, 1, '回滾必須打在 captured 的 A 身上（資料層與動畫層分開驗證）');
        assert.equal(videoB.user_rating, 0, 'B 完全不該被碰');
        assert.equal(anim.calls.length, 1,
            '換片後已經停在 B，回滾動畫若播出來就會把 A 的回滾畫到 B 的星上——stale 檢查必須擋下這次呼叫');
    } finally {
        mock.restore();
        anim.restore();
    }
});

test('T4：沒換片時回滾 → 動畫照常播一次，方向是 newValue→oldValue（防止過度攔截）', async () => {
    const mock = mockFetchManual();
    const anim = mockAnimationsSpy();
    try {
        const video = { path: PATH_A, user_rating: 1, number: 'ABC-123' };
        const c = makeComponent({ currentLightboxVideo: video });

        const p = c.togglePickStar();
        assert.equal(video.user_rating, 0, '樂觀更新：取消精選');
        assert.equal(anim.calls.length, 1, '樂觀更新階段一次');

        mock.calls[0].reject(new Error('network down'));
        await p;

        assert.equal(video.user_rating, 1, '回滾');
        assert.equal(anim.calls.length, 2, '沒換片，stale 檢查不該擋下這次——回滾動畫照常播');
        assert.deepEqual(
            { fromPicked: anim.calls[1].fromPicked, toPicked: anim.calls[1].toPicked },
            { fromPicked: false, toPicked: true },
            'catch 區塊呼叫方向是 (newValue>0, oldValue>0)：newValue=0(false) → oldValue=1(true)，從樂觀值畫回舊值'
        );
    } finally {
        mock.restore();
        anim.restore();
    }
});

test('T4：樂觀更新階段呼叫一次 playPickFill(oldValue>0, newValue>0)（$nextTick 觸發鏈沒斷）', async () => {
    const mock = mockFetchManual();
    const anim = mockAnimationsSpy();
    try {
        const video = { path: PATH_A, user_rating: 0 };
        const c = makeComponent({ currentLightboxVideo: video });

        const p = c.togglePickStar();
        assert.equal(video.user_rating, 1, '樂觀更新：按下精選');
        assert.equal(anim.calls.length, 1, '按下當下應有一次動畫呼叫');
        assert.deepEqual(
            { fromPicked: anim.calls[0].fromPicked, toPicked: anim.calls[0].toPicked },
            { fromPicked: false, toPicked: true },
            '樂觀階段呼叫方向是 (oldValue>0, newValue>0)：oldValue=0(false) → newValue=1(true)'
        );

        mock.calls[0].resolve(okResp());
        await p;
        assert.equal(anim.calls.length, 1, '成功路徑不再補播第二次');
    } finally {
        mock.restore();
        anim.restore();
    }
});
