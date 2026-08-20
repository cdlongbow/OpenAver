// feature/122（Codex PR#147 P2）：合併卡的破壞性確認要明示「刪的是整組」。
//
// T4 起 DELETE /api/showcase/video 對分集片刪的是整組 DB 列，但確認彈窗的既有文案
// 只說「這筆紀錄」——prd 的「破壞性 modal 明示授權」在那個情況下不成立。
// 本檔鎖的是 state 那一半：pending 快照要帶著 part_tokens，且取消/完成後要清乾淨
// （殘留會讓下一張單檔卡的彈窗多出一段假的分集警語）。
//
// state-delete.js 用瀏覽器 importmap 別名 `@/showcase/...`，plain `node --test` 不認得，
// 比照 card-shape-persist.test.mjs 自帶與 base.html importmap 對齊的 resolve hook。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;

const IMPORTMAP = {
    '@/showcase/': 'pages/showcase/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
};
const JS_ROOT = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '../../..');

register('data:text/javascript,' + encodeURIComponent(`
const MAP = ${JSON.stringify(IMPORTMAP)};
const ROOT = ${JSON.stringify(pathToFileURL(JS_ROOT + path.sep).href)};
export function resolve(specifier, context, next) {
    for (const [alias, target] of Object.entries(MAP)) {
        if (specifier.startsWith(alias)) {
            return next(ROOT + target + specifier.slice(alias.length), context);
        }
    }
    return next(specifier, context);
}
`));

const { stateDelete } = await import('@/showcase/state-delete.js');

function mk(video) {
    const s = stateDelete();
    s.currentLightboxVideo = video;
    return s;
}

test('分集卡開啟確認彈窗：pending 快照帶著 part_tokens', () => {
    const s = mk({ path: 'file:///m/ABC-123-cd1.mp4', number: 'ABC-123', part_tokens: ['cd1', 'cd2'] });
    s.openDeleteVideoModal();
    assert.deepEqual(s._pendingDeleteParts, ['cd1', 'cd2']);
    assert.equal(s.deleteVideoModalOpen, true);
});

test('單檔卡：part_tokens 空陣列，彈窗不會多出分集警語', () => {
    const s = mk({ path: 'file:///m/ABC-123.mp4', number: 'ABC-123', part_tokens: [] });
    s.openDeleteVideoModal();
    assert.deepEqual(s._pendingDeleteParts, []);
});

test('後端沒回 part_tokens（舊快取的 response）不炸，退成空陣列', () => {
    const s = mk({ path: 'file:///m/ABC-123.mp4', number: 'ABC-123' });
    s.openDeleteVideoModal();
    assert.deepEqual(s._pendingDeleteParts, []);
});

test('取消後清乾淨：下一張單檔卡不會沿用上一張的分集警語', () => {
    const s = mk({ path: 'file:///m/ABC-123-cd1.mp4', number: 'ABC-123', part_tokens: ['cd1', 'cd2'] });
    s.openDeleteVideoModal();
    s.cancelDeleteVideo();
    assert.deepEqual(s._pendingDeleteParts, []);
    assert.equal(s.deleteVideoModalOpen, false);
});
