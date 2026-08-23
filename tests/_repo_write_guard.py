"""TASK-127b-T3 —— 純判定核心：G1（sqlite3.connect 接縫）／G2（repo 根快照）。

零 pytest 相依，慣例同 `tests/smoke/_canary_core.py`／`_probe.py`（底線前綴 helper
模組，`tests/` 沒有 `__init__.py`，pytest 會把 `tests/` 插進 sys.path ⇒
`import _repo_write_guard` 從 `tests/conftest.py` 與 `tests/unit/` 底下的測試都可用）。

為什麼判定邏輯不放進 conftest.py：
1. 12 列矩陣要能直接 import 來參數化測試，不必從 conftest 偷東西。
2. T5 的 `pytester` 子 session 要重用同一份判定（子 session 有自己的 tmp／cwd，
   兩個根一律吃環境變數，見下方 ENV_REPO_ROOT / ENV_TMP_ROOTS）。

G1 判定矩陣（白名單制、fail-closed，見 TASK-127b-T3.md §③）：
    row01  ":memory:"                                   → 通過
    row02  "file::memory:?cache=shared" (uri=True)       → 通過
    row03  pytest basetemp 底下的一般路徑                  → 通過
    row04  系統 tempfile.gettempdir() 底下的一般路徑        → 通過
    row05  f"file:{row03/04 路徑}?mode=ro" (uri=True)     → 通過
    row06  真實 DB 的一般路徑                              → 拒絕
    row07  f"file:{真實 DB}?mode=ro" (uri=True)           → 拒絕（mutation 標的）
    row08  相對路徑                                       → 拒絕
    row09  非 file scheme 的 URI                          → 拒絕
    row10  uri=True 但字串不合法／解析拋例外                 → 拒絕（fail-closed）
    row11  非 str／非 PathLike（裸 MagicMock 等）           → 拒絕
    row12  空字串 ""                                      → 拒絕
"""
from __future__ import annotations

import fnmatch
import functools
import json
import os
import sys
import tempfile
import unittest.mock as _mock
from pathlib import Path
from typing import Iterable, NamedTuple, Optional
from urllib.parse import unquote, urlparse

# ── 環境變數（兩個根／模式／報告輸出路徑，全部可注入，不得寫死）──────────────
ENV_REPO_ROOT = "OPENAVER_GUARD_REPO_ROOT"      # 未設 → Path(__file__).resolve().parent.parent
ENV_TMP_ROOTS = "OPENAVER_GUARD_TMP_ROOTS"      # 未設 → 只有系統 tempfile.gettempdir()
                                                 # 有設 → os.pathsep 分隔，**取代**預設而不是附加
ENV_MODE = "OPENAVER_REPO_WRITE_GUARD"          # off / report / fail（未設 → report）
ENV_REPORT_PATH = "OPENAVER_GUARD_REPORT"       # 未設 → tempfile.gettempdir() 底下的固定檔名

MODE_OFF = "off"
MODE_REPORT = "report"
MODE_FAIL = "fail"
# TASK-127b-T5：T3/T4 用 `report` 只印不擋跑清單；T4 把 67 個違規清乾淨之後，
# T5 把預設切成 `fail`——`report` 只在那一次性的清點期間用，不是長期預設。
DEFAULT_MODE = MODE_FAIL
VALID_MODES = (MODE_OFF, MODE_REPORT, MODE_FAIL)

ALLOW_REAL_DB_MARKER = "allow_real_db"

_DEFAULT_REPORT_FILENAME = "openaver_repo_write_guard_report.jsonl"

# G2 必須用「真的」os.scandir，不能在呼叫當下才動態查找 `os.scandir`——實測發現
# `tests/unit/test_gallery_scanner.py` 有 4 支測試會
# `monkeypatch.setattr("core.gallery_scanner.os.scandir", fake_scandir)`。因為
# `core.gallery_scanner` 是 `import os`（不是 `from os import scandir`），
# `core.gallery_scanner.os` 跟全域 `os` 模組是同一個物件，這個 patch 其實是在
# **全域**改寫 `os.scandir`。G2 的 teardown 掃描沒有跟該測試的 `monkeypatch`
# 建立 fixture 依賴關係，兩者的 teardown 先後順序不受保證——實測是 G2 的
# teardown 掃描先於該 `monkeypatch` 的 undo 執行，导致 G2 掃到被那 4 支測試
# 換上的 `fake_scandir`（永遠 raise），把原本會綠的測試變成 ERROR。
# 在**本模組被 import 的當下**（早於任何測試跑、任何 monkeypatch 生效）就把
# 真正的 `os.scandir`存成模組層級常數，往後一律呼叫這個常數，不再動態查
# `os.scandir` 屬性,即可讓 G2 對任何「全域 monkeypatch os.scandir」的既有測試免疫。
_REAL_SCANDIR = os.scandir


