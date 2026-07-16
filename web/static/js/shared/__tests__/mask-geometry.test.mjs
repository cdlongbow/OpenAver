// mask-geometry.test.mjs — CD-2 軸向/凍結判定 + G1 亮窗幾何 object-form 回歸鎖（100b-T2a）
// + CD-7 門檻純函式回歸鎖（100c-T1）。
// 零新依賴：Node 內建 node:test + node:assert/strict（純函式，無 DOM stub 需求）。
// 跑：npm test（glob 涵蓋本檔，package.json:13）。
//
// 守的四件事：
//   (a) CD-2 軸向選擇：寬圖(a>r)→'x'、窄圖(a<r)→'y'（mutation：把比較反向 → 必 RED）
//   (b) CD-2 凍結模式：Math.max(dragExtentX, dragExtentY) < 2 **CSS px 空間**判定。
//       🔴 「px 空間」是硬需求不是實作細節——女優圖 height:60vh（plan §B-5），H 隨視窗變，
//       同一個 aspect-ε 在不同視窗高度對應的可拖像素不同。下方「同 aspect 不同 H → frozen
//       結論不同」那條專鎖這點（mutation：改用 aspect-空間常數 → 必 RED）。
//   (c) G1：computeMaskWinGeometry 回傳**型別為 object 非 string**——99a-T5 事故本體
//       （`:style` 綁字串 → setAttribute('style') 整串覆寫 → 抹掉 x-show 的 display:none →
//       x-show 快取短路不自我修復 → 948 條全綠、功能完全不可用）。兩個軸向分支各鎖一次。
//   (d) CD-7：computeMaskDragRoom 門檻判定——四類分支、真實邊界值的「在／不在門檻內」
//       歸屬、尺度無關、非有限值 fail-closed（不可回 NaN）。詳見下方「CD-7 門檻」一節。
//
// state-lightbox.js 為何不直接測：該檔用 `@/showcase/...` importmap alias（只有瀏覽器的
// base.html importmap 認得），plain Node 無法 import；故 CD-2/G1/CD-7 的承重幾何抽至
// shared/mask-geometry.js（只用相對路徑 import），本檔直接驗純函式。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const { computeMaskAxis, computeMaskWinGeometry, computeMaskDragRoom, MASK_MIN_DRAG_ROOM } = await import('../mask-geometry.js');

const R_ACTRESS = 0.75;   // --actress-crop-ratio（女優 3/4 置中窗，CD-3）
const R_POSTER = 0.71;    // --poster-crop-ratio（影片右裁，CD-3——本檔只用於「video 恆 x 軸」對照）

// ── CD-2 軸向選擇 ────────────────────────────────────────────────────────────

test('computeMaskAxis〔寬圖 a>r〕1000×600 (a=1.67) vs r=0.75 → axis=x（水平溢出，只能左右拖）', () => {
  const { axis, frozen } = computeMaskAxis(1000, 600, R_ACTRESS);
  assert.equal(axis, 'x');
  assert.equal(frozen, false, '1000-450=550px 可拖餘裕，遠超 2px 門檻');
});

test('computeMaskAxis〔窄圖 a<r〕400×800 (a=0.5) vs r=0.75 → axis=y（垂直溢出，只能上下拖）', () => {
  const { axis, frozen } = computeMaskAxis(400, 800, R_ACTRESS);
  assert.equal(axis, 'y');
  assert.equal(frozen, false, '800-533=267px 可拖餘裕');
});

test('computeMaskAxis〔video 比例〕1490×1000 (a=1.49) vs r=0.71 → axis=x（影片封面恆寬於窗，無 Y 軸情境）', () => {
  assert.equal(computeMaskAxis(1490, 1000, R_POSTER).axis, 'x');
});

