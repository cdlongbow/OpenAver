"""Unit tests for scripts/verify_artifact_imports.py (TASK-120d-T3).

The script itself is stdlib-only (runs on the artifact interpreter). These
tests import it the same way test_build_artifact_audit.py imports its script.
"""

from __future__ import annotations

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


def test_each_stdlib_module_has_silent_death_comment():
    """Every _STDLIB_SWEEP entry must have an adjacent Chinese reason comment."""
    src = Path(vai.__file__).read_text(encoding="utf-8")
    lines = src.splitlines()
    sweep_idx = next(i for i, line in enumerate(lines) if "_STDLIB_SWEEP" in line and "=" in line)
    window = "\n".join(lines[sweep_idx : sweep_idx + 20])
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
    # Strip comments / docstring noise loosely; still fail if a real path sneaks in
    # as an assignment or comparison (the module docstring mentions the two
    # layouts in prose, which is documentation, not a hardcoded probe).
    code_lines = []
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("''"):
            continue
        if "Layout-agnostic" in line or "Windows" in line and "site-packages" in line:
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)
    assert "Lib/site-packages" not in code
    assert not re.search(r"lib/python\d", code)


def test_no_second_return_or_exit_for_stdlib():
    """修訂 4: stdlib sweep must not grow a second return / sys.exit() exit."""
    src = Path(vai.__file__).read_text(encoding="utf-8")
    # The final success/fail gate is this single expression.
    assert src.count("return 1 if fails else 0") == 1
    # Ignore comments (the ctypes silent-death note mentions standalone's
    # sys.exit(0) as the user-visible sink — that is not a script exit).
    code_only = "\n".join(
        line.split("#", 1)[0] for line in src.splitlines()
    )
    assert "sys.exit(" not in code_only
