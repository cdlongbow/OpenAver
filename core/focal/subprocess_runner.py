"""Parent-side focal detection subprocess runner (TASK-152b-T1b).

Spawns a child via spawn_fn (default: core.focal._detect_child), waits with a
background reader thread + queue.Queue (CD-152b-18), classifies FOUND / NO_FACE
/ ABANDONED, reaps before releasing the single slot lock, and maintains a
session-level circuit breaker (CD-152b-17).
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.logger import get_logger

logger = get_logger(__name__)

_STARTUP_TIMEOUT_S = 10.0
_BREAKER_THRESHOLD = 3
_slot_lock = threading.Lock()
_breaker_streak = 0

_TIMEOUT = object()  # sentinel from queue.get timeout


@dataclass(frozen=True)
class RunnerOutcome:
    """Three-way result of run_detection (CD-152b-3)."""

    kind: str  # "FOUND" | "NO_FACE" | "ABANDONED"
    focal: tuple[float, float] | None = None
    reason: str | None = None


def _found(x: float, y: float) -> RunnerOutcome:
    return RunnerOutcome(kind="FOUND", focal=(x, y))


def _no_face() -> RunnerOutcome:
    return RunnerOutcome(kind="NO_FACE")


def _abandoned(reason: str) -> RunnerOutcome:
    return RunnerOutcome(kind="ABANDONED", reason=reason)


class _CallState:
    """Per-invocation abandon reason (monotonic write-once; never module-level)."""

    __slots__ = ("abandon_reason",)

    def __init__(self) -> None:
        self.abandon_reason: str | None = None

    def set_abandon(self, reason: str) -> None:
        if self.abandon_reason is None:
            self.abandon_reason = reason


def _default_spawn(fs_path: str, ratio: float):
    """Spawn core.focal._detect_child per CD-152b-1."""
    import core.focal as focal_pkg

    root = Path(focal_pkg.__file__).resolve().parents[2]
    cmd = [
        sys.executable,
        "-u",
        "-m",
        "core.focal._detect_child",
        fs_path,
        str(ratio),
    ]
    kwargs: dict[str, Any] = {
        "args": cmd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": str(root),
        "env": {**os.environ, "PYTHONPATH": str(root)},
        "text": True,
        "encoding": "utf-8",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(**kwargs)


def _start_reader(stdout, event_q: queue.Queue) -> None:
    def _read() -> None:
        try:
            while True:
                line = stdout.readline()
                if line == "" or line is None:
                    event_q.put(("eof", None))
                    return
                event_q.put(("line", line.rstrip("\r\n")))
        except Exception:
            event_q.put(("eof", None))

    threading.Thread(target=_read, name="focal-stdout-reader", daemon=True).start()


def _start_stderr_drain(stderr) -> None:
    if stderr is None:
        return

    def _drain() -> None:
        try:
            for line in stderr:
                logger.debug("focal child stderr: %s", line.rstrip())
        except Exception:
            logger.debug("focal child stderr drain ended", exc_info=True)

    threading.Thread(target=_drain, name="focal-stderr-drain", daemon=True).start()


def _queue_get(event_q: queue.Queue, timeout_s: float):
    try:
        return event_q.get(timeout=timeout_s)
    except queue.Empty:
        return _TIMEOUT


def _safe_kill(child) -> None:
    try:
        child.kill()
    except Exception:
        logger.exception("focal child kill failed")


def _parse_result_line(text: str) -> RunnerOutcome | None:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or "focal" not in payload:
        return None
    focal = payload["focal"]
    if focal is None:
        return _no_face()
    if (
        isinstance(focal, (list, tuple))
        and len(focal) == 2
        and all(isinstance(v, (int, float)) for v in focal)
    ):
        return _found(float(focal[0]), float(focal[1]))
    return None


def _classify_event(event, call_state: _CallState) -> RunnerOutcome:
    """Classify at the moment an event is consumed (CD-152b-3)."""
    # Under T1b's single-writer design this branch is only hit by the direct
    # unit test (normal flow returns ABANDONED on queue.Empty without consuming
    # a late event). Kept for CD-152b-3: once abandon_reason is set, late JSON
    # and EOF are discarded. 152d's cancel() adds a second cross-thread writer
    # and will exercise this path in the live flow.
    if call_state.abandon_reason is not None:
        return _abandoned(call_state.abandon_reason)
    if event is None or event is _TIMEOUT or event[0] == "eof":
        return _abandoned("crashed")
    parsed = _parse_result_line(event[1])
    if parsed is None:
        return _abandoned("crashed")
    return parsed


def _apply_breaker(outcome: RunnerOutcome) -> None:
    global _breaker_streak
    if outcome.kind in ("FOUND", "NO_FACE"):
        _breaker_streak = 0
        return
    if outcome.kind != "ABANDONED":
        return
    reason = outcome.reason
    if reason in ("startup_timeout", "crashed"):
        _breaker_streak += 1
    elif reason == "detect_timeout":
        _breaker_streak = 0
    # circuit_open / skipped_disabled: neither increment nor reset


def _run_child_phases(
    child,
    timeout_s: float,
    call_state: _CallState,
) -> RunnerOutcome:
    """Startup + detect phases. Returns classification only.

    Whether to kill is decided by the caller from the outcome (ABANDONED ⇒
    kill before wait), so live children that printed garbage cannot deadlock
    the slot lock on an unbounded wait().
    """
    event_q: queue.Queue = queue.Queue()
    _start_reader(child.stdout, event_q)
    _start_stderr_drain(getattr(child, "stderr", None))

    startup_limit = _STARTUP_TIMEOUT_S  # read module attr at call time
    event = _queue_get(event_q, startup_limit)
    if event is _TIMEOUT:
        # Write abandon reason before kill (kill happens in caller's finally).
        call_state.set_abandon("startup_timeout")
        return _abandoned("startup_timeout")

    # Same CD-152b-3 precedence; see comment on _classify_event.
    if call_state.abandon_reason is not None:
        return _classify_event(event, call_state)
    if event[0] == "eof":
        return _abandoned("crashed")
    if event[1] != "READY":
        return _abandoned("crashed")

    event = _queue_get(event_q, timeout_s)
    if event is _TIMEOUT:
        call_state.set_abandon("detect_timeout")
        return _abandoned("detect_timeout")

    return _classify_event(event, call_state)


def run_detection(
    fs_path: str,
    ratio: float,
    *,
    job_key: str,
    timeout_s: float,
    spawn_fn: Callable[..., Any] = _default_spawn,
) -> RunnerOutcome:
    """Run one focal detection in a child process (CD-152b-3/4/10/17/18)."""
    logger.debug("run_detection job_key=%s path=%s", job_key, fs_path)
    if _breaker_streak >= _BREAKER_THRESHOLD:
        return _abandoned("circuit_open")

    child = None
    need_kill = False
    call_state = _CallState()

    _slot_lock.acquire()
    try:
        try:
            child = spawn_fn(fs_path, ratio)
        except OSError:
            logger.exception("focal spawn_fn raised")
            outcome = _abandoned("crashed")
            _apply_breaker(outcome)
            return outcome

        outcome = _run_child_phases(child, timeout_s, call_state)
        # Any abandon => terminate before wait (CD-152b-10). Harmless if child
        # already exited; required if it is still alive after garbage stdout.
        need_kill = outcome.kind == "ABANDONED"
        _apply_breaker(outcome)
        return outcome
    finally:
        if child is not None:
            if need_kill:
                _safe_kill(child)
            try:
                child.wait()
            except Exception:
                logger.exception("focal child wait failed")
        _slot_lock.release()
