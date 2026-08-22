/**
 * vendor-guard.test.mjs — `scripts/vendor_guard_lint.mjs` 的守衛測試（plan-125 T3）
 *
 * 手法比照 `scripts/__tests__/cjk-guard.test.mjs`：`mkdtempSync` 建 scratch root、
 * `spawnSync` 黑箱跑守衛、斷言 exit code 與合併後的 stdout+stderr。
 *
 * 覆蓋 plan §2.3 的 S1–S9 九個場景 ＋ spec §3.4 三態（加檔／刪清單筆／改一個 byte）
 * 各自**單獨** RED ＋ 還原後 GREEN ＋ 真 repo regression。
 *
 * 每個 RED 場景都對應一個「還原後轉 GREEN」或「同批中另一項維持不報」的對照，
 * 避免寫出「永遠紅」或「永遠綠」的空殼測試。
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
import { createHash } from 'node:crypto';

const __dirname = dirname(fileURLToPath(import.meta.url));
const GUARD_PATH = join(__dirname, '..', 'vendor_guard_lint.mjs');
const REPO_ROOT = join(__dirname, '..', '..');

const VENDOR_REL = 'web/static/vendor';
const FACEFINDER_REL = 'core/focal/facefinder';

const sha256 = (buf) => createHash('sha256').update(buf).digest('hex');

function runGuard(root) {
  const args = root ? [GUARD_PATH, root] : [GUARD_PATH];
  const result = spawnSync(process.execPath, args, { encoding: 'utf8' });
  return { ...result, output: `${result.stdout}\n${result.stderr}` };
}

function writeAt(root, rel, buf) {
  const abs = join(root, ...rel.split('/'));
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, buf);
  return abs;
}

function writeManifest(root, manifest) {
  writeAt(root, `${VENDOR_REL}/manifest.json`,
    Buffer.from(JSON.stringify(manifest, null, 2), 'utf8'));
}

/**
 * 建一個最小但**合法且完整**的 scratch root：
 *  - 一個 banner_added:true 的檔案（模擬 Alpine）
 *  - 一個 banner_added:false 的檔案（模擬 GSAP，內容自帶原生 /*! banner）
 *  - 一個二進位檔（模擬 .woff，含非法 UTF-8 序列）
 *  - facefinder
 * 回傳 { root, manifest, bodies } 供各場景微調。
 */
function makeScratchRoot() {
  const root = mkdtempSync(join(tmpdir(), 'vendor-guard-'));

  const alpineBody = Buffer.from('(()=>{var a=1;})();\n', 'utf8');
  const alpineBanner = Buffer.from('/*! fake-alpine v1.0.0 | MIT | https://example.test */\n', 'utf8');
  const alpineFile = Buffer.concat([alpineBanner, alpineBody]);

  // 上游原生就自帶 banner 的檔案：我們沒有加東西，banner_added 必須是 false
  const gsapFile = Buffer.from('/*! fake-gsap 3.0.0 native banner */\n!function(){}();\n', 'utf8');

  // 二進位：0xFF 0xFE 0x00 這類序列不是合法 UTF-8，走字串路徑會被換成 U+FFFD
  const binFile = Buffer.from([0x00, 0xff, 0xfe, 0x80, 0x81, 0x00, 0xc0, 0xaf, 0xf5, 0x7f]);

  const ffFile = Buffer.from([0x01, 0x02, 0xff, 0x03, 0xfd]);

  writeAt(root, `${VENDOR_REL}/alpine/alpine.min.js`, alpineFile);
  writeAt(root, `${VENDOR_REL}/gsap/gsap.min.js`, gsapFile);
  writeAt(root, `${VENDOR_REL}/bootstrap-icons/fonts/icons.woff`, binFile);
  writeAt(root, FACEFINDER_REL, ffFile);

  const manifest = {
    _comment: '測試用；守衛不得對頂層做無條件遍歷',
    vendor: [
      {
        path: `${VENDOR_REL}/alpine/alpine.min.js`,
        package: 'fake-alpine', version: '1.0.0',
        upstream_url: 'https://example.test/alpine.js',
        upstream_sha256: sha256(alpineBody),
        local_sha256: sha256(alpineFile),
        license: 'MIT', vendored_date: '2026-06-21', banner_added: true,
      },
      {
        path: `${VENDOR_REL}/gsap/gsap.min.js`,
        package: 'fake-gsap', version: '3.0.0',
        upstream_url: 'https://example.test/gsap.js',
        upstream_sha256: sha256(gsapFile),
        local_sha256: sha256(gsapFile),
        license: 'X', vendored_date: '2026-06-21', banner_added: false,
      },
      {
        path: `${VENDOR_REL}/bootstrap-icons/fonts/icons.woff`,
        package: 'fake-icons', version: '1.0.0',
        upstream_url: 'https://example.test/icons.woff',
        upstream_sha256: sha256(binFile),
        local_sha256: sha256(binFile),
        license: 'MIT', vendored_date: '2026-06-21', banner_added: false,
      },
    ],
    facefinder: {
      path: FACEFINDER_REL,
      package: 'fake/pigo (cascade)', version: 'v1.0.0',
      upstream_url: 'https://example.test/facefinder',
      upstream_sha256: sha256(ffFile), local_sha256: sha256(ffFile),
      license: 'MIT', copyright: 'Copyright (c) test',
      vendored_date: '2026-07-13', banner_added: false,
      note: '未修改的上游原檔複本',
    },
  };
  writeManifest(root, manifest);
  return { root, manifest, bodies: { alpineBody, alpineBanner, alpineFile, gsapFile, binFile, ffFile } };
}

