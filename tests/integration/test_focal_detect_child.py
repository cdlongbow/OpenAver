"""True-spawn integration tests for core.focal._detect_child (TASK-152b-T1a)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from core.focal.detector import detect_focal

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = str(REPO_ROOT / "tests" / "fixtures" / "focal" / "sample.jpg")
RATIO = 1.5


def _spawn_env():
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT)}


def _cmd(*, with_u: bool = True):
    cmd = [sys.executable]
    if with_u:
        cmd.append("-u")
    cmd.extend(["-m", "core.focal._detect_child", SAMPLE, str(RATIO)])
    return cmd


def test_child_stdout_matches_direct_call_raw_precision():
    """CD-152b-1/-2: stdout is READY + full-precision JSON matching direct call."""
    direct = detect_focal(SAMPLE, RATIO)
    assert direct is not None

    p = subprocess.Popen(
        _cmd(with_u=True),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
        env=_spawn_env(),
        text=True,
        encoding="utf-8",
    )
    try:
        stdout, _stderr = p.communicate(timeout=30)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)

    assert p.returncode == 0
    lines = stdout.splitlines()
    assert len(lines) == 2, f"expected exactly 2 stdout lines, got {lines!r}"
    assert lines[0] == "READY"
    payload = json.loads(lines[1])
    child_tuple = tuple(payload["focal"])
    assert child_tuple == direct


def test_child_ready_arrives_before_result_while_alive():
    """Event order: READY first while process still alive, then result."""
    p = subprocess.Popen(
        _cmd(with_u=True),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
        env=_spawn_env(),
        text=True,
        encoding="utf-8",
    )
    try:
        ready_line = p.stdout.readline()
        t_ready = time.monotonic()
        assert ready_line.strip() == "READY"
        assert p.poll() is None
        result_line = p.stdout.readline()
        t_result = time.monotonic()
        payload = json.loads(result_line)
        assert "focal" in payload
        gap = t_result - t_ready
        assert gap >= 0.05, (
            f"READY→result gap {gap:.4f}s too small; READY likely printed after detect"
        )
        p.wait(timeout=10)
        assert p.returncode == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)
        if p.stderr is not None:
            p.stderr.read()


def test_child_flush_true_delivers_ready_without_u_flag():
    """Without -u, flush=True alone must deliver READY before result with a real gap."""
    p = subprocess.Popen(
        _cmd(with_u=False),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
        env=_spawn_env(),
        text=True,
        encoding="utf-8",
    )
    try:
        ready_line = p.stdout.readline()
        t_ready = time.monotonic()
        assert ready_line.strip() == "READY"
        result_line = p.stdout.readline()
        t_result = time.monotonic()
        payload = json.loads(result_line)
        assert "focal" in payload
        gap = t_result - t_ready
        assert gap >= 0.05, (
            f"READY→result gap {gap:.4f}s too small; flush=True likely missing"
        )
        p.wait(timeout=10)
        assert p.returncode == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)
        if p.stderr is not None:
            p.stderr.read()
