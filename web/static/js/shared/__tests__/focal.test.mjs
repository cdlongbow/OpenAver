// focal.test.mjs — parseFocal / focalObjectPosition / focalCellObjectPosition 純函式守衛
// （98b-T1 + 99a-T2）。零新依賴：Node 內建 node:test + node:assert/strict。跑：npm test（glob 涵蓋本檔）。
//
// 守 parseFocal 與 Python core/focal/detector.py::parse_focal 同粒度契約
// （falsy→null；恰 2 段；空段/非數/非有限→null；閉區間 [0,1]²；否則 null）。
// 守 focalObjectPosition 的 crop_mode gate（auto/manual）+ parse gate + deadzone gate（auto only）
// + .toFixed(2) 格式。
// 守 focalCellObjectPosition（99a-T2 §1 aspect-aware 公式）的 crop_mode gate / parse gate /
// a≤r gate / deadzone gate（auto only）/ clamp / by-construction 與遮罩幾何一致性。
// 含 mutation 案（越界 clamp、deadzone 判斷、a≤r 邊界）：放寬/拔掉必 RED。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const { FOCAL_X_DEADZONE, parseFocal, focalObjectPosition, focalCellObjectPosition, clampMaskWinLeft } =
  await import('../focal.js');

// ── parseFocal（鏡射 parse_focal 同粒度） ─────────────────────────────────


test('parseFocal〔空段〕"0.5," → null（JS Number("")===0 陷阱須擋）', () => {
  assert.equal(parseFocal('0.5,'), null);
  assert.equal(parseFocal(',0.5'), null);
  assert.equal(parseFocal('0.5, '), null);  // 純空白段
});


// ── focalObjectPosition（crop_mode gate + parse + deadzone + 格式） ────────


test('focalObjectPosition〔auto + x<deadzone〕"0.3820,0.5000" → "38.20% center"（只 X、Y=center、.toFixed(2)）', () => {
  assert.equal(
    focalObjectPosition({ crop_mode: 'auto', auto_focal: '0.3820,0.5000' }),
    '38.20% center',
  );
});


// ── focalObjectPosition〔manual 分支〕（99a-T2 §1.5 spec §7 缺口補完）────────


test('focalObjectPosition〔manual 對照 auto〕同一 x=0.70：manual 非 null、auto null（deadzone 只對 auto 生效，mutation 抓點）', () => {
  const manualResult = focalObjectPosition({ crop_mode: 'manual', auto_focal: '0.7000,0.5000' });
  const autoResult = focalObjectPosition({ crop_mode: 'auto', auto_focal: '0.7000,0.5000' });
  assert.notEqual(manualResult, null);
  assert.equal(autoResult, null);
});


// ── focalCellObjectPosition（99a-T2 §1 aspect-aware 公式 + §4 邊界表）─────────
//
// 公式（card §1，a>r 且未被 gate 擋下）：
//   objPos = clamp((x − r/(2a)) / (1 − r/a), 0, 1)
// 以下 REF_* 是測試內鏡射同一公式的獨立計算，用來：
//   (1) 產生非硬編的 expected 值（非簡單複製實作字面）
//   (2) 驗證「回傳值 ≠ raw x%」（mutation 抓點：若實作退化回 raw x%，這條必 RED）

function refCellFormula(x, a, r) {
  const v = r / a;
  const raw = (x - v / 2) / (1 - v);
  const clamped = Math.max(0, Math.min(1, raw));
  return `${(clamped * 100).toFixed(2)}% center`;
}

const A = 1.49; // 典型 poster 圖片 naturalWidth/naturalHeight（16:9-ish demo 值，非 --poster-crop-ratio）
const R = 0.71; // --poster-crop-ratio 單一真理值（theme.css:561）


test('focalCellObjectPosition〔偏側 x 算對〕x=0.30, a=1.49, r=0.71 → 依公式算出，非等於 raw 30.00%（mutation 抓點）', () => {
  const result = focalCellObjectPosition({ crop_mode: 'auto', auto_focal: '0.3000,0.5000' }, A, R);
  assert.notEqual(result, '30.00% center');
  assert.equal(result, refCellFormula(0.30, A, R));
});


// ── CD-7〔空操作證明〕女優型資料（manual 模式）在 x 分支不會被 deadzone 攔下 ──
// 不改 focal.js 的 deadzone 邏輯（:94 維持原樣）——本節只證明現有結構已保證「女優打不到它」。


test('focalCellObjectPosition〔a==r〕a=0.71 == r=0.71 → null（a<=r 恆 null 的子情況，函式須顯式擋下，不可讓反向公式意外算出 NaN%）', () => {
  assert.equal(
    focalCellObjectPosition({ crop_mode: 'auto', auto_focal: '0.3000,0.5000' }, 0.71, 0.71),
    null,
  );
});


test('focalCellObjectPosition〔clamp 下界〕x=0（極端左）→ clamp 進 0 → "0.00% center"', () => {
  assert.equal(
    focalCellObjectPosition({ crop_mode: 'manual', auto_focal: '0.0000,0.5000' }, A, R),
    '0.00% center',
  );
});


// ── by-construction：小格 objPos% 換算的可見窗中心 應與遮罩換算的可見窗中心一致 ──
// 鏡射 state-lightbox.js:867-892 的像素空間算法（正規化 W=1），驗證兩套機制對同一
// (x, a, r) 算出「所見即所得」（不做像素級 CDP 驗收，計算層一致性即可，見 card §1）。

function maskWindowCenterFraction(x, a, r) {
  const W = 1;
  const H = W / a;
  const winW = Math.min(W, H * r);
  let left = x * W - winW / 2;
  left = Math.max(0, Math.min(left, W - winW));
  return (left + winW / 2) / W;
}

function cellWindowCenterFraction(objPosStr, a, r) {
  const p = parseFloat(objPosStr) / 100;
  const v = r / a;
  return p * (1 - v) + v / 2;
}


// ── clampMaskWinLeft（99a Gemini P2：拖曳死區）────────────────────────────
// 語意：把窗左緣鉗進 [0, W - winW]。render / dragStart / onMove 三處共用。


// 死區本體：raw x 貼右緣（0.95）算出的起手左緣落在界外 → 必須被鉗回視覺位置，
// 否則反向拖曳要先吃掉 (unclamped - clamped) 差值才會動（此案約封面寬 17%）。
test('clampMaskWinLeft〔死區回歸〕raw x=0.95 的起手左緣鉗回視覺右界（差值即原死區寬）', () => {
  const W = 1000;
  const winW = 444;
  const unclamped = 0.95 * W - winW / 2;          // 728 — 界外
  const clamped = clampMaskWinLeft(unclamped, W, winW);
  assert.equal(clamped, W - winW);                 // 556 ＝ 視覺上窗子實際停的位置
  assert.ok(unclamped - clamped > 0.17 * W);       // 未修版的死區寬 > 封面 17%
});

