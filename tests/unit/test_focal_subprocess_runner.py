"""Unit tests for core.focal.subprocess_runner (TASK-152b-T1b).

All scenarios use a fake spawn_fn / fake process. True OS-pipe races
(INV-152b-1a) live in tests/integration/test_focal_detect_child.py.
"""
from __future__ import annotations

import json
import queue
import threading
import time

import pytest

import core.focal.subprocess_runner as subprocess_runner
from core.focal.subprocess_runner import RunnerOutcome, run_detection


# ---------------------------------------------------------------------------
# Isolation: module-level lock + breaker streak must not leak across tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_runner_module_state(monkeypatch):
    monkeypatch.setattr(subprocess_runner, "_breaker_streak", 0)
    lock = subprocess_runner._slot_lock
    if lock.acquire(timeout=0):
        lock.release()
    else:
        monkeypatch.setattr(subprocess_runner, "_slot_lock", threading.Lock())


# ---------------------------------------------------------------------------
# Fake process / stdout pipe (event-driven; kill feeds EOF)
# ---------------------------------------------------------------------------


class _FakeStdout:
    """readline() blocks until feed_line() / feed_eof()."""

    def __init__(self):
        self._q: queue.Queue[str] = queue.Queue()

    def readline(self) -> str:
        return self._q.get()

    def feed_line(self, text: str) -> None:
        self._q.put(text if text.endswith("\n") else text + "\n")

    def feed_eof(self) -> None:
        self._q.put("")


class FakeProcess:
    def __init__(self, *, wait_delay: float = 0.0):
        self.stdout = _FakeStdout()
        self.stderr = None
        self._wait_delay = wait_delay
        self._alive = True
        self.wait_returned_at: float | None = None
        self.kill_called = False

    def kill(self) -> None:
        self.kill_called = True
        self._alive = False
        self.stdout.feed_eof()

    def wait(self) -> int:
        if self._wait_delay > 0:
            time.sleep(self._wait_delay)
        self.wait_returned_at = time.monotonic()
        self._alive = False
        return 0

    def poll(self):
        return None if self._alive else 0


def _spawn_ready_then_result(focal):
    """spawn_fn: READY then JSON result immediately (event-driven)."""

    def spawn_fn(fs_path, ratio):
        proc = FakeProcess()
        payload = {"focal": list(focal) if focal is not None else None}
        proc.stdout.feed_line("READY")
        proc.stdout.feed_line(json.dumps(payload))
        return proc

    return spawn_fn


def _spawn_ready_then_hang():
    """spawn_fn: READY then silence (detect timeout)."""

    def spawn_fn(fs_path, ratio):
        proc = FakeProcess()
        proc.stdout.feed_line("READY")
        return proc

    return spawn_fn


def _spawn_early_eof():
    """spawn_fn: EOF before READY (crashed)."""

    def spawn_fn(fs_path, ratio):
        proc = FakeProcess()
        proc.stdout.feed_eof()
        return proc

    return spawn_fn


def _is_abandoned(outcome: RunnerOutcome, reason: str) -> bool:
    return outcome.kind == "ABANDONED" and outcome.reason == reason


def _is_found(outcome: RunnerOutcome, focal: tuple[float, float]) -> bool:
    return outcome.kind == "FOUND" and outcome.focal == focal


def _maybe_commit(outcome: RunnerOutcome, spy: list) -> None:
    if outcome.kind in ("FOUND", "NO_FACE"):
        spy.append(outcome)


# ---------------------------------------------------------------------------
# DoD tests
# ---------------------------------------------------------------------------


def test_detect_timeout_abandons_without_commit():
    commit_spy: list = []
    outcome = run_detection(
        "/fake.jpg",
        1.5,
        job_key="j1",
        timeout_s=0.05,
        spawn_fn=_spawn_ready_then_hang(),
    )
    _maybe_commit(outcome, commit_spy)
    assert _is_abandoned(outcome, "detect_timeout")
    assert commit_spy == []


def test_detect_completes_before_timeout_delivers_result():
    commit_spy: list = []
    focal = (0.12, 0.34)
    outcome = run_detection(
        "/fake.jpg",
        1.5,
        job_key="j2",
        timeout_s=2.0,
        spawn_fn=_spawn_ready_then_result(focal),
    )
    _maybe_commit(outcome, commit_spy)
    assert _is_found(outcome, focal)
    assert len(commit_spy) == 1


def test_child_reports_no_face_classified_as_no_face_and_resets_breaker(monkeypatch):
    """P3-2：child 回 {"focal": null} 必須真的餵到 run_detection（非手搭
    RunnerOutcome），涵蓋 :146-148 的 `focal is None → NO_FACE` 分支——回歸成
    "crashed" 會讓無臉片永遠不蓋 focal_attempted_at（每次掃描重排）且誤計入
    斷路器（連三張無臉封面就殺掉整個 session 的自動對焦）。"""
    monkeypatch.setattr(subprocess_runner, "_breaker_streak", 2)
    outcome = run_detection(
        "/fake.jpg",
        1.5,
        job_key="no-face",
        timeout_s=2.0,
        spawn_fn=_spawn_ready_then_result(None),
    )
    assert outcome.kind == "NO_FACE"
    assert outcome.focal is None
    assert subprocess_runner._breaker_streak == 0


def test_circuit_breaker_opens_after_three_crashed():
    calls = {"n": 0}

    def spawn_fn(fs_path, ratio):
        calls["n"] += 1
        return _spawn_early_eof()(fs_path, ratio)

    for _ in range(3):
        outcome = run_detection(
            "/fake.jpg", 1.5, job_key="c", timeout_s=1.0, spawn_fn=spawn_fn
        )
        assert _is_abandoned(outcome, "crashed")
    assert calls["n"] == 3

    outcome4 = run_detection(
        "/fake.jpg", 1.5, job_key="c4", timeout_s=1.0, spawn_fn=spawn_fn
    )
    assert _is_abandoned(outcome4, "circuit_open")
    assert calls["n"] == 3


# ---------------------------------------------------------------------------
# TASK-4b: pre_spawn_check / on_outcome hooks
# ---------------------------------------------------------------------------


