"""自訂來源服務層（service.py）：上傳／驗收／移除／列表／啟用／適用性／硬限；全離線、真 tmp 資料根與 config.json。"""

import json
import os
import socket
import threading
import time

import pytest

import core.config as core_config
import core.custom_source.fetch as fetch_mod
import core.public_target as public_target_mod
from core.config import load_config, save_config
from core.custom_source import service, state
from core.custom_source.errors import LoadError
from core.custom_source.schema import load_uploaded
from core.scrapers.errors import SourceUnreachable
from tests.unit._custom_source_fake import FakeTransport, TrackedLock, finalize_root, gate_route, page, put_source
from tests.unit._custom_source_pages import FIXTURE_DIR, PAGES

SID = "single-og"
MIN = "single-og-min"
GOOD = (FIXTURE_DIR / "single-og.yaml").read_text(encoding="utf-8")
GOOD_MIN = (FIXTURE_DIR / "single-og-min.yaml").read_text(encoding="utf-8")
SOG = "https://single-og.example/sone-205"
SOG_MISS = "https://single-og.example/zzzz-999"
MIN_HIT = "https://single-og-min.example/videos/sone-205/"
MIN_MISS = "https://single-og-min.example/videos/zzzz-999/"


@pytest.fixture(autouse=True)
def _no_real_dns_or_sleep(monkeypatch):
    monkeypatch.setattr("core.public_target.resolve_host", lambda host: ["8.8.8.8"])
    monkeypatch.setattr("core.custom_source.fetch.rate_limit", lambda delay=0: None)


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    cfg_path = tmp_path / "cfg" / "config.json"
    cfg_path.parent.mkdir()
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(root))
    monkeypatch.setattr(core_config, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(core_config, "CONFIG_DEFAULT_PATH", tmp_path / "none.json")
    monkeypatch.setattr(state, "_gens", {})
    monkeypatch.setattr(state, "_running_id", None)
    save_config(load_config())
    load_config()
    finalize_root(root)
    return root, cfg_path


def _entries(cfg_path):
    return json.loads(cfg_path.read_text(encoding="utf-8")).get("custom_sources", {})


def _routes(changed=False):
    body = PAGES["single-og"].replace("Sample Title One", "Changed Title") if changed else PAGES["single-og"]
    return {SOG: page(body), SOG_MISS: page("", 404)}


def _tp(changed=False):
    return FakeTransport(_routes(changed))


def _status(source_id=SID):
    return next(s for s in service.list_sources() if s["id"] == source_id)


def _passed(env_):
    service.upload(GOOD)
    assert service.verify(SID, transport=_tp())["status"] == "passed"


def _bad_variants():
    return {
        "syntax": "id: [unclosed",
        "unknown_key": GOOD + "\nbogus_key: 1\n",
        "reserved_id": GOOD.replace("id: single-og", "id: auto", 1),
        "too_big": GOOD + "\n#" + "x" * 70000 + "\n",
    }


# ---------------------------------------------------------------- upload

def test_upload_good_file_is_unverified_and_never_touches_network(env, monkeypatch):
    calls = []

    def boom(name):
        def _f(*a, **k):
            calls.append(name)
            raise AssertionError(name)
        return _f

    monkeypatch.setattr(public_target_mod, "resolve_host", boom("resolve_host"))
    monkeypatch.setattr(socket, "getaddrinfo", boom("getaddrinfo"))
    monkeypatch.setattr(fetch_mod, "make_transport", boom("make_transport"))
    monkeypatch.setattr(fetch_mod.PlainTransport, "request", boom("plain"))
    monkeypatch.setattr(fetch_mod.TlsTransport, "request", boom("tls"))
    root, cfg_path = env
    result = service.upload(GOOD)
    assert result == {"id": SID, "source_id": "custom:single-og", "status": "unverified", "replaced": False}
    for text in _bad_variants().values():
        with pytest.raises(service.ServiceError):
            service.upload(text)
    assert calls == []
    assert (root / "custom_sources" / "single-og.yaml").read_text(encoding="utf-8") == GOOD
    assert SID not in _entries(cfg_path)


@pytest.mark.parametrize("existing", [True], ids=["dir_has_other_file"])
@pytest.mark.parametrize("variant", ["syntax"])
def test_upload_rejected_leaves_directory_untouched(env, variant, existing):
    root, _ = env
    directory = root / "custom_sources"
    if existing:
        put_source(root, MIN, GOOD_MIN)
    before = sorted((n, (directory / n).read_bytes()) for n in os.listdir(directory)) if existing else None
    text = _bad_variants()[variant]
    with pytest.raises(LoadError) as expected:
        load_uploaded(text)
    with pytest.raises(service.ServiceError) as caught:
        service.upload(text)
    err = caught.value
    assert (err.code, err.http_status) == (expected.value.reason, 400)
    assert err.payload()["field_path"] == expected.value.field_path
    assert err.payload()["success"] is False
    if existing:
        assert sorted((n, (directory / n).read_bytes()) for n in os.listdir(directory)) == before
    else:
        assert not directory.exists()


def test_reupload_same_bytes_resets_to_unverified(env):
    _, cfg_path = env
    _passed(env)
    assert service.set_enabled(SID, True) == {"id": SID, "enabled": True}
    assert SID in _entries(cfg_path)
    result = service.upload(GOOD)
    assert result["replaced"] is True and result["status"] == "unverified"
    assert SID not in _entries(cfg_path)
    item = _status()
    assert (item["status"], item["enabled"]) == ("unverified", False)


# ---------------------------------------------------------------- verify

def test_verify_returns_full_shape_and_records(env):
    _, cfg_path = env
    service.upload(GOOD)
    out = service.verify(SID, transport=_tp())
    assert out["status"] == "passed" and out["id"] == SID
    assert out["total"] == 2 and out["failed"] == 0 and len(out["cases"]) == 2
    assert set(out["cases"][0]) == {"index", "number", "passed", "mismatches"}
    assert out["verified_at"] == _entries(cfg_path)[SID]["verified_at"]
    assert state.get_running_id() is None


def test_verify_failed_content_returns_full_mismatches(env):
    service.upload(GOOD)
    out = service.verify(SID, transport=_tp(changed=True))
    assert out["status"] == "failed" and out["failed"] >= 1
    bad = [c for c in out["cases"] if not c["passed"]][0]
    assert set(bad["mismatches"][0]) == {"key", "expected", "actual", "url"}


@pytest.mark.parametrize("kind", ["load_failed"])
def test_verify_refuses_unloadable_source(env, kind):
    root, _ = env
    if kind == "load_failed":
        put_source(root, "broken", "id: [unclosed")
    with pytest.raises(service.ServiceError) as caught:
        service.verify("broken" if kind == "load_failed" else "nope", transport=_tp())
    err = caught.value
    if kind == "unknown":
        assert (err.code, err.http_status) == ("not_loaded", 404)
    else:
        assert (err.code, err.http_status) == ("load_failed", 409)
        assert set(err.extra["load_error"]) == {"reason", "field_path", "line", "message"}
    assert state.get_running_id() is None


class _Stall:
    """在另一個 thread 跑 verify，卡在 FakeTransport 的第一個請求。"""

    def __init__(self, source_id=SID):
        self.entered = threading.Event()
        self.release = threading.Event()
        routes = _routes()
        routes[SOG] = gate_route(self.entered, self.release, page(PAGES["single-og"]))
        self.out = None
        self.exc = None
        self.thread = threading.Thread(target=self._run, args=(source_id, FakeTransport(routes)), daemon=True)

    def _run(self, source_id, transport):
        try:
            self.out = service.verify(source_id, transport=transport)
        except Exception as exc:  # noqa: BLE001
            self.exc = exc

    def __enter__(self):
        self.thread.start()
        assert self.entered.wait(5), "verify never reached the transport"
        return self

    def finish(self):
        self.release.set()
        self.thread.join(10)
        assert not self.thread.is_alive()

    def __exit__(self, *exc):
        self.release.set()
        self.thread.join(10)


def test_verify_single_flight_rejects_second_call(env):
    root, cfg_path = env
    service.upload(GOOD)
    service.upload(GOOD_MIN)
    with _Stall() as stall:
        for other in (SID, MIN):
            with pytest.raises(service.ServiceError) as caught:
                service.verify(other, transport=_tp())
            assert (caught.value.code, caught.value.http_status) == ("verify_busy", 409)
            assert caught.value.extra["busy_id"] == SID
        stall.finish()
    assert stall.out["status"] == "passed"
    assert set(_entries(cfg_path)) == {SID}


def test_list_shows_verifying_and_unrelated_config_write_is_not_blocked(env):
    service.upload(GOOD)
    with _Stall() as stall:
        assert _status()["status"] == "verifying"
        worker = threading.Thread(target=lambda: core_config.mutate_config(lambda cfg: cfg.__setitem__("zz_unrelated", 1)))
        worker.start()
        worker.join(1)
        assert not worker.is_alive()
        stall.finish()
    assert stall.out["status"] == "passed"


def _act_remove(env_):
    service.remove(SID)


@pytest.mark.parametrize("action", [_act_remove],
                         ids=["remove"])
def test_verify_discarded_when_source_changes_mid_flight(env, action):
    _, cfg_path = env
    service.upload(GOOD)
    with _Stall() as stall:
        action(env)
        stall.finish()
    assert isinstance(stall.exc, service.ServiceError)
    assert (stall.exc.code, stall.exc.http_status) == ("changed_during_verify", 409)
    assert SID not in _entries(cfg_path)
    listed = [s["id"] for s in service.list_sources()]
    if action is _act_remove:
        assert listed == []
    else:
        assert _status()["status"] == "unverified"


def test_verify_discards_result_after_same_bytes_reupload(env):
    _, cfg_path = env
    service.upload(GOOD)
    with _Stall() as stall:
        assert service.upload(GOOD)["replaced"] is True
        stall.finish()
    assert stall.out is None and stall.exc.code == "changed_during_verify"
    assert SID not in _entries(cfg_path)
    assert _status()["status"] == "unverified"


def test_failed_reverify_closes_enabled(env):
    _, cfg_path = env
    _passed(env)
    service.set_enabled(SID, True)
    assert _status()["enabled"] is True
    out = service.verify(SID, transport=_tp(changed=True))
    assert out["status"] == "failed"
    item = _status()
    assert (item["status"], item["enabled"]) == ("failed", False)
    assert _entries(cfg_path)[SID]["enabled"] is False  # 持久化的開關也被關掉，不是只有顯示層遮住
    assert service.verify(SID, transport=_tp())["status"] == "passed"
    assert _status()["enabled"] is True  # 失敗是系統關的；之後修好再通過即恢復啟用（165-T16 Q1）


def test_first_pass_auto_enables(env):
    service.upload(GOOD)
    out = service.verify(SID, transport=_tp())
    assert out["status"] == "passed" and out["enabled"] is True
    assert _status()["enabled"] is True


def test_same_sha_reverify_keeps_user_disabled(env):
    _passed(env)
    service.set_enabled(SID, False)
    out = service.verify(SID, transport=_tp())
    assert out["status"] == "passed" and out["enabled"] is False
    assert _status()["enabled"] is False
    service.upload(GOOD)  # 重傳清掉紀錄 → 驗收通過即啟用
    assert service.verify(SID, transport=_tp())["enabled"] is True


# ---------------------------------------------------------------- enable / list / remove / applicable

def test_set_enabled_requires_passed(env):
    service.upload(GOOD)
    with pytest.raises(service.ServiceError) as caught:
        service.set_enabled(SID, True)
    assert (caught.value.code, caught.value.http_status) == ("not_passed", 409)
    service.verify(SID, transport=_tp(changed=True))
    with pytest.raises(service.ServiceError) as caught:
        service.set_enabled(SID, True)
    assert caught.value.code == "not_passed"
    with pytest.raises(service.ServiceError) as caught:
        service.set_enabled("nope", True)
    assert (caught.value.code, caught.value.http_status) == ("not_loaded", 404)
    assert _status()["enabled"] is False
    service.verify(SID, transport=_tp())
    assert service.set_enabled(SID, True) == {"id": SID, "enabled": True}
    assert service.set_enabled(SID, False) == {"id": SID, "enabled": False}


def test_hand_edit_after_enable_makes_it_unverified_and_disabled(env):
    root, _ = env
    _passed(env)
    service.set_enabled(SID, True)
    put_source(root, SID, GOOD + "\n# edited\n")
    item = _status()
    assert (item["status"], item["enabled"]) == ("unverified", False)
    assert item["verified_at"] is None and item["last_result"] is None


def test_list_sources_shape_and_load_failed_and_orphans(env):
    root, cfg_path = env
    put_source(root, "broken", "id: [unclosed")
    _passed(env)
    state.bump_gen("ghost")
    assert state.record_result("ghost", "b" * 64, "passed", {"total": 0, "failed": 0, "cases": []}, state.get_gen("ghost"))
    items = {s["id"]: s for s in service.list_sources()}
    assert set(items) == {"broken", SID}
    good = items[SID]
    assert good["source_id"] == "custom:single-og" and good["name"]
    assert good["status"] == "passed" and good["enabled"] is True
    assert good["load_error"] is None and good["verified_at"] == _entries(cfg_path)[SID]["verified_at"]
    assert good["last_result"]["total"] == 2
    bad = items["broken"]
    assert bad["status"] == "load_failed"
    assert set(bad["load_error"]) == {"reason", "field_path", "line", "message"}
    assert bad["load_error"]["reason"]
    assert bad["last_result"] is None and bad["verified_at"] is None


def test_remove_clears_state_and_listing(env):
    root, cfg_path = env
    _passed(env)
    service.set_enabled(SID, True)
    assert service.remove(SID) == {"id": SID}
    assert SID not in _entries(cfg_path)
    assert service.list_sources() == []
    assert not (root / "custom_sources" / "single-og.yaml").exists()


def test_applicable_is_pure_and_lists_only_routable(env, monkeypatch):
    service.upload(GOOD)
    service.upload(GOOD_MIN)
    assert service.applicable("SONE-205") == {}
    service.verify(SID, transport=_tp())
    assert service.applicable("SONE-205") == {"custom:single-og": True}  # 通過即啟用（165-T16）
    service.set_enabled(SID, False)
    assert service.applicable("SONE-205") == {}  # passed 但被使用者關閉
    service.set_enabled(SID, True)

    def boom(*a, **k):
        raise AssertionError("network touched")

    monkeypatch.setattr(public_target_mod, "resolve_host", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(fetch_mod, "make_transport", boom)
    assert service.applicable("SONE-205") == {"custom:single-og": True}
    assert service.applicable("FC2-123456") == {"custom:single-og": False}


# ---------------------------------------------------------------- call_bounded

def test_call_bounded_times_out_with_source_unreachable(monkeypatch):
    monkeypatch.setattr(service, "CALL_LIMIT_S", 0.2)
    stuck = threading.Event()
    t0 = time.monotonic()
    try:
        with pytest.raises(SourceUnreachable):
            service.call_bounded(lambda: stuck.wait(3))
        assert time.monotonic() - t0 < 1
    finally:
        stuck.set()


# ---------------------------------------------------------------- 鎖不變式

def _tracked(monkeypatch):
    tracker = TrackedLock()
    monkeypatch.setattr(state, "LOCK", tracker)
    return tracker


def test_mutate_config_callbacks_never_take_state_lock(env, monkeypatch):
    tracker = _tracked(monkeypatch)
    real = state.mutate_config

    def wrapped(mutator):
        def inner(cfg):
            tracker.in_callback = True
            try:
                mutator(cfg)
            finally:
                tracker.in_callback = False
        return real(inner)

    monkeypatch.setattr(state, "mutate_config", wrapped)
    service.upload(GOOD)
    service.verify(SID, transport=_tp())
    service.set_enabled(SID, True)
    service.remove(SID)
    assert tracker.acquired > 0
    assert tracker.violations == 0


class _RecordingGens(dict):
    def __init__(self, tracker, marks, *a):
        super().__init__(*a)
        self._tracker, self._marks = tracker, marks

    def get(self, key, default=None):
        self._marks.append(self._tracker.hold_id())
        return super().get(key, default)


