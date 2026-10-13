// 168b-T6b: path-map table pure logic.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    connectActions, mergeRows, staleRows, rulesForSave, isRowsDirty, rowResultView, pathMapForApply,
} from '../connect-logic.js';

const SRC = [
    { path: '/volume1/av', kind: 'directory', readonly: false, sample: '/volume1/av/a.mp4' },
    { path: '/volume1/fav', kind: 'favorite', readonly: false, sample: null },
    { path: '/volume1/ro', kind: 'directory', readonly: true, sample: '/volume1/ro/x.mp4' },
];
const SAVED = [
    { server: '/volume1/av', local: '\\\\nas\\av' },
    { server: '/volume1/gone', local: 'Z:\\gone' },
];
const URL_A = 'http://good.test:8765';

function allRows() {
    return [...mergeRows(SRC, SAVED), ...staleRows(SRC, SAVED)];
}

test('test_merge_prefills_only_exact_server_match', () => {
    const rows = mergeRows(SRC, SAVED);
    assert.equal(rows.length, 3);
    assert.equal(rows[0].local, '\\\\nas\\av');
    assert.equal(rows[1].local, '');
    assert.equal(rows[0].kind, 'directory');
    assert.equal(rows[1].kind, 'favorite');
    assert.equal(rows[2].readonly, true);
    assert.equal(rows[0].sample, '/volume1/av/a.mp4');
    assert.equal(rows[0].state, null);
    assert.equal(rows[0].testing, false);
    assert.equal(rows[0].testGen, 0);
    assert.equal(rows[0].removed, false);
    assert.equal(rows[0].stale, false);
    const near = mergeRows(SRC, [
        { server: '/VOLUME1/av', local: 'A' },
        { server: '/volume1/fav/', local: 'B' },
    ]);
    assert.deepEqual(near.map((r) => r.local), ['', '', '']);
});

test('test_saved_rule_for_missing_source_is_kept_and_marked', () => {
    const rows = staleRows(SRC, SAVED);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].server, '/volume1/gone');
    assert.equal(rows[0].local, 'Z:\\gone');
    assert.equal(rows[0].stale, true);
    assert.equal(rows[0].kind, 'saved_only');
    assert.equal(rows[0].sample, null);
    assert.equal(rows[0].removed, false);
    assert.deepEqual(staleRows(SRC, []), []);
});

test('test_rules_for_save_excludes_empty_and_trims_in_order', () => {
    const rows = allRows();
    rows[1].local = '  /Volumes/fav  ';
    rows[2].local = '   ';
    assert.deepEqual(rulesForSave(rows), [
        { server: '/volume1/av', local: '\\\\nas\\av' },
        { server: '/volume1/fav', local: '/Volumes/fav' },
        { server: '/volume1/gone', local: 'Z:\\gone' },
    ]);
    for (const r of rows) r.local = '';
    assert.deepEqual(rulesForSave(rows), []);
});

test('test_removed_stale_rule_not_saved', () => {
    const rows = allRows();
    rows[3].removed = true;
    assert.deepEqual(rulesForSave(rows).map((r) => r.server), ['/volume1/av']);
});

test('test_rows_dirty_detects_local_edit', () => {
    const rows = allRows();
    const snap = JSON.stringify(rulesForSave(rows));
    assert.equal(isRowsDirty(rows, snap), false);
    rows[0].local = '\\\\nas\\other';
    assert.equal(isRowsDirty(rows, snap), true);
    rows[0].local = '\\\\nas\\av';
    assert.equal(isRowsDirty(rows, snap), false);
    rows[0].local = '';
    assert.equal(isRowsDirty(rows, snap), true);
    assert.equal(isRowsDirty(rows, JSON.stringify(rulesForSave(rows))), false);
});