test('computeMaskAxis〔dragExtent 恰有一個 >0〕a>r 時 dragExtentY==0；a<r 時 dragExtentX==0（軸向由兩數字落出，非另設判斷）', () => {
  // 寬圖：winH = min(H, W/r) = min(600, 1333) = 600 = H → dragExtentY = 0
  assert.equal(computeMaskAxis(1000, 600, R_ACTRESS).axis, 'x');
  // 窄圖：winW = min(W, H*r) = min(400, 600) = 400 = W → dragExtentX = 0
  assert.equal(computeMaskAxis(400, 800, R_ACTRESS).axis, 'y');
});

// ── CD-2 凍結模式 ────────────────────────────────────────────────────────────

test('computeMaskAxis〔a==r 精準相等〕600×800 (a=0.75) vs r=0.75 → 兩軸 extent 皆 0 → frozen=true', () => {
  const { frozen } = computeMaskAxis(600, 800, R_ACTRESS);
  assert.equal(frozen, true, 'a==r → dragExtentX==dragExtentY==0 → max(0,0)=0 < 2');
});

test('computeMaskAxis〔梓ヒカリ.jpg 真實案例〕322×429 = 0.7506（a>r 極微）→ frozen=true（無此模式會進 X 軸卻只能拖 ~0.4px＝死手感）', () => {
  // plan-100b CD-2 點名的實測案例（21 張女優照中的邊界圖）。
  const W = 322;
  const H = 429;
  const dragExtentX = W - Math.min(W, H * R_ACTRESS);   // 322 - 321.75 = 0.25px
  assert.ok(dragExtentX > 0, `a>r 成立（dragExtentX=${dragExtentX}px > 0），確實會被選進 X 軸`);
  assert.ok(dragExtentX < 2, `但可拖餘裕僅 ${dragExtentX}px，遠低於 2px 可用門檻`);

  const { axis, frozen } = computeMaskAxis(W, H, R_ACTRESS);
  assert.equal(axis, 'x', '軸向仍解出 x（extent 較大者），凍結不改變軸向語意');
  assert.equal(frozen, true, '🔴 凍結模式必須攔下——否則使用者進 X 軸只能拖 0.25px（spec-99 §3.3 要避免的死手感）');
});

test('computeMaskAxis〔剛好跨過門檻〕dragExtentX 略 <2px → frozen=true；略 >2px → frozen=false（門檻是 2，非 0）', () => {
  // 湊 dragExtentX = W - H*r：固定 H=400, r=0.75 → H*r=300；W=301.5 → extent=1.5px（凍結）
  assert.equal(computeMaskAxis(301.5, 400, R_ACTRESS).frozen, true, '1.5px < 2 → 凍結');
  // W=302.5 → extent=2.5px（可拖）
  assert.equal(computeMaskAxis(302.5, 400, R_ACTRESS).frozen, false, '2.5px >= 2 → 可拖');
});

test('🔴 computeMaskAxis〔凍結判定必須在 px 空間〕同一 aspect(0.7506)、不同 H（模擬 60vh 隨視窗變）→ frozen 結論不同', () => {
  // CD-2 硬需求：「必須在 px 空間判、不可用 aspect 空間的 epsilon 常數」——女優圖
  // height:60vh（plan §B-5），H 隨視窗高度變，**同一個 aspect 在不同視窗高度對應的可拖
  // 像素不同**。此測試是該需求的唯一機械證明：若把凍結判定改成 aspect-空間常數
  // （如 `Math.abs(W/H - r) < ε`），下面兩個 assert 會得到相同結論 → 必 RED。
  const ASPECT = 322 / 429;   // 0.75058...（梓ヒカリ.jpg，a>r 極微）

  // 小視窗（H=429px，如 715px 高的視窗 × 60vh）→ 可拖餘裕僅 0.25px → 凍結
  const small = computeMaskAxis(429 * ASPECT, 429, R_ACTRESS);
  assert.equal(small.frozen, true, `H=429 時可拖 ${(429 * ASPECT - 429 * R_ACTRESS).toFixed(2)}px → 凍結`);

  // 大視窗（H=2400px，如 4K 螢幕 4000px 高 × 60vh）→ **同一張圖、同一個 aspect**，
  // 可拖餘裕放大成 ~1.4px... 仍不足；拉到 H=4000 → ~2.3px → 不凍結。
  const large = computeMaskAxis(4000 * ASPECT, 4000, R_ACTRESS);
  assert.equal(large.frozen, false, `H=4000 時可拖 ${(4000 * ASPECT - 4000 * R_ACTRESS).toFixed(2)}px → 有真實拖曳空間，不可凍結`);

  // 兩者 aspect 完全相同——證明結論差異純粹來自 px 空間量測，不是來自 aspect
  assert.equal(429 * ASPECT / 429, 4000 * ASPECT / 4000, '兩案 aspect 相同（aspect-空間 ε 無法區分它們）');
  assert.notEqual(small.frozen, large.frozen, '🔴 同 aspect 不同 H → frozen 結論必須不同（px 空間判定的定義性證據）');
});

