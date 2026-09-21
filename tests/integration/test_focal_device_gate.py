"""tests/integration/test_focal_device_gate.py — TASK-5c path①④ device gate.

Cross-module behaviour: two consecutive ABANDONED("detect_timeout") outcomes
disable the device; the third candidate must not spawn (pre_spawn_check short-
circuits to ABANDONED("skipped_disabled")).

Trap A/B avoidance (TASK-5c directive §7):
- Do NOT inject a fake FocalWorker.detect_fn that skips run_detection.
- Do NOT monkeypatch subprocess_runner._default_spawn (bound at def time).
- Instead monkeypatch the consumer module's run_detection name to a wrapper
  that forwards to the real runner with an injected spawn_fn spy.
"""
from __future__ import annotations

import queue
import threading

import pytest
from PIL import Image

import core.config as core_config
import core.focal.subprocess_runner as subprocess_runner
import core.focal.worker as worker_mod
import core.organizer as organizer_mod
from core.config import save_config
from core.focal import device_state
from core.focal.subprocess_runner import RunnerOutcome
from core.focal.worker import FocalWorker
from core.organizer import crop_to_poster
from core.version import VERSION


# ---------------------------------------------------------------------------
# Fake child (shape copied from tests/unit/test_focal_subprocess_runner.py)
# ---------------------------------------------------------------------------


class _FakeStdout:
    def __init__(self):
        self._q: queue.Queue[str] = queue.Queue()

    def readline(self) -> str:
        return self._q.get()

    def feed_line(self, text: str) -> None:
        self._q.put(text if text.endswith("\n") else text + "\n")

    def feed_eof(self) -> None:
        self._q.put("")


class FakeProcess:
    def __init__(self):
        self.stdout = _FakeStdout()
        self.stderr = None
        self._alive = True

    def kill(self) -> None:
        self._alive = False
        self.stdout.feed_eof()

    def wait(self) -> int:
        self._alive = False
        return 0

    def poll(self):
        return None if self._alive else 0


def _spawn_ready_then_hang(fs_path, ratio):
    """READY then silence → detect_timeout (same shape as unit helper)."""
    del fs_path, ratio
    proc = FakeProcess()
    proc.stdout.feed_line("READY")
    return proc


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_runner_module_state(monkeypatch):
    monkeypatch.setattr(subprocess_runner, "_breaker_streak", 0)
    lock = subprocess_runner._slot_lock
    if lock.acquire(timeout=0):
        lock.release()
    else:
        monkeypatch.setattr(subprocess_runner, "_slot_lock", threading.Lock())


def _patch_config_paths(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(core_config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(core_config, "CONFIG_DEFAULT_PATH", tmp_path / "config.default.json")
    return config_path


def _seed_enabled_device():
    save_config(
        {
            "focal_device": {
                "disabled": False,
                "consecutive_timeout_count": 0,
                "judged_at_version": VERSION,
            }
        }
    )


class _SpawnSpy:
    def __init__(self):
        self.call_count = 0

    def __call__(self, fs_path, ratio):
        self.call_count += 1
        return _spawn_ready_then_hang(fs_path, ratio)


def _install_run_detection_wrapper(module, monkeypatch, spawn_spy):
    """Replace module.run_detection with a wrapper that keeps real hooks/timing
    but forces spawn_fn=spawn_spy (avoids the bound-default spawn trap)."""
    outcomes: list[RunnerOutcome] = []

    def wrapper(
        fs_path, ratio, *, job_key, timeout_s,
        pre_spawn_check=None, on_outcome=None, **_kwargs,
    ):
        # Short timeout for test speed; hooks/critical-section timing stay real.
        outcome = subprocess_runner.run_detection(
            fs_path,
            ratio,
            job_key=job_key,
            timeout_s=0.05,
            pre_spawn_check=pre_spawn_check,
            on_outcome=on_outcome,
            spawn_fn=spawn_spy,
        )
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(module, "run_detection", wrapper)
    return outcomes


# ---------------------------------------------------------------------------
# path① — FocalWorker
# ---------------------------------------------------------------------------


class TestPath1WorkerDeviceGate:
    def test_two_timeouts_then_third_does_not_spawn(self, tmp_path, monkeypatch):
        _patch_config_paths(tmp_path, monkeypatch)
        _seed_enabled_device()

        spawn_spy = _SpawnSpy()
        outcomes = _install_run_detection_wrapper(worker_mod, monkeypatch, spawn_spy)

        img = tmp_path / "cover.jpg"
        Image.new("RGB", (64, 64), (10, 20, 30)).save(img)
        path = str(img)

        w = FocalWorker(auto_start=False)
        for i in range(2):
            w.submit("video", f"v{i}", path, 1.0, lambda *_a: None)
            w._process_one()

        assert spawn_spy.call_count == 2
        assert all(o.kind == "ABANDONED" and o.reason == "detect_timeout" for o in outcomes)
        assert device_state.is_disabled() is True

        w.submit("video", "v2", path, 1.0, lambda *_a: None)
        w._process_one()

        assert spawn_spy.call_count == 2, "third candidate must not spawn after disable"
        assert outcomes[-1].kind == "ABANDONED"
        assert outcomes[-1].reason == "skipped_disabled"


# ---------------------------------------------------------------------------
# path④ — crop_to_poster wiring + behaviour
# ---------------------------------------------------------------------------


class TestPath4OrganizerDeviceGate:
    def test_organizer_wiring_passes_device_state_hooks(self, tmp_path, monkeypatch):
        """DoD path④ wiring: kwargs are device_state.is_disabled / record_outcome."""
        captured = {}

        def fake_run_detection(
            fs_path, ratio, *, job_key, timeout_s,
            pre_spawn_check=None, on_outcome=None, **_kwargs,
        ):
            captured["pre_spawn_check"] = pre_spawn_check
            captured["on_outcome"] = on_outcome
            return RunnerOutcome(kind="NO_FACE")

        monkeypatch.setattr(organizer_mod, "run_detection", fake_run_detection)

        src = tmp_path / "wide.jpg"
        Image.new("RGB", (800, 538), (80, 80, 80)).save(src)
        dst = tmp_path / "poster.jpg"
        assert crop_to_poster(str(src), str(dst), number="FC2-1234567", maker="") is True

        assert captured["pre_spawn_check"] is device_state.is_disabled
        assert captured["on_outcome"] is device_state.record_outcome

    def test_two_timeouts_then_third_does_not_spawn(self, tmp_path, monkeypatch):
        _patch_config_paths(tmp_path, monkeypatch)
        _seed_enabled_device()

        spawn_spy = _SpawnSpy()
        outcomes = _install_run_detection_wrapper(organizer_mod, monkeypatch, spawn_spy)

        src = tmp_path / "wide.jpg"
        Image.new("RGB", (800, 538), (80, 80, 80)).save(src)

        for i in range(2):
            dst = tmp_path / f"poster_{i}.jpg"
            assert crop_to_poster(str(src), str(dst), number="FC2-1234567", maker="") is True

        assert spawn_spy.call_count == 2
        assert all(o.kind == "ABANDONED" and o.reason == "detect_timeout" for o in outcomes)
        assert device_state.is_disabled() is True

        dst3 = tmp_path / "poster_2.jpg"
        assert crop_to_poster(str(src), str(dst3), number="FC2-1234567", maker="") is True

        assert spawn_spy.call_count == 2, "third crop_to_poster must not spawn after disable"
        assert outcomes[-1].kind == "ABANDONED"
        assert outcomes[-1].reason == "skipped_disabled"
