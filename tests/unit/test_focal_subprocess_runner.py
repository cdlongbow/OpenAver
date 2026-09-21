"""Unit tests for core.focal.subprocess_runner (TASK-152b-T1b).

All scenarios use a fake spawn_fn / fake process. True OS-pipe races
(INV-152b-1a) live in tests/integration/test_focal_detect_child.py.
"""
from __future__ import annotations

import json
import logging
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


def test_reap_completes_before_next_spawn_starts():
    """INV-152b-2: concurrent B must not spawn until A's wait() returns."""
    a_spawned = threading.Event()
    wait_done_a: list[float] = []
    spawn_b_at: list[float] = []
    results: dict = {}

    def spawn_a(fs_path, ratio):
        proc = FakeProcess(wait_delay=0.3)
        proc.stdout.feed_line("READY")
        original_wait = proc.wait

        def tracked_wait():
            rc = original_wait()
            wait_done_a.append(proc.wait_returned_at)  # type: ignore[arg-type]
            return rc

        proc.wait = tracked_wait
        a_spawned.set()
        return proc

    def spawn_b(fs_path, ratio):
        spawn_b_at.append(time.monotonic())
        proc = FakeProcess()
        proc.stdout.feed_line("READY")
        proc.stdout.feed_line(json.dumps({"focal": [0.5, 0.5]}))
        return proc

    def run_a():
        results["a"] = run_detection(
            "/a.jpg", 1.5, job_key="a", timeout_s=0.05, spawn_fn=spawn_a
        )

    def run_b():
        results["b"] = run_detection(
            "/b.jpg", 1.5, job_key="b", timeout_s=2.0, spawn_fn=spawn_b
        )

    t_a = threading.Thread(target=run_a, name="focal-reap-a")
    t_a.start()
    assert a_spawned.wait(timeout=2.0), "job A never spawned"
    t_b = threading.Thread(target=run_b, name="focal-reap-b")
    t_b.start()
    t_a.join(timeout=5.0)
    t_b.join(timeout=5.0)
    assert not t_a.is_alive() and not t_b.is_alive()

    assert _is_abandoned(results["a"], "detect_timeout")
    assert _is_found(results["b"], (0.5, 0.5))
    assert len(wait_done_a) == 1
    assert len(spawn_b_at) == 1
    assert spawn_b_at[0] >= wait_done_a[0]


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


def test_popen_raises_releases_slot_lock_without_wait():
    def boom(fs_path, ratio):
        raise OSError("spawn blocked")

    outcome = run_detection(
        "/fake.jpg", 1.5, job_key="p1", timeout_s=1.0, spawn_fn=boom
    )
    assert _is_abandoned(outcome, "crashed")

    got = subprocess_runner._slot_lock.acquire(timeout=0.1)
    assert got is True
    subprocess_runner._slot_lock.release()

    for _ in range(2):
        outcome = run_detection(
            "/fake.jpg", 1.5, job_key="p", timeout_s=1.0, spawn_fn=boom
        )
        assert _is_abandoned(outcome, "crashed")

    outcome4 = run_detection(
        "/fake.jpg", 1.5, job_key="p4", timeout_s=1.0, spawn_fn=boom
    )
    assert _is_abandoned(outcome4, "circuit_open")


def test_circuit_breaker_tripped_log_fires_exactly_once_on_the_crossing_call(caplog):
    """152b pre-merge branch review P2-2 追加：`_apply_breaker` 的 `just_tripped`
    必須恰好在 streak 跨過 `_BREAKER_THRESHOLD` 的那一次為 True，其餘時候皆 False。
    兩種壞掉的形狀都是靜默的：恆 False ⇒ 斷路器跳脫又變回無聲（本輪要修的症狀）；
    恆 True ⇒ 斷路器開路後每次 circuit_open 短路都再刷一次「tripped」warning。"""
    logger_name = "OpenAver.core.focal.subprocess_runner"
    with caplog.at_level(logging.WARNING, logger=logger_name):
        for i in range(subprocess_runner._BREAKER_THRESHOLD):
            outcome = run_detection(
                "/fake.jpg",
                1.5,
                job_key=f"trip{i}",
                timeout_s=1.0,
                spawn_fn=_spawn_early_eof(),
            )
            assert _is_abandoned(outcome, "crashed")
            tripped_so_far = [
                r for r in caplog.records if "circuit breaker tripped" in r.getMessage()
            ]
            if i < subprocess_runner._BREAKER_THRESHOLD - 1:
                assert tripped_so_far == [], (
                    f"tripped log fired too early at call #{i + 1} "
                    f"(streak={subprocess_runner._breaker_streak})"
                )
            else:
                assert len(tripped_so_far) == 1, (
                    f"expected exactly 1 tripped log at the crossing call "
                    f"#{i + 1} (streak={subprocess_runner._breaker_streak}), "
                    f"got {len(tripped_so_far)}"
                )

        # 斷路器已開：再呼叫一次會走 circuit_open 短路，「tripped」不應再出現，
        # 但一般的 "abandoned" 線索仍要留（reason=circuit_open）。
        caplog.clear()
        outcome = run_detection(
            "/fake.jpg",
            1.5,
            job_key="after-trip",
            timeout_s=1.0,
            spawn_fn=_spawn_early_eof(),
        )
        assert _is_abandoned(outcome, "circuit_open")
        assert not any(
            "circuit breaker tripped" in r.getMessage() for r in caplog.records
        ), "tripped log must not repeat on every subsequent circuit_open short-circuit"
        assert any(
            "focal detection abandoned" in r.getMessage()
            and "reason=circuit_open" in r.getMessage()
            for r in caplog.records
        )


