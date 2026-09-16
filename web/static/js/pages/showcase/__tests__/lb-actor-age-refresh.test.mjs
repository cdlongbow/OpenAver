// TASK-149b-T3 mutation 點①: _refreshLbActorAges() 對 this._lbActorAges 明確重新賦值
// （新物件參照，不是原地 mutate）——Alpine 的 proxy-only 依賴追蹤看不到原地 mutate，
// 換片後歲數會卡在上一部片（見 plan-149b §9 陷阱①、CD-149b-3）。
//
// 範本：pick-star-lightbox.test.mjs（importmap resolve hook + $nextTick 同步 stub 形狀）

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;

// closeLightbox / searchFromMetadata 等 stateLightbox() 方法會碰 document；給最小 stub
// （比照 pick-star-lightbox.test.mjs）。
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
const { _setActresses } = await import('@/showcase/state-base.js');

function makeComponent(overrides = {}) {
    return Object.assign({}, stateLightbox(), {
        $nextTick(fn) { if (typeof fn === 'function') fn(); },
        ...overrides,
    });
}

test('_refreshLbActorAges 對最愛女優、資料完整的片算出年齡並寫入 _lbActorAges', () => {
    _setActresses([{ name: '明里つむぎ', birth: '1990-06-15' }]);
    const c = makeComponent({
        currentLightboxVideo: { actresses: '明里つむぎ', release_date: '2020-06-15', duration: 60 },
    });
    c._refreshLbActorAges();
    assert.deepEqual(c._lbActorAges, { '明里つむぎ': 30 });
});

test('_refreshLbActorAges reassigns _lbActorAges to a new object reference each call', () => {
    _setActresses([{ name: 'A', birth: '1990-01-01' }]);
    const c = makeComponent({
        currentLightboxVideo: { actresses: 'A', release_date: '2020-01-01', duration: 60 },
    });
    c._refreshLbActorAges();
    const ref1 = c._lbActorAges;
    c._refreshLbActorAges();
    const ref2 = c._lbActorAges;
    assert.notEqual(ref1, ref2, '每次呼叫都必須產生新物件參照，Alpine 的 proxy set 攔截才抓得到變化');
    assert.deepEqual(ref2, { A: 30 });
});

test('_refreshLbActorAges 換片後（無最愛女優/算不出年齡）清空成 {}，不殘留上一部片的舊值', () => {
    _setActresses([{ name: 'A', birth: '1990-01-01' }]);
    const c = makeComponent({
        currentLightboxVideo: { actresses: 'A', release_date: '2020-01-01', duration: 60 },
    });
    c._refreshLbActorAges();
    assert.deepEqual(c._lbActorAges, { A: 30 });

    // 換到下一部片：沒有女優列
    c.currentLightboxVideo = { actresses: '', release_date: '2021-01-01', duration: 60 };
    c._refreshLbActorAges();
    assert.deepEqual(c._lbActorAges, {});
});
