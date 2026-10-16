"""windows/restart.py 單元測試（168b-T5a）。除兩個真行程 smoke 外全部注入。"""
import ast
import os
import subprocess
import sys
import threading
import time
from unittest.mock import Mock

import pytest

from windows import restart

PID_ENV = "OPENAVER_RESTART_PARENT_PID"


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setattr(restart, "QUIT_DELAY", 0)
    restart._state.update(requested=False, spawned=False)
    monkeypatch.delenv(PID_ENV, raising=False)
    yield
    restart._state.update(requested=False, spawned=False)


# ---- restart_command ----

def test_restart_command_script_file():
    cmd = restart.restart_command("/py", ["/app/launcher.py", "--x"], "/app", lambda p: True)
    assert cmd == ["/py", "/app/launcher.py", "--x"]


def test_restart_command_dash_c_form():
    cmd = restart.restart_command("/py", ["-c"], "/app", lambda p: False)
    assert cmd[:2] == ["/py", "-c"] and len(cmd) == 3
    assert "windows.standalone" in cmd[2]


def test_restart_command_dash_c_quotes_awkward_app_dir():
    app_dir = "C:\\Program Files\\Open Aver"
    cmd = restart.restart_command("/py", ["-c"], app_dir, lambda p: False)
    tree = ast.parse(cmd[2])
    inserted = [
        n.args[1].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "insert"
    ]
    assert inserted == [app_dir]


# ---- request / spawn ----

def test_request_restart_calls_quit_and_sets_flag():
    quit_app = Mock()
    restart.request_restart(quit_app).join(5)
    restart.request_restart(quit_app).join(5)
    assert restart._state["requested"] is True
    assert quit_app.call_count == 2


def test_request_restart_returns_before_quit_runs_on_other_thread(monkeypatch):
    """bridge 呼叫要先返回：退出不得在呼叫端執行緒同步執行（Mac 上同步 destroy 會卡死整個行程）。"""
    monkeypatch.setattr(restart, "QUIT_DELAY", 0.05)
    release = threading.Event()
    seen = {}

    def quit_app():
        seen["thread"] = threading.current_thread()
        release.set()

    th = restart.request_restart(quit_app)
    assert "thread" not in seen                 # 呼叫返回時 quit_app 尚未執行
    assert release.wait(5)
    th.join(5)
    assert seen["thread"] is not threading.current_thread()
    assert seen["thread"].daemon is True


def test_request_restart_quit_failure_does_not_raise(monkeypatch):
    log = Mock()
    monkeypatch.setattr(restart, "logger", log)
    quit_app = Mock(side_effect=RuntimeError("x"))
    restart.request_restart(quit_app).join(5)
    quit_app.assert_called_once()
    log.error.assert_called_once()


def test_request_restart_does_not_spawn_before_loop_exit(monkeypatch):
    popen = Mock()
    monkeypatch.setattr(restart.subprocess, "Popen", popen)
    seen = {}

    def quit_app():
        seen["spawned_calls"] = popen.call_count

    restart.request_restart(quit_app).join(5)
    assert popen.call_count == 0
    assert seen["spawned_calls"] == 0
    assert restart._state["spawned"] is False


def test_spawn_without_request_never_spawns():
    popen = Mock()
    assert restart.spawn_if_requested(popen=popen) is False
    popen.assert_not_called()


def test_spawn_twice_for_one_request_spawns_once(monkeypatch):
    monkeypatch.setattr(restart, "restart_command", lambda *a, **k: ["x"])
    popen = Mock()
    restart.request_restart(Mock()).join(5)
    restart.request_restart(Mock()).join(5)
    assert restart.spawn_if_requested(popen=popen) is True
    assert restart.spawn_if_requested(popen=popen) is False
    assert popen.call_count == 1


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_spawn_popen_arguments(monkeypatch, platform):
    monkeypatch.setattr(restart.sys, "platform", platform)
    monkeypatch.setattr(restart, "restart_command", lambda *a, **k: ["py", "a.py"])
    popen = Mock()
    restart.request_restart(Mock()).join(5)
    restart.spawn_if_requested(popen=popen)
    args, kw = popen.call_args
    assert args[0] == ["py", "a.py"]
    assert not kw.get("shell")
    assert kw["env"][PID_ENV] == str(os.getpid())
    assert kw["stdin"] == kw["stdout"] == kw["stderr"] == subprocess.DEVNULL
    assert kw["close_fds"] is True
    if platform == "win32":
        assert kw["creationflags"] == 0x8 | 0x200 | 0x08000000
        assert "start_new_session" not in kw
    else:
        assert kw["start_new_session"] is True
        assert "creationflags" not in kw


def test_spawn_failure_notifies_once_and_never_retries(monkeypatch):
    monkeypatch.setattr(restart, "restart_command", lambda *a, **k: ["x"])
    popen = Mock(side_effect=OSError("boom"))
    notify = Mock()
    restart.request_restart(Mock()).join(5)
    assert restart.spawn_if_requested(notify_error=notify, popen=popen) is False
    assert restart.spawn_if_requested(notify_error=notify, popen=popen) is False
    assert popen.call_count == 1
    notify.assert_called_once()
    msg = notify.call_args[0][0]
    assert isinstance(msg, str) and msg and not msg.startswith("[")


