// PR#115 Codex P2 finding: handleKeydown() 原僅排除 searchQuery input（`document.activeElement
// === this.$refs.searchQuery`），未涵蓋標題/中文/演員編輯 textarea·input、date input、rescrape
// 番號 input。ArrowLeft/ArrowRight 在這些欄位聚焦時本應移動文字游標，卻冒泡觸發
// navigate(-1)/navigate(1) 換候選/檔，連帶 _resetPendingEdits() 清掉使用者未確認的編輯。
//
// 修法：把 searchQuery-specific 判斷改成通用「焦點在可編輯欄位」guard（INPUT / TEXTAREA /
// SELECT / isContentEditable），單一 choke point 涵蓋所有現有與未來的編輯欄位。
//
// navigation.js 匯入瀏覽器 importmap 別名 `@/shared/...`，需掛 alias-loader.mjs resolve hook
// 才能動態 import（同 build-organize-metadata.test.mjs / reset-pending-edits.test.mjs 慣例）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;

register(new URL('./alias-loader.mjs', import.meta.url), import.meta.url);
const { searchStateNavigation } = await import('../state/navigation.js');

function makeFakeThis(activeElement) {
    globalThis.document = { activeElement };
    return {
        ...searchStateNavigation(),
        rescrapeOpen: false,
        sampleGalleryOpen: false,
        lightboxOpen: false,
        displayMode: 'detail',
        _navCalls: [],
        navigate(delta) {
            this._navCalls.push(delta);
        },
    };
}

test('handleKeydown: focus on INPUT + ArrowLeft → navigate NOT called (caret 移動留給欄位本身)', () => {
    const fakeThis = makeFakeThis({ tagName: 'INPUT' });

    searchStateNavigation().handleKeydown.call(fakeThis, { key: 'ArrowLeft', preventDefault() {} });

    assert.deepEqual(fakeThis._navCalls, [], 'INPUT 聚焦時 ArrowLeft 不應觸發 navigate（否則會清掉未確認編輯）');
});

test('handleKeydown: focus on TEXTAREA + ArrowRight → navigate NOT called（標題/中文/演員編輯欄位）', () => {
    const fakeThis = makeFakeThis({ tagName: 'TEXTAREA' });

    searchStateNavigation().handleKeydown.call(fakeThis, { key: 'ArrowRight', preventDefault() {} });

    assert.deepEqual(fakeThis._navCalls, [], 'TEXTAREA 聚焦時 ArrowRight 不應觸發 navigate');
});

test('handleKeydown: focus on non-editable DIV + ArrowLeft → navigate(-1) 正常觸發（guard 不過度攔截）', () => {
    const fakeThis = makeFakeThis({ tagName: 'DIV' });

    searchStateNavigation().handleKeydown.call(fakeThis, { key: 'ArrowLeft', preventDefault() {} });

    assert.deepEqual(fakeThis._navCalls, [-1], '非可編輯欄位聚焦時 detail 模式 ArrowLeft 應正常換候選');
});
