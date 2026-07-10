#!/usr/bin/env node
/**
 * static_guard_lint.mjs — 靜態文字契約 linter（96b-T1，zero-dep）
 *
 * 表驅動引擎：`RULES` 陣列（{file, kind, pattern, anyOf?, scope?, count?, note}）+
 * `evalRule(rule, ROOT)` dispatcher。取代 test_frontend_lint.py 大量「某字串必存在／
 * 必不存在」的純字串/regex class（north-star：能用 lint 機械處理的不進 pytest、不耗
 * Codex 審）。
 *
 * 本 task（T1）只開兩種 kind：
 *   - required-string：`pattern` 必須出現（`anyOf: true` 時陣列只需其一命中；
 *     `count` 給定時要求出現次數 ≥ count；預設 1）
 *   - forbidden-string：`pattern` 不得出現
 * 兩者皆支援可選 `scope`（RegExp）：先用 scope 抽出 match[1]（無 group 則 match[0]）
 * 子字串範圍，pattern 只在該範圍內檢查。scope anchor 找不到＝獨立錯誤（不可誤判為
 * pattern 缺席／forbidden 通過）。
 *
 * `file` 欄支援單檔路徑字串，或 `{dir, ext: string[]}` 目錄變體（非遞迴掃描，
 * 複刻 pytest `glob("*.html")` 排除子目錄語意，NoVanillaHandlers 需要）。
 *
 * kind 集合預留 dup-id / structure-count / tag-scan / inline-style-token / order
 * 分支位置給 T2、ESM 家族給 T3，本 task 不實作（switch 落到 default 丟錯）。
 *
 * 用法：
 *   node scripts/static_guard_lint.mjs                 # 掃真 repo
 *   node scripts/static_guard_lint.mjs <scratch-root>   # 掃 scratch 副本（供 mutation 自驗）
 *
 * 非 pytest（遵 CLAUDE.md「lint 守衛寫 lint config、不寫 pytest」）。串 `npm run lint`。
 */

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dirname, '..');

// ---- args：scratch-root 覆蓋（比照 i18n_lint.mjs 的 argv.find 拆 flag 與 path）----
const argv = process.argv.slice(2);
const rootArg = argv.find((a) => !a.startsWith('--'));
const ROOT = rootArg ? resolve(rootArg) : REPO_ROOT;

