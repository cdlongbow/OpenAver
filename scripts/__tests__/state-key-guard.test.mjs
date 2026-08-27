/**
 * state-key-guard.test.mjs — `scripts/state_key_guard.mjs` 黑箱測試（plan-131a T3）
 *
 * 手法比照 `scripts/__tests__/vendor-guard.test.mjs`：`mkdtempSync` 建 scratch root、
 * `spawnSync` 黑箱跑守衛、斷言 exit code 與合併後的 stdout+stderr。
 *
 * 覆蓋 TASK-131a-T3 案例清單：正向 6、反向 4、基準 1、fail-closed 14 子案例、
 * 箭頭函式 2、real-repo 4。共 31 個 test()。
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import {
  mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, cpSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { collectPages } from '../lib/alpine-state.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const GUARD_PATH = join(__dirname, '..', 'state_key_guard.mjs');
const REPO_ROOT = join(__dirname, '..', '..');

const PAGES = ['showcase', 'search', 'scanner', 'settings'];

const REGRESSION_KEYS = [
  'lightboxOpen',
  'lightboxIndex',
  'lightboxCloseTimer',
  '_lightboxAnimating',
  '_lightboxGeneration',
];

function runGuard(root) {
  const args = root ? [GUARD_PATH, root] : [GUARD_PATH];
  const result = spawnSync(process.execPath, args, { encoding: 'utf8' });
  return { ...result, output: `${result.stdout}\n${result.stderr}` };
}

function writeAt(root, rel, content) {
  const abs = join(root, ...rel.split('/'));
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, content);
  return abs;
}

function defaultImports(extra = {}) {
  return {
    '@/shared/': '/static/js/shared/',
    '@/showcase/': '/static/js/pages/showcase/',
    '@/scanner/': '/static/js/pages/scanner/',
    '@/settings/': '/static/js/pages/settings/',
    '@/search/': '/static/js/pages/search/',
    '@/demo/': '/static/js/pages/demo/',
    ...extra,
  };
}

function writeBase(root, imports = defaultImports()) {
  writeAt(
    root,
    'web/templates/base.html',
    `<script type="importmap">\n${JSON.stringify({ imports }, null, 2)}\n</script>\n`,
  );
}

function factoryFile(name, keysObj) {
  return `export function ${name}() {\n  return ${keysObj};\n}\n`;
}

function mainMerging(page, factories, inlineObj = null) {
  const alias = `@/${page}/`;
  const lines = [];
  for (const f of factories) {
    lines.push(`import { ${f} } from '${alias}${f}.js';`);
  }
  lines.push(`import { mergeState } from '@/shared/merge-state.js';`);
  const args = factories.map((f) => `${f}()`);
  if (inlineObj) args.push(inlineObj);
  lines.push(`mergeState(${args.join(', ')});`);
  lines.push('');
  return lines.join('\n');
}

function writePage(root, page, shards, inlineObj = null) {
  const names = Object.keys(shards);
  for (const [name, body] of Object.entries(shards)) {
    writeAt(root, `web/static/js/pages/${page}/${name}.js`, body);
  }
  writeAt(root, `web/static/js/pages/${page}/main.js`, mainMerging(page, names, inlineObj));
}

/** 乾淨基準：demo 兩貢獻者、五個不重複 key → `demo 2/5` */
function makeCleanDemo(root) {
  writeBase(root);
  writePage(root, 'demo', {
    shardA: factoryFile('shardA', '{\n    a: 1,\n    b: 2,\n    c: 3,\n  }'),
    shardB: factoryFile('shardB', '{\n    d: 4,\n    e: 5,\n  }'),
  });
}

