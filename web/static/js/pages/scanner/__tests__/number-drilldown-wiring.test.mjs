// TASK-155b-T4: scanner 頁三處 numberDrilldown payload / items getter 契約。
// 鎖 category 過濾、file_path→path 映射、nfo note 組字、footnote 空字串、空番號保留。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
window.t = (key) => key;

register(
  new URL('../../search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);

const { stateBatch } = await import('../state-batch.js');
const { stateScan } = await import('../state-scan.js');

/** Object.assign 會把 getter 求值成資料屬性；改用 descriptor 在 fakeThis 上讀。 */
function readGetter(factory, name, fakeThis) {
  const desc = Object.getOwnPropertyDescriptor(factory(), name);
  assert.equal(typeof desc?.get, 'function', `${name} getter 應存在`);
  return desc.get.call(fakeThis);
}

/** payload getter 會讀 this.xxxDrilldownItems；把 items 層 getter 掛回同一 this。 */
function withItemsGetter(factory, itemsName, fakeThis) {
  const desc = Object.getOwnPropertyDescriptor(factory(), itemsName);
  assert.equal(typeof desc?.get, 'function', `${itemsName} getter 應存在`);
  Object.defineProperty(fakeThis, itemsName, {
    get: desc.get,
    enumerable: true,
    configurable: true,
  });
  return fakeThis;
}

const MIXED_MISSING = [
  { number: 'AAA-001', file_path: '/a/both.mp4', category: 'both' },
  { number: 'BBB-002', file_path: '/b/nfo.mp4', category: 'nfo' },
  { number: 'CCC-003', file_path: '/c/cover.mp4', category: 'cover' },
  { number: 'DDD-004', file_path: '/d/both2.mp4', category: 'both' },
];

test('missingBothDrilldownItems 只含 both 分類且 path 對應 file_path', () => {
  const fakeThis = Object.assign({}, stateBatch(), { missingItems: MIXED_MISSING });
  const items = readGetter(stateBatch, 'missingBothDrilldownItems', fakeThis);

  assert.equal(items.length, 2);
  assert.deepEqual(
    items.map((i) => i.number),
    ['AAA-001', 'DDD-004'],
  );
  assert.equal(items[0].path, '/a/both.mp4');
  assert.equal(items[1].path, '/d/both2.mp4');
  assert.ok(items.every((i) => i.path !== undefined));

  withItemsGetter(stateBatch, 'missingBothDrilldownItems', fakeThis);
  const payload = readGetter(stateBatch, 'missingBothDrilldownPayload', fakeThis);
  assert.equal(payload.items[0].note, 'scanner.stats.missing_both_tag');
  assert.equal(payload.items[0].path, '/a/both.mp4');
  assert.equal(payload.footnote, 'scanner.stats.missing_list_footnote');
  assert.equal(payload.title, 'scanner.stats.missing_both_prefix');
});

test('nfoUpdateDrilldownItems 每列附註以缺：開頭並用頓號分隔多個欄位', () => {
  const fakeThis = Object.assign({}, stateScan(), {
    nfoUpdateItems: [
      { number: 'EEE-005', path: '/e/one.mp4', missing: ['director'] },
      { number: 'FFF-006', path: '/f/two.mp4', missing: ['director', 'duration'] },
    ],
  });
  const items = readGetter(stateScan, 'nfoUpdateDrilldownItems', fakeThis);

  assert.equal(
    items[0].note,
    'scanner.stats.nfo_field_note_prefix' + 'scanner.stats.nfo_field_director',
  );
  assert.equal(
    items[1].note,
    'scanner.stats.nfo_field_note_prefix'
      + 'scanner.stats.nfo_field_director'
      + '、'
      + 'scanner.stats.nfo_field_duration',
  );
  assert.ok(items.every((i) => i.note !== undefined));
});

test('nfoUpdateDrilldownPayload 與 jellyfinDrilldownPayload 的 footnote 恆為空字串', () => {
  const nfoThis = withItemsGetter(
    stateScan,
    'nfoUpdateDrilldownItems',
    Object.assign({}, stateScan(), {
      nfoUpdateItems: [{ number: 'GGG-007', path: '/g.mp4', missing: ['title'] }],
    }),
  );
  const nfoPayload = readGetter(stateScan, 'nfoUpdateDrilldownPayload', nfoThis);
  assert.equal(nfoPayload.footnote, '');

  const jfThis = withItemsGetter(
    stateScan,
    'jellyfinDrilldownItems',
    Object.assign({}, stateScan(), {
      jellyfinItems: [{ number: 'HHH-008', path: '/h.mp4' }],
    }),
  );
  const jfPayload = readGetter(stateScan, 'jellyfinDrilldownPayload', jfThis);
  assert.equal(jfPayload.footnote, '');
});

test('jellyfinDrilldownItems 保留空番號項目', () => {
  const emptyPath = 'file:///C:/AVtest/無番號片.mp4';
  const fakeThis = Object.assign({}, stateScan(), {
    jellyfinItems: [{ number: '', path: emptyPath }],
  });
  withItemsGetter(stateScan, 'jellyfinDrilldownItems', fakeThis);
  const payload = readGetter(stateScan, 'jellyfinDrilldownPayload', fakeThis);

  assert.equal(payload.items.length, 1);
  assert.deepEqual(payload.items[0], { number: '', path: emptyPath });
});

test('missingXxxDrilldownItems note 走分類 tag；nfoUpdate 每筆皆有 note', () => {
  const batchThis = Object.assign({}, stateBatch(), { missingItems: MIXED_MISSING });
  const both = readGetter(stateBatch, 'missingBothDrilldownItems', batchThis);
  const nfo = readGetter(stateBatch, 'missingNfoDrilldownItems', batchThis);
  const cover = readGetter(stateBatch, 'missingCoverDrilldownItems', batchThis);

  assert.equal(both[0].note, 'scanner.stats.missing_both_tag');
  assert.equal(nfo[0].note, 'scanner.stats.missing_nfo_tag');
  assert.equal(cover[0].note, 'scanner.stats.missing_cover_tag');

  const scanThis = Object.assign({}, stateScan(), {
    nfoUpdateItems: [{ number: 'III-009', path: '/i.mp4', missing: [] }],
  });
  const nfoItems = readGetter(stateScan, 'nfoUpdateDrilldownItems', scanThis);
  // BC5：每筆都有 note（可為「缺：」+ 空欄位清單）；prefix 組字由上一支 expect_fail 測試鎖
  assert.equal(typeof nfoItems[0].note, 'string');
  assert.notEqual(nfoItems[0].note, undefined);
});
