"""Unit tests for scripts/verify_artifact_imports.py (TASK-120d-T3).

The script itself is stdlib-only (runs on the artifact interpreter). These
tests import it the same way test_build_artifact_audit.py imports its script.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import verify_artifact_imports as vai  # noqa: E402


def _patch_usable_site_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make main() see a site-packages dir with one always-importable name.

    ``json`` is stdlib, so the site-packages sweep succeeds without touching
    a real venv package (keeps these tests independent of third-party health).
    """
    monkeypatch.setattr(vai, "_site_packages_dirs", lambda: [Path("/fake/site-packages")])
    monkeypatch.setattr(vai, "_top_level_modules", lambda _sp: (["json"], []))


# ── DoD 1: ctypes is on the list ─────────────────────────────────────────────


def test_stdlib_sweep_contains_ctypes():
    """_STDLIB_SWEEP must list ctypes (CD-120d-11 / 修訂 1)."""
    assert "ctypes" in vai._STDLIB_SWEEP


def test_stdlib_sweep_approved_only_ctypes():
    """Opus 修訂 1: the approved list is ctypes and nothing else."""
    assert list(vai._STDLIB_SWEEP) == ["ctypes"]


# ── DoD 2: fail-closed sweep helper + main() exit 1 ──────────────────────────


def test_import_sweep_records_module_name_and_exception():
    """_import_sweep must return (name, exc_type, exc_msg) for a missing module."""
    missing = "__does_not_exist_xyz__"
    fails = vai._import_sweep([missing])
    assert fails, "expected a failure record for a missing module"
    name, exc_type, msg = fails[0]
    assert name == missing
    assert exc_type
    assert missing in msg or exc_type == "ModuleNotFoundError"


def test_import_sweep_success_returns_empty():
    """A present stdlib module must not be recorded as a failure."""
    assert vai._import_sweep(["json"]) == []


def test_main_stdlib_import_failure_exits_1(monkeypatch, capsys):
    """stdlib 失敗必須讓 exit code 變 1，且 stdout 印模組名與例外原文."""
    _patch_usable_site_packages(monkeypatch)
    missing = "__does_not_exist_xyz__"
    monkeypatch.setattr(vai, "_STDLIB_SWEEP", [missing])
    rc = vai.main([])
    assert rc == 1
    out = capsys.readouterr().out
    assert missing in out
    assert "FAIL[stdlib]" in out


# ── DoD 1 / C: Windows windll.user32 probe ───────────────────────────────────


def test_windll_user32_probe_failure_enters_fails(monkeypatch, capsys):
    """win32 + windll.user32 存取拋例外 → 結果進 fails、main() 回 1."""
    _patch_usable_site_packages(monkeypatch)

    class _BoomWindll:
        @property
        def user32(self):
            raise OSError("simulated LoadLibrary failure")

    import ctypes

    monkeypatch.setattr(vai.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", _BoomWindll(), raising=False)
    rc = vai.main([])
    assert rc == 1
    out = capsys.readouterr().out
    assert "ctypes.windll.user32" in out
    assert "simulated LoadLibrary failure" in out


def test_windll_user32_skipped_on_non_windows(monkeypatch, capsys):
    """Non-Windows must print an explicit SKIP, not a silent no-op or FAIL."""
    _patch_usable_site_packages(monkeypatch)
    monkeypatch.setattr(vai.sys, "platform", "linux")
    rc = vai.main([])
    captured = capsys.readouterr()
    assert "SKIP  ctypes.windll.user32" in captured.out
    assert "ctypes.windll.user32" not in captured.err
    assert rc == 0


def test_probe_not_called_when_ctypes_import_fails(monkeypatch, capsys):
    """ctypes import 失敗時不得再呼叫 windll.user32 probe（契約 C）。"""
    _patch_usable_site_packages(monkeypatch)
    orig_sweep = vai._import_sweep

    def _sweep_ctypes_fails(names: list[str]) -> list[tuple[str, str, str]]:
        if "ctypes" in names:
            return [("ctypes", "ImportError", "simulated ctypes import failure")]
        return orig_sweep(names)

    probe_calls: list[object] = []

    def _spy_probe() -> None:
        probe_calls.append(True)
        return None

    monkeypatch.setattr(vai, "_import_sweep", _sweep_ctypes_fails)
    monkeypatch.setattr(vai, "_probe_ctypes_windll_user32", _spy_probe)
    rc = vai.main([])
    assert rc == 1
    assert probe_calls == []
    out = capsys.readouterr().out
    assert "FAIL[stdlib]" in out
    assert "ctypes" in out


# ── DoD 4: missing site-packages still early-returns before stdlib ───────────


def test_main_missing_site_packages_exits_before_stdlib_sweep(monkeypatch, capsys):
    """找不到 site-packages 必須在到達 stdlib sweep 之前以 1 提早退出."""
    sweep_calls: list[list[str]] = []

    def _record(names: list[str]) -> list[tuple[str, str, str]]:
        sweep_calls.append(list(names))
        return []

    monkeypatch.setattr(vai, "_site_packages_dirs", lambda: [])
    monkeypatch.setattr(vai, "_import_sweep", _record)
    rc = vai.main([])
    assert rc == 1
    assert sweep_calls == []
    err = capsys.readouterr().err
    assert "no site-packages" in err


# ── DoD 4 sibling: 0 packages attempted still exit 1 ─────────────────────────


def test_zero_packages_attempted_still_exits_1(monkeypatch, capsys):
    """site-packages 存在但無可 import 模組 → 仍走既有防假綠 return 1."""
    monkeypatch.setattr(vai, "_site_packages_dirs", lambda: [Path("/fake/site-packages")])
    monkeypatch.setattr(vai, "_top_level_modules", lambda _sp: ([], []))
    rc = vai.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "0 packages attempted" in err


# ── DoD 7: each listed module has a Chinese silent-death comment ─────────────


def _docstring_constants(tree: ast.AST) -> set[ast.Constant]:
    """Constant nodes that are Module / Function / Class docstrings."""
    found: set[ast.Constant] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(first.value)
    return found


def _code_string_literal_nodes(src: str) -> list[ast.Constant]:
    tree = ast.parse(src)
    docs = _docstring_constants(tree)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node not in docs
    ]


