"""桌面殼的「關掉後再開一次」：請求、spawn、新行程等舊行程退出（168b-T5a）。

本模組不 import tray／webview；退出動作由呼叫端以 ``quit_app`` 注入。
"""
import os
import subprocess
import sys
import threading
import time

from core.i18n import t
from core.logger import get_logger

logger = get_logger(__name__)

PARENT_PID_ENV = "OPENAVER_RESTART_PARENT_PID"
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

QUIT_DELAY = 0.3
QUIT_THREAD_NAME = "openaver-restart-quit"

_state = {"requested": False, "spawned": False}


def restart_command(executable=None, argv=None, app_dir=None, isfile=None):
    """重新啟動用的命令列（list，不走 shell）"""
    executable = executable or sys.executable
    argv = list(sys.argv if argv is None else argv)
    app_dir = app_dir or APP_DIR
    isfile = isfile or os.path.isfile
    if argv and isfile(argv[0]):
        return [executable, *argv]
    code = f"import sys; sys.path.insert(0, {app_dir!r}); from windows.standalone import main; main()"
    return [executable, "-c", code]


def request_restart(quit_app):
    """登記重啟請求並排程退出；本函式不 spawn（spawn 要等 GUI 迴圈返回）

    退出不得在呼叫端執行緒同步執行：呼叫端常是 pywebview 的 bridge 執行緒，
    macOS 上它在 destroy 後還要把回傳值送回頁面，會卡死整個行程。
    回傳排程用的執行緒（測試用來 join）。
    """
    _state["requested"] = True

    def _later():
        time.sleep(QUIT_DELAY)
        try:
            quit_app()
        except Exception as e:
            logger.error(f"[restart] quit failed ({type(e).__name__})")

    th = threading.Thread(target=_later, name=QUIT_THREAD_NAME, daemon=True)
    th.start()
    return th


def _spawn_kwargs():
    env = dict(os.environ)
    env[PARENT_PID_ENV] = str(os.getpid())
    kwargs = {
        "cwd": os.getcwd(), "env": env, "close_fds": True,
        "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
    else:
        kwargs["start_new_session"] = True
    return kwargs


def spawn_if_requested(notify_error=None, popen=None):
    """有重啟請求時起新行程，一次請求恰一次；失敗不重試也不拋"""
    if not _state["requested"]:
        return False
    if _state["spawned"]:
        return False
    _state["spawned"] = True
    popen = popen or subprocess.Popen
    try:
        popen(restart_command(), **_spawn_kwargs())
    except Exception as e:
        logger.error(f"[restart] spawn failed ({type(e).__name__})")
        if notify_error is not None:
            notify_error(t("desktop.restart.spawn_failed", "zh-TW"))
        return False
    return True


def _pid_alive(pid):
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    # Windows 絕不可用 os.kill：它會對該 pid 呼叫 TerminateProcess
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x102
    finally:
        kernel32.CloseHandle(handle)


def wait_for_parent_exit(timeout=10.0, *, alive=None, sleep=None, clock=None):
    """新行程啟動時等舊行程退出；逾時照常返回"""
    raw = os.environ.pop(PARENT_PID_ENV, None)
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return
    if pid <= 0:
        return
    alive = alive or _pid_alive
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    deadline = clock() + timeout
    while alive(pid):
        if clock() >= deadline:
            logger.warning("[restart] parent process still alive after timeout")
            return
        sleep(0.1)