function withScratch(fn) {
  const root = mkdtempSync(join(tmpdir(), 'state-key-guard-'));
  try {
    fn(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function withWebCopy(fn) {
  const root = mkdtempSync(join(tmpdir(), 'state-key-guard-repo-'));
  try {
    cpSync(join(REPO_ROOT, 'web'), join(root, 'web'), { recursive: true });
    fn(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------------------
// 基準
// ---------------------------------------------------------------------------

test('〔基準〕乾淨合成 scratch root → exit 0，摘要 demo 2/5', () => {
  withScratch((root) => {
    makeCleanDemo(root);
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
    assert.match(r.output, /demo 2\/5/);
    assert.match(r.output, /頂層狀態零跨貢獻者撞名/);
  });
});

// ---------------------------------------------------------------------------
// 正向鎖
// ---------------------------------------------------------------------------

test('〔正1〕同一頁兩個分片宣告同名 key → exit 1；訊息含兩路徑＋行號＋key 名', () => {
  withScratch((root) => {
    writeBase(root);
    writePage(root, 'demo', {
      shardA: factoryFile('shardA', '{\n    foo: 1,\n  }'),
      shardB: factoryFile('shardB', '{\n    foo: 2,\n  }'),
    });
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /\bfoo\b/);
    assert.match(r.output, /web\/static\/js\/pages\/demo\/shardA\.js:\d+/);
    assert.match(r.output, /web\/static\/js\/pages\/demo\/shardB\.js:\d+/);
  });
});

test('〔正2〕四頁（showcase／search／scanner／settings）各做一次同名撞名 → 皆 exit 1', () => {
  withScratch((root) => {
    writeBase(root);
    for (const page of PAGES) {
      writePage(root, page, {
        shardA: factoryFile('shardA', '{\n    collided: 1,\n  }'),
        shardB: factoryFile('shardB', '{\n    collided: 2,\n  }'),
      });
    }
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    for (const page of PAGES) {
      assert.match(r.output, new RegExp(`${page} 頁跨貢獻者撞名`), `missing page ${page}`);
    }
  });
});

test('〔正3〕同一頁三個貢獻者宣告同名 key → 訊息三來源全列', () => {
  withScratch((root) => {
    writeBase(root);
    writePage(root, 'demo', {
      shardA: factoryFile('shardA', '{\n    triple: 1,\n  }'),
      shardB: factoryFile('shardB', '{\n    triple: 2,\n  }'),
      shardC: factoryFile('shardC', '{\n    triple: 3,\n  }'),
    });
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /\btriple\b/);
    assert.match(r.output, /web\/static\/js\/pages\/demo\/shardA\.js:\d+/);
    assert.match(r.output, /web\/static\/js\/pages\/demo\/shardB\.js:\d+/);
    assert.match(r.output, /web\/static\/js\/pages\/demo\/shardC\.js:\d+/);
  });
});

test('〔正4〕factory key × inline 物件撞名 → 訊息同時列出分片與 main.js', () => {
  withScratch((root) => {
    writeBase(root);
    writePage(
      root,
      'demo',
      { shardA: factoryFile('shardA', '{\n    sharedKey: 1,\n  }') },
      '{\n    sharedKey: 2,\n  }',
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /\bsharedKey\b/);
    assert.match(r.output, /web\/static\/js\/pages\/demo\/shardA\.js:\d+/);
    assert.match(r.output, /web\/static\/js\/pages\/demo\/main\.js:\d+/);
  });
});

test('〔正5〕同檔兩個 factory 都進 mergeState、彼此撞名 → 訊息列兩個 factory', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/dual.js',
      `export function factoryOne() {
  return {
    clash: 1,
  };
}
export function factoryTwo() {
  return {
    clash: 2,
  };
}
`,
    );
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `import { factoryOne, factoryTwo } from '@/demo/dual.js';
import { mergeState } from '@/shared/merge-state.js';
mergeState(factoryOne(), factoryTwo());
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /\bclash\b/);
    // 兩個 factory 同檔；若誤用檔案 collapse 會靜默轉綠。訊息應出現兩次同檔不同行。
    const hits = r.output.match(/web\/static\/js\/pages\/demo\/dual\.js:\d+/g) || [];
    assert.ok(hits.length >= 2, `expected ≥2 dual.js locs, got ${hits}: ${r.output}`);
    assert.notEqual(hits[0], hits[1], 'two factories must report distinct lines');
  });
});

test('〔正6〕正1 案例還原後 → exit 0（避免恆紅空殼）', () => {
  withScratch((root) => {
    writeBase(root);
    writePage(root, 'demo', {
      shardA: factoryFile('shardA', '{\n    foo: 1,\n  }'),
      shardB: factoryFile('shardB', '{\n    foo: 2,\n  }'),
    });
    assert.equal(runGuard(root).status, 1, 'precondition: collision must be RED');
    // 還原：改名消除撞名
    writeAt(root, 'web/static/js/pages/demo/shardB.js', factoryFile('shardB', '{\n    bar: 2,\n  }'));
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  });
});

// ---------------------------------------------------------------------------
// 反向鎖
// ---------------------------------------------------------------------------

test('〔反①〕同一貢獻者內 get/set 配對（真實形狀 uncensoredMode）→ exit 0', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/settings/state-config.js',
      `export function stateConfig() {
  return {
    sources: [],
    CENSORED_SOURCES: [],
    get uncensoredMode() {
      const censored = this.sources.filter(s => this.CENSORED_SOURCES.includes(s.id));
      return censored.length > 0 && censored.every(s => !s.enabled);
    },
    set uncensoredMode(v) {
      if (v === true) {
        this.sources.forEach(s => {
          if (this.CENSORED_SOURCES.includes(s.id) && !s.manual_only) {
            s.enabled = false;
          }
        });
      }
    },
  };
}
`,
    );
    writeAt(
      root,
      'web/static/js/pages/settings/state-ui.js',
      factoryFile('stateUI', '{\n    panelOpen: false,\n  }'),
    );
    writeAt(
      root,
      'web/static/js/pages/settings/main.js',
      `import { stateConfig } from '@/settings/state-config.js';
import { stateUI } from '@/settings/state-ui.js';
import { mergeState } from '@/shared/merge-state.js';
mergeState(stateConfig(), stateUI());
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
    // kinds collapse：get+set 必須併成同一個 key 且兩種 kind 都在。
    // 卡片 mutation #1（existing.kinds.add → keys.set 覆寫）會丟掉先寫入的 get，
    // exit-code 黑箱看不出來（Map 仍只有一個 name），所以這裡直接驗 kinds。
    const pages = collectPages(root);
    const config = pages
      .find((p) => p.page === 'settings')
      .contributors
      .find((c) => c.factoryName === 'stateConfig');
    const info = config.keys.get('uncensoredMode');
    assert.ok(info, 'uncensoredMode must be collected');
    assert.equal(config.keys.size, 3, 'sources + CENSORED_SOURCES + uncensoredMode');
    assert.ok(info.kinds.has('get'), 'get must survive collapse');
    assert.ok(info.kinds.has('set'), 'set must survive collapse');
  });
});

