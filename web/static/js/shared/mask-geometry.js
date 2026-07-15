/**
 * mask-geometry.js — 焦點裁切遮罩軸向/窗幾何 純函式（shared ESM，100b-T2a）
 *
 * 從 state-lightbox.js 抽出的兩段承重幾何邏輯，抽成純函式的唯一理由是**可測試性**——
 * state-lightbox.js 本身用 `@/showcase/...` 等 importmap alias（僅瀏覽器/base.html 的
 * importmap 認得），plain Node（node:test）無法直接 import 該檔；本檔只用相對路徑 import
 * `./focal.js` 的 clampMaskWinLeft，比照 focal-cell.js 的既有慣例，讓 node:test 可直接
 * import 驗證。
 *
 * 不動 focal.js／focal-cell.js 本體（T3 範圍）——本檔只消費 focal.js 既有 export，不修改它。
 *
 * computeMaskAxis：CD-2 軸向 + 凍結模式判定。
 * computeMaskWinGeometry：亮窗 inline style 物件建構（G1：恆回傳 object，不可為字串——
 * `_computeMaskWinStyle()` 與 `_maskDragStart()` 的 onMove 兩個獨立 writer 皆委派本函式，
 * 讓「留一個字串 writer」這個 99a-T5 事故的 by-construction 復發面從多處收斂為一處）。
 */

import { clampMaskWinLeft } from './focal.js';

/**
 * CD-2（100b-T2a）：依 render rect 解出拖曳軸向 + 凍結模式判定（純函式，state-lightbox.js
 * 的 openMask() 呼叫一次後將結果凍結進 _maskAxis/_maskFrozen，不在 pointermove/
 * _computeMaskWinStyle 內重判，G4）。
 *
 * dragExtentX/Y 為 CSS px 空間的「可拖曳餘裕」，恰有一個 >0（a==r 時兩者皆 0）——
 * 🔴 必須在 px 空間判、不可用 aspect 空間的 epsilon 常數：女優圖 height:60vh（§B-5），
 * H 隨視窗變，同一個 aspect-ε 在不同視窗高度對應的可拖像素不同。
 *
 * @param {number} W render 寬（px）
 * @param {number} H render 高（px）
 * @param {number} r 裁切窗比例（--poster-crop-ratio / --actress-crop-ratio）
 * @returns {{axis: 'x'|'y', frozen: boolean}}
 */
export function computeMaskAxis(W, H, r) {
  const dragExtentX = W - Math.min(W, H * r);   // a > r 時 > 0，否則 0
  const dragExtentY = H - Math.min(H, W / r);   // a < r 時 > 0，否則 0
  const frozen = Math.max(dragExtentX, dragExtentY) < 2;
  const axis = dragExtentY > dragExtentX ? 'y' : 'x';
  return { axis, frozen };
}

/**
 * 亮窗 inline style 物件建構（軸向分流）。呼叫端（state-lightbox.js）負責讀
 * getComputedStyle/CSS var（裁決3：ratio 讀取受 static_guard_lint.mjs scope-anchor 規則
 * 錨定在 `_computeMaskWinStyle()` 本體內，不可委派），本函式只吃已解出的數字 r。
 *
 * @param {number} W render 寬（px）
 * @param {number} H render 高（px）
 * @param {number} r 裁切窗比例
 * @param {'x'|'y'} axis 已凍結的拖曳軸向
 * @param {number|null|undefined} focalX raw x（[0,1]，未鉗）
 * @param {number|null|undefined} focalY raw y（[0,1]，未鉗）
 * @returns {{width: string, height: string, transform: string}} 恆為 object（G1，絕不回傳字串）
 */
export function computeMaskWinGeometry(W, H, r, axis, focalX, focalY) {
  const winW = Math.min(W, H * r);
  const winH = Math.min(H, W / r);
  if (axis === 'y') {
    let top = (focalY !== null && focalY !== undefined) ? focalY * H - winH / 2 : H - winH;
    top = clampMaskWinLeft(top, H, winH);   // 數學軸無關的純量 clamp（B-4：(top,H,winH) 傳法正確）
    return { width: `${W}px`, height: `${winH}px`, transform: `translateY(${top}px)` };
  }
  let left = (focalX !== null && focalX !== undefined) ? focalX * W - winW / 2 : W - winW;
  left = clampMaskWinLeft(left, W, winW);
  return { width: `${winW}px`, height: `${H}px`, transform: `translateX(${left}px)` };
}