class Decision(NamedTuple):
    """G1 對單次 `sqlite3.connect(...)` 呼叫的判定結果。"""

    allowed: bool
    case: str            # row01 ... row12（含可讀後綴），用於 report 的 reason 與人工定位
    resolved: Optional[str]  # 解析後的路徑（realpath 後）；解析不出來時是 None
    raw_repr: str         # 原始參數的 repr——判定拒絕時 T4 靠這個知道命中哪一類


# ── ① 兩個根：可注入，未設走預設 ────────────────────────────────────────────
def get_repo_root() -> Path:
    """repo 根。優先讀 ENV_REPO_ROOT（T5 的 pytester 子 session 用它指自己的 tmp cwd）。"""
    override = os.environ.get(ENV_REPO_ROOT)
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent


def get_tmp_roots() -> list[Path]:
    """合法 tmp 根清單。ENV_TMP_ROOTS 有設就**取代**預設（不是附加），os.pathsep 分隔。"""
    override = os.environ.get(ENV_TMP_ROOTS)
    if override:
        return [Path(p) for p in override.split(os.pathsep) if p]
    return [Path(tempfile.gettempdir())]


def get_mode() -> str:
    val = os.environ.get(ENV_MODE, DEFAULT_MODE)
    if val not in VALID_MODES:
        # 未知值：fail-closed 當成最嚴格的 fail，而不是靜默退回 report。
        return MODE_FAIL
    return val


# ── ③ G1：判定矩陣本體 ──────────────────────────────────────────────────────
def _safe_realpath(path_like) -> Optional[str]:
    """realpath 失敗（例如吃到不支援的型別）一律回 None——呼叫端要 fail-closed。"""
    try:
        return os.path.realpath(str(path_like))
    except Exception:
        return None


def _under_any_root(resolved: str, roots: Iterable) -> bool:
    for root in roots:
        if root is None:
            continue
        root_rp = _safe_realpath(root)
        if root_rp is None:
            continue
        if resolved == root_rp or resolved.startswith(root_rp + os.sep):
            return True
    return False


