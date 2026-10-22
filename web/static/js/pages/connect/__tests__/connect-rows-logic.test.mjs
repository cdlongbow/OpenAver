// 168b-T6b: path-map table pure logic.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    connectActions, mergeRows, staleRows, rulesForSave, stripWrappingQuotes, isRowsDirty, rowResultView, pathMapForApply,
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

// 與 tests/unit/test_path_translate.py::STRIP_TABLE 同表（輸入 -> 輸出逐字相同）
const STRIP_TABLE = [
    ['"\\\\nas\\av"', '\\\\nas\\av'],
    ['  "D:\\av"  ', 'D:\\av'],
    ['  D:\\av  ', 'D:\\av'],
    ['"D:\\av', '"D:\\av'],
    ['D:\\av"', 'D:\\av"'],
    ['"', '"'],
    ['"D:\\a"v"', 'D:\\a"v'],
    ['""', ''],
    ['" D:\\av "', 'D:\\av'],
];

test('rulesForSave 去掉成對引號且與 Python 同表', () => {
    for (const [raw, want] of STRIP_TABLE) {
        assert.equal(stripWrappingQuotes(raw), want, raw);
    }
    const rows = [
        { server: '/a', local: '"\\\\nas\\av"' },
        { server: '/b', local: '""' },
        { server: '/c', local: '  "D:\\av"  ' },
        { server: '/d', local: '"D:\\av' },
    ];
    assert.deepEqual(rulesForSave(rows), [
        { server: '/a', local: '\\\\nas\\av' },
        { server: '/c', local: 'D:\\av' },
        { server: '/d', local: '"D:\\av' },
    ]);
    const snap = JSON.stringify(rulesForSave(rows));
    assert.equal(isRowsDirty(rows, snap), false);
});


function loaded(over = {}) {
    const rows = allRows();
    return {
        sourcesState: 'ok', sourcesFor: URL_A, rows, rowsSnapshot: JSON.stringify(rulesForSave(rows)),
        probe: { url: URL_A }, ...over,
    };
}


function actionState(over = {}) {
    return {
        ...loaded(),
        bridge: 'ready', busy: null, restarting: false, mode: 'client', phase: 'authed',
        urlText: URL_A, savedUrl: URL_A, probedText: URL_A, pin: '',
        probe: { ok: true, url: URL_A, auth_required: true, authed: true, compat: { status: 'ok' } },
        ...over,
    };
}