// ── G1：computeMaskWinGeometry 恆回傳 object（99a-T5 回歸鎖）────────────────

test('🔴 G1〔x 軸 writer〕computeMaskWinGeometry 回傳 object 非 string（99a-T5：字串會抹掉 x-show 的 display:none）', () => {
  const s = computeMaskWinGeometry(1000, 600, R_ACTRESS, 'x', 0.5, 0.5);
  assert.equal(typeof s, 'object', 'mutation：改回 CSS 字串模板 → 必 RED');
  assert.notEqual(s, null);
  assert.equal(typeof s.width, 'string');
  assert.equal(typeof s.height, 'string');
  assert.equal(typeof s.transform, 'string');
  assert.ok(s.transform.startsWith('translateX('), 'x 軸走 translateX');
});

test('🔴 G1〔y 軸 writer〕computeMaskWinGeometry 回傳 object 非 string（軸向分支同樣不可組字串）', () => {
  const s = computeMaskWinGeometry(400, 800, R_ACTRESS, 'y', 0.5, 0.5);
  assert.equal(typeof s, 'object', 'mutation：改回 CSS 字串模板 → 必 RED');
  assert.equal(typeof s.width, 'string');
  assert.equal(typeof s.height, 'string');
  assert.ok(s.transform.startsWith('translateY('), 'y 軸走 translateY');
});

test('computeMaskWinGeometry〔x 軸幾何〕1000×600, r=0.75, focalX=0.5 → 窗寬 450px、置中（left=275）', () => {
  const s = computeMaskWinGeometry(1000, 600, R_ACTRESS, 'x', 0.5, 0.5);
  assert.equal(s.width, '450px', 'winW = min(1000, 600*0.75) = 450');
  assert.equal(s.height, '600px', 'x 軸窗高 = 整個 render 高');
  assert.equal(s.transform, 'translateX(275px)', 'left = 0.5*1000 - 450/2 = 275（3/4 置中基準）');
});

test('computeMaskWinGeometry〔y 軸幾何〕400×800, r=0.75, focalY=0.5 → 窗高 533.33px、置中', () => {
  const s = computeMaskWinGeometry(400, 800, R_ACTRESS, 'y', 0.5, 0.5);
  assert.equal(s.width, '400px', 'y 軸窗寬 = 整個 render 寬');
  const winH = Math.min(800, 400 / R_ACTRESS);   // 533.33
  assert.equal(s.height, `${winH}px`, 'winH = min(800, 400/0.75) = 533.33');
  const top = 0.5 * 800 - winH / 2;              // 133.33
  assert.equal(s.transform, `translateY(${top}px)`);
});

// ── G5：|| 吞掉合法 numeric 0（焦點貼邊是合法值）────────────────────────────

