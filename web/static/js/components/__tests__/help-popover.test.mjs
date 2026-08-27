// TASK-131b-T4: Alpine.data('helpPopover') open/toggle/close + 註冊

import { test } from 'node:test';
import assert from 'node:assert/strict';

let alpineInitCb;
globalThis.window = globalThis;
globalThis.document = { addEventListener: (_name, fn) => { alpineInitCb = fn; } };

const registered = [];
globalThis.Alpine = { data: (name, fn) => registered.push([name, fn]) };

const { helpPopover } = await import('../help-popover.js');

test('helpPopover().open 初值為 false', () => {
    const popover = helpPopover();
    assert.equal(popover.open, false);
});

test('toggle() 一次 → open 變 true', () => {
    const popover = helpPopover();
    popover.toggle();
    assert.equal(popover.open, true);
});

test('toggle() 兩次 → 再按一次要關', () => {
    const popover = helpPopover();
    popover.toggle();
    popover.toggle();
    assert.equal(popover.open, false);
});

test('close() 後 open 為 false（從 open === true 開始）', () => {
    const popover = helpPopover();
    popover.toggle();
    assert.equal(popover.open, true);
    popover.close();
    assert.equal(popover.open, false);
});

test('模組在 alpine:init 時把自己註冊成 Alpine.data(\'helpPopover\', …)', () => {
    assert.equal(typeof alpineInitCb, 'function');
    alpineInitCb();
    assert.equal(registered.length, 1);
    assert.equal(registered[0][0], 'helpPopover');
    assert.equal(typeof registered[0][1], 'function');
    const instance = registered[0][1]();
    assert.equal(instance.open, false);
    assert.equal(typeof instance.toggle, 'function');
    assert.equal(typeof instance.close, 'function');
});
