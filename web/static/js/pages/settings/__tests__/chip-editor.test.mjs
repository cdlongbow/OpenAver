// tokenizer round-trip 守衛（CD-95a-10〔1〕，plan-95a T3）。
// 零新依賴：Node 內建 node:test。跑：npm run test:tokenizer
//
// 守 serializeTokens(tokenize(s)) 的 round-trip 性質、未知 token 留字面、
// 字面大括號不誤判、idempotence——tokenizer 演算法正確性（ESLint 表達不了）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  tokenize, serializeTokens,
} from '../chip-editor.js';

// 與端點 SSOT 對齊的白名單（測試自帶，驗 tokenize 對注入 whitelist 的行為）
const WL = new Set([
  '{num}', '{title}', '{actor}', '{actors}', '{maker}',
  '{date}', '{year}', '{month}', '{day}', '{suffix}',
]);

const roundtrip = (s) => serializeTokens(tokenize(s, WL));

test('〔a〕白名單串 round-trip：serializeTokens(tokenize(s))===s', () => {
  const cases = [
    '[{num}][{maker}] {title}{suffix}',   // 預設檔名格式
    '{actor}/{num}',                       // 資料夾兩層
    '{num} - {title} ({year})',            // 含空格/-/()
    '~{maker}~ "{title}" \'{actor}\'',     // 含 ~ 與引號字面
    '{num}{title}{actor}{actors}{maker}{date}{year}{month}{day}{suffix}',  // 全變數相連
  ];
  for (const s of cases) assert.equal(roundtrip(s), s, `round-trip 破壞：${s}`);
});

test('〔b〕未知 token 留字面（不轉膠囊、round-trip 不變）', () => {
  const cases = ['{studio}', '{tit-le}', '{titel}', '{title', '{}', '{123}', '{NUM}'];
  for (const s of cases) {
    assert.equal(roundtrip(s), s, `未知 token 應留字面：${s}`);
    // 且不得產生 chip
    assert.ok(
      tokenize(s, WL).every((tk) => tk.t === 'text'),
      `未知 token 不應成 chip：${s}`,
    );
  }
});

test('〔b2〕已知 token 確實成 chip', () => {
  const toks = tokenize('{num}', WL);
  assert.deepEqual(toks, [{ t: 'chip', v: '{num}' }]);
});

test('〔c〕字面大括號不誤判', () => {
  const cases = ['{', '}', 'a{b}c', '{ num }', 'plain text', '前綴{num後綴'];
  for (const s of cases) assert.equal(roundtrip(s), s, `字面大括號誤判：${s}`);
  // {b} 非白名單 → 全字面
  assert.ok(tokenize('a{b}c', WL).every((tk) => tk.t === 'text'));
});

test('〔d〕idempotence：serialize→tokenize 穩定', () => {
  const cases = ['[{num}] {title}{suffix}', '{studio}{num}', 'a{b}c{actor}'];
  for (const s of cases) {
    const once = tokenize(s, WL);
    const twice = tokenize(serializeTokens(once), WL);
    assert.deepEqual(twice, once, `idempotence 破壞：${s}`);
  }
});

test('〔e〕空字串 → [] → 空字串', () => {
  assert.deepEqual(tokenize('', WL), []);
  assert.equal(serializeTokens([]), '');
  assert.equal(roundtrip(''), '');
});

test('〔f〕{actor} 與 {actors} 各自正確成 chip（無子字串誤併）', () => {
  assert.deepEqual(tokenize('{actor}', WL), [{ t: 'chip', v: '{actor}' }]);
  assert.deepEqual(tokenize('{actors}', WL), [{ t: 'chip', v: '{actors}' }]);
  // 相鄰：{actor} 後接 s} 字面
  assert.equal(roundtrip('{actor}s and {actors}'), '{actor}s and {actors}');
});

// ── requiredVars（TASK-154b-T4）──────────────────────────────────────────────
// ChipEditor class 需最小 DOM shim（repo 無 jsdom）。只支援本檔實際碰到的 API。

