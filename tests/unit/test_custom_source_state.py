"""自訂來源狀態層：持久化（真 tmp config.json）、五態推導、截斷、操作世代、單飛行、鎖可追蹤。"""

import json
import threading

import pytest

import core.config as core_config
from core.config import AppConfig, load_config, mutate_config, save_config
from core.custom_source import state

SID = "single-og"
SHA_A = "a" * 64


@pytest.fixture
def env(tmp_path, monkeypatch):
    """資料根與 config.json 分開放（避免 ConfigRootNotFinalizedError）；走真檔案 I/O。"""
    root = tmp_path / "root"
    root.mkdir()
    cfg_path = tmp_path / "cfg" / "config.json"
    cfg_path.parent.mkdir()
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(root))
    monkeypatch.setattr(core_config, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(core_config, "CONFIG_DEFAULT_PATH", tmp_path / "none.json")
    monkeypatch.setattr(state, "_gens", {})
    monkeypatch.setattr(state, "_running_id", None)
    save_config(load_config())  # 先跑過 migration 到不動點（兩趟），之後的 bytes 比對才乾淨
    load_config()
    return root, cfg_path


def _cases(n, mismatches=0, value="x"):
    return [
        {
            "index": i, "number": f"N-{i}", "passed": mismatches == 0,
            "mismatches": [
                {"key": f"k{j}", "expected": value, "actual": value, "url": value}
                for j in range(mismatches)
            ],
        }
        for i in range(n)
    ]


def _result(cases=None, total=None, failed=0):
    cases = _cases(1) if cases is None else cases
    return {"total": len(cases) if total is None else total, "failed": failed, "cases": cases}


def _record(source_id, sha, status="passed", result=None):
    return state.record_result(source_id, sha, status, result or _result(), state.get_gen(source_id))


def test_stale_snapshot_put_does_not_roll_back_custom_sources(env):
    root, cfg_path = env
    stale_payload = AppConfig().model_dump()  # 前端長駐的舊快照，在寫入之前取得
    assert _record(SID, SHA_A)
    written = load_config()["custom_sources"]
    assert written[SID]["status"] == "passed"
    mutate_config(lambda cfg: cfg.update(stale_payload))  # 同 web/routers/config.py 的整包寫回
    assert load_config()["custom_sources"] == written
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["custom_sources"] == written


class _TrackedLock:
    def __init__(self):
        self._real = threading.RLock()
        self.acquired = 0
        self.in_callback = False
        self.violations = 0

    def acquire(self, *a, **k):
        self.acquired += 1
        if self.in_callback:
            self.violations += 1
        return self._real.acquire(*a, **k)

    def release(self):
        self._real.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


