"""True-spawn integration tests for core.focal._detect_child (TASK-152b-T1a)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import core.focal.subprocess_runner as subprocess_runner

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = str(REPO_ROOT / "tests" / "fixtures" / "focal" / "sample.jpg")
RATIO = 1.5


# ---------------------------------------------------------------------------
# Isolation: module-level lock + breaker streak must not leak across tests
# (P3-1 — mirrors tests/unit/test_focal_subprocess_runner.py's fixture shape;
# this file's real-spawn tests drive `crashed`/`startup_timeout` ABANDONED
# outcomes that increment the module-level `_breaker_streak`, which would
# otherwise leak into later tests in the same pytest session).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_runner_module_state(monkeypatch):
    monkeypatch.setattr(subprocess_runner, "_breaker_streak", 0)
    lock = subprocess_runner._slot_lock
    if lock.acquire(timeout=0):
        lock.release()
    else:
        monkeypatch.setattr(subprocess_runner, "_slot_lock", threading.Lock())


def _spawn_env():
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT)}


def _cmd(*, with_u: bool = True):
    cmd = [sys.executable]
    if with_u:
        cmd.append("-u")
    cmd.extend(["-m", "core.focal._detect_child", SAMPLE, str(RATIO)])
    return cmd


# ---------------------------------------------------------------------------
# TASK-152b-T1b appendices (do not modify the three tests above)
# ---------------------------------------------------------------------------


def _inline_spawn(script: str):
    """spawn_fn factory: real subprocess via python -u -c <script>."""

    def spawn_fn(fs_path, ratio):
        del fs_path, ratio
        return subprocess.Popen(
            [sys.executable, "-u", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(REPO_ROOT),
            env=_spawn_env(),
            text=True,
            encoding="utf-8",
        )

    return spawn_fn


def test_default_spawn_matches_direct_detect_child_call():
    """_default_spawn must wire to T1a child; raw focal matches pinned oracle."""
    from core.focal.subprocess_runner import run_detection

    outcome = run_detection(
        SAMPLE,
        RATIO,
        job_key="int-default",
        # 這是測試容許值，產品端上限仍是 core/organizer.py 的 _DETECT_TIMEOUT_S，放寬只為容納 CI 平行擁塞。
        timeout_s=30.0,
    )
    assert outcome.kind == "FOUND"
    assert outcome.focal == (0.47336394430921885, 0.4569366320183266)


def test_live_child_with_garbage_first_line_does_not_deadlock_slot_lock():
    """Live child that prints non-READY must be killed so the slot lock releases."""
    from core.focal.subprocess_runner import run_detection

    script = (
        "import time\n"
        "print('GARBAGE_NOT_READY', flush=True)\n"
        "time.sleep(30)\n"
    )
    box: dict = {}

    def call():
        box["outcome"] = run_detection(
            SAMPLE,
            RATIO,
            job_key="int-garbage",
            timeout_s=1.0,
            spawn_fn=_inline_spawn(script),
        )

    t = threading.Thread(target=call, name="focal-garbage-probe")
    t.start()
    t.join(timeout=10.0)
    assert not t.is_alive(), "run_detection deadlocked on live child after garbage line"
    outcome = box["outcome"]
    assert outcome.kind == "ABANDONED"
    assert outcome.reason == "crashed"

    got = subprocess_runner._slot_lock.acquire(timeout=0.5)
    assert got is True
    subprocess_runner._slot_lock.release()
