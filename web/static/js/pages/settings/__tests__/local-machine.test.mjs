// 168c-T4: local-machine.js 純函式 (node:test, no DOM).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const STATIC_JS_ROOT = pathToFileURL(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../') + '/',
).href;
register(`data:text/javascript,${encodeURIComponent(`
export async function resolve(specifier, context, nextResolve) {
    if (specifier.startsWith('@/')) return nextResolve(${JSON.stringify(STATIC_JS_ROOT)} + specifier.slice(2), context);
    return nextResolve(specifier, context);
}`)}`, import.meta.url);

const {
    applyServerLocalFields, buildLocalPatch, localDiff,
     resolveLocalMachine,
} = await import('../local-machine.js');

const FORM = { viewerPlayer: '  FORM-PLAYER  ', closeAction: 'exit', defaultPage: 'search' };
function makeConfig() {
    return { showcase: { player: 'SERVER-PLAYER', other: 1 }, general: { close_action: 'ask', theme: 'dark' } };
}

test('test_apply_server_local_fields_ready_keeps_server_values', () => {
    const out = applyServerLocalFields(makeConfig(), FORM, 'ready');
    assert.equal(out.showcase.player, 'SERVER-PLAYER');
    assert.equal(out.general.close_action, 'ask');
    assert.equal(out.showcase.other, 1);
});


test('apply_server_local_fields: off and legacy write form values (player trimmed)', () => {
    for (const state of ['off', 'legacy']) {
        const out = applyServerLocalFields(makeConfig(), FORM, state);
        assert.equal(out.showcase.player, 'FORM-PLAYER', state);
        assert.equal(out.general.close_action, 'exit', state);
        assert.equal(out.showcase.other, 1, state);
        assert.equal(out.general.theme, 'dark', state);
    }
});

test('buildLocalPatch: trimmed player and close_action only', () => {
    assert.deepEqual(buildLocalPatch(FORM), { player: 'FORM-PLAYER', close_action: 'exit' });
});

test('localDiff: per-field value compare, player trimmed', () => {
    const saved = { viewerPlayer: 'P', closeAction: 'ask' };
    assert.deepEqual(localDiff({ viewerPlayer: '  P ', closeAction: 'ask' }, saved), []);
    assert.deepEqual(localDiff({ viewerPlayer: 'Q', closeAction: 'ask' }, saved), ['viewerPlayer']);
    assert.deepEqual(localDiff({ viewerPlayer: 'P', closeAction: 'tray' }, saved), ['closeAction']);
    assert.deepEqual(localDiff({ viewerPlayer: 'Q', closeAction: 'tray' }, saved), ['viewerPlayer', 'closeAction']);
});


function deps({ ready = true, api = {}, getReply = { ok: true, player: 'L', close_action: 'tray' } } = {}) {
    const calls = [];
    return {
        calls,
        whenBridgeReady: async () => { calls.push('ready'); return ready; },
        callBridge: async (name) => { calls.push(name); return getReply; },
        getBridge: () => { calls.push('getBridge'); return api; },
    };
}
const FULL = { local_settings_get() {}, local_settings_save() {} };

test('resolveLocalMachine: four states and zero deps calls when not client', async () => {
    for (const mode of ['', 'local', undefined]) {
        const d = deps({ api: FULL });
        assert.deepEqual(await resolveLocalMachine(mode, d), { state: 'off' });
        assert.deepEqual(d.calls, []);
    }
    let d = deps({ api: { local_settings_get() {} } });
    assert.equal((await resolveLocalMachine('client', d)).state, 'legacy');
    d = deps({ api: null });
    assert.equal((await resolveLocalMachine('client', d)).state, 'legacy');
    d = deps({ ready: false, api: null });
    assert.equal((await resolveLocalMachine('client', d)).state, 'legacy');
    d = deps({ ready: false, api: FULL });
    assert.equal((await resolveLocalMachine('client', d)).state, 'unavailable');
    d = deps({ api: FULL, getReply: { ok: false, reason: 'untrusted' } });
    assert.equal((await resolveLocalMachine('client', d)).state, 'unavailable');
    d = deps({ api: FULL, getReply: { ok: false } });
    assert.equal((await resolveLocalMachine('client', d)).state, 'unavailable');
    d = deps({ api: FULL });
    const r = await resolveLocalMachine('client', d);
    assert.equal(r.state, 'ready');
    assert.equal(r.local.player, 'L');
    assert.equal(r.local.close_action, 'tray');
});