function installDomShim() {
  function makeNode(tag) {
    const children = [];
    const classSet = new Set();
    const attrs = {};
    const node = {
      tagName: String(tag).toUpperCase(),
      nodeType: 1,
      className: '',
      contentEditable: 'true',
      spellcheck: false,
      tabIndex: 0,
      textContent: '',
      dataset: {},
      children,
      childNodes: children,
      parentNode: null,
      setAttribute(k, v) { attrs[k] = String(v); },
      getAttribute(k) { return attrs[k]; },
      appendChild(c) {
        if (c && c.nodeType === 11) {
          for (const child of [...c.childNodes]) {
            child.parentNode = node;
            children.push(child);
          }
          c.childNodes.length = 0;
          return c;
        }
        c.parentNode = node;
        children.push(c);
        return c;
      },
      remove() {
        if (!node.parentNode) return;
        const sibs = node.parentNode.childNodes;
        const i = sibs.indexOf(node);
        if (i >= 0) sibs.splice(i, 1);
        node.parentNode = null;
      },
      classList: {
        add(...xs) { xs.forEach((x) => classSet.add(x)); },
        remove(...xs) { xs.forEach((x) => classSet.delete(x)); },
        contains(x) { return classSet.has(x); },
      },
      closest(sel) {
        if (sel === '.source-pill' && String(node.className).includes('source-pill')) return node;
        if (sel === '.chip-x' && String(node.className).includes('chip-x')) return node;
        return node.parentNode && node.parentNode.closest
          ? node.parentNode.closest(sel)
          : null;
      },
      addEventListener() {},
      removeEventListener() {},
    };
    Object.defineProperty(node, 'innerHTML', {
      set(v) { if (v === '') children.length = 0; },
      get() { return ''; },
    });
    return node;
  }

  globalThis.document = {
    createElement: (tag) => makeNode(tag),
    createTextNode: (text) => ({
      nodeType: 3,
      textContent: String(text),
      parentNode: null,
    }),
    createDocumentFragment: () => {
      const children = [];
      return {
        nodeType: 11,
        childNodes: children,
        get lastChild() { return children[children.length - 1] || null; },
        appendChild(c) { children.push(c); return c; },
      };
    },
  };
  globalThis.window = globalThis;
  globalThis.window.getSelection = () => ({
    rangeCount: 1,
    isCollapsed: true,
    getRangeAt: () => ({}),
  });
}

installDomShim();

const { ChipEditor: ChipEditorClass } = await import('../chip-editor.js');

function makeHost() {
  const children = [];
  return {
    children,
    childNodes: children,
    appendChild(c) { children.push(c); c.parentNode = this; return c; },
  };
}

function chipXCount(chip) {
  return chip.childNodes.filter(
    (c) => c.nodeType === 1 && String(c.className).split(/\s+/).includes('chip-x'),
  ).length;
}

test('requiredVars 內的變數不建立 .chip-x 刪除鈕', () => {
  const editor = new ChipEditorClass(makeHost(), {
    requiredVars: new Set(['{num}', '{title}']),
    whitelist: new Set(['{num}', '{title}', '{actor}']),
  });
  editor.load('[{num}]{title}{actor}');
  const chips = editor.ed.childNodes.filter((n) => n.nodeType === 1 && n.dataset && n.dataset.var);
  const byVar = Object.fromEntries(chips.map((c) => [c.dataset.var, c]));
  assert.equal(byVar['{num}'].dataset.required, 'true');
  assert.equal(byVar['{title}'].dataset.required, 'true');
  assert.equal(chipXCount(byVar['{num}']), 0);
  assert.equal(chipXCount(byVar['{title}']), 0);
  assert.notEqual(byVar['{actor}'].dataset.required, 'true');
  assert.equal(chipXCount(byVar['{actor}']), 1);
});

test('requiredVars 內的膠囊 Backspace 刪不掉', () => {
  const editor = new ChipEditorClass(makeHost(), {
    requiredVars: new Set(['{num}', '{title}']),
    whitelist: new Set(['{num}', '{title}', '{actor}']),
  });
  let changes = 0;
  editor.onChange = () => { changes += 1; };
  const required = editor._makeChip('{num}');
  editor.ed.appendChild(required);
  editor._nodeBefore = () => required;
  let prevented = false;
  editor._onKey({
    key: 'Backspace',
    isComposing: false,
    preventDefault() { prevented = true; },
  });
  assert.equal(prevented, true);
  assert.equal(required.parentNode, editor.ed);
  assert.equal(changes, 0);
});

test('非 requiredVars 的膠囊 Backspace 仍可刪除（零回歸）', () => {
  const editor = new ChipEditorClass(makeHost(), {
    requiredVars: new Set(['{num}', '{title}']),
    whitelist: new Set(['{num}', '{title}', '{actor}']),
  });
  let changes = 0;
  editor.onChange = () => { changes += 1; };
  const optional = editor._makeChip('{actor}');
  editor.ed.appendChild(optional);
  editor._nodeBefore = () => optional;
  editor._onKey({
    key: 'Backspace',
    isComposing: false,
    preventDefault() {},
  });
  assert.equal(optional.parentNode, null);
  assert.equal(changes, 1);
});

test('requiredVars 膠囊 dragstart 仍設定 _drag（拖曳零改動）', () => {
  const editor = new ChipEditorClass(makeHost(), {
    requiredVars: new Set(['{num}', '{title}']),
    whitelist: new Set(['{num}', '{title}']),
  });
  const chip = editor._makeChip('{num}');
  editor.ed.appendChild(chip);
  editor._handlers.dragstart({
    target: chip,
    dataTransfer: { effectAllowed: '', setData() {} },
  });
  assert.equal(editor._drag, chip);
});

test('未傳 requiredVars 時 {num} 仍有 .chip-x（既有呼叫端零回歸）', () => {
  const editor = new ChipEditorClass(makeHost(), {
    whitelist: new Set(['{num}', '{title}']),
  });
  const chip = editor._makeChip('{num}');
  assert.equal(chipXCount(chip), 1);
  assert.notEqual(chip.dataset.required, 'true');
});