test('〔反②〕不同頁出現同名 key → exit 0', () => {
  withScratch((root) => {
    writeBase(root);
    for (const page of PAGES) {
      writePage(root, page, {
        shardA: factoryFile('shardA', '{\n    sameAcrossPages: 1,\n  }'),
        shardB: factoryFile('shardB', '{\n    unique_' + page + ': 2,\n  }'),
      });
    }
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  });
});

test('〔反③〕分片 method 內部巢狀 return {...} 帶同名 key → exit 0', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/shardA.js',
      `export function shardA() {
  return {
    outer: 1,
    method() {
      return { shared: 99 };
    },
  };
}
`,
    );
    writeAt(
      root,
      'web/static/js/pages/demo/shardB.js',
      factoryFile('shardB', '{\n    shared: 1,\n  }'),
    );
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      mainMerging('demo', ['shardA', 'shardB']),
    );
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  });
});

test('〔反④〕同一貢獻者內同一個 key 宣告兩次 → exit 0（屬 ESLint no-dupe-keys）', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/shardA.js',
      `export function shardA() {
  return {
    duped: 1,
    duped: 2,
  };
}
`,
    );
    writeAt(
      root,
      'web/static/js/pages/demo/shardB.js',
      factoryFile('shardB', '{\n    other: 3,\n  }'),
    );
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      mainMerging('demo', ['shardA', 'shardB']),
    );
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  });
});

// ---------------------------------------------------------------------------
// fail-closed
// ---------------------------------------------------------------------------

test('〔FC-1a〕base.html 沒有 importmap 區塊 → exit 1，含 FAIL_CLOSED_1', () => {
  withScratch((root) => {
    writeAt(root, 'web/templates/base.html', '<html><body>no importmap here</body></html>\n');
    writePage(root, 'demo', {
      shardA: factoryFile('shardA', '{\n    a: 1,\n  }'),
    });
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_1/);
  });
});