// ---- RULES ----
// note 一律標明來源 class（供 T6 對照表直接引用）。
const RULES = [
  // ---- [TestShowcaseMetadataGuard] showcase.html：10 個 all-of required + 1 個 any-of ----
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: 'video.series', note: '[TestShowcaseMetadataGuard] metadata binding' },
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: 'video.duration', note: '[TestShowcaseMetadataGuard] metadata binding' },
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: 'video.director', note: '[TestShowcaseMetadataGuard] metadata binding' },
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: 'table-cell-duration', note: '[TestShowcaseMetadataGuard] metadata binding' },
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: 'currentLightboxVideo?.director', note: '[TestShowcaseMetadataGuard] lightbox field' },
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: 'currentLightboxVideo?.duration', note: '[TestShowcaseMetadataGuard] lightbox field' },
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: 'currentLightboxVideo?.series', note: '[TestShowcaseMetadataGuard] lightbox field' },
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: 'currentLightboxVideo?.label', note: '[TestShowcaseMetadataGuard] lightbox field' },
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: 'lb-details', note: '[TestShowcaseMetadataGuard] lightbox field' },
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: "searchFromMetadata(currentLightboxVideo?.director)", note: '[TestShowcaseMetadataGuard] searchFromMetadata call' },
  {
    file: 'web/templates/showcase.html', kind: 'required-string', anyOf: true,
    pattern: ["searchFromMetadata(video.series)", "searchFromMetadata(currentLightboxVideo?.series)"],
    note: '[TestShowcaseMetadataGuard] series searchFromMetadata call (grid panel or lightbox, OR)',
  },

  // ---- [TestSearchLightboxMetadataGuard] search.html：5 個 required ----
  { file: 'web/templates/search.html', kind: 'required-string', pattern: 'currentLightboxVideo()?.director', note: '[TestSearchLightboxMetadataGuard] lightbox field' },
  { file: 'web/templates/search.html', kind: 'required-string', pattern: 'currentLightboxVideo()?.duration', note: '[TestSearchLightboxMetadataGuard] lightbox field' },
  { file: 'web/templates/search.html', kind: 'required-string', pattern: 'currentLightboxVideo()?.series', note: '[TestSearchLightboxMetadataGuard] lightbox field' },
  { file: 'web/templates/search.html', kind: 'required-string', pattern: 'currentLightboxVideo()?.label', note: '[TestSearchLightboxMetadataGuard] lightbox field' },
  { file: 'web/templates/search.html', kind: 'required-string', pattern: 'lb-details', note: '[TestSearchLightboxMetadataGuard] lightbox field' },

  // ---- [TestShowcaseHeroCard] required 半邊 + forbidden（同批簡單字串）+ animations.js required ----
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: 'hero-card', note: '[TestShowcaseHeroCard] hero card structure' },
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: "t('common.no_image')", note: '[TestShowcaseHeroCard] hero card structure' },
  { file: 'web/templates/showcase.html', kind: 'required-string', pattern: "searchFromMetadata(actress.trim(), 'actress')", note: '[TestShowcaseHeroCard] hero card structure' },
  { file: 'web/templates/showcase.html', kind: 'forbidden-string', pattern: '<span>No Image</span>', note: '[TestShowcaseHeroCard] retired no-image markup' },
  { file: 'web/static/js/pages/showcase/animations.js', kind: 'required-string', pattern: 'playHeroCardAppear', note: '[TestShowcaseHeroCard] animations.js' },

  // ---- [TestNoVanillaHandlers] web/templates/*.html（非遞迴，天然排除 design_system/） ----
  {
    file: { dir: 'web/templates', ext: ['.html'] },
    kind: 'forbidden-string',
    pattern: /(?<=\s)on(?:click|change|submit|keydown|input)\s*=\s*["']/i,
    note: '[TestNoVanillaHandlers] no inline vanilla event handler',
  },

  // ---- [TestActressIconGuard] ----
  {
    file: 'web/templates/showcase.html', kind: 'forbidden-string',
    pattern: /class="bi bi-person(?!-circle|-heart)"/,
    note: '[TestActressIconGuard] showcase.html bi-person (non circle/heart)',
  },
  { file: 'web/templates/scanner.html', kind: 'forbidden-string', pattern: 'bi-person-badge', note: '[TestActressIconGuard] scanner.html bi-person-badge' },

  // ---- [TestSwitchSourceBtnRemoved] ----
  { file: 'web/templates/search.html', kind: 'forbidden-string', pattern: 'id="switchSourceBtn"', note: '[TestSwitchSourceBtnRemoved] switchSourceBtn id gone' },
  {
    file: 'web/templates/search.html', kind: 'forbidden-string',
    pattern: 'bi-arrow-repeat',
    scope: /<div class="av-card-full-header">([\s\S]*?)<\/div>\s*<div class="av-card-full-(?:title|body)">/,
    note: '[TestSwitchSourceBtnRemoved] bi-arrow-repeat gone from .av-card-full-header scope',
  },

  // ---- [TestSearchSubmitBtnNoLongPress]（scoped forbidden ×4） ----
  { file: 'web/templates/search.html', kind: 'forbidden-string', pattern: 'longPressStart', scope: /<button\b[^>]*\bid="btnSubmit"[^>]*>/, note: '[TestSearchSubmitBtnNoLongPress] #btnSubmit tag no long-press' },
  { file: 'web/templates/search.html', kind: 'forbidden-string', pattern: 'longPressEnd', scope: /<button\b[^>]*\bid="btnSubmit"[^>]*>/, note: '[TestSearchSubmitBtnNoLongPress] #btnSubmit tag no long-press' },
  { file: 'web/templates/search.html', kind: 'forbidden-string', pattern: 'longPressCancel', scope: /<button\b[^>]*\bid="btnSubmit"[^>]*>/, note: '[TestSearchSubmitBtnNoLongPress] #btnSubmit tag no long-press' },
  { file: 'web/templates/search.html', kind: 'forbidden-string', pattern: 'longPressClickGuard', scope: /<button\b[^>]*\bid="btnSubmit"[^>]*>/, note: '[TestSearchSubmitBtnNoLongPress] #btnSubmit tag no long-press' },

  // ---- [TestUS1IdPreserved] ----
  { file: 'web/templates/search.html', kind: 'required-string', pattern: 'id="resultActors"', note: '[TestUS1IdPreserved] result id preserved' },
  { file: 'web/templates/search.html', kind: 'required-string', pattern: 'id="resultDate"', note: '[TestUS1IdPreserved] result id preserved' },
  { file: 'web/templates/search.html', kind: 'required-string', pattern: 'id="resultMaker"', note: '[TestUS1IdPreserved] result id preserved' },
  { file: 'web/templates/search.html', kind: 'required-string', pattern: 'id="resultTags"', note: '[TestUS1IdPreserved] result id preserved' },

  // ---- [TestUS1FooterClassRemoved]（forbidden wrapper + required 子 class，互補） ----
  { file: 'web/templates/search.html', kind: 'forbidden-string', pattern: 'class="av-card-full-footer"', note: '[TestUS1FooterClassRemoved] wrapper renamed, must not remain' },
  { file: 'web/templates/search.html', kind: 'required-string', pattern: 'class="av-card-full-footer-content"', note: '[TestUS1FooterClassRemoved] child class must survive (not over-deleted)' },

  // ---- [TestDesignSystemLongPressCard]（3 個 forbidden） ----
  { file: 'web/templates/design_system/settings-components.html', kind: 'forbidden-string', pattern: 'D.14', note: '[TestDesignSystemLongPressCard] D.14 long-press demo card retired' },
  { file: 'web/templates/design_system/settings-components.html', kind: 'forbidden-string', pattern: 'longPressStart', note: '[TestDesignSystemLongPressCard] D.14 long-press demo card retired' },
  { file: 'web/templates/design_system/settings-components.html', kind: 'forbidden-string', pattern: 'long-press.js', note: '[TestDesignSystemLongPressCard] D.14 long-press demo card retired' },

  // ---- [TestGridSettlePulse]（只港 flat required 半邊，method-body window 半邊留 T2） ----
  { file: 'web/static/js/pages/search/animations.js', kind: 'required-string', pattern: 'playGridSettle', note: '[TestGridSettlePulse] animations.js flat required (method-body window half deferred to T2)' },
  { file: 'web/static/js/pages/search/animations.js', kind: 'required-string', pattern: 'CustomEase.create("settle"', note: '[TestGridSettlePulse] animations.js flat required (method-body window half deferred to T2)' },

  // ---- [TestFetchAbortController]（純 flat required，含 count-based） ----
  { file: 'web/static/js/pages/search/state/base.js', kind: 'required-string', pattern: '_abortControllers: {}', note: '[TestFetchAbortController] base.js abort state' },
  { file: 'web/static/js/pages/search/state/search-flow.js', kind: 'required-string', pattern: '_getAbortSignal(', note: '[TestFetchAbortController] search-flow.js abort methods' },
  { file: 'web/static/js/pages/search/state/search-flow.js', kind: 'required-string', pattern: '_abortAllFetches(', note: '[TestFetchAbortController] search-flow.js abort methods' },
  { file: 'web/static/js/pages/search/state/search-flow.js', kind: 'required-string', pattern: '_abortAllFetches()', note: '[TestFetchAbortController] search-flow.js abort methods' },
  { file: 'web/static/js/pages/search/state/navigation.js', kind: 'required-string', pattern: "_getAbortSignal('loadMore')", note: '[TestFetchAbortController] navigation.js signal usage' },
  { file: 'web/static/js/pages/search/state/navigation.js', kind: 'required-string', pattern: 'AbortError', note: '[TestFetchAbortController] navigation.js AbortError handling' },
  { file: 'web/static/js/pages/search/state/batch.js', kind: 'required-string', pattern: "_getAbortSignal('translateAll')", note: '[TestFetchAbortController] batch.js signal usage' },
  { file: 'web/static/js/pages/search/state/batch.js', kind: 'required-string', pattern: 'AbortError', note: '[TestFetchAbortController] batch.js AbortError handling' },
  { file: 'web/static/js/pages/search/state/file-list.js', kind: 'required-string', pattern: "_getAbortSignal('setFileList')", note: '[TestFetchAbortController] file-list.js signal usage' },
  { file: 'web/static/js/pages/search/state/file-list.js', kind: 'required-string', pattern: "_getAbortSignal('loadFavorite')", note: '[TestFetchAbortController] file-list.js signal usage' },
  { file: 'web/static/js/pages/search/state/file-list.js', kind: 'required-string', pattern: 'AbortError', count: 2, note: '[TestFetchAbortController] file-list.js AbortError x2 (count-based, precise)' },

  // ---- [TestTimerTracking]（只港 required 半邊，禁半邊刻意不建網） ----
  { file: 'web/static/js/pages/search/state/base.js', kind: 'required-string', pattern: '_timers: {}', note: '[TestTimerTracking] base.js timer registry' },
  { file: 'web/static/js/pages/search/state/search-flow.js', kind: 'required-string', pattern: '_setTimer(', note: '[TestTimerTracking] search-flow.js timer methods' },
  { file: 'web/static/js/pages/search/state/search-flow.js', kind: 'required-string', pattern: '_clearAllTimers(', note: '[TestTimerTracking] search-flow.js timer methods' },
  { file: 'web/static/js/pages/search/state/search-flow.js', kind: 'required-string', pattern: '_clearAllTimers()', note: '[TestTimerTracking] search-flow.js timer methods' },
  { file: 'web/static/js/pages/search/state/result-card.js', kind: 'required-string', pattern: "_setTimer('toast'", note: '[TestTimerTracking] result-card.js timer' },
  { file: 'web/static/js/pages/search/state/persistence.js', kind: 'required-string', pattern: "_setTimer('autosave'", note: '[TestTimerTracking] persistence.js timer' },
  { file: 'web/static/js/pages/search/state/file-list.js', kind: 'required-string', pattern: "_setTimer('loadFavorite'", note: '[TestTimerTracking] file-list.js timer' },

  // ---- [TestTutorialExpandGuard]（handoff 96a→96b，7 個 step-id required） ----
  { file: 'web/static/js/components/tutorial.js', kind: 'required-string', pattern: "id: 'folder'", note: '[TestTutorialExpandGuard] tutorial step id' },
  { file: 'web/static/js/components/tutorial.js', kind: 'required-string', pattern: "id: 'generate'", note: '[TestTutorialExpandGuard] tutorial step id' },
  { file: 'web/static/js/components/tutorial.js', kind: 'required-string', pattern: "id: 'scanner'", note: '[TestTutorialExpandGuard] tutorial step id' },
  { file: 'web/static/js/components/tutorial.js', kind: 'required-string', pattern: "id: 'showcase'", note: '[TestTutorialExpandGuard] tutorial step id' },
  { file: 'web/static/js/components/tutorial.js', kind: 'required-string', pattern: "id: 'search'", note: '[TestTutorialExpandGuard] tutorial step id' },
  { file: 'web/static/js/components/tutorial.js', kind: 'required-string', pattern: "id: 'settings'", note: '[TestTutorialExpandGuard] tutorial step id' },
  { file: 'web/static/js/components/tutorial.js', kind: 'required-string', pattern: "id: 'help'", note: '[TestTutorialExpandGuard] tutorial step id' },
];