def _spawn_fail_notice(monkeypatch):
    monkeypatch.setattr(restart, "restart_command", lambda *a, **k: ["x"])
    notify = Mock()
    restart.request_restart(Mock()).join(5)
    assert restart.spawn_if_requested(notify_error=notify, popen=Mock(side_effect=OSError("boom"))) is False
    notify.assert_called_once()
    return notify.call_args[0][0]


def test_spawn_failure_notice_follows_tray_locale(monkeypatch):
    import core.i18n as i18n
    from core import client_settings
    real = i18n.load_locale
    monkeypatch.setattr(i18n, "load_locale", lambda lang: (
        {"desktop": {"restart": {"spawn_failed": "EN-SPAWN-FAILED"}}} if lang == "en" else real(lang)))
    monkeypatch.setattr(client_settings, "tray_locale", lambda: "en")
    assert _spawn_fail_notice(monkeypatch) == "EN-SPAWN-FAILED"


def test_spawn_failure_notice_en_missing_key_falls_back_to_zh_tw(monkeypatch):
    from core import client_settings
    monkeypatch.setattr(client_settings, "tray_locale", lambda: "en")
    msg = _spawn_fail_notice(monkeypatch)
    assert msg and not msg.startswith("[")


def test_spawn_failure_locale_lookup_raising_still_notifies_zh_tw(monkeypatch):
    from core import client_settings

    def boom():
        raise RuntimeError("locale lookup failed")

    monkeypatch.setattr(client_settings, "tray_locale", boom)
    msg = _spawn_fail_notice(monkeypatch)
    assert msg and not msg.startswith("[")


# ---- wait_for_parent_exit ----

def test_wait_for_parent_missing_or_bad_env_returns_immediately():
    alive = Mock(side_effect=AssertionError("must not poll"))
    restart.wait_for_parent_exit(alive=alive)
    for bad in ("abc", "0", "-5", ""):
        os.environ[PID_ENV] = bad
        restart.wait_for_parent_exit(alive=alive)
    alive.assert_not_called()


def test_wait_for_parent_removes_env_and_polls_until_gone(monkeypatch):
    monkeypatch.setenv(PID_ENV, "4242")
    answers = iter([True, True, False])
    alive = Mock(side_effect=lambda pid: next(answers))
    restart.wait_for_parent_exit(alive=alive, sleep=lambda s: None, clock=lambda: 0.0)
    assert PID_ENV not in os.environ
    assert alive.call_count == 3
    alive.assert_called_with(4242)


def test_wait_for_parent_timeout_returns(monkeypatch):
    monkeypatch.setenv(PID_ENV, "4242")
    now = [0.0]

    def sleep(s):
        now[0] += s

    restart.wait_for_parent_exit(timeout=1.0, alive=lambda pid: True, sleep=sleep, clock=lambda: now[0])
    assert PID_ENV not in os.environ


class _FakeFn:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, *a):
        self.calls.append(a)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


class _FakeCtypes:
    def __init__(self):
        k = type("K", (), {})()
        k.OpenProcess = _FakeFn([0x77, 0])
        k.WaitForSingleObject = _FakeFn([0x102])
        k.CloseHandle = _FakeFn([1])
        self.kernel32 = k
        self.windll = type("W", (), {"kernel32": k})()


def test_wait_for_parent_never_uses_os_kill_on_windows(monkeypatch):
    fake = _FakeCtypes()
    monkeypatch.setitem(sys.modules, "ctypes", fake)
    monkeypatch.setattr(restart.sys, "platform", "win32")
    kill = Mock(side_effect=AssertionError("os.kill on Windows terminates the process"))
    monkeypatch.setattr(restart.os, "kill", kill)
    monkeypatch.setenv(PID_ENV, "1234")
    restart.wait_for_parent_exit(timeout=5.0, sleep=lambda s: None, clock=lambda: 0.0)
    kill.assert_not_called()
    assert fake.kernel32.OpenProcess.calls[0] == (0x00100000, False, 1234)
    assert fake.kernel32.CloseHandle.calls == [(0x77,)]


# ---- 真行程 smoke（POSIX）----

@pytest.mark.skipif(sys.platform == "win32", reason="POSIX smoke")
def test_smoke_spawn_real_child_sees_parent_pid(monkeypatch, tmp_path):
    out = tmp_path / "pid.txt"
    code = f"import os; open({str(out)!r},'w').write(os.environ.get('{PID_ENV}',''))"
    monkeypatch.setattr(restart, "restart_command", lambda *a, **k: [sys.executable, "-c", code])
    restart.request_restart(Mock()).join(5)
    assert restart.spawn_if_requested() is True
    deadline = time.time() + 10
    while time.time() < deadline and not (out.exists() and out.read_text()):
        time.sleep(0.05)
    assert out.read_text() == str(os.getpid())


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX smoke")
def test_smoke_wait_for_real_parent_exit(monkeypatch):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
    # 子行程結束後要被收掉（殭屍行程仍讓 kill(pid,0) 成功）；正式情境舊行程不是新行程的子行程
    threading.Thread(target=proc.wait, daemon=True).start()
    monkeypatch.setenv(PID_ENV, str(proc.pid))
    t0 = time.time()
    try:
        restart.wait_for_parent_exit(timeout=5)
    finally:
        proc.wait(timeout=10)
    assert time.time() - t0 < 3
    assert PID_ENV not in os.environ