test('test_row_result_maps_unavailable_states_to_fail', () => {
    assert.equal(rowResultView('ok'), 'ok');
    assert.equal(rowResultView('not_found'), 'fail');
    assert.equal(rowResultView('uncovered'), 'fail');
    assert.equal(rowResultView('timeout'), 'slow');
    assert.notEqual(rowResultView('timeout'), rowResultView('not_found'));
    assert.equal(rowResultView('no_sample'), 'note');
    assert.equal(rowResultView('empty'), 'none');
    assert.equal(rowResultView('weird'), 'none');
    assert.equal(rowResultView(null), 'none');
    assert.equal(rowResultView('toString'), 'none');
});

function loaded(over = {}) {
    const rows = allRows();
    return {
        sourcesState: 'ok', sourcesFor: URL_A, rows, rowsSnapshot: JSON.stringify(rulesForSave(rows)),
        probe: { url: URL_A }, ...over,
    };
}

test('test_apply_keeps_saved_map_when_sources_not_loaded', () => {
    assert.deepEqual(pathMapForApply(loaded()), rulesForSave(allRows()));
    assert.strictEqual(pathMapForApply(loaded({ sourcesState: 'error' })), null);
    assert.strictEqual(pathMapForApply(loaded({ sourcesFor: 'http://other.test' })), null);
    assert.strictEqual(pathMapForApply(loaded({ probe: null })), null);
    const empty = loaded();
    for (const r of empty.rows) r.local = '';
    assert.deepEqual(pathMapForApply(empty), []);
});

function actionState(over = {}) {
    return {
        ...loaded(),
        bridge: 'ready', busy: null, restarting: false, mode: 'client', phase: 'authed',
        urlText: URL_A, savedUrl: URL_A, probedText: URL_A, pin: '',
        probe: { ok: true, url: URL_A, auth_required: true, authed: true, compat: { status: 'ok' } },
        ...over,
    };
}

test('test_table_visible_follows_auth', () => {
    assert.equal(connectActions(actionState()).tableVisible, true);
    assert.equal(connectActions(actionState({
        phase: 'probed', probe: { ok: true, url: URL_A, auth_required: true, authed: false, compat: { status: 'ok' } },
    })).tableVisible, false);
    assert.equal(connectActions(actionState({
        phase: 'probed', probe: { ok: true, url: URL_A, auth_required: false, compat: { status: 'ok' } },
    })).tableVisible, true);
    assert.equal(connectActions({ bridge: 'ready', mode: 'local' }).tableVisible, false);
});

test('test_rows_save_locked_while_url_edited', () => {
    const dirty = () => { const s = actionState(); s.rows[0].local = 'changed'; return s; };
    assert.equal(connectActions(dirty()).canSaveRows, true);
    const other = dirty();
    other.urlText = 'http://other.test:8765';
    other.probedText = other.urlText;
    other.probe = { ...other.probe, url: other.urlText };
    other.sourcesFor = other.urlText;
    assert.equal(connectActions(other).canSaveRows, false);
});

test('test_rows_save_other_conditions', () => {
    assert.equal(connectActions(actionState()).canSaveRows, false);
    const dirty = (over) => { const s = actionState(over); s.rows[0].local = 'changed'; return s; };
    assert.equal(connectActions(dirty({ mode: 'local', savedUrl: '' })).canSaveRows, false);
    assert.equal(connectActions(dirty({ sourcesState: 'error' })).canSaveRows, false);
    assert.equal(connectActions(dirty({ sourcesFor: 'http://x' })).canSaveRows, false);
    assert.equal(connectActions(dirty({ busy: 'apply' })).canSaveRows, false);
    assert.equal(connectActions(dirty({ restarting: true })).canSaveRows, false);
    assert.equal(connectActions(dirty({ bridge: 'pending' })).canSaveRows, false);
});

test('test_can_reload_sources', () => {
    assert.equal(connectActions(actionState({ sourcesState: 'error' })).canReloadSources, true);
    assert.equal(connectActions(actionState({ sourcesState: 'error', busy: 'probe' })).canReloadSources, false);
    assert.equal(connectActions(actionState({ sourcesState: 'ok' })).canReloadSources, false);
    assert.equal(connectActions(actionState({ sourcesState: 'error', phase: 'probed',
        probe: { ok: true, url: URL_A, auth_required: true, authed: false, compat: { status: 'ok' } } })).canReloadSources, false);
});