// ---- helpers ----
let hadError = false;
function err(msg) {
  console.error(`✗ static_guard_lint: ${msg}`);
  hadError = true;
}

const fileCache = new Map();
function readTarget(relPath) {
  const full = join(ROOT, relPath);
  if (fileCache.has(full)) return fileCache.get(full);
  let text;
  try {
    text = readFileSync(full, 'utf8');
  } catch (e) {
    fileCache.set(full, null);
    return null;
  }
  fileCache.set(full, text);
  return text;
}

// 非遞迴目錄掃描（複刻 pytest glob("*.html") 排除子目錄語意，NoVanillaHandlers 需要）
function listDirFiles(relDir, exts) {
  const full = join(ROOT, relDir);
  let entries;
  try {
    entries = readdirSync(full, { withFileTypes: true });
  } catch {
    return null; // 目錄本身讀取失敗
  }
  return entries
    .filter((e) => e.isFile() && exts.some((ext) => e.name.endsWith(ext)))
    .map((e) => join(relDir, e.name));
}

function countOccurrences(haystack, pattern) {
  if (pattern instanceof RegExp) {
    const flags = pattern.flags.includes('g') ? pattern.flags : pattern.flags + 'g';
    const re = new RegExp(pattern.source, flags);
    let n = 0;
    while (re.exec(haystack) !== null) n += 1;
    return n;
  }
  let n = 0;
  let i = haystack.indexOf(pattern);
  while (i !== -1) {
    n += 1;
    i = haystack.indexOf(pattern, i + pattern.length);
  }
  return n;
}

