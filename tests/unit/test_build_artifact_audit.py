"""Unit tests for scripts/audit_build_artifact.py.

Tests use synthetic in-memory/temp ZIPs to verify:
  - playwright (hard-fail tier) → exit 1
  - uvloop (warn tier) → default exit 0, --strict exit 1
  - ZIP exceeding --max-mb → exit 1
  - Clean ZIP with baseline noise (pydantic/mypy.py, pytest_base_url/,
    greenlet/, *__mypyc.cp312-win_amd64.pyd) → exit 0 (no false positives)
  - glob matching 0 files → SystemExit (non-zero)

The audit() function is imported directly for fast, no-subprocess tests.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path


# Ensure the repo root is importable so we can import the script directly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from audit_build_artifact import audit  # noqa: E402  (after path insert)


# ── Helpers ───────────────────────────────────────────────────────────────────


_FACEFINDER_ENTRY = "OpenAver/app/core/focal/facefinder"


def _make_zip(
    tmp_path: Path,
    entries: dict[str, bytes | None],
    name: str = "test.zip",
    include_facefinder: bool = True,
) -> Path:
    """Build a ZIP at tmp_path/name with the given {entry_path: content} mapping.

    Pass None as content to use a tiny 4-byte placeholder.

    include_facefinder (TASK-98a-T1): the facefinder gate is an unconditional
    hard-fail, so by default this helper injects a valid 240KB
    OpenAver/app/core/focal/facefinder entry (unless the caller already
    provided that exact key, or passed include_facefinder=False) — this keeps
    every pre-existing "expected green" case green without each of them having
    to know about the new gate.
    """
    zip_path = tmp_path / name
    if include_facefinder and _FACEFINDER_ENTRY not in entries:
        entries = {**entries, _FACEFINDER_ENTRY: b"\0" * 240_000}
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry_name, content in entries.items():
            zf.writestr(entry_name, content if content is not None else b"test")
    return zip_path


def _site(pkg: str, filename: str = "__init__.py") -> str:
    """Return a canonical site-packages path for a package."""
    return f"OpenAver/python/Lib/site-packages/{pkg}/{filename}"


# ── Hard-fail tier ────────────────────────────────────────────────────────────


def test_playwright_hard_fails(tmp_path):
    """playwright in site-packages/ must cause exit 1 (hard-fail tier)."""
    zp = _make_zip(tmp_path, {_site("playwright", "driver/node.exe"): b"x"})
    code, msgs = audit(zp, "win", 55.0, False)
    assert code == 1, f"Expected exit 1 for playwright, got {code}\nMessages: {msgs}"
    combined = "\n".join(msgs)
    assert "playwright" in combined
    assert "FAIL" in combined


# ── Warn tier (uvloop / langdetect) ──────────────────────────────────────────


# ── Size ceiling ──────────────────────────────────────────────────────────────


def test_oversized_zip_fails(tmp_path):
    """ZIP exceeding --max-mb must cause exit 1."""
    # Create a ZIP that is over 1 MB compressed (we use incompressible data)
    big_data = bytes(range(256)) * (1024 * 5)  # ~1.28 MB uncompressed
    zp = _make_zip(
        tmp_path,
        {"OpenAver/python/Lib/site-packages/dummy/__init__.py": big_data},
    )
    # Set max to 0 MB — guaranteed to fail
    code, msgs = audit(zp, "win", 0.0, False)
    assert code == 1, f"Expected exit 1 for oversized ZIP, got {code}"
    assert any("SIZE" in m or "ceiling" in m.lower() for m in msgs)


# ── False-positive / baseline noise tests ─────────────────────────────────────


# ── dist-info existence checks (spec-97 G-2 static first pass) ─────────────────


def test_curl_cffi_pkg_without_dist_info_fails(tmp_path):
    """curl_cffi package present but its .dist-info stripped → HARD-FAIL.

    This is the EXACT spec-97 regression: dist-info gone → PackageNotFoundError
    at import → javdb silently disabled in every release. The audit must catch it.
    """
    zp = _make_zip(tmp_path, {_site("curl_cffi", "__init__.py"): b"x"})
    code, msgs = audit(zp, "win", 55.0, False)
    assert code == 1, f"curl_cffi without dist-info must hard-fail, got {code}\n" + "\n".join(msgs)
    assert any("curl_cffi" in m and "FAIL" in m for m in msgs)


# ── facefinder cascade existence checks (TASK-98a-T1) ───────────────────────────


def test_facefinder_mislocated_same_name_fails(tmp_path):
    """A same-named 'facefinder' file at the WRONG path (app/core/facefinder,
    or under site-packages/) must NOT satisfy the anchored check -> fail."""
    zp = _make_zip(
        tmp_path,
        {
            _site("fastapi", "__init__.py"): b"x",
            "OpenAver/app/core/facefinder": b"\0" * 240_000,
            "OpenAver/python/Lib/site-packages/somepkg/facefinder": b"\0" * 240_000,
        },
        include_facefinder=False,
    )
    code, msgs = audit(zp, "win", 55.0, False)
    assert code == 1, (
        "mislocated same-named facefinder must not satisfy the anchored gate,"
        f" got {code}\n" + "\n".join(msgs)
    )
    assert any("FACEFINDER" in m and "FAIL" in m for m in msgs)


def test_facefinder_undersized_fails(tmp_path):
    """facefinder present at the correct path but only 10 bytes -> fail
    (proves the size floor, not just presence)."""
    zp = _make_zip(
        tmp_path,
        {
            _site("fastapi", "__init__.py"): b"x",
            "OpenAver/app/core/focal/facefinder": b"\0" * 10,
        },
        include_facefinder=False,
    )
    code, msgs = audit(zp, "win", 55.0, False)
    assert code == 1, f"undersized facefinder must hard-fail, got {code}\n" + "\n".join(msgs)
    assert any("FACEFINDER" in m and "FAIL" in m for m in msgs)


# ── Glob resolution errors ────────────────────────────────────────────────────


# ── Test-tool still hard-fails on mac platform ────────────────────────────────


def test_playwright_hard_fails_on_mac(tmp_path):
    """Test tools must hard-fail on mac too (playwright is never OK anywhere)."""
    zp = _make_zip(tmp_path, {_site("playwright", "driver/node.exe"): b"x"})
    code, msgs = audit(zp, "mac", 55.0, False)
    assert code == 1


# ── Summary message ───────────────────────────────────────────────────────────