function withScratch(fn) {
  const ctx = makeScratchRoot();
  try {
    fn(ctx);
  } finally {
    rmSync(ctx.root, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------------------
// 基準：乾淨的 scratch root 必須 GREEN（沒有這條，下面所有 RED 都證明不了東西）
// ---------------------------------------------------------------------------

test('〔S1〕banner_added:true 正常剝除 → GREEN（且基準 root 整體乾淨）', () => {
  withScratch(({ root }) => {
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
    assert.match(r.output, /對帳一致/);
  });
});

test('〔S2〕banner 與原碼之間多一個空行 → RED', () => {
  withScratch(({ root, bodies }) => {
    // banner 之後多插一個 \n 才接原碼：local_sha256 也會跟著變，但我們只改檔案、不改清單，
    // 所以會先撞上 local_sha256 不符；把 local 一起更新才能證明「剝除後比對」這條真的在管事。
    const broken = Buffer.concat([bodies.alpineBanner, Buffer.from('\n'), bodies.alpineBody]);
    writeAt(root, `${VENDOR_REL}/alpine/alpine.min.js`, broken);
    const m = JSON.parse(readFileSync(join(root, ...`${VENDOR_REL}/manifest.json`.split('/')), 'utf8'));
    m.vendor[0].local_sha256 = sha256(broken); // 只讓 upstream 那條檢查落單
    writeManifest(root, m);

    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /剝除 banner 後與上游不符/);
    assert.match(r.output, /alpine\.min\.js/);
  });
});

test('〔S3〕banner 被整個拿掉（還原成裸檔）→ RED，訊息明確是 banner 格式不符', () => {
  withScratch(({ root, bodies }) => {
    writeAt(root, `${VENDOR_REL}/alpine/alpine.min.js`, bodies.alpineBody);
    const m = JSON.parse(readFileSync(join(root, ...`${VENDOR_REL}/manifest.json`.split('/')), 'utf8'));
    m.vendor[0].local_sha256 = sha256(bodies.alpineBody);
    writeManifest(root, m);

    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /banner 格式不符/);
    assert.match(r.output, /未以 \/\*! 起始/);
  });
});

test('〔S4〕上游原生 banner 被誤標 banner_added:true → RED（證明不靠內容嗅探）', () => {
  withScratch(({ root }) => {
    // gsap 檔案內容不動（它自帶原生 /*! banner），只把旗標從 false 誤改成 true。
    // 若守衛改用「檔案開頭是不是 /*!」嗅探，就會把上游自己的 banner 剝掉而算出錯誤的 hash。
    const m = JSON.parse(readFileSync(join(root, ...`${VENDOR_REL}/manifest.json`.split('/')), 'utf8'));
    m.vendor[1].banner_added = true;
    writeManifest(root, m);

    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /剝除 banner 後與上游不符/);
    assert.match(r.output, /gsap\.min\.js/);
  });
});

