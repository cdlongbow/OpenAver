"""Acceptance tests for build shipping items (TASK-134a-T3 DoD 1-3)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import build
import build_macos

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_build_copy_items_contains_dmm_prefix_table():
    """DoD 1: dmm_prefix_table.json is included in build.py COPY_ITEMS."""
    assert "dmm_prefix_table.json" in build.COPY_ITEMS


def test_build_macos_copy_items_contains_dmm_prefix_table():
    """DoD 2: dmm_prefix_table.json is included in build_macos.py COPY_ITEMS."""
    assert "dmm_prefix_table.json" in build_macos.COPY_ITEMS


def test_dmm_prefix_table_not_gitignored():
    """DoD 3: dmm_prefix_table.json is not ignored by .gitignore (--no-index ensures tracked files are checked against rules)."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "dmm_prefix_table.json"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode != 0


def test_build_copy_items_contains_maker_mapping():
    """maker_mapping.json is included in build.py COPY_ITEMS."""
    assert "maker_mapping.json" in build.COPY_ITEMS


def test_build_macos_copy_items_contains_maker_mapping():
    """maker_mapping.json is included in build_macos.py COPY_ITEMS."""
    assert "maker_mapping.json" in build_macos.COPY_ITEMS


def test_maker_mapping_not_gitignored():
    """maker_mapping.json is not ignored by .gitignore (--no-index ensures tracked files are checked against rules)."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "maker_mapping.json"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode != 0


def test_maker_mapping_is_git_tracked():
    """maker_mapping.json is tracked by Git."""
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "maker_mapping.json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

