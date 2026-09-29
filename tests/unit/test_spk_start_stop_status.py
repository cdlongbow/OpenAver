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


def _stop(tmp_path, pid):
    pidfile = tmp_path / "openaver.pid"
    pidfile.write_text(str(pid))
    env = dict(os.environ, OPENAVER_PID_FILE=str(pidfile), SYNOPKG_PKGNAME="T",
               OPENAVER_STOP_WAIT="1", OPENAVER_KILL_WAIT="3")
    r = subprocess.run(["bash", str(SCRIPT), "stop"], env=env, timeout=30,
                       stderr=subprocess.DEVNULL)
    return r.returncode, pidfile


def test_stop_escalates_to_sigkill_when_term_ignored(tmp_path):
    pid = _spawn('trap "" TERM; while :; do sleep 1; done')
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
    pid = _spawn("sleep 60")
    try:
        rc, pidfile = _stop(tmp_path, pid)
        assert rc == 0
        assert not pidfile.exists()
    finally:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