test('〔S5〕banner_added:false 的檔案被改一個位元組 → RED（走一般三態，不進剝除）', () => {
  withScratch(({ root, bodies }) => {
    const tampered = Buffer.from(bodies.gsapFile);
    tampered[tampered.length - 2] ^= 0x01; // 翻一個 bit
    writeAt(root, `${VENDOR_REL}/gsap/gsap.min.js`, tampered);

    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /內容與清單不符/);
    assert.match(r.output, /gsap\.min\.js/);
    assert.doesNotMatch(r.output, /banner 格式不符/);
  });
});

test('〔S6〕三態同時發生 → 三筆各自獨立回報，不會只報第一個就短路', () => {
  withScratch(({ root, bodies }) => {
    // ① 加一個未登記檔案
    writeAt(root, `${VENDOR_REL}/gsap/Unregistered.min.js`, Buffer.from('x'));
    // ② 刪掉一筆 manifest 對應的磁碟檔案
    rmSync(join(root, ...`${VENDOR_REL}/bootstrap-icons/fonts/icons.woff`.split('/')));
    // ③ 另一筆改一個 byte
    const tampered = Buffer.from(bodies.gsapFile);
    tampered[0] ^= 0xff;
    writeAt(root, `${VENDOR_REL}/gsap/gsap.min.js`, tampered);

    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /Unregistered\.min\.js/);
    assert.match(r.output, /icons\.woff/);
    assert.match(r.output, /gsap\.min\.js/);
  });
});

test('〔S7〕二進位內容的 hash 必須走 Buffer——字串路徑會失真（對照組證明本案例非空殼）', () => {
  withScratch(({ root, bodies }) => {
    // ① 真二進位檔在乾淨狀態下必須 GREEN
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);

    // ② 對照組：同一段位元組走 utf8 字串路徑再 hash，必須與 Buffer 路徑不同。
    //    若兩者相同，代表這個 fixture 沒有非法 UTF-8 序列，S7 就是空案例。
    const abs = join(root, ...`${VENDOR_REL}/bootstrap-icons/fonts/icons.woff`.split('/'));
    const bufHash = sha256(readFileSync(abs));
    const strHash = sha256(Buffer.from(readFileSync(abs, 'utf8'), 'utf8'));
    assert.notEqual(strHash, bufHash,
      'fixture 必須含非法 UTF-8 序列，否則本案例證明不了 Buffer 路徑的必要性');
    // 磁碟內容確實就是我們寫進去的那段位元組（Buffer 路徑沒有在中途失真）
    assert.equal(bufHash, sha256(bodies.binFile));
  });
});

test('〔S8〕dotfile 略過、非 dotfile 的未登記檔案照樣 RED（同一次掃描並存）', () => {
  withScratch(({ root }) => {
    writeAt(root, `${VENDOR_REL}/.DS_Store`, Buffer.from('junk'));
    writeAt(root, `${VENDOR_REL}/alpine/some.min.js`, Buffer.from('unregistered'));

    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /some\.min\.js/);
    assert.doesNotMatch(r.output, /\.DS_Store/);
  });
});

test('〔S8b〕只有 dotfile、沒有其他未登記檔案 → GREEN（證明 dotfile 真的被跳過）', () => {
  withScratch(({ root }) => {
    writeAt(root, `${VENDOR_REL}/.DS_Store`, Buffer.from('junk'));
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  });
});

test('〔S8c〕不以 . 開頭的系統暫存檔（Thumbs.db）不得被放行 → RED（非副檔名白名單）', () => {
  withScratch(({ root }) => {
    writeAt(root, `${VENDOR_REL}/Thumbs.db`, Buffer.from('junk'));
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /Thumbs\.db/);
  });
});

test('〔S9〕守衛不把自己的 manifest 當未登記檔案，但同目錄其他 .json 照樣 RED', () => {
  withScratch(({ root }) => {
    // manifest.json 已存在於 VENDOR_REL 底下（makeScratchRoot 寫的），基準已證明 GREEN。
    // 這裡加一個未登記的 other.json：若排除規則誤寫成 *.json 萬用字元，它會被誤放行。
    writeAt(root, `${VENDOR_REL}/other.json`, Buffer.from('{}'));
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /other\.json/);
    // 錯誤輸出不得把 manifest.json 自己列為未登記
    assert.doesNotMatch(r.output, /多出未登記的第三方檔案：web\/static\/vendor\/manifest\.json/);
  });
});

