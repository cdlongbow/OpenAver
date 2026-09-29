"""stop 必須確認程序真的死了才刪 PID 檔（Codex review P2）。"""

import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "synology/spk-src/scripts/start-stop-status"


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _spawn(cmd):
    """孫程序（被 init 收養）：模擬 daemon，死了不會留殭屍讓 kill -0 誤判。"""
    out = subprocess.run(["bash", "-c", f"({cmd}) >/dev/null 2>&1 & echo $!"],
                         capture_output=True, text=True, timeout=10).stdout
    time.sleep(0.3)  # 讓 trap 先設好
    return int(out.strip())


def _run(tmp_path, pid, action):
    pidfile = tmp_path / "openaver.pid"
    pidfile.write_text(str(pid))
    env = dict(os.environ, OPENAVER_PID_FILE=str(pidfile), SYNOPKG_PKGNAME="T",
               OPENAVER_STOP_WAIT="1", OPENAVER_KILL_WAIT="3")
    r = subprocess.run(["bash", str(SCRIPT), action], env=env, timeout=30,
                       stderr=subprocess.DEVNULL)
    return r.returncode, pidfile


def _stop(tmp_path, pid):
    return _run(tmp_path, pid, "stop")


# /proc/<pid>/cmdline 含 uvicorn 與 web.app:app ＝ 我們的 daemon
OURS_SLEEP = 'exec -a "python3 -m uvicorn web.app:app" sleep 60'
# 子殼層沿用外層 bash -c 的 cmdline，字串放在前面的空指令裡即可被認成我們的
OURS_TRAP = ': uvicorn web.app:app; trap "" TERM; while :; do sleep 1; done'


def test_stop_escalates_to_sigkill_when_term_ignored(tmp_path):
    pid = _spawn(OURS_TRAP)
    try:
        rc, pidfile = _stop(tmp_path, pid)
        assert rc == 0
        assert not _alive(pid)
        assert not pidfile.exists()
    finally:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


def test_stop_normal_term(tmp_path):
    pid = _spawn(OURS_SLEEP)
    try:
        rc, pidfile = _stop(tmp_path, pid)
        assert rc == 0
        assert not pidfile.exists()
    finally:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


def test_stale_pid_reused_by_other_process_is_not_killed(tmp_path):
    """PID 被無關程序重用：stop 不送訊號只清 PID 檔；status 不誤判為在跑。"""
    pid = _spawn("sleep 60")
    try:
        rc, pidfile = _run(tmp_path, pid, "status")
        assert rc == 3
        rc, pidfile = _stop(tmp_path, pid)
        assert rc == 0
        assert not pidfile.exists()
        assert _alive(pid)
    finally:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