function matches(haystack, pattern) {
  if (pattern instanceof RegExp) return pattern.test(haystack);
  return haystack.includes(pattern);
}

function patternLabel(pattern) {
  return pattern instanceof RegExp ? pattern.toString() : JSON.stringify(pattern);
}

// ---- evalRule dispatcher ----
function evalRule(rule, text, fileLabel) {
  switch (rule.kind) {
    case 'required-string':
      evalRequiredString(rule, text, fileLabel);
      break;
    case 'forbidden-string':
      evalForbiddenString(rule, text, fileLabel);
      break;
    // 預留給 T2/T3：分支位置保留、不實作（骨架須通用可擴，CD-96b-11）
    case 'dup-id':
    case 'structure-count':
    case 'tag-scan':
    case 'inline-style-token':
    case 'order':
    default:
      throw new Error('kind not implemented: ' + rule.kind);
  }
}

function resolveScope(rule, text, fileLabel) {
  if (!rule.scope) return { scopedText: text, ok: true };
  const m = rule.scope.exec(text);
  if (!m) {
    err(`${rule.note} — ${fileLabel}: scope anchor 找不到（regex ${rule.scope} 無匹配，非 pattern 缺席）`);
    return { scopedText: null, ok: false };
  }
  const scopedText = m.length > 1 && m[1] !== undefined ? m[1] : m[0];
  return { scopedText, ok: true };
}