// ---------------------------------------------------------------------------
// spec §3.4 三態：各自**單獨**觸發 → RED，還原後 → GREEN
// ---------------------------------------------------------------------------

test('〔三態-加檔〕單獨新增未登記檔案 → RED；移除後 → GREEN', () => {
  withScratch(({ root }) => {
    assert.equal(runGuard(root).status, 0);
    const abs = writeAt(root, `${VENDOR_REL}/alpine/extra.min.js`, Buffer.from('x'));
    const red = runGuard(root);
    assert.notEqual(red.status, 0, red.output);
    assert.match(red.output, /extra\.min\.js/);
    rmSync(abs);
    assert.equal(runGuard(root).status, 0);
  });
});

test('〔三態-刪檔〕單獨刪掉清單有記錄的檔案 → RED；還原後 → GREEN', () => {
  withScratch(({ root, bodies }) => {
    const rel = `${VENDOR_REL}/gsap/gsap.min.js`;
    rmSync(join(root, ...rel.split('/')));
    const red = runGuard(root);
    assert.notEqual(red.status, 0, red.output);
    assert.match(red.output, /清單有記錄但磁碟找不到檔案/);
    assert.match(red.output, /gsap\.min\.js/);
    writeAt(root, rel, bodies.gsapFile);
    assert.equal(runGuard(root).status, 0);
  });
});

test('〔三態-改一個 byte〕單獨改動 → RED；還原後 → GREEN', () => {
  withScratch(({ root, bodies }) => {
    const rel = `${VENDOR_REL}/bootstrap-icons/fonts/icons.woff`;
    const tampered = Buffer.from(bodies.binFile);
    tampered[0] ^= 0x01;
    writeAt(root, rel, tampered);
    const red = runGuard(root);
    assert.notEqual(red.status, 0, red.output);
    assert.match(red.output, /內容與清單不符/);
    writeAt(root, rel, bodies.binFile);
    assert.equal(runGuard(root).status, 0);
  });
});

test('〔facefinder〕core/focal/facefinder 被改動 → RED（它不在 vendor 遞迴範圍內，走獨立分支）', () => {
  withScratch(({ root, bodies }) => {
    const tampered = Buffer.from(bodies.ffFile);
    tampered[1] ^= 0x01;
    writeAt(root, FACEFINDER_REL, tampered);
    const red = runGuard(root);
    assert.notEqual(red.status, 0, red.output);
    assert.match(red.output, /facefinder/);
    writeAt(root, FACEFINDER_REL, bodies.ffFile);
    assert.equal(runGuard(root).status, 0);
  });
});

test('〔focal 非對帳檔〕core/focal 下的 .py 不進掃描範圍 → 加了也 GREEN（CD-2）', () => {
  withScratch(({ root }) => {
    writeAt(root, 'core/focal/some_new_module.py', Buffer.from('# not a vendored asset\n'));
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  });
});

// ---------------------------------------------------------------------------
// fail-closed
// ---------------------------------------------------------------------------

test('〔fail-closed〕manifest.json 不存在 → RED', () => {
  withScratch(({ root }) => {
    rmSync(join(root, ...`${VENDOR_REL}/manifest.json`.split('/')));
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /manifest\.json/);
  });
});

test('〔fail-closed〕manifest.json 不是合法 JSON → RED', () => {
  withScratch(({ root }) => {
    writeAt(root, `${VENDOR_REL}/manifest.json`, Buffer.from('{ "vendor": [ ,, ] '));
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /無法解析|讀不到/);
  });
});

test('〔fail-closed〕vendor[] 為空 → RED（不得因為「沒東西可對」而綠）', () => {
  withScratch(({ root, manifest }) => {
    writeManifest(root, { ...manifest, vendor: [] });
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /vendor\[\] 不存在或為空/);
  });
});

