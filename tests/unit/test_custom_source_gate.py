"""自訂來源 gate：七種 reason 各一格（輸入互不相同）、通過回快照、views 形狀。"""

import hashlib
import shutil

import pytest

import core.config as core_config
from core.config import load_config, save_config
from core.custom_source import gate, state, views
from tests.unit._custom_source_fake import FakeTransport
from tests.unit._custom_source_pages import FIXTURE_DIR

NUMBER = "SONE-205"


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "custom_sources").mkdir(parents=True)
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(root))
    monkeypatch.setattr(core_config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(core_config, "CONFIG_DEFAULT_PATH", tmp_path / "none.json")
    (tmp_path / "cfg").mkdir()
    monkeypatch.setattr(state, "_gens", {})
    monkeypatch.setattr(state, "_running_id", None)
    save_config(load_config())
    load_config()  # migration 收斂到不動點
    return root / "custom_sources"


def _put(d, name):
    shutil.copy(FIXTURE_DIR / f"{name}.yaml", d / f"{name}.yaml")
    return d / f"{name}.yaml"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(sid, sha, status="passed", enable=False):
    assert state.record_result(sid, sha, status, {"total": 1, "failed": 0, "cases": []}, state.get_gen(sid))
    if status == "passed":  # 通過即啟用（165-T16）；enable=False 明確關閉才是「通過但未啟用」
        assert state.set_enabled(sid, bool(enable), sha)


def test_gate_unverified(env):
    _put(env, "fuzzy")
    r = gate.check_usable("fuzzy", NUMBER)
    assert (r.ok, r.reason) == (False, "unverified")


def test_gate_disabled(env):
    p = _put(env, "single-og")
    _record("single-og", _sha(p), enable=False)
    assert gate.check_usable("single-og", NUMBER).reason == "disabled"


def test_gate_pattern_mismatch(env):
    p = _put(env, "text")
    _record("text", _sha(p), enable=True)
    transport = FakeTransport({})
    r = gate.check_usable("text", NUMBER)
    assert (r.ok, r.reason) == (False, "pattern_mismatch")
    assert transport.calls == []  # gate 不碰網路
    assert gate.check_usable("text").ok is True  # number=None 不判 pattern


def test_gate_overwritten_file_becomes_unverified(env):
    p = _put(env, "single-og")
    _record("single-og", _sha(p), enable=True)
    assert gate.check_usable("single-og", NUMBER).ok is True
    p.write_bytes(p.read_bytes() + b"# x\n")
    assert gate.check_usable("single-og", NUMBER).reason == "unverified"


def test_views_shape_order_and_names(env):
    pa = _put(env, "fuzzy")
    (env / "g-bad.yaml").write_text("id: [unclosed", encoding="utf-8")
    pb = _put(env, "text")
    _record("text", _sha(pb), enable=True)
    got = views.custom_source_views()
    assert [v.loaded.id for v in got] == ["fuzzy", "g-bad", "text"]
    assert [v.config.order for v in got] == [1000, 1001, 1002]
    assert [v.status for v in got] == ["unverified", "load_failed", "passed"]
    assert [v.routable for v in got] == [False, False, True]
    bad = got[1].config
    assert bad.display_name_raw == "g-bad"
    assert got[0].config.display_name_raw == got[0].loaded.spec.name
    for v in got:
        c = v.config
        assert c.id == f"custom:{v.loaded.id}" and c.type == "custom"
        assert c.manual_only is True and c.is_beta is False and c.requires_proxy is False
        assert c.model_dump()["is_censored"] is True
    assert [c.enabled for c in views.custom_source_configs()] == [False, False, True]
    assert pa.exists()