def evaluate_connect(
    database,
    uri: bool = False,
    *,
    repo_root,
    tmp_roots: Iterable,
    basetemp=None,
) -> Decision:
    """對一次 `sqlite3.connect(database, ..., uri=uri)` 呼叫做白名單判定。

    `repo_root` 目前不參與判定本身（判定只問「在不在合法 tmp 內」），保留參數是
    因為呼叫端（conftest 的 report 訊息／未來擴充）需要它；純函式簽名先留好。
    """
    raw_repr = repr(database)

    # row11（實作中發現的坑，卡片沒預期到）：Mock／MagicMock 從 Python 3.8 起會
    # 自動配置 `__fspath__`，導致 `isinstance(x, os.PathLike)` 對它們回傳 True——
    # 若只靠泛用的「非 str／非 PathLike」檢查，裸 MagicMock 會被誤判成 PathLike，
    # 經 os.fspath() 轉成一個看似合法的相對路徑字串（如
    # "MagicMock/mock.db_path/<id>"），雖然最終仍會被 row08（相對路徑）擋下、
    # 安全性不受影響，但 report 的 reason 會失真成 row08，T4 拿到報告時看不出
    # 「這其實是裸 MagicMock」。故明確先攔 Mock 家族（NonCallableMock 是
    # Mock／MagicMock／AsyncMock／PropertyMock 的共同基底），再做泛用型別檢查。
    if isinstance(database, _mock.NonCallableMock):
        return Decision(False, "row11_bare_mock_pathlike_spoofing", None, raw_repr)

    # row11：非 str／非 PathLike（bytes 等——不是 str 也不是 os.PathLike，
    # 落在同一個 fail-closed 分支，不需要另外特判 bytes）。
    if not isinstance(database, (str, os.PathLike)):
        return Decision(False, "row11_not_str_or_pathlike", None, raw_repr)

    db_str = database if isinstance(database, str) else os.fspath(database)
    if not isinstance(db_str, str):
        # PathLike.__fspath__() 回傳 bytes 的極端情形——今天零呼叫端會這樣，
        # fail-closed 落同一桶。
        return Decision(False, "row11_pathlike_bytes", None, raw_repr)

    # row12：空字串——sqlite 會開一個匿名的「磁碟」DB，不是安全的 no-op。
    if db_str == "":
        return Decision(False, "row12_empty_string", "", raw_repr)

    # row01：純 ":memory:" sentinel（非 URI 形式）。
    if not uri and db_str == ":memory:":
        return Decision(True, "row01_memory", ":memory:", raw_repr)

    roots = list(tmp_roots)
    if basetemp is not None:
        roots = roots + [basetemp]

    if uri:
        try:
            parsed = urlparse(db_str)
        except Exception as exc:  # noqa: BLE001 — fail-closed，任何解析例外都算不合法
            return Decision(False, f"row10_urlparse_raised:{exc!r}", None, raw_repr)

        if parsed.scheme != "file":
            # row09：非 file scheme 的 URI。
            return Decision(False, "row09_non_file_scheme", None, raw_repr)

        path_part = unquote(parsed.path)

        if path_part == ":memory:":
            # row02：file::memory:?cache=shared 這種 URI 形式的記憶體庫。
            return Decision(True, "row02_memory_uri", ":memory:", raw_repr)

        if path_part == "":
            # URI 是 file: 但解不出路徑——沒有落在 12 列表裡的形狀，
            # 但「解析不出來」本身就該 fail-closed 拒絕。
            return Decision(False, "row10_uri_empty_path", None, raw_repr)

        candidate = path_part
    else:
        candidate = db_str

    if not os.path.isabs(candidate):
        # row08：相對路徑（cwd 在跑 pytest 時就是 repo 根）。
        return Decision(False, "row08_relative_path", candidate, raw_repr)

    resolved = _safe_realpath(candidate)
    if resolved is None:
        # 對應 uri=True 走到這裡代表 realpath 本身炸掉的極端情形；同樣落
        # row10 的 fail-closed 語意（表格沒有另開一列，但精神相同）。
        return Decision(False, "row10_realpath_exception", None, raw_repr)

    if _under_any_root(resolved, roots):
        if uri:
            # row05：唯讀 URI 形式，路徑落在合法 tmp 內。
            return Decision(True, "row05_uri_tmp_path", resolved, raw_repr)
        basetemp_rp = _safe_realpath(basetemp) if basetemp is not None else None
        if basetemp_rp is not None and (
            resolved == basetemp_rp or resolved.startswith(basetemp_rp + os.sep)
        ):
            # row03：pytest basetemp 底下。
            return Decision(True, "row03_basetemp", resolved, raw_repr)
        # row04：系統 tempfile.gettempdir() 底下（不一定在 basetemp 內）。
        return Decision(True, "row04_system_tmp", resolved, raw_repr)

    if uri:
        # row07：唯讀 URI 形式指向合法 tmp 之外的路徑——collection.py 四處的形狀。
        return Decision(False, "row07_uri_real_path", resolved, raw_repr)
    # row06：一般路徑指向合法 tmp 之外的路徑（真實 DB 的常見形狀）。
    return Decision(False, "row06_real_path", resolved, raw_repr)


# ── ④ G2：repo 根第一層快照 ──────────────────────────────────────────────────
class RepoRootScanEmptyError(RuntimeError):
    """G2 baseline 掃到 0 個 entry——代表路徑錯了，不是 repo 真的乾淨（BE-TEST-05）。"""


# `.pytest_cache/` 不在專案 .gitignore 裡（由使用者的全域 gitignore 排除），
# 但它是穩定存在的第一層目錄，明文補上避免它被誤判成「新增」。
_EXTRA_IGNORE_PATTERNS = [".pytest_cache/"]

# 🔴 例外中的例外：即使 .gitignore 有 `<MagicMock*` / `<Mock*` 這兩行 pattern
# （見 .gitignore:94-97——那兩行 pattern 是為了擋「MagicMock repr 當檔名」而加的），
# G2 一律把它們當硬失敗，不放行：被 gitignore 蓋住不代表它不該存在。
_DANGEROUS_LEFTOVER_PREFIXES = ("<MagicMock", "<Mock")


def is_dangerous_leftover(name: str) -> bool:
    return name.startswith(_DANGEROUS_LEFTOVER_PREFIXES)


