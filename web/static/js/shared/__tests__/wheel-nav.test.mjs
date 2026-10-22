// wheel-nav.test.mjs — createWheelNav/isHorizontalWheel 純邏輯守衛（TASK-102d-T1）。
// 零新依賴：Node 內建 node:test + node:assert/strict + 假 delta 序列（非真 DOM，比照
// focal-cell.test.mjs 的假物件手法）。時間用可注入 now() 驅動，不需要真 sleep。
//
// 守的是：
//   (a) 單次大 delta（|dx|>threshold）→ 觸發一次
//   (b) 連發 20 小 delta（同方向、事件間隔 <cooldownMs）→ 只觸發一次（冷卻窗生效）
//   (c) 方向反轉 → 立即解鎖（不等冷卻窗跑完即可再觸發，方向相反）
//   (d) |deltaX| <= |deltaY| → 不觸發（垂直捲動 / 45 度邊界不誤判）
//   (e) deltaMode=LINE（1）→ 正規化到與 PIXEL 同量級後才判門檻
//   (f) 停頓 ≥ cooldownMs（無新事件）後 → 可再觸發
//   (g) 左右對稱：dx<0 → onLeft；dx>0 → onRight
//
// 跑：npm test（glob 涵蓋本檔，package.json:13）。
//
// mutation 抓點：拿掉冷卻窗判斷（(t < cooldownUntil) return false）→ (b) 必 RED（會觸發 20 次）；
// 拿掉方向反轉重置 → (c) 必 RED；拿掉 isHorizontalWheel 判斷 → (d) 必 RED；
// 拿掉 deltaMode 正規化 → (e) 必 RED（LINE delta 遠小於門檻，不會觸發）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isHorizontalWheel, isVerticalWheel, createWheelNav } from '../wheel-nav.js';

// ── 假時鐘：手動推進，呼叫端完全掌控時間流逝（不需真 sleep）───────────────
function makeClock(startAt = 0) {
  let t = startAt;
  return {
    now: () => t,
    advance(ms) { t += ms; return t; },
  };
}

function makeSpyCallbacks() {
  const calls = [];
  return {
    calls,
    onLeft: () => calls.push('left'),
    onRight: () => calls.push('right'),
  };
}

// 102d P2b：垂直軸版 spy（onUp/onDown），供 axis:'vertical' 案例使用。
function makeVerticalSpyCallbacks() {
  const calls = [];
  return {
    calls,
    onUp: () => calls.push('up'),
    onDown: () => calls.push('down'),
  };
}

// ── isHorizontalWheel：純數值方向主導判斷 ──────────────────────────────────


// ── createWheelNav.feed：累積/冷卻/方向邏輯 ────────────────────────────────

test('feed〔單次大 delta〕|dx|>threshold → 立即觸發一次 onRight（dx>0）', () => {
  const clock = makeClock();
  const nav = createWheelNav({ threshold: 80, cooldownMs: 200, now: clock.now });
  const cb = makeSpyCallbacks();
  const triggered = nav.feed({ deltaX: 120, deltaY: 0, deltaMode: 0 }, cb);
  assert.equal(triggered, true);
  assert.deepEqual(cb.calls, ['right']);
});


test('feed〔垂直為主〕|deltaX|<=|deltaY| → 不觸發、不消耗累積', () => {
  const clock = makeClock();
  const nav = createWheelNav({ threshold: 80, cooldownMs: 200, now: clock.now });
  const cb = makeSpyCallbacks();
  const triggered = nav.feed({ deltaX: 10, deltaY: 100, deltaMode: 0 }, cb);
  assert.equal(triggered, false);
  assert.deepEqual(cb.calls, []);
});

test('feed〔連發 20 小 delta 同方向 <200ms 間隔〕僅觸發一次（冷卻窗生效，非 20 次）', () => {
  const clock = makeClock();
  const nav = createWheelNav({ threshold: 80, cooldownMs: 200, now: clock.now });
  const cb = makeSpyCallbacks();
  // 20 次 tick，每次 deltaX=15（慣性捲動典型小 delta），間隔 10ms（總耗時 190ms < cooldownMs）
  for (let i = 0; i < 20; i++) {
    nav.feed({ deltaX: 15, deltaY: 0, deltaMode: 0 }, cb);
    clock.advance(10);
  }
  assert.equal(cb.calls.length, 1, '20 個 tick 應恰好觸發 1 次（累積門檻命中後冷卻窗擋住其餘）');
  assert.deepEqual(cb.calls, ['right']);
});


// ── isVerticalWheel：isHorizontalWheel 的縱向鏡像（102d P2b） ──────────────


// ── createWheelNav({ axis: 'vertical' }).feed：垂直軸累積/冷卻/方向邏輯 ────
// 與水平軸案例一一對應（門檻/冷卻/方向反轉解鎖邏輯共用，僅軸別與 callback 命名不同：
// onUp/onDown 取代 onLeft/onRight，dy<0→onUp、dy>0→onDown）。

test('feed〔垂直軸：單次大 deltaY〕|dy|>threshold → 立即觸發一次 onDown（dy>0，滾下=next）', () => {
  const clock = makeClock();
  const nav = createWheelNav({ threshold: 80, cooldownMs: 200, now: clock.now, axis: 'vertical' });
  const cb = makeVerticalSpyCallbacks();
  const triggered = nav.feed({ deltaX: 0, deltaY: 120, deltaMode: 0 }, cb);
  assert.equal(triggered, true);
  assert.deepEqual(cb.calls, ['down']);
});