function evalRequiredString(rule, text, fileLabel) {
  const { scopedText, ok } = resolveScope(rule, text, fileLabel);
  if (!ok) return; // scope anchor 錯誤已回報，不繼續誤判 pattern 缺席

  const patterns = Array.isArray(rule.pattern) ? rule.pattern : [rule.pattern];

  if (rule.anyOf) {
    const hit = patterns.some((p) => matches(scopedText, p));
    if (!hit) {
      err(`${rule.note} — ${fileLabel}: any-of 全未命中（需其一）：${patterns.map(patternLabel).join(' OR ')}`);
    }
    return;
  }

  for (const p of patterns) {
    if (rule.count !== undefined) {
      const n = countOccurrences(scopedText, p);
      if (n < rule.count) {
        err(`${rule.note} — ${fileLabel}: 出現次數 ${n} < 要求 ${rule.count}：${patternLabel(p)}`);
      }
    } else if (!matches(scopedText, p)) {
      err(`${rule.note} — ${fileLabel}: 缺少必要字串/pattern：${patternLabel(p)}`);
    }
  }
}

function evalForbiddenString(rule, text, fileLabel) {
  const { scopedText, ok } = resolveScope(rule, text, fileLabel);
  if (!ok) return; // scope anchor 錯誤已回報

  const patterns = Array.isArray(rule.pattern) ? rule.pattern : [rule.pattern];
  for (const p of patterns) {
    if (matches(scopedText, p)) {
      err(`${rule.note} — ${fileLabel}: 不應出現卻出現：${patternLabel(p)}`);
    }
  }
}

// ---- main ----
for (const rule of RULES) {
  if (typeof rule.file === 'string') {
    const text = readTarget(rule.file);
    if (text === null) {
      err(`${rule.note} — ${rule.file}: 檔案不存在或無法讀取`);
      continue;
    }
    evalRule(rule, text, rule.file);
  } else {
    const { dir, ext } = rule.file;
    const files = listDirFiles(dir, ext);
    if (files === null) {
      err(`${rule.note} — ${dir}: 目錄不存在或無法讀取`);
      continue;
    }
    for (const relPath of files) {
      const text = readTarget(relPath);
      if (text === null) {
        err(`${rule.note} — ${relPath}: 檔案不存在或無法讀取`);
        continue;
      }
      evalRule(rule, text, relPath);
    }
  }
}

if (hadError) {
  process.exit(1);
}
console.log(`✓ static_guard_lint: ${RULES.length} 條規則全數通過（required-string/forbidden-string，含 any-of/scope/count）`);
