// TASK-120a-T1: .lb-full 載入失敗提示 pill
// isStaleLbFullError 判定＋_handleLbFullError 生命週期（裁決 4 七條）。
// harness 照 pill-entry.test.mjs：工廠 + Object.assign 合併後直接呼叫方法。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;

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

const { stateLightbox, isStaleLbFullError } = await import('../state-lightbox.js');

const FULL_SRC = '/api/gallery/image?path=%2Fdata%2Fcover.jpg';
const OTHER_SRC = '/api/gallery/image?path=%2Fdata%2Fother.jpg';

function makeImg(src) {
    return {
        getAttribute(name) {
            return name === 'src' ? src : null;
        },
    };
}

function makeComponent(overrides) {
    const img = makeImg(FULL_SRC);
    const c = Object.assign({}, stateLightbox(), {
        currentLightboxVideo: { cover_full_url: FULL_SRC, has_cover: true },
        $refs: { lightboxCoverFull: img },
        $nextTick: (fn) => fn(),
        handleCoverError() {
            throw new Error('handleCoverError must not be called');
        },
    }, overrides);
    return c;
}

function fireError(c, { target, src } = {}) {
    const img = target || c.$refs.lightboxCoverFull;
    if (src !== undefined) {
        img.getAttribute = (name) => (name === 'src' ? src : null);
    }
    c._handleLbFullError({ target: img });
}

// 1. isStaleLbFullError 三種（沿用 isStaleCoverError 短路語意）
test('isStaleLbFullError: src 相符 → false', () => {
    assert.equal(isStaleLbFullError(FULL_SRC, FULL_SRC), false);
});

test('isStaleLbFullError: src 不符 → true', () => {
    assert.equal(isStaleLbFullError(OTHER_SRC, FULL_SRC), true);
});

test('isStaleLbFullError: expectedSrc 為空 → false', () => {
    assert.equal(isStaleLbFullError(FULL_SRC, ''), false);
    assert.equal(isStaleLbFullError(FULL_SRC, undefined), false);
    assert.equal(isStaleLbFullError('', FULL_SRC), false);
});

// 2. AC-A6：空 cover_full_url 短路，旗標仍 false
test('AC-A6: cover_full_url 為空字串 → _handleLbFullError 後旗標仍 false', () => {
    const c = makeComponent({
        currentLightboxVideo: { cover_full_url: '', has_cover: false },
    });
    fireError(c, { src: '' });
    assert.equal(c._lbFullErrorPill, false);
});

// 3. AC-A4：遲到 error 的 src 已不是當下 cover_full_url
test('AC-A4: getAttribute(src) 是舊值、current cover_full_url 已是新值 → 旗標仍 false', () => {
    const c = makeComponent({
        currentLightboxVideo: { cover_full_url: FULL_SRC, has_cover: true },
    });
    fireError(c, { src: OTHER_SRC });
    assert.equal(c._lbFullErrorPill, false);
});

// 4. AC-A5：不呼叫 handleCoverError、不寫 has_cover
test('AC-A5: _handleLbFullError 不呼叫 handleCoverError、不寫 has_cover', () => {
    let handleCoverErrorCalls = 0;
    const video = { cover_full_url: FULL_SRC, has_cover: true };
    const c = makeComponent({
        currentLightboxVideo: video,
        handleCoverError() {
            handleCoverErrorCalls += 1;
        },
    });
    fireError(c, { src: FULL_SRC });
    assert.equal(handleCoverErrorCalls, 0);
    assert.equal(video.has_cover, true);
    assert.equal(c.currentLightboxVideo.has_cover, true);
});

// 5. Happy path：src 相符且非空 → 旗標 true
test('happy path: src 相符且非空 → _lbFullErrorPill 為 true', () => {
    const c = makeComponent();
    fireError(c, { src: FULL_SRC });
    assert.equal(c._lbFullErrorPill, true);
});

// 6. $refs 防呆
test('$refs 防呆: event.target !== lightboxCoverFull → 旗標仍 false', () => {
    const c = makeComponent();
    const stranger = makeImg(FULL_SRC);
    fireError(c, { target: stranger, src: FULL_SRC });
    assert.equal(c._lbFullErrorPill, false);
});

// 7. 生命週期：_refreshLbFullBlurUp 是唯一重置點
test('生命週期: _refreshLbFullBlurUp() 後旗標回 false', () => {
    const c = makeComponent();
    fireError(c, { src: FULL_SRC });
    assert.equal(c._lbFullErrorPill, true);
    c._refreshLbFullBlurUp();
    assert.equal(c._lbFullErrorPill, false);
});
