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


