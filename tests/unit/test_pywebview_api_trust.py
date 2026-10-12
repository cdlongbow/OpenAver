"""windows/pywebview_api.py 信任閘測試（168a-T3b）。

只驅動假 window 事件並斷言結果；不推演事件先後。
oracle：(a) 載入序列、(i) before_load 立即撤銷、(ii) 遲到驗證不套用、origin 比對表、None==None、例外路徑。
"""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

import core.config as core_config

TRUSTED = "http://127.0.0.1:8000"
OTHER = "http://127.0.0.1:8001"

METHODS = ["open_file", "open_folder", "open_url", "select_files",
           "select_folder", "select_folder_path", "on_drop"]
REFUSALS = {
    "open_file": {"ok": False, "reason": "untrusted", "local_path": None, "server_path": None},
    "open_folder": {"ok": False, "reason": "untrusted", "local_path": None, "server_path": None},
    "open_url": False,
    "select_files": [],
    "select_folder": None,
    "select_folder_path": None,
    "on_drop": None,
}


class _FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def fire(self):
        for fn in list(self.handlers):
            fn()


class _FakeEvents:
    def __init__(self):
        self.before_load = _FakeEvent()
        self.loaded = _FakeEvent()


@pytest.fixture
def api_module(monkeypatch, tmp_path):
    mock_webview = MagicMock()
    mock_webview.OPEN_DIALOG = 10
    mock_webview.FOLDER_DIALOG = 20
    monkeypatch.setitem(sys.modules, "webview", mock_webview)
    monkeypatch.setitem(sys.modules, "webview.dom", MagicMock())
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core_config, "CONFIG_PATH", tmp_path / "config.json")
    spec = importlib.util.spec_from_file_location(
        "pywebview_api_trust_test",
        Path(__file__).parent.parent.parent / "windows" / "pywebview_api.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    module.set_window(None)


@pytest.fixture
def fx(api_module, monkeypatch, tmp_path):
    """副作用口全換成 Mock；window 是假的（events 只含 before_load／loaded）"""
    monkeypatch.setattr(sys, "platform", "win32")
    effects = {"Popen": Mock(), "run": Mock(), "startfile": Mock()}
    monkeypatch.setattr(api_module.subprocess, "Popen", effects["Popen"])
    monkeypatch.setattr(api_module.subprocess, "run", effects["run"])
    monkeypatch.setattr(api_module.os, "startfile", effects["startfile"], raising=False)
    video = tmp_path / "x.mp4"
    video.write_bytes(b"v")
    window = MagicMock()
    window.events = _FakeEvents()
    window.create_file_dialog.side_effect = lambda kind, **kw: [str(video)] if kind == 10 else [str(tmp_path)]
    window.evaluate_js.return_value = TRUSTED
    window.get_current_url.return_value = TRUSTED + "/"
    window.dom.document.events.drop = _FakeEvent()
    effects["create_file_dialog"] = window.create_file_dialog
    ns = type("FX", (), dict(m=api_module, window=window, effects=effects, video=video))
    api = api_module.Api()
    api._set_trusted_origin(TRUSTED)
    _wire(ns, api)
    return ns


def _wire(fx, api):
    """把 api 設為模組級實例並（重新）綁事件"""
    fx.api = api
    fx.m.api = api
    fx.window.events = _FakeEvents()
    fx.m.bind_events(fx.window)


def _call(fx, method):
    if method == "open_file":
        return fx.api.open_file(str(fx.video))
    if method == "open_folder":
        return fx.api.open_folder(str(fx.video))
    if method == "open_url":
        return fx.api.open_url("https://example.com")
    if method == "on_drop":
        return fx.m.on_drop({"dataTransfer": {"files": [{"pywebviewFullPath": str(fx.video)}]}})
    return getattr(fx.api, method)()


def _call_ok(fx, method):
    return _call(fx, method) != REFUSALS[method]


def _all_effects_called(fx):
    e = fx.effects
    return any(e[k].called for k in ("Popen", "run", "startfile", "create_file_dialog")) \
        or fx.window.evaluate_js.called


def _reset(fx):
    for k in ("Popen", "run", "startfile"):
        fx.effects[k].reset_mock()
    fx.window.create_file_dialog.reset_mock()
    fx.window.evaluate_js.reset_mock()


def _load(fx, origin):
    fx.window.evaluate_js.return_value = origin
    fx.window.get_current_url.return_value = origin + "/p?q=1" if isinstance(origin, str) else origin
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()


def _assert_all_inert(fx):
    for method in METHODS:
        _reset(fx)
        assert _call(fx, method) == REFUSALS[method], method
        assert not _all_effects_called(fx), method


def _assert_all_live(fx):
    for method in METHODS:
        _reset(fx)
        assert method == "on_drop" or _call_ok(fx, method), method
        if method == "on_drop":
            _call(fx, method)
        assert _all_effects_called(fx), method


def test_default_state_is_fail_closed(api_module, fx):
    _wire(fx, api_module.Api())
    _assert_all_inert(fx)


@pytest.mark.parametrize("method", METHODS)
def test_untrusted_page_gets_refusal_and_zero_side_effects(fx, method):
    _load(fx, OTHER)
    _reset(fx)
    mock_logger = MagicMock()
    fx.m.logger = mock_logger
    assert _call(fx, method) == REFUSALS[method]
    assert not _all_effects_called(fx)
    lines = [c[0][0] for c in mock_logger.warning.call_args_list
             if "refused reason=untrusted origin=" in c[0][0]]
    assert len(lines) == 1
    assert method in lines[0]


@pytest.mark.parametrize("method", METHODS)
def test_trusted_page_reaches_side_effects(fx, method):
    _load(fx, TRUSTED)
    _reset(fx)
    result = _call(fx, method)
    assert method == "on_drop" or result != REFUSALS[method]
    assert _all_effects_called(fx)


def test_load_sequence_trusts_only_trusted_segments(fx):
    _load(fx, TRUSTED)
    _assert_all_live(fx)
    _load(fx, OTHER)
    _assert_all_inert(fx)
    _load(fx, TRUSTED)
    _assert_all_live(fx)


def test_before_load_revokes_trust_before_any_verification(fx):
    _load(fx, TRUSTED)
    _assert_all_live(fx)
    fx.window.events.before_load.fire()
    _assert_all_inert(fx)


def test_stale_verification_never_trusts_later_navigation(fx):
    def late_verdict(_js):
        fx.window.events.before_load.fire()
        return TRUSTED

    fx.window.evaluate_js.side_effect = late_verdict
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()
    assert fx.api._trusted is False
    assert fx.window.dom.document.events.drop.handlers == []
    fx.window.evaluate_js.side_effect = None
    fx.window.evaluate_js.return_value = TRUSTED
    _assert_all_inert(fx)


def test_drop_bound_only_on_trusted_page(fx):
    _load(fx, OTHER)
    assert fx.window.dom.document.events.drop.handlers == []
    _load(fx, TRUSTED)
    assert len(fx.window.dom.document.events.drop.handlers) == 1


def test_no_trusted_origin_set_means_nothing_is_trusted(api_module, fx):
    fresh = api_module.Api()  # 從未 _set_trusted_origin
    _wire(fx, fresh)
    _load(fx, None)
    assert fresh._trusted is False
    _assert_all_inert(fx)


@pytest.mark.parametrize("origin", [
    OTHER,
    "http://localhost:8000",
    "http://localhost:8000.evil.com",
    "http://127.0.0.1:8000.evil.com",
    "null",
])
def test_origin_comparison_is_exact(fx, origin):
    _load(fx, origin)
    assert fx.api._trusted is False
    _assert_all_inert(fx)
    # 信任值是頁面 origin 的字串前綴（埠 800 vs 8000）也不能放行
    fx.api._set_trusted_origin("http://127.0.0.1:800")
    _load(fx, "http://127.0.0.1:8000")
    assert fx.api._trusted is False


@pytest.mark.parametrize("origin", ["HTTP://127.0.0.1:8000", "http://127.0.0.1:8000/", "http://127.0.0.1:8000/x?y=1"])
def test_equivalent_spellings_of_trusted_origin_are_trusted(fx, origin):
    _load(fx, origin)
    assert fx.api._trusted is True


def test_trailing_slash_on_configured_origin_is_normalised(fx):
    fx.api._set_trusted_origin(TRUSTED + "/")
    _load(fx, TRUSTED)
    assert fx.api._trusted is True


def test_evaluate_js_exception_is_untrusted_without_raising(fx):
    fx.window.evaluate_js.side_effect = RuntimeError("boom")
    mock_logger = MagicMock()
    fx.m.logger = mock_logger
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()
    assert fx.api._trusted is False
    assert "RuntimeError" in mock_logger.warning.call_args[0][0]


WHITELIST = {"open_file", "open_folder", "open_url",
             "select_files", "select_folder", "select_folder_path"}


def test_exposed_bridge_surface_is_exactly_the_whitelist(api_module):
    import inspect
    funcs = api_module.exposed_functions()
    assert {f.__name__ for f in funcs} == WHITELIST
    assert len(funcs) == len(WHITELIST)
    assert all(inspect.isfunction(f) and f.__module__ == api_module.__name__ for f in funcs)
    assert all("self" not in inspect.getfullargspec(f).args for f in funcs)


def _resolve(functions, name):
    """照 webview/util.py js_bridge_call（:330）：window._functions 精確查表，否則對 js_api(None) 逐層 getattr（:268-274）"""
    def get_nested_attribute(obj, attr_str):
        for attr in attr_str.split("."):
            obj = getattr(obj, attr, None)
            if obj is None:
                return None
        return obj
    return functions.get(name) or get_nested_attribute(None, name)


def test_dispatch_cannot_reach_api_internals(fx):
    functions = {f.__name__: f for f in fx.m.exposed_functions()}
    for name in ("open_file.__func__.__globals__", "_set_trusted_origin", "api._trusted", "_trusted"):
        assert _resolve(functions, name) is None, name
    # None 自己的方法（如 __setattr__）可被 getattr 到，但綁在 None 上，碰不到 Api
    hit = _resolve(functions, "__setattr__")
    assert hit is None or hit.__self__ is None
    with pytest.raises(Exception):
        hit("_trusted", True)
    assert fx.api._trusted is False


def test_dispatch_open_file_wrapper_refuses_when_untrusted(fx):
    functions = {f.__name__: f for f in fx.m.exposed_functions()}
    wrapper = _resolve(functions, "open_file")
    assert wrapper is functions["open_file"]
    _load(fx, OTHER)
    _reset(fx)
    assert wrapper(str(fx.video)) == REFUSALS["open_file"]
    assert not _all_effects_called(fx)


@pytest.mark.parametrize("js,native,trusted", [
    (TRUSTED, OTHER + "/", False),            # eval 被偽造：JS 說信任、原生說別處
    (OTHER, TRUSTED + "/", False),            # 原生對、JS 不對
    (TRUSTED, TRUSTED + "/", True),
    (TRUSTED, None, False),
    (TRUSTED, TRUSTED + "/search?x=1", True),  # 同 origin 不同 path／query
    (TRUSTED, "HTTP://127.0.0.1:8000/a", True),  # 原生 URL 依瀏覽器規則正規化
])
def test_both_origin_sources_must_match_trusted(fx, js, native, trusted):
    fx.window.evaluate_js.return_value = js
    fx.window.get_current_url.return_value = native
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()
    assert fx.api._trusted is trusted


def test_native_url_exception_is_untrusted(fx):
    fx.window.get_current_url.side_effect = RuntimeError("no url")
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()
    assert fx.api._trusted is False


def test_forged_js_origin_cannot_trust_foreign_native_page(fx):
    fx.window.evaluate_js.return_value = TRUSTED
    fx.window.get_current_url.return_value = "http://evil.example/"
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()
    _assert_all_inert(fx)