def _code_string_literals(src: str) -> list[str]:
    """All str constants in src EXCLUDING docstrings (comments never exist in AST)."""
    return [node.value for node in _code_string_literal_nodes(src)]


def _sys_exit_calls(src: str) -> list[int]:
    """Line numbers of real sys.exit(...) Call nodes (prose can never match)."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "exit"
            and isinstance(func.value, ast.Name)
            and func.value.id == "sys"
        ):
            hits.append(node.lineno)
    return hits


def _stdlib_sweep_assign(src: str) -> ast.Assign:
    tree = ast.parse(src)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(t, ast.Name) and t.id == "_STDLIB_SWEEP" for t in node.targets):
            return node
    raise AssertionError("_STDLIB_SWEEP assignment not found")


def _layout_literal_hits(src: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in _code_string_literal_nodes(src):
        value = node.value
        if "Lib/site-packages" in value or re.search(r"lib/python\d", value):
            hits.append((node.lineno, value))
    return hits


def test_each_stdlib_module_has_silent_death_comment():
    """Every _STDLIB_SWEEP entry must have an adjacent Chinese reason comment."""
    src = Path(vai.__file__).read_text(encoding="utf-8")
    assign = _stdlib_sweep_assign(src)
    # Window is the assignment's real AST span (lineno / end_lineno), not a
    # fixed +20 lines. Printed proof: lineno=44 end_lineno=51; the "ctypes"
    # item's trailing / continuation comments (lines 45-50) sit inside that
    # span (closing ']' is line 51), so no post-assignment comment extension.
    assert assign.end_lineno is not None
    lines = src.splitlines()
    window = "\n".join(lines[assign.lineno - 1 : assign.end_lineno])
    chinese = re.compile(r"[\u4e00-\u9fff]")
    for mod in vai._STDLIB_SWEEP:
        # quoted name must appear in the constant block
        assert f'"{mod}"' in window or f"'{mod}'" in window
        # adjacent comments in the same window must contain Chinese
        comment_text = "\n".join(
            ln for ln in window.splitlines() if "#" in ln
        )
        assert chinese.search(comment_text), f"no Chinese comment near {mod}"
        assert len(chinese.findall(comment_text)) >= 8


def test_script_has_no_hardcoded_site_packages_layout():
    """Must stay layout-agnostic: no Lib/ or lib/pythonX.Y/ site-packages paths."""
    src = Path(vai.__file__).read_text(encoding="utf-8")
    hits = _layout_literal_hits(src)
    assert not hits, (
        "hardcoded site-packages layout in non-docstring string literal(s): "
        + "; ".join(f"L{lineno}: {value!r}" for lineno, value in hits)
    )


def test_no_second_return_or_exit_for_stdlib():
    """修訂 4: stdlib sweep must not grow a second return / sys.exit() exit."""
    src = Path(vai.__file__).read_text(encoding="utf-8")
    exits = _sys_exit_calls(src)
    assert exits == [], f"unexpected sys.exit(...) at line(s) {exits}"

    tree = ast.parse(src)
    main_fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    last = main_fn.body[-1]
    assert isinstance(last, ast.Return), (
        f"main() last statement must be a Return, got {type(last).__name__}"
    )
    assert isinstance(last.value, ast.IfExp), (
        "main() last return must be IfExp (return 1 if fails else 0), "
        f"got {type(last.value).__name__ if last.value is not None else None}"
    )


# ── F4: helpers must ignore prose and still catch real code ──────────────────

_DOC_ONLY_SRC = '''\
"""Module docs.

Historically shipped under lib/python3.13/site-packages before the layout-agnostic rewrite.
"""

def helper():
    """Earlier drafts called sys.exit(1) directly."""
    return 0

# lib/python3.12/site-packages was the old layout
'''

_DOC_PLUS_CODE_SRC = _DOC_ONLY_SRC + '''
from pathlib import Path
import sys
P = Path("Lib/site-packages")
sys.exit(2)
'''


def test_helpers_ignore_prose_but_catch_real_layout_and_sys_exit():
    """Docstrings/comments must not trip the helpers; real code still must."""
    literals = _code_string_literals(_DOC_ONLY_SRC)
    assert not any(
        "Lib/site-packages" in value or re.search(r"lib/python\d", value)
        for value in literals
    ), f"prose leaked into code literals: {literals!r}"
    assert _sys_exit_calls(_DOC_ONLY_SRC) == []

    positives = _code_string_literals(_DOC_PLUS_CODE_SRC)
    assert any("Lib/site-packages" in value for value in positives), positives
    assert _sys_exit_calls(_DOC_PLUS_CODE_SRC)
