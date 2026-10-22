// TASK-177-T3a: favorite-sync.js 純函式契約。期望值一律手寫字面，不拿被測函式的輸出當期望。

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { classifyFavoriteResponse, buildFavoriteEntry, mergeFavorite } from '../favorite-sync.js';

test('classifyFavoriteResponse: 先看 status 不看 success，八種回應各歸其類', () => {
    const rows = [
        [200, { success: true, actress: { name: 'A' } }, 'added'],
        [200, { success: true }, 'failed'],
        [409, { actress: { name: 'A' } }, 'already'],
        [409, { error: 'already_exists' }, 'failed'],
        [404, { error: 'not_found' }, 'not_found'],
        [504, null, 'failed'],
        [500, { actress: { name: 'A' } }, 'failed'],
        [undefined, undefined, 'failed'],
    ];
    for (const [status, body, want] of rows) {
        assert.equal(classifyFavoriteResponse(status, body), want, `status=${status} body=${JSON.stringify(body)}`);
    }
});

test('buildFavoriteEntry: 有圖有生日／無圖／對焦欄位為 null 三種條目', () => {
    assert.deepEqual(
        buildFavoriteEntry({ name: '石川澪', birth: '1999-01-02', photo_url: '/p.jpg', auto_focal: [0.5, 0.3], crop_mode: 'face' }),
        { birth: '1999-01-02', photoName: '石川澪', hasPhoto: true, auto_focal: [0.5, 0.3], crop_mode: 'face' },
    );
    assert.deepEqual(
        buildFavoriteEntry({ name: 'B', birth: '', photo_url: null, auto_focal: null, crop_mode: null }),
        { birth: null, photoName: 'B', hasPhoto: false, auto_focal: null, crop_mode: null },
    );
    // 409 形狀：無 photo_downloaded、無 crop_mode；hasPhoto 由 photo_url 決定
    assert.deepEqual(
        buildFavoriteEntry({ name: 'C', birth: '2000-05-06', photo_url: '/c.jpg' }),
        { birth: '2000-05-06', photoName: 'C', hasPhoto: true, auto_focal: null, crop_mode: null },
    );
});

test('mergeFavorite: 回傳新物件、舊物件不被改動、其他鍵保留', () => {
    const old = { X: { birth: null } };
    const entry = { birth: '1999-01-02' };
    const out = mergeFavorite(old, 'Y', entry);
    assert.notEqual(out, old);
    assert.deepEqual(Object.keys(old), ['X']);
    assert.deepEqual(out, { X: { birth: null }, Y: { birth: '1999-01-02' } });
    assert.deepEqual(mergeFavorite(null, 'Z', entry), { Z: { birth: '1999-01-02' } });
    assert.deepEqual(mergeFavorite(undefined, 'Z', entry), { Z: { birth: '1999-01-02' } });
});