def read_gitignore_patterns(repo_root) -> list[str]:
    """實讀 repo_root/.gitignore 取字面 pattern（略過空行／註解／否定 `!` 規則）。"""
    gi_path = Path(repo_root) / ".gitignore"
    patterns: list[str] = []
    try:
        with open(gi_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("!"):
                    continue
                patterns.append(line)
    except OSError:
        pass
    return patterns


def get_g2_ignore_patterns(repo_root) -> list[str]:
    patterns = list(read_gitignore_patterns(repo_root))
    for extra in _EXTRA_IGNORE_PATTERNS:
        if extra not in patterns:
            patterns.append(extra)
    return patterns


def is_ignored_entry(name: str, is_dir: bool, patterns: Iterable[str]) -> bool:
    """G2 忽略清單判定。`<MagicMock*`／`<Mock*` 永遠不被忽略（硬失敗形狀）。

    ⚠️ **這支只是 `_is_ignored_fast` 的薄包裝，不是第二份實作。**

    T3 初版曾有兩份：這支「逐一線性 fnmatch」的參考實作，以及熱路徑用的
    `_is_ignored_fast`，並靠一支 parity 測試互相印證。**sonnet review 證明那個
    設計是錯的**——parity 測試取樣 24 個手挑名字，漏掉了「同時是目錄限定（結尾 `/`）
    又含萬用字元」這一類，而本 repo 的 `.gitignore:9` 就有一個：

        pattern = "*.egg-info/"，name = "openaver.egg-info"，is_dir=True
          舊參考實作 → False（把整個 pattern 當字面字串比 `name == pattern[:-1]`）
          _is_ignored_fast → True（正確地對目錄限定的萬用字元 pattern 做 glob）

    兩份實作對**現存的**一條 gitignore 規則答案相反，而 parity 測試是綠的。
    這正是本專案自己的反模式（TASK-127b-T1 的技術要點寫過：「自己重寫一份等於
    在測試裡複製一份可能不同步的實作，是假綠的溫床」）。

    ⇒ **處置不是把 parity 測試寫好，是刪掉其中一份。** 語意以編譯路徑為準
    （它才符合 gitignore 的真實語意）。
    """
    return _is_ignored_fast(name, is_dir, _compile_ignore_patterns(tuple(patterns)))


class _CompiledIgnoreRules(NamedTuple):
    """忽略清單的**唯一**判定形式——把「逐一線性比對 ~35 個 pattern」拆成
    「精確名字 O(1) set 查」＋「只對真正含萬用字元的少數 pattern 才 fnmatch」。
    """

    exact_dir_only: frozenset
    exact_any: frozenset
    glob_dir_only: tuple
    glob_any: tuple


_GLOB_CHARS = ("*", "?", "[")


def _compile_ignore_patterns(patterns: tuple) -> _CompiledIgnoreRules:
    exact_dir_only: set = set()
    exact_any: set = set()
    glob_dir_only: list = []
    glob_any: list = []
    for pattern in patterns:
        dir_only = pattern.endswith("/")
        body = pattern[:-1] if dir_only else pattern
        has_wildcard = any(ch in body for ch in _GLOB_CHARS)
        if has_wildcard:
            (glob_dir_only if dir_only else glob_any).append(body)
        else:
            (exact_dir_only if dir_only else exact_any).add(body)
    return _CompiledIgnoreRules(
        frozenset(exact_dir_only), frozenset(exact_any),
        tuple(glob_dir_only), tuple(glob_any),
    )


def _gitignore_stamp(repo_root_str: str) -> tuple:
    """`.gitignore` 的內容指紋（mtime_ns ＋ size），當作快取 key 的一部分。

    不存在時回 `(0, -1)`——`-1` 不可能是真實檔案大小，所以「檔案不存在」與
    「存在但是空的（`(mtime, 0)`）」是兩個不同的 key，不會互相冒充。
    """
    try:
        st = os.stat(os.path.join(str(repo_root_str), ".gitignore"))
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, -1)


@functools.lru_cache(maxsize=8)
def _compile_rules_cached(repo_root_str: str, stamp: tuple) -> _CompiledIgnoreRules:
    patterns = tuple(get_g2_ignore_patterns(repo_root_str))
    return _compile_ignore_patterns(patterns)