def test_breaker_streak_resets_on_found_between_crashes():
    sequence = ["crash", "found", "crash", "crash"]
    idx = {"i": 0}

    def spawn_fn(fs_path, ratio):
        step = sequence[idx["i"]]
        idx["i"] += 1
        if step == "crash":
            return _spawn_early_eof()(fs_path, ratio)
        return _spawn_ready_then_result((0.1, 0.2))(fs_path, ratio)

    outcomes = [
        run_detection("/f.jpg", 1.5, job_key=f"s{i}", timeout_s=1.0, spawn_fn=spawn_fn)
        for i in range(4)
    ]
    assert _is_abandoned(outcomes[0], "crashed")
    assert _is_found(outcomes[1], (0.1, 0.2))
    assert _is_abandoned(outcomes[2], "crashed")
    assert _is_abandoned(outcomes[3], "crashed")
    # After FOUND reset, two crashes ⇒ streak=2, breaker still closed
    assert subprocess_runner._breaker_streak == 2
    fifth = run_detection(
        "/f.jpg", 1.5, job_key="s5", timeout_s=1.0, spawn_fn=_spawn_early_eof()
    )
    assert _is_abandoned(fifth, "crashed")  # third after reset → opens next
    assert subprocess_runner._breaker_streak == 3


def test_breaker_streak_resets_on_detect_timeout_between_crashes():
    sequence = ["crash", "timeout", "crash", "crash"]
    idx = {"i": 0}

    def spawn_fn(fs_path, ratio):
        step = sequence[idx["i"]]
        idx["i"] += 1
        if step == "crash":
            return _spawn_early_eof()(fs_path, ratio)
        return _spawn_ready_then_hang()(fs_path, ratio)

    outcomes = []
    for i, step in enumerate(sequence):
        timeout_s = 0.05 if step == "timeout" else 1.0
        outcomes.append(
            run_detection(
                "/f.jpg", 1.5, job_key=f"t{i}", timeout_s=timeout_s, spawn_fn=spawn_fn
            )
        )
    assert _is_abandoned(outcomes[0], "crashed")
    assert _is_abandoned(outcomes[1], "detect_timeout")
    assert _is_abandoned(outcomes[2], "crashed")
    assert _is_abandoned(outcomes[3], "crashed")
    assert subprocess_runner._breaker_streak == 2


def test_abandon_reason_does_not_leak_to_next_call():
    first = run_detection(
        "/a.jpg",
        1.5,
        job_key="leak1",
        timeout_s=0.05,
        spawn_fn=_spawn_ready_then_hang(),
    )
    assert _is_abandoned(first, "detect_timeout")

    second = run_detection(
        "/b.jpg",
        1.5,
        job_key="leak2",
        timeout_s=2.0,
        spawn_fn=_spawn_ready_then_result((0.7, 0.8)),
    )
    assert _is_found(second, (0.7, 0.8))
    assert not _is_abandoned(second, "detect_timeout")


def test_abandon_precedence_discards_late_result_line():
    """CD-152b-3: once abandon_reason is set, late JSON/EOF must not reclassify."""
    from core.focal.subprocess_runner import _CallState, _classify_event

    state = _CallState()
    state.set_abandon("detect_timeout")
    late_found = _classify_event(("line", '{"focal": [0.5, 0.5]}'), state)
    assert _is_abandoned(late_found, "detect_timeout")
    assert late_found.kind != "FOUND"

    state2 = _CallState()
    state2.set_abandon("startup_timeout")
    late_eof = _classify_event(("eof", None), state2)
    assert _is_abandoned(late_eof, "startup_timeout")
    assert late_eof.reason != "crashed"


def test_breaker_rechecked_after_acquiring_slot_lock(monkeypatch):
    """Streak that opens only after acquire must still short-circuit spawn."""
    spawn_calls = {"n": 0}
    real_lock = subprocess_runner._slot_lock

    class TripAfterAcquireLock:
        """Deterministic seam: trip streak after acquire, before spawn."""

        def acquire(self, *args, **kwargs):
            ok = real_lock.acquire(*args, **kwargs)
            if ok:
                # Outer short-circuit already passed with streak=0; trip the
                # authoritative under-lock recheck before spawn_fn runs.
                monkeypatch.setattr(
                    subprocess_runner,
                    "_breaker_streak",
                    subprocess_runner._BREAKER_THRESHOLD,
                )
            return ok

        def release(self):
            return real_lock.release()

    monkeypatch.setattr(subprocess_runner, "_slot_lock", TripAfterAcquireLock())

    def spawn_fn(fs_path, ratio):
        spawn_calls["n"] += 1
        return _spawn_ready_then_result((0.1, 0.2))(fs_path, ratio)

    outcome = run_detection(
        "/fake.jpg", 1.5, job_key="recheck", timeout_s=1.0, spawn_fn=spawn_fn
    )
    assert _is_abandoned(outcome, "circuit_open")
    assert spawn_calls["n"] == 0

    got = subprocess_runner._slot_lock.acquire(timeout=0.1)
    assert got is True
    subprocess_runner._slot_lock.release()
