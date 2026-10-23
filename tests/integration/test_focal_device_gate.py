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
import core.organizer as organizer_mod
from core.config import save_config
from core.focal import device_state
from core.focal.subprocess_runner import RunnerOutcome
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


# ---------------------------------------------------------------------------
# path④ — crop_to_poster wiring + behaviour
# ---------------------------------------------------------------------------


class TestPath4OrganizerDeviceGate:

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


# ---------------------------------------------------------------------------
# 呼叫端窮舉守衛（152c pre-merge /simplify altitude A1）
# ---------------------------------------------------------------------------


class TestRunDetectionCallSitesAllPassDeviceGate:
    """每一個 production 的 run_detection 呼叫端都必須傳 pre_spawn_check。

    為什麼需要機械守衛：`pre_spawn_check` 是 optional、**預設 None ＝ 裝置停用不生效**。
    上面那些測試是「一個已知呼叫端一支測試」的形狀——它們證明現有四條路是對的，但**擋不住
    第五條路**。下一個入口（152d 很可能就會加）忘了傳，行為是「在已經判定算不動的機器上
    照樣 spawn、照樣空等幾十秒」，而全部測試都是綠的。那正是這支 branch 存在的理由被靜默
    繞過。

    ⚠️ 兩種呼叫形狀都要涵蓋：四個呼叫端裡有兩個是
    `asyncio.to_thread(run_detection, ...)`（`web/routers/actress.py`）與
    `executor.submit(run_detection, ...)`（`web/routers/showcase.py`），它們**不是**
    `run_detection(` 的字面形狀——只比對 Call.func 名字的守衛會漏掉它而不自知。
    """

    #: 目前已知、且已被上面各自的行為測試證明接線正確的呼叫端。
    EXPECTED_FILES = {
        "core/focal/worker.py",        # path① 背景 worker（貢獻判定）
        "core/organizer.py",           # path④ 海報裁切（貢獻判定）
        "web/routers/showcase.py",     # path② 影片手動（服從、不貢獻）
        "web/routers/actress.py",      # path③ 女優手動（服從、不貢獻，走 to_thread）
    }

    @staticmethod
    def _collect_sites():
        import ast
        from pathlib import Path

        sites = []
        for root in ("core", "web"):
            for path in sorted(Path(root).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    func = node.func
                    # 形狀 A：直接呼叫 run_detection(...)
                    direct = (
                        (isinstance(func, ast.Name) and func.id == "run_detection")
                        or (isinstance(func, ast.Attribute) and func.attr == "run_detection")
                    )
                    # 形狀 B：asyncio.to_thread(run_detection, ...)／executor.submit(run_detection, ...)
                    # —— 名字在第一個位置引數上（showcase.py 的手動偵測走 submit 以套 5 秒回應上限）
                    via_thread = (
                        isinstance(func, ast.Attribute)
                        and func.attr in ("to_thread", "submit")
                        and node.args
                        and isinstance(node.args[0], ast.Name)
                        and node.args[0].id == "run_detection"
                    )
                    if not (direct or via_thread):
                        continue
                    kwargs = {kw.arg for kw in node.keywords if kw.arg}
                    sites.append((str(path), node.lineno, kwargs))
        return sites

    def test_every_call_site_passes_pre_spawn_check(self):
        sites = self._collect_sites()
        assert sites, "一個呼叫端都沒找到 ⇒ 守衛自己壞了（被改名？），不是「沒有呼叫端」"
        missing = [(f, ln) for f, ln, kw in sites if "pre_spawn_check" not in kw]
        assert not missing, (
            "這些 run_detection 呼叫端沒有傳 pre_spawn_check ⇒ 裝置被判定停用後，"
            f"這條路仍會 spawn 並空等：{missing}"
        )

