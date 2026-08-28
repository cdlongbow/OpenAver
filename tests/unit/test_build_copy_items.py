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
    """DoD 3: dmm_prefix_table.json is not ignored by .gitignore."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "dmm_prefix_table.json"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode != 0