test('〔FC-1b〕importmap 不是合法 JSON → exit 1，含 FAIL_CLOSED_1', () => {
  withScratch((root) => {
    writeAt(
      root,
      'web/templates/base.html',
      '<script type="importmap">\n{ imports: BROKEN }\n</script>\n',
    );
    writePage(root, 'demo', {
      shardA: factoryFile('shardA', '{\n    a: 1,\n  }'),
    });
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_1/);
  });
});

test('〔FC-2〕所有 pages/*/main.js 都不 import mergeState → exit 1，含 FAIL_CLOSED_2', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `// no mergeState import
export function demo() { return {}; }
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_2/);
  });
});

test('〔FC-3a〕某頁 import 了 mergeState 卻沒有 mergeState(...) 呼叫 → FAIL_CLOSED_3', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `import { mergeState } from '@/shared/merge-state.js';
// imported but never called
const x = mergeState;
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_3/);
  });
});

test('〔FC-3b〕同一頁多於一處 mergeState(...) 呼叫 → FAIL_CLOSED_3，訊息列每一處行號', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/shardA.js',
      factoryFile('shardA', '{\n    a: 1,\n  }'),
    );
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `import { shardA } from '@/demo/shardA.js';
import { mergeState } from '@/shared/merge-state.js';
mergeState(shardA());
mergeState(shardA());
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_3/);
    // 兩處呼叫的行號都要出現（main.js 第 3、4 行）
    assert.match(r.output, /lines \d+, \d+/);
  });
});

test('〔FC-4a〕mergeState argument 是字面量（非 Call／Object）→ FAIL_CLOSED_4', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `import { mergeState } from '@/shared/merge-state.js';
mergeState(42);
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_4/);
  });
});

test('〔FC-4b〕CallExpression 取不出識別字（window[\'x\']()）→ FAIL_CLOSED_4', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `import { mergeState } from '@/shared/merge-state.js';
mergeState(window['x']());
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_4/);
  });
});

test('〔FC-5〕factory 識別字在 main.js 找不到對應 import → FAIL_CLOSED_5', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `import { mergeState } from '@/shared/merge-state.js';
mergeState(ghostFactory());
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_5/);
  });
});

test('〔FC-6a〕specifier 解析不到存在的檔 → FAIL_CLOSED_6', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `import { missing } from '@/demo/missing.js';
import { mergeState } from '@/shared/merge-state.js';
mergeState(missing());
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_6/);
  });
});

test('〔FC-6b〕specifier 不吃任何別名 → FAIL_CLOSED_6', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `import { orphan } from 'orphan-pkg/no-alias.js';
import { mergeState } from '@/shared/merge-state.js';
mergeState(orphan());
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_6/);
  });
});

test('〔FC-7a〕分片檔找不到該具名 factory → FAIL_CLOSED_7', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/shardA.js',
      `export function otherName() {
  return { a: 1 };
}
`,
    );
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `import { shardA } from '@/demo/shardA.js';
import { mergeState } from '@/shared/merge-state.js';
mergeState(shardA());
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_7/);
  });
});

test('〔FC-7b〕頂層 return 不是 ObjectExpression → FAIL_CLOSED_7', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/shardA.js',
      `export function shardA() {
  return 42;
}
`,
    );
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      mainMerging('demo', ['shardA']),
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_7/);
  });
});

test('〔FC-8a〕頂層 return 出現 SpreadElement → FAIL_CLOSED_8', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/shardA.js',
      `const base = { x: 1 };
export function shardA() {
  return {
    ...base,
    y: 2,
  };
}
`,
    );
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      mainMerging('demo', ['shardA']),
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_8/);
  });
});

test('〔FC-8b〕頂層 return 出現 computed key → FAIL_CLOSED_8', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/shardA.js',
      `export function shardA() {
  const k = 'dyn';
  return {
    [k]: 1,
  };
}
`,
    );
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      mainMerging('demo', ['shardA']),
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /FAIL_CLOSED_8/);
  });
});

// ---------------------------------------------------------------------------
// 箭頭函式 factory
// ---------------------------------------------------------------------------

test('〔箭1〕export const demoState = () => ({ a, b }) → 解析 2 key、exit 0', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/arrow.js',
      `export const demoState = () => ({ a: 1, b: 2 });
