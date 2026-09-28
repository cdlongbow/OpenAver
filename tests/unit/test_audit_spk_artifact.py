"""Synthetic DSM packages for the SPK artifact audit."""

from __future__ import annotations

import io
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


AUDITOR = Path(__file__).resolve().parents[2] / "scripts/audit_spk_artifact.py"


def _add_file(archive: tarfile.TarFile, name: str, content: bytes = b"x") -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    archive.addfile(info, io.BytesIO(content))


def _make_spk(
    path: Path,
    archs: tuple[str, ...],
    dist_counts: dict[str, int] | None = None,
) -> None:
    package_bytes = io.BytesIO()
    with tarfile.open(fileobj=package_bytes, mode="w:gz") as package:
        for arch in archs:
            _add_file(package, f"python-{arch}/bin/python3")
            _add_file(package, f"python-{arch}/bin/python3.12")
            for number in range((dist_counts or {}).get(arch, 5)):
                _add_file(
                    package,
                    f"python-{arch}/lib/python3.12/site-packages/pkg{number}-1.0.dist-info/METADATA",
                )
    with tarfile.open(path, mode="w") as spk:
        _add_file(spk, "package.tgz", package_bytes.getvalue())


def _audit(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDITOR), str(path), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_audit_spk_artifact_accepts_complete_package(tmp_path: Path) -> None:
    spk = tmp_path / "complete.spk"
    _make_spk(spk, ("aarch64", "x86_64"))

    result = _audit(spk)

    assert result.returncode == 0, result.stdout + result.stderr


def test_audit_spk_artifact_flags_missing_architecture(tmp_path: Path) -> None:
    spk = tmp_path / "missing.spk"
    _make_spk(spk, ("aarch64",))

    result = _audit(spk)

    assert result.returncode != 0
    assert "x86_64" in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("aarch64_count", "x86_64_count", "expected_code"),
    [(2, 5, 1), (2, 4, 0)],
)
def test_audit_spk_artifact_dist_info_ratio_boundary(
    tmp_path: Path,
    aarch64_count: int,
    x86_64_count: int,
    expected_code: int,
) -> None:
    spk = tmp_path / "ratio.spk"
    _make_spk(
        spk,
        ("aarch64", "x86_64"),
        {"aarch64": aarch64_count, "x86_64": x86_64_count},
    )

    result = _audit(spk)

    assert result.returncode == expected_code, result.stdout + result.stderr
