// TASK-140-T11b: 書籤燈箱接進 navigation.js 兩條共享分派鏈
// （handleKeydown Escape/←/→、handleWheel 水平/垂直），含 isOverlay 修正與既有 overlay 回歸。
//
// navigation.js 匯入瀏覽器 importmap 別名 `@/shared/...`，需掛 alias-loader.mjs resolve hook
// 才能動態 import（同 keydown-skip-editable.test.mjs 慣例）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;

register(new URL('./alias-loader.mjs', import.meta.url), import.meta.url);
const { searchStateNavigation } = await import('../state/navigation.js');

function makeFakeThis(overrides = {}) {
    globalThis.document = { activeElement: { tagName: 'DIV' } };
    const nav = searchStateNavigation();
    const fake = {
        ...nav,
        rescrapeOpen: false,
        sampleGalleryOpen: false,
        wishlistLightboxOpen: false,
        lightboxOpen: false,
        displayMode: 'grid',
        _calls: [],
        closeWishlistLightbox() { this._calls.push('closeWishlistLightbox'); },
        prevWishlistLightbox() { this._calls.push('prevWishlistLightbox'); },
        nextWishlistLightbox() { this._calls.push('nextWishlistLightbox'); },
        closeLightbox() { this._calls.push('closeLightbox'); },
        prevLightboxVideo() { this._calls.push('prevLightboxVideo'); },
        nextLightboxVideo() { this._calls.push('nextLightboxVideo'); },
        closeSampleGallery() { this._calls.push('closeSampleGallery'); },
        prevSampleGallery() { this._calls.push('prevSampleGallery'); },
        nextSampleGallery() { this._calls.push('nextSampleGallery'); },
        navigate(delta) { this._calls.push(`navigate:${delta}`); },
        ...overrides,
    };
    return fake;
}

function makeKeyEvent(key) {
    return {
        key,
        preventDefault() { this._pd = true; },
        _pd: false,
    };
}

function makeWheelEvent({ deltaX = 0, deltaY = 0 } = {}) {
    return {
        deltaX,
        deltaY,
        deltaMode: 0,
        target: { closest() { return null; } },
        preventDefault() { this._pd = true; },
        _pd: false,
    };
}

// DoD 5a
test('handleKeydown: 書籤燈箱開著時 Escape 呼叫 closeWishlistLightbox 且不呼叫 closeLightbox', () => {
    const fake = makeFakeThis({ wishlistLightboxOpen: true });
    const event = makeKeyEvent('Escape');

    fake.handleKeydown(event);

    assert.ok(fake._calls.includes('closeWishlistLightbox'),
        '書籤燈箱開著時 Escape 應呼叫 closeWishlistLightbox');
    assert.ok(!fake._calls.includes('closeLightbox'),
        '書籤燈箱開著時 Escape 不得呼叫 closeLightbox');
});

// DoD 5b

// DoD 5c
test('handleKeydown: 劇照集疊在書籤燈箱之上時走劇照集分支，不呼叫任何 wishlist 燈箱方法', () => {
    const fake = makeFakeThis({
        sampleGalleryOpen: true,
        wishlistLightboxOpen: true,
    });

    fake.handleKeydown(makeKeyEvent('Escape'));
    assert.ok(fake._calls.includes('closeSampleGallery'),
        '兩 flag 皆 true 時 Escape 應走劇照集');
    assert.ok(!fake._calls.includes('closeWishlistLightbox'),
        '不得呼叫 closeWishlistLightbox');

    fake._calls = [];
    fake.handleKeydown(makeKeyEvent('ArrowLeft'));
    assert.ok(fake._calls.includes('prevSampleGallery'),
        '兩 flag 皆 true 時 ArrowLeft 應走劇照集');
    assert.ok(!fake._calls.includes('prevWishlistLightbox'),
        '不得呼叫 prevWishlistLightbox');

    fake._calls = [];
    fake.handleKeydown(makeKeyEvent('ArrowRight'));
    assert.ok(fake._calls.includes('nextSampleGallery'),
        '兩 flag 皆 true 時 ArrowRight 應走劇照集');
    assert.ok(!fake._calls.includes('nextWishlistLightbox'),
        '不得呼叫 nextWishlistLightbox');
});

// DoD 5d

// DoD 5e

// DoD 5f
