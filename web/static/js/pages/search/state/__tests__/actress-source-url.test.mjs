import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

register(new URL('../../__tests__/alias-loader.mjs', import.meta.url), import.meta.url);

const { searchStateBase } = await import('../base.js');

test('actressSourceUrl xcity branch returns xcity search URL', () => {
    const state = searchStateBase();
    state.actressProfile = { primary_text_source: 'xcity', name: '三上悠亜' };
    assert.equal(
        state._actressSourceUrl(),
        'https://xcity.jp/idol/?genre=%2Fidol%2F&q=%E4%B8%89%E4%B8%8A%E6%82%A0%E4%BA%9C&sg=idol',
    );
});
