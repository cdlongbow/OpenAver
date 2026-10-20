// TASK-173-T11：片商膠囊分片 searchStateMakerLatest（真 searchPage()＋假 fetch）
//
// 守住的行為：
//   - 載入成功 ⇒ makerCapsules 為預期排名；回應 hidden_keys 內的片商不出現
//   - javbus 關閉／success:false／fetch 例外／非 JSON ⇒ makerCapsules===[] 且不 reject
//   - hideMakerCapsule 後該顆消失、下一名補上、陣列為新參照
//   - startMakerSearch 以 ('', {maker: capsule}) 呼叫 doSearch
//   - clearAll 不影響膠囊列、不重抓；分片無 init()

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {} };
window.t = (key) => key;

register(new URL('./alias-loader.mjs', import.meta.url), import.meta.url);

const { searchStateMakerLatest } = await import('../state/maker-latest.js');
const { searchPage } = await import('../main.js');

const MAKERS = ['A', 'B', 'C', 'D', 'E', 'F'].map((m, i) => ({ maker: m, total: 50, recent: 20 - i }));

function fakeFetch(body, { throws = false, badJson = false } = {}) {
    const calls = [];
    globalThis.fetch = async (url) => {
        calls.push(url);
        if (throws) throw new Error('network down');
        return { json: async () => { if (badJson) throw new SyntaxError('not json'); return body; } };
    };
    return calls;
}

const okBody = (extra = {}) => ({ success: true, javbus_enabled: true, makers: MAKERS, hidden_keys: [], ...extra });
const labels = (page) => page.makerCapsules.map((c) => c.label);

test('slice shape: 無 init()、searchPage().init 仍存在、初值為空', () => {
    assert.equal('init' in searchStateMakerLatest(), false);
    assert.equal(typeof searchPage().init, 'function');
    assert.deepEqual(searchPage().makerCapsules, []);
});

test('load: 成功載入 ⇒ makerCapsules 為預期排名（至多 5 顆）', async () => {
    fakeFetch(okBody());
    const page = searchPage();
    await page.loadMakerCapsules();
    assert.deepEqual(labels(page), ['A', 'B', 'C', 'D', 'E']);
});

test('javbus-disabled-empty: javbus_enabled:false（makers 非空）⇒ []', async () => {
    fakeFetch(okBody({ javbus_enabled: false }));
    const page = searchPage();
    await page.loadMakerCapsules();
    assert.deepEqual(page.makerCapsules, []);
});

test('success-false-empty: success:false（makers 非空）⇒ []', async () => {
    fakeFetch(okBody({ success: false }));
    const page = searchPage();
    await page.loadMakerCapsules();
    assert.deepEqual(page.makerCapsules, []);
});

test('failure-collapses-to-empty: fetch 例外／非 JSON ⇒ [] 且不 reject', async () => {
    const origError = console.error;
    console.error = () => {};
    try {
        for (const opts of [{ throws: true }, { badJson: true }]) {
            fakeFetch(okBody(), opts);
            const page = searchPage();
            await page.loadMakerCapsules();
            assert.deepEqual(page.makerCapsules, []);
        }
    } finally {
        console.error = origError;
    }
});

test('load-applies-hidden-keys: 回應 hidden_keys 內的片商不出現，下一名補上', async () => {
    fakeFetch(okBody({ hidden_keys: ['b'] }));
    const page = searchPage();
    await page.loadMakerCapsules();
    assert.deepEqual(labels(page), ['A', 'C', 'D', 'E', 'F']);
});

test('hide-removes-and-backfills: hideMakerCapsule 後該顆消失、第 6 名補上', async () => {
    fakeFetch(okBody());
    const page = searchPage();
    await page.loadMakerCapsules();
    page.hideMakerCapsule('b');
    assert.ok(page._makerHiddenKeys.includes('b'));
    assert.deepEqual(labels(page), ['A', 'C', 'D', 'E', 'F']);
});

test('hide-rebuilds-display: hideMakerCapsule 後 makerCapsules 是新陣列', async () => {
    fakeFetch(okBody());
    const page = searchPage();
    await page.loadMakerCapsules();
    const before = page.makerCapsules;
    page.hideMakerCapsule('a');
    assert.notStrictEqual(page.makerCapsules, before);
    assert.equal(page.makerCapsules.some((c) => c.key === 'a'), false);
});

test('start-passes-maker-opts: startMakerSearch ⇒ doSearch("", { maker: capsule })', () => {
    const page = searchPage();
    const calls = [];
    page.doSearch = (...args) => { calls.push(args); };
    const capsule = { key: 's1', label: 'S1', spellings: ['S1'], count: 7 };
    page.startMakerSearch(capsule);
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0], ['', { maker: capsule }]);
});

test('clearAll-keeps-capsules: clearAll 前後膠囊內容相同、不重抓', async () => {
    const calls = fakeFetch(okBody());
    const page = searchPage();
    await page.loadMakerCapsules();
    const before = JSON.stringify(page.makerCapsules);
    const n = calls.length;
    globalThis.sessionStorage = { setItem() {}, getItem: () => null, removeItem() {} };
    page.$nextTick = (fn) => fn && fn();
    page.clearAll();
    assert.equal(JSON.stringify(page.makerCapsules), before);
    assert.equal(calls.length, n);
});
