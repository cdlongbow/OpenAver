"""TASK-153b-T4: true-subprocess startup gates for data-root bootstrap."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from core.data_root import LAYOUT_MARKER_NAME, LAYOUT_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXED_STDERR_SUMMARY = (
    "OpenAver 啟動失敗：資料位置尚未就緒或已損毀，詳細原因請查看 debug.log。"
)
# Must match web.app.LIFESPAN_BOOTSTRAP_EXIT_CODE
EXPECTED_EXIT_CODE = 78


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _spawn_env(data_dir: Path) -> dict[str, str]:
    env = {**os.environ, "OPENAVER_DATA_DIR": str(data_dir)}
    # Ensure repo root is importable for `uvicorn web.app:app`
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(REPO_ROOT) if not existing else f"{REPO_ROOT}{os.pathsep}{existing}"
    )
    return env


def _uvicorn_cmd(port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "web.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]


def test_direct_uvicorn_bootstrap_failure_exit_code_and_stderr(tmp_path):
    """損毀 .layout.json → exit 78、固定摘要、無 Traceback。"""
    broken_root = tmp_path / "broken_root"
    broken_root.mkdir()
    (broken_root / LAYOUT_MARKER_NAME).write_text("{not json", encoding="utf-8")

    port = _free_port()
    result = subprocess.run(
        _uvicorn_cmd(port),
        cwd=str(REPO_ROOT),
        env=_spawn_env(broken_root),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == EXPECTED_EXIT_CODE, (
        f"returncode={result.returncode!r}\n"
        f"stdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )
    assert "Traceback" not in result.stderr
    assert FIXED_STDERR_SUMMARY in result.stderr


def test_direct_uvicorn_preprovisioned_root_serves_200(tmp_path):
    """已定版資料根（config + marker）→ subprocess GET / 回 200。"""
    root = tmp_path / "ready_root"
    root.mkdir()
    default_config = REPO_ROOT / "web" / "config.default.json"
    dest_config = root / "config.json"
    shutil.copyfile(default_config, dest_config)
    dest_config.chmod(0o600)
    (root / LAYOUT_MARKER_NAME).write_text(
        json.dumps({"version": LAYOUT_VERSION, "complete": True}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    port = _free_port()
    p = subprocess.Popen(
        _uvicorn_cmd(port),
        cwd=str(REPO_ROOT),
        env=_spawn_env(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + 20
    last_exc: Exception | None = None
    try:
        while time.monotonic() < deadline:
            if p.poll() is not None:
                stdout, stderr = p.communicate(timeout=5)
                pytest.fail(
                    f"uvicorn exited early code={p.returncode}\n"
                    f"stdout={stdout!r}\nstderr={stderr!r}"
                )
            try:
                with opener.open(url, timeout=1) as resp:
                    if resp.status == 200:
                        break
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                last_exc = exc
            time.sleep(0.2)
        else:
            pytest.fail(
                f"timed out waiting for GET / 200; last_exc={last_exc!r}"
            )
    finally:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)


def test_direct_uvicorn_marker_valid_config_missing_recovers_and_serves_200(tmp_path):
    """已定版 marker 但 config.json 缺失 → 自我修復後 GET / 回 200，config 重建為 0600。"""
    root = tmp_path / "recover_root"
    root.mkdir()
    # 只放有效 marker（不放假 DB：lifespan 後續 init_db 需要可開啟的 sqlite）
    (root / LAYOUT_MARKER_NAME).write_text(
        json.dumps({"version": LAYOUT_VERSION, "complete": True}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    assert not (root / "config.json").exists()

    port = _free_port()
    p = subprocess.Popen(
        _uvicorn_cmd(port),
        cwd=str(REPO_ROOT),
        env=_spawn_env(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + 20
    last_exc: Exception | None = None
    try:
        while time.monotonic() < deadline:
            if p.poll() is not None:
                stdout, stderr = p.communicate(timeout=5)
                pytest.fail(
                    f"uvicorn exited early code={p.returncode}\n"
                    f"stdout={stdout!r}\nstderr={stderr!r}"
                )
            try:
                with opener.open(url, timeout=1) as resp:
                    if resp.status == 200:
                        break
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                last_exc = exc
            time.sleep(0.2)
        else:
            pytest.fail(
                f"timed out waiting for GET / 200; last_exc={last_exc!r}"
            )
    finally:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)

    cfg = root / "config.json"
    assert cfg.is_file(), "bootstrap 應重建缺失的 config.json"
    assert (cfg.stat().st_mode & 0o777) == 0o600