test('🔴 G5〔focalX=0 是合法值〕臉貼最左 → 窗鉗到 left=0，不可被當 falsy 退回右裁基準', () => {
  // G5（gotchas-frontend :236-264）：`focal.x || 0.5` 會把合法的 0 變成 0.5。
  // 本函式用 `!== null && !== undefined` 判斷（非 `||`），0 必須原樣通過。
  const s = computeMaskWinGeometry(1000, 600, R_ACTRESS, 'x', 0, 0.5);
  // left = 0*1000 - 450/2 = -225 → clamp 進 [0, 550] → 0
  assert.equal(s.transform, 'translateX(0px)', 'focalX=0 → 窗貼左緣（clamp 下界）');
  // 對照：若 0 被吞掉走 fallback，left = W - winW = 550
  assert.notEqual(s.transform, 'translateX(550px)', '🔴 不可退回右裁基準（那是 focalX 為 null 時才有的行為）');
});

test('🔴 G5〔focalY=0 是合法值〕臉貼最上 → 窗鉗到 top=0，不可被當 falsy 退回基準', () => {
  const s = computeMaskWinGeometry(400, 800, R_ACTRESS, 'y', 0.5, 0);
  assert.equal(s.transform, 'translateY(0px)', 'focalY=0 → 窗貼上緣（clamp 下界）');
});

test('computeMaskWinGeometry〔focalX=null〕無焦點 → 右裁基準 left=W-winW（99a 既有語意，零回歸）', () => {
  const s = computeMaskWinGeometry(1000, 600, R_ACTRESS, 'x', null, null);
  assert.equal(s.transform, 'translateX(550px)', 'left = 1000-450 = 550（右裁基準 D2）');
});

// ── B-4：clampMaskWinLeft 數學軸無關（傳 (top,H,winH) 正確）─────────────────

test('B-4〔clamp 軸無關〕y 軸 focalY=1（臉貼最下）→ top 鉗進 [0, H-winH] 上界，不溢出', () => {
  // clampMaskWinLeft 本體是 Math.max(0, Math.min(v, max - size)) 的純量 clamp，
  // 參數只是名字像 X；傳 (top, H, winH) 完全正確（plan B-4：只改 JSDoc、不改實作，
  // 改實作會踩 focal.test.mjs:286-319 的 6 個回歸測試）。
  const s = computeMaskWinGeometry(400, 800, R_ACTRESS, 'y', 0.5, 1);
  const winH = Math.min(800, 400 / R_ACTRESS);   // 533.33
  const maxTop = 800 - winH;                     // 266.67
  // 未鉗值 = 1*800 - 533.33/2 = 533.33 → 超過上界 266.67 → 鉗回
  assert.equal(s.transform, `translateY(${maxTop}px)`, 'top 鉗進上界，窗不溢出圖外');
});

test('B-4〔clamp 軸無關〕x 軸 focalX=1（臉貼最右）→ left 鉗進 [0, W-winW] 上界（既有行為對照）', () => {
  const s = computeMaskWinGeometry(1000, 600, R_ACTRESS, 'x', 1, 0.5);
  assert.equal(s.transform, 'translateX(550px)', 'left 鉗進 W-winW=550');
});

// ── CD-7 門檻：computeMaskDragRoom ───────────────────────────────────────────

test('computeMaskDragRoom〔a < r 窄圖〕明里つむぎ a=0.7087 vs r=0.75 → 0（X 軸零溢出）', () => {
  assert.equal(computeMaskDragRoom(0.7087, R_ACTRESS), 0);
});

test('computeMaskDragRoom〔a === r 精準相等〕a=0.75 vs r=0.75 → 恆 0（不落入除法路徑算出殘值）', () => {
  assert.equal(computeMaskDragRoom(0.75, R_ACTRESS), 0, 'mutation：把 <= 改成 < → a===r 時會落入 1-r/a=0 的除法路徑，數值仍為 0 但分支覆蓋消失');
});

test('computeMaskDragRoom〔a > r 寬圖〕a=1.0 vs r=0.75 → 1 - r/a = 0.25（數值斷言，容浮點誤差）', () => {
  const result = computeMaskDragRoom(1.0, R_ACTRESS);
  assert.ok(Math.abs(result - 0.25) < 1e-6, `預期 ≈0.25，實得 ${result}`);
});

