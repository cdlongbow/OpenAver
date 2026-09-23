// TASK-153b-T3：掃描頁 outputPathDisplay 行為鎖。
// 守「解析路徑優先、空值不回退字面 output」——字串存在性測試擋不住把 getter
// 整行換成 'output' 的回歸，必須實際設值、讀 getter 回傳值。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
window.t = (key) => key;

register(
  new URL('../../search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);

const { stateScan } = await import('../state-scan.js');

/** Object.assign 會把 getter 求值成資料屬性；改用 descriptor 在 fakeThis 上讀。 */
function readOutputPathDisplay(fakeThis) {
  const desc = Object.getOwnPropertyDescriptor(stateScan(), 'outputPathDisplay');
  assert.equal(typeof desc?.get, 'function', 'stateScan() 應有 outputPathDisplay getter');
  return desc.get.call(fakeThis);
}

test('outputPathDisplay uses resolvedGalleryOutputPath when set', () => {
  const resolved = '/var/packages/OpenAver/var/data';
  const fakeThis = Object.assign({}, stateScan(), {
    resolvedGalleryOutputPath: resolved,
    config: {
      gallery: {
        output_dir: 'should_not_win',
        output_filename: 'gallery_output.html',
      },
    },
  });

  const display = readOutputPathDisplay(fakeThis);
  assert.ok(
    display.includes(resolved),
    `outputPathDisplay 應包含 resolved 路徑，got ${JSON.stringify(display)}`,
  );
  assert.ok(
    display.includes('gallery_output.html'),
    `outputPathDisplay 應含檔名，got ${JSON.stringify(display)}`,
  );
});

test('outputPathDisplay falls back to config.gallery.output_dir when resolved empty', () => {
  const custom = '../openaver_gallery';
  const fakeThis = Object.assign({}, stateScan(), {
    resolvedGalleryOutputPath: '',
    config: {
      gallery: {
        output_dir: custom,
        output_filename: 'gallery_output.html',
      },
    },
  });

  const display = readOutputPathDisplay(fakeThis);
  assert.ok(
    display.includes(custom),
    `resolved 空時應使用自訂 output_dir，got ${JSON.stringify(display)}`,
  );
});

test('outputPathDisplay must not contain literal output when both sources empty', () => {
  // 檔名刻意不含字串 output，讓「回傳值不得出現字面 output」能直接斷言目錄 sentinel。
  const fakeThis = Object.assign({}, stateScan(), {
    resolvedGalleryOutputPath: '',
    config: {
      gallery: {
        output_dir: '',
        output_filename: 'list.html',
      },
    },
  });

  const display = readOutputPathDisplay(fakeThis);
  assert.equal(
    display.includes('output'),
    false,
    `兩者皆空時不得出現字面 output（本 task 要消滅的 sentinel），got ${JSON.stringify(display)}`,
  );
});