test('〔fail-closed〕缺 facefinder 條目 → RED', () => {
  withScratch(({ root, manifest }) => {
    const m = { ...manifest };
    delete m.facefinder;
    writeManifest(root, m);
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /缺 facefinder/);
  });
});

test('〔schema〕vendor 條目缺必填欄位 → RED', () => {
  withScratch(({ root, manifest }) => {
    const m = JSON.parse(JSON.stringify(manifest));
    delete m.vendor[0].upstream_url;
    writeManifest(root, m);
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /缺必填欄位/);
    assert.match(r.output, /upstream_url/);
  });
});

test('〔schema〕facefinder 用自己的必填清單，多出的 copyright/note 不影響判定', () => {
  withScratch(({ root, manifest }) => {
    // 拿掉 facefinder 的 copyright 與 note（vendor[] 本來就沒有這兩欄）→ 仍應 GREEN，
    // 證明守衛沒有拿 vendor 的白名單去驗 facefinder。
    const m = JSON.parse(JSON.stringify(manifest));
    delete m.facefinder.copyright;
    delete m.facefinder.note;
    writeManifest(root, m);
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  });
});

test('〔_comment〕頂層的 _comment 說明 key 不得被當成資料群而報錯', () => {
  withScratch(({ root, manifest }) => {
    writeManifest(root, { ...manifest, _comment: '換一段完全不同的說明文字', _meta: { x: 1 } });
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  });
});

// ---------------------------------------------------------------------------
// 真 repo regression
// ---------------------------------------------------------------------------

test('〔real-repo〕掃真 repo 必須 GREEN（T1 的 banner + T2 的 manifest 對得上）', () => {
  const r = runGuard();
  assert.equal(r.status, 0, r.output);
  assert.match(r.output, /對帳一致/);
});

test('〔real-repo mutation〕真 repo 副本改一個 byte → RED（證明 real-repo 案例不是恆綠）', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'vendor-guard-repo-'));
  try {
    for (const rel of [VENDOR_REL, 'core/focal']) {
      cpSync(join(REPO_ROOT, ...rel.split('/')), join(tmp, ...rel.split('/')), { recursive: true });
    }
    assert.equal(runGuard(tmp).status, 0, '副本本身應該是乾淨的');

    const abs = join(tmp, ...`${VENDOR_REL}/gsap/gsap.min.js`.split('/'));
    const buf = readFileSync(abs);
    buf[buf.length - 1] ^= 0x01;
    writeFileSync(abs, buf);

    const r = runGuard(tmp);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /gsap\.min\.js/);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// 清單↔磁碟一一對應的兩個洞（path 逃出掃描範圍／重複登記）
// ---------------------------------------------------------------------------

test('〔path 範圍〕vendor[] 的 path 指到掃描範圍外 → RED（否則該筆永遠不會被 walk 對到）', () => {
  withScratch(({ root, manifest, bodies }) => {
    const m = JSON.parse(JSON.stringify(manifest));
    // 把 gsap 那筆改指到 core/focal 底下的檔案，並讓 hash 對得上——
    // 若沒有範圍檢查，這筆會「對帳通過」，而磁碟上真正的 gsap.min.js 變成未登記。
    writeAt(root, 'core/focal/sneaky.js', bodies.gsapFile);
    m.vendor[1].path = 'core/focal/sneaky.js';
    writeManifest(root, m);
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /必須位於 web\/static\/vendor\/ 底下/);
  });
});

test('〔path 逃逸〕vendor[] 的 path 含 .. → RED', () => {
  withScratch(({ root, manifest }) => {
    const m = JSON.parse(JSON.stringify(manifest));
    m.vendor[1].path = `${VENDOR_REL}/../../../etc/hosts`;
    writeManifest(root, m);
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /不得含/);
  });
});

test('〔重複登記〕同一個 path 出現兩筆 → RED', () => {
  withScratch(({ root, manifest }) => {
    const m = JSON.parse(JSON.stringify(manifest));
    m.vendor.push({ ...m.vendor[1] });
    writeManifest(root, m);
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /重複登記/);
  });
});

test('〔schema〕facefinder 缺 provenance 必填欄位（vendored_date）→ RED', () => {
  withScratch(({ root, manifest }) => {
    const m = JSON.parse(JSON.stringify(manifest));
    delete m.facefinder.vendored_date;
    writeManifest(root, m);
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /facefinder 缺必填欄位/);
    assert.match(r.output, /vendored_date/);
  });
});