`,
    );
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `import { demoState } from '@/demo/arrow.js';
import { mergeState } from '@/shared/merge-state.js';
mergeState(demoState());
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
    assert.match(r.output, /demo 1\/2/);
  });
});

test('〔箭2〕箭頭函式 factory 與另一分片撞名 → exit 1', () => {
  withScratch((root) => {
    writeBase(root);
    writeAt(
      root,
      'web/static/js/pages/demo/arrow.js',
      `export const demoState = () => ({ shared: 1 });
`,
    );
    writeAt(
      root,
      'web/static/js/pages/demo/other.js',
      factoryFile('other', '{\n    shared: 2,\n  }'),
    );
    writeAt(
      root,
      'web/static/js/pages/demo/main.js',
      `import { demoState } from '@/demo/arrow.js';
import { other } from '@/demo/other.js';
import { mergeState } from '@/shared/merge-state.js';
mergeState(demoState(), other());
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /\bshared\b/);
  });
});

// ---------------------------------------------------------------------------
// real-repo
// ---------------------------------------------------------------------------

test('〔真1〕掃真 repo（不帶 root）→ exit 0', () => {
  const r = runGuard();
  assert.equal(r.status, 0, r.output);
  assert.match(r.output, /頂層狀態零跨貢獻者撞名/);
});

test('〔真2〕真 repo 副本複製一個 key 到另一分片 → exit 1', () => {
  withWebCopy((root) => {
    assert.equal(runGuard(root).status, 0, '副本本身應乾淨');
    const lightboxPath = join(root, 'web/static/js/pages/showcase/state-lightbox.js');
    const src = readFileSync(lightboxPath, 'utf8');
    // state-base 有 loading: true；注入到 state-lightbox 頂層 return 造成跨貢獻者撞名
    const injected = src.replace(
      'return {',
      'return {\n        loading: true, // state-key-guard test injection',
    );
    assert.notEqual(injected, src, 'injection must modify file');
    writeFileSync(lightboxPath, injected);
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /\bloading\b/);
  });
});

test('〔真3〕回歸鎖：注入 §F 五個 key 到 showcase/state-base.js → exit 1 且命中字面值', () => {
  withWebCopy((root) => {
    assert.equal(runGuard(root).status, 0, '副本本身應乾淨');
    const basePath = join(root, 'web/static/js/pages/showcase/state-base.js');
    const src = readFileSync(basePath, 'utf8');
    const injection = REGRESSION_KEYS.map((k) => `        ${k}: null,`).join('\n');
    // stateBase() 的 return { 在 export function stateBase 之後；用獨特錨點
    const anchor = 'export function stateBase() {\n    return {';
    assert.ok(src.includes(anchor), 'stateBase return anchor must exist');
    const injected = src.replace(
      anchor,
      `${anchor}\n${injection}`,
    );
    assert.notEqual(injected, src, 'injection must modify file');
    writeFileSync(basePath, injected);
    const r = runGuard(root);
    assert.equal(r.status, 1, r.output);
    for (const key of REGRESSION_KEYS) {
      assert.match(r.output, new RegExp(`\\b${key}\\b`), `missing key ${key}`);
    }
  });
});

// ⚠️ 這條是**前瞻性**回歸鎖，不是「證明有主動排除」。現況 collectPages() 只讀
// web/templates/base.html 與 readdirSync(web/static/js/pages)，沒有全庫走訪、也沒有
// 排除清單 —— 所以 scripts/ 底下的東西是「結構上看不見」，不是「被過濾掉」。
// 留著的理由：哪天有人把 collectPages 改成廣域 tree-walk，這條會立刻紅。
// （vendor-guard / cjk-guard 那兩支真的會走全庫，它們的同型測試證明力比這條強。）
test('〔真4〕掃描範圍不含 scripts/：scratch 下放假撞名檔仍 exit 0', () => {
  withWebCopy((root) => {
    writeAt(
      root,
      'scripts/fake-collision.js',
      `// looks like a collision fixture but must not be scanned
export function a() { return { boom: 1 }; }
export function b() { return { boom: 2 }; }
mergeState(a(), b());
`,
    );
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  });
});
