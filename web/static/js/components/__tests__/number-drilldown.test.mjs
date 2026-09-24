// TASK-155b-T2: Alpine.data('numberDrilldown') toggle/copyText/hasFootnote + 註冊

import { test } from 'node:test';
import assert from 'node:assert/strict';

let alpineInitCb;
globalThis.window = globalThis;
globalThis.document = { addEventListener: (_name, fn) => { alpineInitCb = fn; } };

const registered = [];
const toastCalls = [];
globalThis.Alpine = {
    data: (name, fn) => registered.push([name, fn]),
    store: (name) => (name === 'toast'
        ? { show: (msg, type) => { toastCalls.push([msg, type]); } }
        : undefined),
};
globalThis.window.t = (key, params) => {
    if (!params) return key;
    return key.replace(/\{(\w+)\}/g, (_, k) => (
        Object.prototype.hasOwnProperty.call(params, k) ? String(params[k]) : `{${k}}`
    ));
};

const { numberDrilldown } = await import('../number-drilldown.js');

function fresh() {
    return numberDrilldown();
}

test('模組在 alpine:init 時註冊 Alpine.data(\'numberDrilldown\', …)', () => {
    assert.equal(typeof alpineInitCb, 'function');
    alpineInitCb();
    assert.equal(registered.length, 1);
    assert.equal(registered[0][0], 'numberDrilldown');
    assert.equal(typeof registered[0][1], 'function');
    const instance = registered[0][1]();
    assert.equal(instance.open, false);
    assert.equal(typeof instance.toggle, 'function');
    assert.equal(typeof instance.close, 'function');
});

test('toggle 第一次呼叫會開啟並寫入 title／items', () => {
    const dd = fresh();
    assert.equal(dd.open, false);
    const items = [
        { number: 'ABP-001', path: 'file:///C:/AVtest/ABP-001.mp4', note: '' },
    ];
    dd.toggle({ title: '缺封面', items });
    assert.equal(dd.open, true);
    assert.equal(dd._title, '缺封面');
    assert.equal(dd._items, items);
    assert.equal(dd.count, 1);
});

test('再次呼叫 toggle 會關閉', () => {
    const dd = fresh();
    dd.toggle({ title: '缺封面', items: [{ number: 'ABP-001', path: 'file:///C:/AVtest/ABP-001.mp4' }] });
    assert.equal(dd.open, true);
    dd.toggle({ title: '別的', items: [] });
    assert.equal(dd.open, false);
});

test('close() 後 open 為 false', () => {
    const dd = fresh();
    dd.toggle({ title: '缺封面', items: [{ number: 'ABP-001', path: 'file:///C:/AVtest/ABP-001.mp4' }] });
    assert.equal(dd.open, true);
    dd.close();
    assert.equal(dd.open, false);
});

test('copyText 一般情況只輸出番號，不含路徑與 note', () => {
    const dd = fresh();
    dd.toggle({
        title: '缺封面',
        items: [
            { number: 'ABP-001', path: 'file:///C:/AVtest/ABP-001.mp4', note: '缺：導演' },
            { number: 'SSIS-100', path: 'file:///C:/AVtest/SSIS-100.mp4', note: '' },
        ],
    });
    assert.equal(dd.copyText(), 'ABP-001\nSSIS-100');
});

test('無番號片時複製結果那一行是檔名', () => {
    const dd = fresh();
    dd.toggle({
        title: '外部媒體管理器封面缺失',
        items: [
            { number: 'WAAA-158', path: 'file:///C:/AVtest/WAAA-158.mp4', note: '' },
            { number: '', path: 'file:///C:/AVtest/無番號片.mp4', note: '' },
        ],
    });
    const lines = dd.copyText().split('\n');
    assert.equal(lines[0], 'WAAA-158');
    assert.equal(lines[1], '無番號片.mp4');
});

test('footnote 未傳時 hasFootnote 為 false', () => {
    const dd = fresh();
    dd.toggle({ title: 'NFO 欄位不全', items: [] });
    assert.equal(dd.hasFootnote, false);

    dd.close();
    dd.toggle({ title: 'NFO 欄位不全', items: [], footnote: '' });
    assert.equal(dd.hasFootnote, false);
});

test('footnote 傳非空字串時 hasFootnote 為 true', () => {
    const dd = fresh();
    const note = '不含已補過但查無結果的片';
    dd.toggle({ title: '缺封面', items: [], footnote: note });
    assert.equal(dd.hasFootnote, true);
    assert.equal(dd._footnote, note);
});
