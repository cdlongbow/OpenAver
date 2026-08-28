/**
 * motion-guard.test.mjs — scripts/motion_guard_lint.mjs 的守衛測試（TASK-133a-T4 / CD-133a-6）
 *
 * 雙向矩陣（FE-GUARD-17）：
 *  - 紅色半邊（R1–R2）：spec AC-3.1 要求的兩種寫法（未登記 CSS / 未登記 JS）各自單獨 RED
 *  - 綠色半邊（G1–G6）：有限次數、註解干擾、字串字面、word boundary 等合法寫法不得誤擋
 *  - 對帳半邊（A1–A2）：殘留白名單條目報錯 ＋ 真 repo regression
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const GUARD_PATH = join(__dirname, '..', 'motion_guard_lint.mjs');
const REPO_ROOT = join(__dirname, '..', '..');

function runGuard(root) {
  const args = root ? [GUARD_PATH, root] : [GUARD_PATH];
  const result = spawnSync(process.execPath, args, { encoding: 'utf8' });
  return { ...result, output: `${result.stdout}\n${result.stderr}` };
}

function writeAt(root, rel, content) {
  const abs = join(root, ...rel.split('/'));
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, content, 'utf8');
  return abs;
}

// ============================================================================
// 紅色半邊（R1–R2）
// ============================================================================

test('〔R1〕未登記的無限 CSS 動畫 → RED (MG-CSS-01)', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    writeAt(
      root,
      'web/static/css/pages/unregistered.css',
      '.unregistered { animation: foo 1s linear infinite; }',
    );
    const r = runGuard(root);
    assert.notEqual(r.status, 0, '未登記的無限 CSS 動畫必須 exit !== 0');
    assert.match(r.output, /MG-CSS-01/);
    assert.match(r.output, /未登記的無限 CSS 動畫/);
    assert.match(r.output, /unregistered\.css/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('〔R2〕未登記的 repeat: -1 JS 動畫 → RED (MG-JS-01)', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    writeAt(
      root,
      'web/static/js/shared/unregistered.js',
      'const tl = gsap.timeline({ repeat: -1 });',
    );
    const r = runGuard(root);
    assert.notEqual(r.status, 0, '未登記的 repeat: -1 JS 動畫必須 exit !== 0');
    assert.match(r.output, /MG-JS-01/);
    assert.match(r.output, /未登記的 repeat: -1 動畫/);
    assert.match(r.output, /unregistered\.js/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// ============================================================================
// 綠色半邊（G1–G6，不得從守衛自己的碼反推，照卡片逐條寫）
// ============================================================================

test('〔G1〕animation-iteration-count: 3 (有限次數) → GREEN', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    writeAt(
      root,
      'web/static/css/test.css',
      '.spin-three { animation-iteration-count: 3; }',
    );
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('〔G2〕CSS 註解內含 infinite (FE-GUARD-03) → GREEN', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    writeAt(
      root,
      'web/static/css/test.css',
      '/* 這裡本來是 infinite */\n.btn { color: red; }\n/* animation: spin 1s infinite; */',
    );
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('〔G3〕JS 註解內含 repeat: -1 → GREEN', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    writeAt(
      root,
      'web/static/js/test.js',
      '// repeat: -1 會洩漏\n/* repeat: -1 */\nconst a = 1;',
    );
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('〔G4〕JS 字串字面 const s = "repeat: -1" → GREEN', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    writeAt(
      root,
      'web/static/js/test.js',
      "const s = 'repeat: -1';\nconst config = { label: 'repeat: -1' };",
    );
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('〔G5〕gsap.timeline({ repeat: 3 }) (有限次數) → GREEN', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    writeAt(
      root,
      'web/static/js/test.js',
      'gsap.timeline({ repeat: 3 });\ngsap.to(".elem", { repeat: 5 });',
    );
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('〔G6〕class 名叫 infinite-scroll 或動畫名含 infinite 但次數有限 (word boundary) → GREEN', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    writeAt(
      root,
      'web/static/css/test.css',
      [
        '.infinite-scroll { animation: scroll-left 10s linear; }',
        '.infinite-bar { animation: bar-move 2s ease 1; }',
        '.card { animation: infinite-slide 3s linear 3; }',
        '.box { animation-name: infinite-pulse; animation-duration: 2s; }',
      ].join('\n'),
    );
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// ============================================================================
// 對帳半邊（A1–A2）＋ 邊界測試
// ============================================================================

test('〔A1〕白名單有登記但檔案內未掃到（殘留條目）→ RED', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    writeAt(
      root,
      'web/static/css/components/rotating-border.css',
      '/* 動畫已移除，檔案內已無 rotate-spotlight infinite 動畫 */\n.box { color: blue; }',
    );
    const r = runGuard(root);
    assert.notEqual(r.status, 0, '白名單有殘留條目必須 exit !== 0');
    assert.match(r.output, /白名單有殘留條目，請刪掉/);
    assert.match(r.output, /rotating-border\.css/);
    assert.match(r.output, /rotate-spotlight/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('〔A2〕真 repo regression → GREEN (今天的 14 CSS + 6 JS 全部登記到位)', () => {
  const r = runGuard(REPO_ROOT);
  assert.equal(r.status, 0, r.output);
  assert.match(r.output, /對帳一致/);
  assert.match(r.output, /CSS 10 條 \/ 14 處/);
  assert.match(r.output, /JS 5 條 \/ 6 處/);
});

test('〔額外-1〕CSS 筆數不符 → RED', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    // source-pill.css 白名單登記 count: 3，此處只提供 1 筆
    writeAt(
      root,
      'web/static/css/components/source-pill.css',
      '.pill { animation: source-pill-spin 0.6s linear infinite; }',
    );
    const r = runGuard(root);
    assert.notEqual(r.status, 0);
    assert.match(r.output, /筆數不符/);
    assert.match(r.output, /source-pill-spin/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('〔額外-2〕JS 筆數不符 → RED', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    // breathing.js 白名單登記 count: 2，此處只提供 1 筆
    writeAt(
      root,
      'web/static/js/shared/constellation/breathing.js',
      'const tl = gsap.timeline({ repeat: -1 });',
    );
    const r = runGuard(root);
    assert.notEqual(r.status, 0);
    assert.match(r.output, /筆數不符/);
    assert.match(r.output, /breathing\.js/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('〔額外-3〕JS 語法錯誤 fail-closed → RED', () => {
  const root = mkdtempSync(join(tmpdir(), 'motion-guard-'));
  try {
    writeAt(
      root,
      'web/static/js/broken.js',
      'const a = ; // 語法錯誤',
    );
    const r = runGuard(root);
    assert.notEqual(r.status, 0);
    assert.match(r.output, /MG-JS-01/);
    assert.match(r.output, /espree failed to parse/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
