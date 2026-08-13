// TASK-118-T6 P2-3：rescrape preview 被擋時不得顯示 not-found。
//
// 後端 {success:false, blocked:true} 必須走統一提前處理（cf_* 之後、entry-point
// 分支之前），設 rescrapeBlocked、不得落入 rescrapeNotFound。
// harness 比照同目錄 state-rescrape-preview-passthrough.test.mjs。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { register } from 'node:module';

globalThis.window = globalThis;

register(
  new URL('../../pages/search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);
const { rescrapeState } = await import('../state-rescrape.js');

const TEMPLATE = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', 'templates', '_rescrape_modal.html'),
  'utf8',
);

function makeThis(overrides = {}) {
  return Object.assign(
    {},
    rescrapeState(),
    {
      rescrapeNumber: 'FC2-123456',
      rescrapeEntryPoint: 'lightbox',
      showToast() {},
    },
    overrides,
  );
}

async function drivePreview(thisArg, json) {
  globalThis.fetch = async () => ({
    json: async () => json,
  });
  await thisArg.rescrapeWithSource('fc2');
}

// 6. blocked:true → rescrapeBlocked，且不得落入 not-found
test('6 rescrapeWithSource：{success:false, blocked:true} → rescrapeBlocked 且非 notFound', async () => {
  const fakeThis = makeThis();
  await drivePreview(fakeThis, { success: false, blocked: true, blocked_sources: ['fc2'] });
  assert.equal(fakeThis.rescrapeBlocked, true);
  assert.equal(fakeThis.rescrapeNotFound, false);
});

// 7. 無 blocked → 既有 not-found 行為不變
test('7 rescrapeWithSource：{success:false} 無 blocked → rescrapeNotFound 既有行為', async () => {
  const fakeThis = makeThis();
  await drivePreview(fakeThis, { success: false });
  assert.equal(fakeThis.rescrapeNotFound, true);
  assert.equal(fakeThis.rescrapeBlocked, false);
});

// 8. 重開／改番號／回 pick／關窗 時 rescrapeBlocked 被清
test('8 重開／改番號時 rescrapeBlocked 被清', async () => {
  const fakeThis = makeThis({ rescrapeBlocked: true, rescrapeNotFound: true });
  fakeThis.openRescrape(null, 'lightbox');
  assert.equal(fakeThis.rescrapeBlocked, false);
  assert.equal(fakeThis.rescrapeNotFound, false);

  fakeThis.rescrapeBlocked = true;
  fakeThis.closeRescrape();
  assert.equal(fakeThis.rescrapeBlocked, false);

  fakeThis.rescrapeBlocked = true;
  fakeThis.rescrapeBackToPick();
  assert.equal(fakeThis.rescrapeBlocked, false);

  fakeThis.rescrapeBlocked = true;
  fakeThis.rescrapeNumber = 'FC2-999999';
  await drivePreview(fakeThis, { success: false });
  assert.equal(fakeThis.rescrapeBlocked, false);
  assert.equal(fakeThis.rescrapeNotFound, true);

  assert.match(
    TEMPLATE,
    /@input="if \(rescrapeCfWaiting\) cancelCfPoll\(\); rescrapeNotFound = false; rescrapeBlocked = false"/,
  );
  assert.match(TEMPLATE, /x-show="rescrapeBlocked"/);
});