test('🔴 computeMaskDragRoom〔非有限值 fail-closed〕a=NaN/Infinity、r=NaN/0/-1 → 皆回傳 0，明確排除 NaN', () => {
  // DoD 1：不可只斷言 `=== 0`——0 和 NaN 在寬鬆比較下容易混淆，需顯式 assert.ok(!Number.isNaN(result))。
  for (const [a, r, label] of [
    [NaN, R_ACTRESS, 'a=NaN'],
    [Infinity, R_ACTRESS, 'a=Infinity'],
    [-Infinity, R_ACTRESS, 'a=-Infinity'],
    [1.0, NaN, 'r=NaN'],
    [1.0, 0, 'r=0'],
    [1.0, -1, 'r=-1'],
  ]) {
    const result = computeMaskDragRoom(a, r);
    assert.ok(!Number.isNaN(result), `${label}：result 不可為 NaN，實得 ${result}`);
    assert.equal(result, 0, `${label}：fail-closed 必回 0`);
  }
});

test('computeMaskDragRoom〔邊界真實值 + 門檻歸屬〕明里つむぎ a=0.7087 → 0（窄圖零溢出，遠低於門檻）', () => {
  const result = computeMaskDragRoom(0.7087, R_ACTRESS);
  assert.ok(Math.abs(result - 0) < 1e-6);
  assert.ok(result < MASK_MIN_DRAG_ROOM, '窄圖零溢出，不在門檻內');
});

test('computeMaskDragRoom〔邊界真實值 + 門檻歸屬〕gfriends a=0.8261 → ≈0.0921，斷言 < MASK_MIN_DRAG_ROOM（不在門檻內）', () => {
  const result = computeMaskDragRoom(0.8261, R_ACTRESS);
  assert.ok(Math.abs(result - 0.0921) < 1e-4, `預期 ≈0.0921，實得 ${result}`);
  // 🔴 門檻歸屬必須直接 import MASK_MIN_DRAG_ROOM 比較，不可硬編 0.20 字面
  // （否則 DoD 4 的 mutation：0.20→0.05 測不出——這條斷言在 mutation 下會單獨翻面 RED）。
  assert.ok(result < MASK_MIN_DRAG_ROOM, 'gfriends 不在門檻內（0.0921 < 0.20）');
});

test('computeMaskDragRoom〔邊界真實值 + 門檻歸屬〕方形 a=1.0 → 0.25，斷言 >= MASK_MIN_DRAG_ROOM（在門檻內）', () => {
  const result = computeMaskDragRoom(1.0, R_ACTRESS);
  assert.ok(Math.abs(result - 0.25) < 1e-6);
  assert.ok(result >= MASK_MIN_DRAG_ROOM, '方形在門檻內（0.25 >= 0.20）');
});

test('computeMaskDragRoom〔邊界真實值 + 門檻歸屬〕二葉エマ a=1.4986 → ≈0.4995，斷言 >= MASK_MIN_DRAG_ROOM（在門檻內）', () => {
  const result = computeMaskDragRoom(1.4986, R_ACTRESS);
  assert.ok(Math.abs(result - 0.4995) < 1e-4, `預期 ≈0.4995，實得 ${result}`);
  assert.ok(result >= MASK_MIN_DRAG_ROOM, '二葉エマ在門檻內（0.4995 >= 0.20）');
});

test('computeMaskDragRoom〔尺度無關〕同一 a 由不同 (W,H) 絕對值算出 → 回傳值相同（CD-7 承重）', () => {
  const aFromSmall = 1000 / 600;   // ≈1.6667
  const aFromLarge = 2000 / 1200;  // 同比值，不同絕對像素
  assert.equal(aFromSmall, aFromLarge, '兩組 (W,H) 算出相同比值（前提）');

  const resultSmall = computeMaskDragRoom(aFromSmall, R_ACTRESS);
  const resultLarge = computeMaskDragRoom(aFromLarge, R_ACTRESS);
  assert.equal(resultSmall, resultLarge, '🔴 同一 a 不同絕對 W/H 來源 → drag room 必須相同（尺度無關，簽名吃 a 的結構保證）');
});
