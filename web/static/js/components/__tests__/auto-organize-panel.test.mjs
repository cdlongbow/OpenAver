// TASK-144-T7: Alpine.data('autoOrganizePanel') open/close/setEnabled/runNow + 註冊

import { test } from 'node:test';
import assert from 'node:assert/strict';

let alpineInitCb;
globalThis.window = globalThis;
globalThis.document = { addEventListener: (_name, fn) => { alpineInitCb = fn; } };

const registered = [];
const toastCalls = [];
// 面板走既有的 Alpine.store('toast')（照 shared/state-toast.js），
// **不是** window.toast——全站沒有那個全域，為一個面板生一個等於開第二條 toast 路徑。
globalThis.Alpine = {
    data: (name, fn) => registered.push([name, fn]),
    store: (name) => (name === 'toast'
        ? { show: (msg, type) => { toastCalls.push([msg, type]); } }
        : undefined),
};
globalThis.window.t = (key) => key;
globalThis.window.pathToDisplay = (p) => p || '';

let fetchImpl = async () => ({ ok: true, json: async () => ({}) });
globalThis.fetch = (...args) => fetchImpl(...args);

const { autoOrganizePanel } = await import('../auto-organize-panel.js');

function freshPanel() {
    toastCalls.length = 0;
    return autoOrganizePanel();
}


test('openPanel: 還沒設最愛資料夾時，灰字顯示後端算出的候選路徑', async () => {
    const panel = freshPanel();
    fetchImpl = async () => ({
        ok: true,
        json: async () => ({
            running: false,
            current_number: null,
            enabled: false,
            folder: '',
            folder_is_set: false,
            resolved_folder: '/home/u/Downloads',
        }),
    });

    await panel.openPanel();
    assert.equal(panel.folderIsSet, false);
    // 顯示「按下『就用這個資料夾』之後會變成什麼」，與後端實際會寫入的值同源
    assert.equal(panel.folderPath, '/home/u/Downloads');
    assert.equal(panel.displayFolderPath(), '/home/u/Downloads');
});


test('setEnabled(true) 打 POST /search/auto-organize/config，回應 {success:false} 時 this.enabled 不變', async () => {
    const panel = freshPanel();
    panel.enabled = false;
    panel.folderIsSet = true;

    let posted = null;
    fetchImpl = async (url, opts = {}) => {
        if (String(url).includes('/auto-organize/config') && opts.method === 'POST') {
            posted = JSON.parse(opts.body);
            return { ok: true, json: async () => ({ success: false, error: 'favorite_folder_unset' }) };
        }
        return { ok: true, json: async () => ({}) };
    };

    // 使用者點擊當下，瀏覽器已經把 checkbox 翻到 true 了——失敗時**兩邊都要還原**
    const el = { checked: true };

    await panel.setEnabled(true, el);
    assert.deepEqual(posted, { enabled: true });
    assert.equal(panel.enabled, false);
    assert.equal(
        el.checked, false,
        '只還原 this.enabled 不夠：綁定是 :checked="enabled"，指回同一個值不會重跑綁定，'
        + '開關會停在使用者撥過去的位置——畫面說開著、後端其實是關的（T7 CDP 實測到）',
    );
    assert.ok(toastCalls.length >= 1);
});


test("模組在 alpine:init 時把自己註冊成 Alpine.data('autoOrganizePanel', …)", () => {
    assert.equal(typeof alpineInitCb, 'function');
    const before = registered.length;
    alpineInitCb();
    assert.equal(registered.length, before + 1);
    assert.equal(registered[registered.length - 1][0], 'autoOrganizePanel');
    assert.equal(typeof registered[registered.length - 1][1], 'function');
    const instance = registered[registered.length - 1][1]();
    assert.equal(instance.open, false);
    assert.equal(typeof instance.openPanel, 'function');
    assert.equal(typeof instance.closePanel, 'function');
    assert.equal(typeof instance.setEnabled, 'function');
    assert.equal(typeof instance.runNow, 'function');
    assert.equal(typeof instance.useResolvedFolder, 'function');
});
