// focal-cell.test.mjs — applyCellFocal load-gate + expected-src guard 守衛（99a-T2）。
// 零新依賴：Node 內建 node:test + node:assert/strict + 假 img stub（非真 DOM）。
// 跑：npm test（glob 涵蓋本檔，package.json:13）。
//
// 鏡射 dom-timing.test.mjs 的假物件/`withStubs` 手法（假 MutationObserver → 這裡改假 img +
// 假 globalThis.getComputedStyle）。守 applyCellFocal 的：
//   (a) complete && naturalWidth>0 → 同步立即套（不掛 listener）
//   (b) complete=false 或 naturalWidth=0 → 掛 load listener，載入後才套
//   (c) expected-src guard：attach 後 src 被換過 → fire 時放棄（不覆寫新圖的 objectPosition）
//   (d) broken image（complete=true, naturalWidth=0）→ 走 load-gate 路徑，不可誤判成已載入
//   (e) focalCellObjectPosition 回 null → el.style.objectPosition 設為 ''（baseline restore）
//
// mutation 抓點：若拿掉 load-gate 判斷（同步無條件套用）、或拿掉 expected-src guard，
// 對應案例必 RED。

import { test } from 'node:test';
import assert from 'node:assert/strict';

// ── 假 img stub（鏡射 dom-timing.test.mjs 的 FakeMutationObserver 手法）────────
function makeFakeImg({ complete, naturalWidth, naturalHeight, src }) {
  const listeners = {};
  return {
    complete,
    naturalWidth,
    naturalHeight,
    src,
    currentSrc: src,
    style: {},
    addEventListener(evt, cb, opts) {
      listeners[evt] = { cb, opts };
    },
    removeEventListener(evt) {
      delete listeners[evt];
    },
    _hasListener(evt) {
      return !!listeners[evt];
    },
    _fireLoad() {
      listeners.load?.cb();
    },
  };
}

// ── 假 getComputedStyle：回傳固定 --poster-crop-ratio（鏡射 state-lightbox.js:875 讀法）──
function withFakeComputedStyle(cssVarValue, run) {
  const orig = globalThis.getComputedStyle;
  globalThis.getComputedStyle = () => ({
    getPropertyValue(name) {
      if (name === '--poster-crop-ratio') return String(cssVarValue);
      return '';
    },
  });
  try {
    return run();
  } finally {
    globalThis.getComputedStyle = orig;
  }
}

const { applyCellFocal } = await import('../focal-cell.js');

const AUTO_VIDEO = { crop_mode: 'auto', auto_focal: '0.3000,0.5000' }; // < deadzone 0.62，非 null 案例
const R = 0.71;

test('applyCellFocal〔已載入同步路徑〕complete=true, naturalWidth>0 → 立即套用，不掛 load listener', () => {
  withFakeComputedStyle(R, () => {
    const img = makeFakeImg({ complete: true, naturalWidth: 1490, naturalHeight: 1000, src: 'a.jpg' });
    applyCellFocal(img, AUTO_VIDEO);
    assert.notEqual(img.style.objectPosition, '', '應立即算出非空 objectPosition');
    assert.equal(img._hasListener('load'), false, '已載入不應掛 load listener');
  });
});

test('applyCellFocal〔complete=false 未載入〕不立即套用，掛 load listener，_fireLoad 後才套', () => {
  withFakeComputedStyle(R, () => {
    const img = makeFakeImg({ complete: false, naturalWidth: 0, naturalHeight: 0, src: 'a.jpg' });
    applyCellFocal(img, AUTO_VIDEO);
    assert.equal(img.style.objectPosition, undefined, '未載入前不應設 objectPosition');
    assert.equal(img._hasListener('load'), true, '未載入應掛 load listener');
    // 模擬載入完成：naturalWidth/naturalHeight 就緒
    img.naturalWidth = 1490;
    img.naturalHeight = 1000;
    img.complete = true;
    img._fireLoad();
    assert.notEqual(img.style.objectPosition, '', 'load 後應套用非空 objectPosition');
  });
});

test('applyCellFocal〔naturalWidth=0 但 complete=true〕不可誤判已載入（不可同步算出 NaN%），走 load-gate 路徑', () => {
  withFakeComputedStyle(R, () => {
    const img = makeFakeImg({ complete: true, naturalWidth: 0, naturalHeight: 0, src: 'a.jpg' });
    applyCellFocal(img, AUTO_VIDEO);
    assert.equal(img.style.objectPosition, undefined, 'naturalWidth=0 不應同步套用（防 NaN%）');
    assert.equal(img._hasListener('load'), true, '應走 load-gate（掛 listener）而非同步路徑');
  });
});

test('applyCellFocal〔expected-src guard〕attach 時 src=A，fire 前換成 src=B → fire 後不套用（不覆寫新圖）', () => {
  withFakeComputedStyle(R, () => {
    const img = makeFakeImg({ complete: false, naturalWidth: 0, naturalHeight: 0, src: 'A.jpg' });
    applyCellFocal(img, AUTO_VIDEO);
    // 換圖（同一 DOM 元素被重用，B 的 .src= 賦值 + load 尚未 fire）
    img.src = 'B.jpg';
    img.currentSrc = 'B.jpg';
    img.naturalWidth = 1490;
    img.naturalHeight = 1000;
    img.complete = true;
    img._fireLoad(); // A 的舊 load listener 遲到 fire
    assert.equal(img.style.objectPosition, undefined, 'A 的舊 load 不可覆寫已換成 B 的 objectPosition');
  });
});

test('applyCellFocal〔result null → 清 inline〕crop_mode=default → objectPosition 設為空字串（baseline restore）', () => {
  withFakeComputedStyle(R, () => {
    const img = makeFakeImg({ complete: true, naturalWidth: 1490, naturalHeight: 1000, src: 'a.jpg' });
    img.style.objectPosition = '38.20% center'; // 模擬殘留舊值（換片 A→B，B 應清掉，不殘留 A）
    applyCellFocal(img, { crop_mode: 'default', auto_focal: '0.3000,0.5000' });
    assert.equal(img.style.objectPosition, '', 'null 結果應清 inline，不殘留舊值');
  });
});

test('applyCellFocal〔result null via load-gate〕未載入時掛 listener，load 後算出 null → 清 inline', () => {
  withFakeComputedStyle(R, () => {
    const img = makeFakeImg({ complete: false, naturalWidth: 0, naturalHeight: 0, src: 'a.jpg' });
    img.style.objectPosition = '38.20% center'; // 殘留舊值
    applyCellFocal(img, { crop_mode: 'default', auto_focal: '0.3000,0.5000' });
    img.naturalWidth = 1490;
    img.naturalHeight = 1000;
    img.complete = true;
    img._fireLoad();
    assert.equal(img.style.objectPosition, '', 'load 後 null 結果應清 inline');
  });
});

test('applyCellFocal〔el 為 null〕不拋錯，靜默 no-op', () => {
  assert.doesNotThrow(() => applyCellFocal(null, AUTO_VIDEO));
});

test('applyCellFocal〔--poster-crop-ratio 讀不到〕r<=0 → 清 inline，不拋錯', () => {
  withFakeComputedStyle(0, () => {
    const img = makeFakeImg({ complete: true, naturalWidth: 1490, naturalHeight: 1000, src: 'a.jpg' });
    img.style.objectPosition = '38.20% center';
    applyCellFocal(img, AUTO_VIDEO);
    assert.equal(img.style.objectPosition, '', 'r<=0 應退化清 inline');
  });
});
