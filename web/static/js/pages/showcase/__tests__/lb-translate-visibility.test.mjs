// TASK-172-T5：翻譯圖示顯示真值表（spec AC1／AC2）與開關 getter。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;

register(new URL('../../search/__tests__/alias-loader.mjs', import.meta.url), import.meta.url);

const { stateLightboxTranslate } = await import('../state-lightbox-translate.js');
const { mergeState } = await import('@/shared/merge-state.js');

function make(video) {
    return mergeState(stateLightboxTranslate(), { currentLightboxVideo: video });
}

function withSwitch(value, fn) {
    const had = Object.prototype.hasOwnProperty.call(globalThis, '__SHOWCASE_TRANSLATE__');
    const old = globalThis.__SHOWCASE_TRANSLATE__;
    if (value === undefined) delete globalThis.__SHOWCASE_TRANSLATE__;
    else globalThis.__SHOWCASE_TRANSLATE__ = value;
    try { fn(); } finally {
        if (had) globalThis.__SHOWCASE_TRANSLATE__ = old; else delete globalThis.__SHOWCASE_TRANSLATE__;
    }
}

const ALL = [
    { needs_translate: true, original_title: '' },
    { needs_translate: true, original_title: '原文' },
    { needs_translate: false, original_title: '原文' },
    { needs_translate: false, original_title: '' },
    {},
];

test('翻譯關閉時兩個圖示都不顯示', () => {
    for (const sw of [undefined, { enabled: false }, {}, { enabled: 'true' }]) {
        withSwitch(sw, () => {
            for (const v of ALL) {
                const c = make(v);
                assert.equal(c.lbTranslateEnabled, false);
                assert.equal(c.lbTrShowOnTitle(), false, JSON.stringify([sw, v]));
                assert.equal(c.lbTrShowOnOtitle(), false, JSON.stringify([sw, v]));
            }
        });
    }
});

test('翻譯開啟：假名無原文只標題行、有原文只原文行、中文無原文皆無', () => {
    withSwitch({ enabled: true }, () => {
        let c = make({ needs_translate: true, original_title: '' });
        assert.equal(c.lbTranslateEnabled, true);
        assert.equal(c.lbTrShowOnTitle(), true);
        assert.equal(c.lbTrShowOnOtitle(), false);
        c = make({ needs_translate: false, original_title: '原文' });
        assert.equal(c.lbTrShowOnTitle(), false);
        assert.equal(c.lbTrShowOnOtitle(), true);
        c = make({ needs_translate: false, original_title: '' });
        assert.equal(c.lbTrShowOnTitle(), false);
        assert.equal(c.lbTrShowOnOtitle(), false);
        c = make(null);
        assert.equal(c.lbTrShowOnTitle(), false);
        assert.equal(c.lbTrShowOnOtitle(), false);
    });
});

test('開關 getter 隨 window 值即時變化（不被 mergeState 凍結）', () => {
    const c = make({ needs_translate: true });
    withSwitch({ enabled: true }, () => assert.equal(c.lbTranslateEnabled, true));
    withSwitch({ enabled: false }, () => assert.equal(c.lbTranslateEnabled, false));
});