// ---------------------------------------------------------------------------
// review 找到的兩個假陰性（P2 dot-目錄盲區、P3 清單自相矛盾）
// ---------------------------------------------------------------------------

test('〔dot-目錄〕藏在 .hidden/ 底下的未登記檔案照樣 RED（dot-檔案跳過、dot-目錄不跳）', () => {
  withScratch(({ root }) => {
    writeAt(root, `${VENDOR_REL}/.hidden/evil.js`, Buffer.from('third-party code'));
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /evil\.js/);
  });
});

test('〔dot-目錄〕dot-目錄裡的 dot-檔案仍跳過 → 只有 dot-檔案時 GREEN', () => {
  withScratch(({ root }) => {
    writeAt(root, `${VENDOR_REL}/.hidden/.DS_Store`, Buffer.from('junk'));
    const r = runGuard(root);
    assert.equal(r.status, 0, r.output);
  });
});

test('〔自相矛盾〕banner_added:false 但 local !== upstream → RED（改了上游碼卻只更新 local）', () => {
  withScratch(({ root, bodies }) => {
    // 模擬：手改一個沒有 banner 的 vendor 檔，並「乖乖」把 local_sha256 更新成新值，
    // upstream_sha256 維持原值。磁碟比對會過，但清單自己已經在說「這檔案不等於上游」。
    const tampered = Buffer.from(bodies.gsapFile);
    tampered[5] ^= 0x01;
    writeAt(root, `${VENDOR_REL}/gsap/gsap.min.js`, tampered);
    const m = JSON.parse(readFileSync(join(root, ...`${VENDOR_REL}/manifest.json`.split('/')), 'utf8'));
    m.vendor[1].local_sha256 = sha256(tampered); // upstream_sha256 不動
    writeManifest(root, m);

    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /自相矛盾/);
    assert.match(r.output, /gsap\.min\.js/);
  });
});

// ---------------------------------------------------------------------------
// Codex P3：banner_added 型別混淆可繞過對帳（fail-open）
// ---------------------------------------------------------------------------

test('〔型別混淆〕facefinder 被改一個 byte ＋ 更新 local ＋ banner_added 寫成字串 "false" → RED', () => {
  withScratch(({ root, manifest, bodies }) => {
    // 這是 Codex 指出的完整攻擊路徑：兩個對帳分支都用嚴格比較，字串 "false"
    // 兩邊都不進，這一筆就只剩「磁碟 hash == local_sha256」一道，把 local 更新就綠了。
    const tampered = Buffer.from(bodies.ffFile);
    tampered[2] ^= 0x01;
    writeAt(root, FACEFINDER_REL, tampered);
    const m = JSON.parse(JSON.stringify(manifest));
    m.facefinder.local_sha256 = sha256(tampered); // upstream_sha256 維持原值
    m.facefinder.banner_added = 'false';          // 字串，不是 boolean
    writeManifest(root, m);

    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /banner_added/);
  });
});

test('〔型別混淆〕vendor 條目的 banner_added 寫成字串 → RED（同一類，vendor 側也要擋）', () => {
  withScratch(({ root, manifest, bodies }) => {
    const tampered = Buffer.from(bodies.gsapFile);
    tampered[3] ^= 0x01;
    writeAt(root, `${VENDOR_REL}/gsap/gsap.min.js`, tampered);
    const m = JSON.parse(JSON.stringify(manifest));
    m.vendor[1].local_sha256 = sha256(tampered);
    m.vendor[1].banner_added = 'false';
    writeManifest(root, m);

    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /banner_added/);
  });
});

test('〔facefinder 恆 false〕banner_added 寫成 true → RED（它是未修改的上游原檔複本）', () => {
  withScratch(({ root, manifest }) => {
    const m = JSON.parse(JSON.stringify(manifest));
    m.facefinder.banner_added = true;
    writeManifest(root, m);
    const r = runGuard(root);
    assert.notEqual(r.status, 0, r.output);
    assert.match(r.output, /facefinder 的 banner_added 必須是 false/);
  });
});
