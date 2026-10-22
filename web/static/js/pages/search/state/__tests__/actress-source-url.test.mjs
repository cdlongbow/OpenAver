import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

register(new URL('../../__tests__/alias-loader.mjs', import.meta.url), import.meta.url);

const { searchStateBase } = await import('../base.js');


test('actressSourceUrl avbase branch returns avbase talent URL', () => {
    const state = searchStateBase();
    state.actressProfile = { primary_text_source: 'avbase', name: '二階堂麗' };
    assert.equal(
        state._actressSourceUrl(),
        'https://www.avbase.net/talents/%E4%BA%8C%E9%9A%8E%E5%A0%82%E9%BA%97',
    );
});