def _cached_compiled_rules(repo_root_str: str) -> _CompiledIgnoreRules:
    """快取 `.gitignore` 讀取＋編譯結果——同一個 repo_root ＋ 同一份 `.gitignore`
    內容，在同一個 process 內只讀＋解析一次。

    🔴 **key 必須含 `.gitignore` 的指紋，不能只用 repo_root 路徑。**
    T3 初版只用路徑當 key，sonnet review 直接重現了 stale：同一個暫存目錄，
    `.gitignore` 從 `foo/` 改成 `bar/` 之後，`scan_repo_root_first_level()`
    **仍然套用舊規則**，沒有任何錯誤訊息。

    這條之所以是 P1 而不是 nit：**T5 的 `pytester` 子 session 如果走
    in-process 模式、又在同一個暫存 repo root 上換 `.gitignore` 跑多個情境**
    （寫 G2 mutation 測試最自然的寫法），守衛會靜默給出舊答案，
    而 `maxsize=8` 的 LRU 逐出會讓它時好時壞——**T5 的 mutation 會假綠**。

    加一次 `os.stat`（14158 次呼叫 ≈ 28ms）換掉整類 stale，代價可忽略：
    本 task 實測守衛的端到端成本是 **0.00%**（`off` 212.28s vs `report` 212.26s）。
    """
    return _compile_rules_cached(str(repo_root_str), _gitignore_stamp(repo_root_str))


# 讓 `_cached_compiled_rules.cache_info()` / `.cache_clear()` 仍可用（既有呼叫端與測試）
_cached_compiled_rules.cache_info = _compile_rules_cached.cache_info
_cached_compiled_rules.cache_clear = _compile_rules_cached.cache_clear


def _is_ignored_fast(name: str, is_dir: bool, compiled: _CompiledIgnoreRules) -> bool:
    if is_dangerous_leftover(name):
        return False
    if is_dir and name in compiled.exact_dir_only:
        return True
    if name in compiled.exact_any:
        return True
    if is_dir:
        for pat in compiled.glob_dir_only:
            if fnmatch.fnmatch(name, pat):
                return True
    for pat in compiled.glob_any:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


def scan_repo_root_first_level(repo_root, patterns: Optional[Iterable[str]] = None) -> set[str]:
    """掃 repo_root 第一層（非遞迴），回傳未被忽略清單擋掉的檔名集合。

    熱路徑效能：`patterns=None`（conftest 的正常用法）時走快取編譯後的規則
    （見 `_cached_compiled_rules`）；顯式帶 `patterns=` 時（測試／T5 子
    session 想換一套規則）現場編譯,不吃快取,語意仍與 `is_ignored_entry`
    一致。
    """
    if patterns is None:
        compiled = _cached_compiled_rules(str(repo_root))
    else:
        compiled = _compile_ignore_patterns(tuple(patterns))
    names: set[str] = set()
    with _REAL_SCANDIR(repo_root) as it:
        for entry in it:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if _is_ignored_fast(entry.name, is_dir, compiled):
                continue
            names.add(entry.name)
    return names


def require_nonzero_baseline(entries: set, repo_root) -> None:
    """BE-TEST-05：掃到 0 個 entry 要大聲失敗，不是「repo 很乾淨」。"""
    if not entries:
        raise RepoRootScanEmptyError(
            f"G2 baseline 掃到 0 個 entry：repo_root={repo_root!r} 疑似路徑錯誤或指到空目錄"
        )


# ── ⑤ 雙層拋出的例外基底 ＋ per-test 違規累積器（TASK-127b-T5）──────────────────
class RepoWriteGuardViolation(BaseException):
    """G1／G2 違規的例外基底。

    🔴 刻意繼承 `BaseException`，不是 `Exception`——本專案產品碼有多處
    `except Exception`（含本 bug 的成因本身：`core/enricher.py:719`
    `except Exception as e: logger.warning(...)`）。T3 的 G1 曾拋
    `AssertionError`（`Exception` 的子類），T4 實測 `fail` 模式下這個例外
    在呼叫當下就被那個 broad except 吞掉——測試照樣綠，守衛完全沒有牙齒。
    改繼承 `BaseException` 讓例外能穿透任何 `except Exception`（含未來新增的）。

    已實測（pytest 9.0.3 / py 3.12.3，見 TASK-127b-T5.md「開工前 Opus 已實測的
    四個前提 ①②」）：自訂 `BaseException` 子類不會中斷整場 pytest session
    （其他測試照跑，被拋的那支報成一般 `FAILED`），也不影響 fixture teardown
    的執行——不需要額外的 pytest hook，也不需要避開
    `KeyboardInterrupt`／`SystemExit` 的特殊處理。
    """


