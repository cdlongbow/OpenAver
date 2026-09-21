"""True-spawn integration tests for core.focal._detect_child (TASK-152b-T1a)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import core.focal.subprocess_runner as subprocess_runner
from core.focal.detector import detect_focal

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


def test_real_timeout_kill_classified_as_detect_timeout_not_crashed():
    """INV-152b-1a(a): parent kill after READY must be detect_timeout, not crashed."""
    from core.focal.subprocess_runner import run_detection

    script = (
        "import sys, time\n"
        "print('READY', flush=True)\n"
        "time.sleep(2)\n"
        "print('{\"focal\": [0.1, 0.2]}', flush=True)\n"
    )
    outcome = run_detection(
        SAMPLE,
        RATIO,
        job_key="int-timeout",
        timeout_s=0.3,
        spawn_fn=_inline_spawn(script),
    )
    assert outcome.kind == "ABANDONED"
    assert outcome.reason == "detect_timeout"


def test_real_early_crash_classified_as_crashed_not_startup_timeout():
    """INV-152b-1a(b): exit before READY must be crashed, not startup_timeout."""
    from core.focal.subprocess_runner import run_detection

    script = "import sys\nsys.exit(1)\n"
    outcome = run_detection(
        SAMPLE,
        RATIO,
        job_key="int-crash",
        timeout_s=2.0,
        spawn_fn=_inline_spawn(script),
    )
    assert outcome.kind == "ABANDONED"
    assert outcome.reason == "crashed"


def test_default_spawn_matches_direct_detect_child_call():
    """_default_spawn must wire to T1a child; raw focal matches pinned oracle."""
    from core.focal.subprocess_runner import run_detection

    outcome = run_detection(
        SAMPLE,
        RATIO,
        job_key="int-default",
        timeout_s=5.0,
    )
    assert outcome.kind == "FOUND"
    assert outcome.focal == (0.47336394430921885, 0.4569366320183266)


def test_startup_hang_classified_as_startup_timeout(monkeypatch):
    """Startup hang (no READY) must be startup_timeout, not crashed/detect_timeout."""
    import core.focal.subprocess_runner as subprocess_runner
    from core.focal.subprocess_runner import run_detection

    monkeypatch.setattr(subprocess_runner, "_STARTUP_TIMEOUT_S", 0.3)
    monkeypatch.setattr(subprocess_runner, "_breaker_streak", 0)

    script = "import time\ntime.sleep(5)\n"
    outcome = run_detection(
        SAMPLE,
        RATIO,
        job_key="int-startup",
        timeout_s=5.0,
        spawn_fn=_inline_spawn(script),
    )
    assert outcome.kind == "ABANDONED"
    assert outcome.reason == "startup_timeout"


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


def test_crop_to_poster_via_runner_matches_direct_detect_focal_bytes(tmp_path):
    """DoD③：crop_to_poster 經真 spawn run_detection 產出的 poster，
    與同圖同程序直接呼叫 detect_focal() 獨立算出的期望裁切 JPEG bytes 逐位元相同。
    """
    from PIL import Image

    from core.organizer import _poster_window_ratio, crop_to_poster

    src = REPO_ROOT / "tests" / "fixtures" / "actress_photos" / "wide_offcenter_face.jpg"
    dst = tmp_path / "poster_via_runner.jpg"
    assert crop_to_poster(str(src), str(dst), number="FC2-1234567") is True
    assert dst.exists()

    with Image.open(src) as img:
        w, h = img.size
    assert h / w < 1.0, "fixture 應落在分支3（橫向）"
    r_window = _poster_window_ratio(w, h)
    assert r_window is not None

    focal = detect_focal(str(src), r_window)
    assert focal is not None

    crop_w = w - int(w / 1.9)
    x0 = max(min(int(w * focal[0]) - crop_w // 2, w - crop_w), 0)
    with Image.open(src) as img:
        expected_cropped = img.convert("RGB").crop((x0, 0, x0 + crop_w, h))
    expected_path = tmp_path / "poster_oracle.jpg"
    expected_cropped.save(str(expected_path), "JPEG", quality=95, subsampling=0)

    assert dst.read_bytes() == expected_path.read_bytes()
