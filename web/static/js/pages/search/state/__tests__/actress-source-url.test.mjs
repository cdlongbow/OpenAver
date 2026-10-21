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

test('actressSourceUrl avbase branch returns avbase talent URL', () => {
    const state = searchStateBase();
    state.actressProfile = { primary_text_source: 'avbase', name: '二階堂麗' };
    assert.equal(
        state._actressSourceUrl(),
        'https://www.avbase.net/talents/%E4%BA%8C%E9%9A%8E%E5%A0%82%E9%BA%97',
    );
});

test('actressSourceUrl returns null for graphis, missing source, missing name', () => {
    const profiles = [
        { primary_text_source: 'graphis', name: 'X' },
        { name: 'X' },
        { primary_text_source: 'avbase' },
    ];
    for (const profile of profiles) {
        const state = searchStateBase();
        state.actressProfile = profile;
        assert.equal(state._actressSourceUrl(), null, JSON.stringify(profile));
    }
});
