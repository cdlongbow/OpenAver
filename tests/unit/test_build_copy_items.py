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
    """DoD 3: dmm_prefix_table.json is not ignored by .gitignore (--no-index ensures tracked files are checked against rules).

    Asserts rc == 1, not rc != 0: git check-ignore only returns 0 (ignored) or 1 (not ignored) on success, and any other code (e.g. 128 when cwd isn't a git repo) is a git execution failure that must not be treated as a pass.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "dmm_prefix_table.json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, (
        "expected rc=1 (not ignored); rc=0 means dmm_prefix_table.json IS matched by "
        f".gitignore, any other rc means git itself failed to run: rc={result.returncode} "
        f"stderr={result.stderr!r}"
    )


def test_build_copy_items_contains_maker_mapping():
    """maker_mapping.json is included in build.py COPY_ITEMS."""
    assert "maker_mapping.json" in build.COPY_ITEMS


def test_build_macos_copy_items_contains_maker_mapping():
    """maker_mapping.json is included in build_macos.py COPY_ITEMS."""
    assert "maker_mapping.json" in build_macos.COPY_ITEMS


def test_maker_mapping_not_gitignored():
    """maker_mapping.json is not ignored by .gitignore (--no-index ensures tracked files are checked against rules).

    Asserts rc == 1, not rc != 0: git check-ignore only returns 0 (ignored) or 1 (not ignored) on success, and any other code (e.g. 128 when cwd isn't a git repo) is a git execution failure that must not be treated as a pass.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "maker_mapping.json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, (
        "expected rc=1 (not ignored); rc=0 means maker_mapping.json IS matched by "
        f".gitignore, any other rc means git itself failed to run: rc={result.returncode} "
        f"stderr={result.stderr!r}"
    )


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


def test_build_py_readme_does_not_point_to_legacy_web_config():
    """README in build.py does not point to legacy app\\web\\config.json."""
    assert r"app\\web\\config.json" not in Path(build.__file__).read_text(encoding="utf-8")


def test_build_py_readme_points_to_output_data_root():
    """README in build.py points to data root app\\output\\."""
    assert r"app\\output\\" in Path(build.__file__).read_text(encoding="utf-8")


def test_build_copy_items_excludes_output():
    """output directory is not packaged into Windows release ZIP."""
    assert "output" not in {Path(item).name for item in build.COPY_ITEMS}


def test_build_macos_copy_items_excludes_output():
    """output directory is not packaged into macOS release bundle."""
    assert "output" not in {Path(item).name for item in build_macos.COPY_ITEMS}