class ViolationAccumulator:
    """per-test 違規累積器——零 pytest 相依，供 `conftest.py` 的 G1 fixture
    建立一個新實例、掛在 `request.node.stash` 上，隨 node 生滅。

    🔴 **不可以是模組級全域**（本 branch 一路在消滅的那種東西）——這支類別本身
    只是「一個可以被安全地當成 per-node 值來 new 的容器」，儲存位置的生滅語意
    由呼叫端（conftest）負責，這裡不持有任何模組級狀態。

    只收「會導致 `fail` 模式拋出」的違規——有 `allow_real_db` marker 豁免的
    違規仍要進 report（審計用），但**不**進這裡；否則 teardown 保險層看到
    「有記錄」會對明知放行的測試補刀，讓 marker 這個逃生口失效
    （見 TASK-127b-T5.md 技術要點①-c 義務 1）。
    """

    def __init__(self) -> None:
        self.records: list[dict] = []

    def add(self, record: dict) -> None:
        self.records.append(record)

    def __bool__(self) -> bool:
        return bool(self.records)

    def __len__(self) -> int:
        return len(self.records)


# ── ⑥ report 輸出（JSONL，一行一筆，不准落在 repo 根）─────────────────────────
def get_report_path() -> Path:
    override = os.environ.get(ENV_REPORT_PATH)
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / _DEFAULT_REPORT_FILENAME


def format_g1_record(nodeid: str, decision: Decision, *, allowed_by_marker: bool = False) -> dict:
    reason = decision.case + ("_allowed_by_marker" if allowed_by_marker else "")
    return {
        "nodeid": nodeid,
        "guard": "G1",
        "raw_arg": decision.raw_repr,
        "resolved": decision.resolved,
        "reason": reason,
    }


def format_g2_record(nodeid: str, new_entries: Iterable[str]) -> dict:
    return {
        "nodeid": nodeid,
        "guard": "G2",
        "new_entries": sorted(new_entries),
    }


#: 報告寫入失敗的次數。**不歸零**——收尾要能看到「這次跑的清單是不完整的」。
report_write_failures: list = []


def append_report_record(record: dict, report_path: Optional[Path] = None) -> None:
    """把一筆違規記錄 append 進 JSONL 報告。**永不拋例外。**

    🔴 **為什麼要吞**：`report` 模式的 DoD 是「不准改變任何測試的綠紅判定」。
    這支會 `mkdir` ＋ `open` ＋ `write`——磁碟滿了、`OPENAVER_GUARD_REPORT`
    指到一個目錄、權限不足，任何一個都會讓**一支跟守衛完全無關的測試**變紅，
    而且失敗訊息裡看不出兇手是守衛自己的檔案 I/O。
    （sonnet review 實測：`report_path` 指到目錄 → `IsADirectoryError`。）

    🔴 **為什麼吞了還要吼**：「靜默吞掉」正是 Finding A 的成因本身
    （`core/enricher.py:719` 的 `except Exception` 讓 `nfo_mtime` 回填從沒被執行過），
    也是 `BE-TEST-05` 的形狀。所以失敗要：
      ① 記進 `report_write_failures`（收尾可查、可斷言）
      ② **第一次失敗時對 stderr 印一次醒目告警**（不是每次都印，避免洗版）

    ⚠️ **這裡吞掉的只有「記錄」這個動作，不是「判定」。**
    `fail` 模式拋的是 `RepoWriteGuardViolation`（**`BaseException` 的子類**，見上），
    由 fixture 獨立拋出、不經過這支 ⇒ 報告寫不進去**不會**讓真違規被放過。

    🔴 **不要把那個型別「對齊」成 `AssertionError` 或任何 `Exception` 子類**——
    本 docstring 上一版就是寫 `AssertionError`（Codex review 2026-08-24 抓到）。
    照那句去改就會讓守衛重新被 `core/enricher.py:719` 那種 broad `except Exception`
    吞掉，**而全套測試照樣全綠**——那正是 T3 交出去、T4 才發現的假綠。
    """
    try:
        path = report_path if report_path is not None else get_report_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 — 見 docstring：這裡吞是刻意的
        first = not report_write_failures
        report_write_failures.append({"record": record, "error": repr(exc)})
        if first:
            # 用 sys.stderr.write 不用 print()：ruff 的 T201 禁 print，
            # 而這裡需要的就是「繞過 pytest 的 stdout capture、讓人看得見」。
            sys.stderr.write(
                "\n[repo_write_guard] 🔴 報告寫入失敗，本次的違規清單將不完整："
                f"{exc!r}\n[repo_write_guard]    （測試判定不受影響；"
                "後續同類失敗不再重複印，總數見 report_write_failures）\n"
            )
