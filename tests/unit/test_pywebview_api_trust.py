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
             "select_files", "select_folder", "select_folder_path",
             "connect_get_state", "connect_probe", "connect_login", "connect_sources",
             "connect_test_row", "connect_save_path_map", "connect_apply_restart",
             "connect_switch_local_restart", "connect_show_offline", "copy_text",
             "offline_get_state", "offline_retry", "offline_save_url", "offline_login",
             "offline_switch_local_restart",
             "local_settings_get", "local_settings_save", "update_check", "update_context",
             "update_run"}


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


# ---------------------------------------------------------------------------
# 168b-T4a：頁面種類 scope（_page_kind／_SCOPE）、離線頁判定、導航失敗分支、離線狀態容器
# ---------------------------------------------------------------------------
import core.client_settings as client_settings  # noqa: E402
import core.self_update as self_update  # noqa: E402

OFFLINE_ORIGIN = "http://127.0.0.1:55555"
OFFLINE_URL = OFFLINE_ORIGIN + "/offline.html"
SERVER_LAN = "http://192.168.1.50:8765"


def _load_raw(fx, js, native):
    """JS 與原生 URL 各給原字串（_load 只能表達同 origin）"""
    fx.window.evaluate_js.return_value = js
    fx.window.get_current_url.return_value = native
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()


def _load_offline(fx, origin=OFFLINE_ORIGIN):
    _load_raw(fx, origin, origin + "/offline.html")


def _write_client(tmp_path, url=SERVER_LAN):
    client_settings.save_client_settings({
        "version": 1, "server": {"url": url, "token": ""}, "path_map": [],
        "player": "", "video_extensions": None, "close_action": "ask", "tray_locale": None})


def test_page_kind_sequence_scopes_the_seven_methods(fx):
    kinds = [fx.api._page_kind]
    _load(fx, TRUSTED)
    kinds.append(fx.api._page_kind)
    _assert_all_live(fx)
    fx.api._expect_offline()
    _load_offline(fx)
    kinds.append(fx.api._page_kind)
    _assert_all_inert(fx)
    _load(fx, TRUSTED)
    kinds.append(fx.api._page_kind)
    _assert_all_live(fx)
    _load_offline(fx, "http://127.0.0.1:55556")  # 無旗標、別的埠
    kinds.append(fx.api._page_kind)
    _assert_all_inert(fx)
    assert kinds == [None, "server", "offline", "server", None]


def test_scope_table_registers_only_server_for_existing_seven(api_module):
    assert {m: api_module._SCOPE[m] for m in METHODS} == {m: "server" for m in METHODS}


def test_unregistered_method_is_denied(fx):
    _load(fx, TRUSTED)
    assert fx.api._page_kind == "server"
    assert fx.api._denied("not_in_scope_table") is True


def test_denied_warning_format_is_unchanged(fx):
    _load(fx, OTHER)
    fx.m.logger = MagicMock()
    assert fx.api._denied("open_file") is True
    line = fx.m.logger.warning.call_args[0][0]
    assert line == f"[pywebview] open_file refused reason=untrusted origin={OTHER!r}"


def test_trusted_property_is_compat_view_of_page_kind(fx):
    fx.api._trusted = True
    assert fx.api._page_kind == "server" and fx.api._trusted is True
    fx.api._trusted = False
    assert fx.api._page_kind is None and fx.api._trusted is False
    fx.api._page_kind = "offline"
    assert fx.api._trusted is False


def test_flag_then_server_page_gives_server_and_clears_flag(fx):
    fx.api._expect_offline()
    _load(fx, TRUSTED)
    assert fx.api._page_kind == "server"
    assert fx.api._offline_expected is False
    _load_offline(fx)  # 無旗標、_offline_origin 空
    assert fx.api._page_kind is None


def test_same_port_as_server_is_server_not_offline(fx):
    fx.api._set_trusted_origin(OFFLINE_ORIGIN)
    fx.api._expect_offline()
    _load_offline(fx)
    assert fx.api._page_kind == "server"
    assert fx.api._offline_expected is False
    assert len(fx.window.dom.document.events.drop.handlers) == 1


def test_offline_page_does_not_bind_drop(fx):
    fx.api._expect_offline()
    _load_offline(fx)
    assert fx.api._page_kind == "offline"
    assert fx.window.dom.document.events.drop.handlers == []


def test_stale_loaded_never_sets_offline_page_kind(fx):
    fx.api._expect_offline()

    def late_verdict(_js):
        fx.window.events.before_load.fire()
        return OFFLINE_ORIGIN

    fx.window.evaluate_js.side_effect = late_verdict
    fx.window.get_current_url.return_value = OFFLINE_URL
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()
    assert fx.api._page_kind is None
    assert fx.api._offline_expected is True  # 遲到的 loaded 不吃旗標
    fx.window.evaluate_js.side_effect = None
    _load_offline(fx)
    assert fx.api._page_kind == "offline"


def test_expect_offline_flag_is_single_use(fx):
    fx.api._expect_offline()
    _load_offline(fx)
    assert fx.api._page_kind == "offline"
    assert fx.api._offline_expected is False
    _load_offline(fx, "http://127.0.0.1:55556")  # 同機別的程式起的 /offline.html
    assert fx.api._page_kind is None


def test_offline_page_reload_stays_offline_other_port_does_not(fx):
    fx.api._expect_offline()
    _load_offline(fx)
    _load_offline(fx)  # 同頁重整（無旗標）
    assert fx.api._page_kind == "offline"
    _load_offline(fx, "http://127.0.0.1:55556")
    assert fx.api._page_kind is None


def test_no_flag_and_no_remembered_origin_is_none(fx):
    _load_offline(fx)
    assert fx.api._page_kind is None


def test_offline_landing_rejects_foreign_host(fx):
    fx.api._expect_offline()
    _load_offline(fx, "http://evil.example:55555")
    assert fx.api._page_kind is None
    for host in ("127.0.0.1.evil.com", "localhost.evil.com"):
        fx.api._expect_offline()
        _load_offline(fx, f"http://{host}:55555")
        assert fx.api._page_kind is None, host


def test_offline_landing_requires_offline_html_path(fx):
    for path in ("/x.html", "/offline.html.evil", "/"):
        fx.api._expect_offline()
        _load_raw(fx, OFFLINE_ORIGIN, OFFLINE_ORIGIN + path)
        assert fx.api._page_kind is None, path


@pytest.mark.parametrize("js,native,expected", [
    ("http://127.0.0.1:5", "http://127.0.0.1:5/offline.html", True),
    ("http://localhost:5", "http://localhost:5/offline.html", True),
    ("http://localhost:5", "http://localhost:5/a/offline.html", True),
    ("http://evil.example:5", "http://evil.example:5/offline.html", False),
    ("http://127.0.0.1.evil.com:5", "http://127.0.0.1.evil.com:5/offline.html", False),
    ("http://127.0.0.1:5", "http://127.0.0.1:5/x.html", False),
    ("http://127.0.0.1:5", "http://127.0.0.1:5/offline.html.evil", False),
    ("http://127.0.0.1:5", "http://127.0.0.1:6/offline.html", False),
    ("http://127.0.0.1:5", "http://localhost:5/offline.html", False),
    ("null", "http://127.0.0.1:5/offline.html", False),
    (None, "http://127.0.0.1:5/offline.html", False),
    ("http://127.0.0.1:5", None, False),
])
def test_is_offline_landing_table(api_module, js, native, expected):
    assert api_module._is_offline_landing(js, native) is expected


def _nav_failure_fx(fx, tmp_path, mode_client=True, native=None):
    if mode_client:
        _write_client(tmp_path)
    fx.api._set_trusted_origin(SERVER_LAN)
    seen = []
    fx.window.load_url.side_effect = lambda url: seen.append(fx.api._offline_expected)
    _load_raw(fx, "chrome-error://chromewebdata", native or SERVER_LAN + "/")
    return seen


def test_nav_failure_in_client_mode_shows_offline_once(fx, tmp_path):
    seen = _nav_failure_fx(fx, tmp_path)
    fx.window.load_url.assert_called_once_with(fx.m.OFFLINE_PAGE)
    assert seen == [True]
    assert fx.api._offline_state["failed_url"] == SERVER_LAN
    assert fx.api._page_kind is None


def test_nav_failure_warning_has_host_only_and_not_refusal_text(fx, tmp_path):
    fx.m.logger = MagicMock()
    _nav_failure_fx(fx, tmp_path)
    lines = [c[0][0] for c in fx.m.logger.warning.call_args_list]
    assert not any("refused reason=untrusted origin=" in line for line in lines)
    assert any("192.168.1.50:8765" in line for line in lines)
    assert not any("oa_token" in line or "http://192" in line for line in lines)


def test_nav_failure_in_local_mode_does_not_show_offline(fx, tmp_path):
    _nav_failure_fx(fx, tmp_path, mode_client=False)
    fx.window.load_url.assert_not_called()


def test_nav_failure_on_non_trusted_native_origin_does_nothing(fx, tmp_path):
    _nav_failure_fx(fx, tmp_path, native=OFFLINE_URL)  # 小頁自己載入失敗
    fx.window.load_url.assert_not_called()


def test_nav_failure_with_js_exception_does_nothing(fx, tmp_path):
    _write_client(tmp_path)
    fx.api._set_trusted_origin(SERVER_LAN)
    fx.window.evaluate_js.side_effect = RuntimeError("boom")
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()
    fx.window.load_url.assert_not_called()


def test_nav_failure_ignored_when_generation_is_stale(fx, tmp_path):
    _write_client(tmp_path)
    fx.api._set_trusted_origin(SERVER_LAN)

    def late(_js):
        fx.window.events.before_load.fire()
        return "chrome-error://chromewebdata"

    fx.window.evaluate_js.side_effect = late
    fx.window.get_current_url.return_value = SERVER_LAN + "/"
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()
    fx.window.load_url.assert_not_called()


def test_offline_state_failed_url_is_canonical_origin_only(fx):
    leaked = "http://192.168.1.50:8765/?oa_shell=windows&oa_mode=client&oa_token=TKN-SENTINEL-9"
    fx.api._set_offline_state("x", leaked)
    assert fx.api._offline_state == {"reason": "x", "failed_url": SERVER_LAN, "host_port": "192.168.1.50:8765"}
    assert "TKN-SENTINEL-9" not in str(fx.api._offline_state)
    assert "oa_token" not in str(fx.api._offline_state)


def test_offline_state_invalid_url_is_stored_empty(fx):
    fx.api._set_offline_state("x", "not a url")
    assert fx.api._offline_state["failed_url"] == ""


def test_exposed_functions_unchanged_by_scope_machinery(api_module):
    assert len(api_module.exposed_functions()) == 26


# ---------------------------------------------------------------------------
# 168b-T4b：27 個方法 × 3 種頁面的 scope 矩陣（期望表為字面值，不由 _SCOPE 衍生）
# ---------------------------------------------------------------------------
SCOPE_LITERAL = {
    "select_files": "server", "select_folder": "server", "select_folder_path": "server",
    "open_file": "server", "open_folder": "server", "open_url": "server", "on_drop": "server",
    "connect_get_state": "server", "connect_probe": "server", "connect_login": "server",
    "connect_sources": "server", "connect_test_row": "server", "connect_save_path_map": "server",
    "connect_apply_restart": "server", "connect_switch_local_restart": "server",
    "connect_show_offline": "server", "copy_text": "server",
    "offline_get_state": "offline", "offline_retry": "offline", "offline_save_url": "offline",
    "offline_login": "offline", "offline_switch_local_restart": "offline",
    "local_settings_get": "server", "local_settings_save": "server", "update_check": "server",
    "update_context": "server", "update_run": "server",
}
NEW_ARGS = {
    "connect_get_state": (), "connect_probe": (SERVER_LAN,), "connect_login": (SERVER_LAN, "1234"),
    "connect_sources": (SERVER_LAN,), "connect_test_row": ("/a", "D:/a", "/a/x.mp4"),
    "connect_save_path_map": ([],), "connect_apply_restart": (SERVER_LAN, []),
    "connect_switch_local_restart": (), "connect_show_offline": (), "copy_text": ("x",),
    "offline_get_state": (), "offline_retry": (), "offline_save_url": (SERVER_LAN,),
    "offline_login": ("1234",), "offline_switch_local_restart": (),
    "local_settings_get": (), "local_settings_save": ({},), "update_check": (),
    "update_context": (), "update_run": (),
}
OFFLINE_METHODS = sorted(m for m, k in SCOPE_LITERAL.items() if k == "offline")
UNTRUSTED_REPLY = {"ok": False, "reason": "untrusted"}


@pytest.fixture
def mx(fx, tmp_path, monkeypatch):
    """matrix fixture：client 模式、所有新方法的副作用口換成 Mock"""
    import core.client_connect as client_connect
    _write_client(tmp_path)
    fx.mocks = {
        "probe": Mock(return_value={"ok": True, "reason": None, "version": "0.17.7", "kind": "nas",
                                    "auth_required": False, "authed": True,
                                    "compat": client_connect.Compat("ok", "")}),
        "login": Mock(return_value={"ok": True, "reason": None, "token": "t"}),
        "fetch_sources": Mock(return_value={"ok": True, "reason": None, "sources": []}),
        "preflight": Mock(return_value=client_connect.Preflight("ok", None, {})),
    }
    for name, mock in fx.mocks.items():
        monkeypatch.setattr(client_connect, name, mock)
    for name in ("apply_connection", "clear_connection", "save_path_map", "touch_last_ok"):
        fx.mocks[name] = Mock()
        monkeypatch.setattr(client_settings, name, fx.mocks[name])
    fx.mocks["copy_text"] = Mock(return_value=True)
    monkeypatch.setattr(fx.m.clipboard, "copy_text", fx.mocks["copy_text"])
    fx.mocks["stat"] = Mock()
    monkeypatch.setattr(fx.m, "_stat_path", fx.mocks["stat"])
    fx.mocks["restart"] = Mock()
    fx.m.set_restart_handler(fx.mocks["restart"])
    fx.mocks["check_latest"] = Mock(return_value={"ok": True, "has_update": False, "current_version": "0.0.0"})
    monkeypatch.setattr(self_update, "check_latest", fx.mocks["check_latest"])
    fx.mocks["launch_installer"] = Mock()
    monkeypatch.setattr(self_update, "launch_installer", fx.mocks["launch_installer"])
    fx.mocks["update_local_settings"] = Mock(return_value={"ok": True, "changed": []})
    monkeypatch.setattr(client_settings, "update_local_settings", fx.mocks["update_local_settings"])
    return fx


def _land(fx, kind):
    if kind == "server":
        _load(fx, TRUSTED)
    elif kind == "offline":
        fx.api._expect_offline()
        _load_offline(fx)
    else:
        _load(fx, OTHER)
    assert fx.api._page_kind == (None if kind == "none" else kind)
    _reset(fx)
    for mock in fx.mocks.values():
        mock.reset_mock()
    fx.window.load_url.reset_mock()
    fx.window.set_title.reset_mock()


def _matrix_call(fx, method):
    if method in NEW_ARGS:
        return getattr(fx.m, method)(*NEW_ARGS[method])
    return _call(fx, method)


def _refusal(method):
    return UNTRUSTED_REPLY if method in NEW_ARGS else REFUSALS[method]


def _assert_zero_effects(fx):
    assert not _all_effects_called(fx)
    for mock in fx.mocks.values():
        mock.assert_not_called()
    fx.window.load_url.assert_not_called()
    fx.window.set_title.assert_not_called()


def test_scope_matrix_literal_covers_exactly_the_scope_table(api_module):
    assert len(SCOPE_LITERAL) == 27
    assert set(SCOPE_LITERAL) == set(api_module._SCOPE)
    assert {m: api_module._SCOPE[m] for m in SCOPE_LITERAL} == SCOPE_LITERAL


@pytest.mark.parametrize("method", sorted(SCOPE_LITERAL))
def test_scope_matrix_method_passes_on_its_own_page_kind(mx, method):
    _land(mx, SCOPE_LITERAL[method])
    result = _matrix_call(mx, method)
    if method in NEW_ARGS:
        assert result != UNTRUSTED_REPLY, method
    else:
        # 既有七項：回傳不是拒絕形狀（open_*：client 模式下會是 uncovered 另一種拒絕），或副作用口真的被碰到
        assert result != REFUSALS[method] or _all_effects_called(mx), method


@pytest.mark.parametrize("kind", ["none", "server", "offline"])
@pytest.mark.parametrize("method", sorted(SCOPE_LITERAL))
def test_scope_matrix_denied_on_other_page_kinds(mx, method, kind):
    if SCOPE_LITERAL[method] == kind:
        pytest.skip("own page kind")
    _land(mx, kind)
    assert _matrix_call(mx, method) == _refusal(method), (method, kind)
    _assert_zero_effects(mx)


@pytest.mark.parametrize("method", OFFLINE_METHODS)
def test_scope_matrix_offline_methods_denied_on_server_page(mx, method):
    _land(mx, "server")
    assert _matrix_call(mx, method) == UNTRUSTED_REPLY
    _assert_zero_effects(mx)


def test_scope_matrix_unregistered_page_none_denies_all_new_methods(mx):
    _land(mx, "none")
    for method in NEW_ARGS:
        assert _matrix_call(mx, method) == UNTRUSTED_REPLY, method
    _assert_zero_effects(mx)


# ---------------------------------------------------------------------------
# 168b-T9a：就緒訊號（F1/F2）與 WebView2 導航失敗簽名 "null"（F3）
# ---------------------------------------------------------------------------
def _ready_calls(fx):
    return [c[0][0] for c in fx.window.evaluate_js.call_args_list if "oabridgeready" in c[0][0]]


def test_loaded_signals_bridge_ready_with_kind_only_after_page_kind_is_set(fx, tmp_path):
    _write_client(tmp_path)
    fx.api._set_trusted_origin(SERVER_LAN)
    kinds_at_signal = []

    def spy(js):
        if "oabridgeready" in js:
            kinds_at_signal.append(fx.api._page_kind)
        return SERVER_LAN

    fx.window.evaluate_js.side_effect = spy
    fx.window.get_current_url.return_value = SERVER_LAN + "/p?oa_token=TKN-SENTINEL-9"
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()
    sent = _ready_calls(fx)
    assert len(sent) == 1
    assert kinds_at_signal == ["server"]
    assert "__oaBridgeKind" in sent[0] and '"server"' in sent[0]
    for secret in ("192.168", "TKN-SENTINEL-9", "oa_token", "http"):
        assert secret not in sent[0]


def test_loaded_signals_offline_kind_for_offline_page(fx):
    fx.api._expect_offline()
    _load_offline(fx)
    sent = _ready_calls(fx)
    assert len(sent) == 1 and '"offline"' in sent[0]


def test_loaded_sends_no_signal_when_page_kind_is_none(fx):
    _load_raw(fx, "http://evil.example:9", "http://evil.example:9/")
    assert fx.api._page_kind is None
    assert _ready_calls(fx) == []


def test_stale_generation_sends_no_signal(fx):
    def late(js):
        if js == "location.origin":
            fx.window.events.before_load.fire()
        return TRUSTED

    fx.window.evaluate_js.side_effect = late
    fx.window.events.before_load.fire()
    fx.window.events.loaded.fire()
    assert _ready_calls(fx) == []


def test_nav_failure_with_webview2_null_origin_on_server_url_shows_offline(fx, tmp_path):
    _write_client(tmp_path)
    fx.api._set_trusted_origin(SERVER_LAN)
    _load_raw(fx, "null", SERVER_LAN + "/settings")
    fx.window.load_url.assert_called_once_with(fx.m.OFFLINE_PAGE)


def test_null_origin_on_about_blank_is_not_a_nav_failure(fx, tmp_path):
    _write_client(tmp_path)
    fx.api._set_trusted_origin(SERVER_LAN)
    _load_raw(fx, "null", "about:blank")
    fx.window.load_url.assert_not_called()


# ---------------------------------------------------------------------------
# 168c-T2：導航空窗複查（原生 origin）與載入完成鉤子
# ---------------------------------------------------------------------------
EVIL_URL = "http://evil.example/"
_KIND_ORIGIN = {"server": TRUSTED, "offline": OFFLINE_ORIGIN}


def _set_native(fx, how, kind):
    """_land 之後才改原生 URL：同／異／None／拋例外"""
    getter = fx.window.get_current_url
    getter.side_effect = None
    if how == "same":
        getter.return_value = _KIND_ORIGIN[kind] + "/next"
    elif how == "other":
        getter.return_value = EVIL_URL
    elif how == "none":
        getter.return_value = None
    else:
        getter.side_effect = RuntimeError("no url")


def _own_kind_methods():
    return sorted(SCOPE_LITERAL)


@pytest.mark.parametrize("how", ["other", "none", "raises"])
@pytest.mark.parametrize("method", _own_kind_methods())
def test_native_origin_recheck_refuses_with_zero_effects(mx, method, how):
    kind = SCOPE_LITERAL[method]
    _land(mx, kind)
    _set_native(mx, how, kind)
    mx.m.logger = MagicMock()
    assert _matrix_call(mx, method) == _refusal(method), (method, how)
    _assert_zero_effects(mx)
    lines = [c[0][0] for c in mx.m.logger.warning.call_args_list
             if "refused reason=navigating origin=" in c[0][0]]
    assert len(lines) == 1 and method in lines[0]
    assert not any("reason=untrusted" in c[0][0] for c in mx.m.logger.warning.call_args_list)


@pytest.mark.parametrize("method", _own_kind_methods())
def test_native_origin_recheck_passes_on_own_page_when_unchanged(mx, method):
    kind = SCOPE_LITERAL[method]
    _land(mx, kind)
    _set_native(mx, "same", kind)
    mx.m.logger = MagicMock()
    result = _matrix_call(mx, method)
    if method in NEW_ARGS:
        assert result != UNTRUSTED_REPLY, method
    else:
        assert result != REFUSALS[method] or _all_effects_called(mx), method
    assert not any("refused reason=navigating" in c[0][0] for c in mx.m.logger.warning.call_args_list)


@pytest.mark.parametrize("platform", ["linux", "freebsd"])
def test_native_origin_recheck_skipped_on_other_platforms(mx, monkeypatch, platform):
    _land(mx, "server")
    _set_native(mx, "other", "server")
    monkeypatch.setattr(sys, "platform", platform)
    assert mx.api._denied("copy_text") is False


def test_loaded_hook_runs_for_server_and_offline_pages(fx):
    hook = Mock()
    fx.m.set_loaded_hook(hook)
    try:
        _load(fx, TRUSTED)
        hook.assert_called_once_with("server", fx.window, fx.api._nav_gen)
        hook.reset_mock()
        fx.api._expect_offline()
        _load_offline(fx)
        hook.assert_called_once_with("offline", fx.window, fx.api._nav_gen)
        hook.reset_mock()
        _load(fx, OTHER)  # 不受信任頁
        hook.assert_not_called()

        def late(js):
            if js == "location.origin":
                fx.window.events.before_load.fire()
            return TRUSTED

        fx.window.evaluate_js.side_effect = late  # 遲到的 loaded
        fx.window.events.before_load.fire()
        fx.window.events.loaded.fire()
        hook.assert_not_called()
        fx.window.evaluate_js.side_effect = None
        fx.m.set_loaded_hook(None)  # 未註冊
        _load(fx, TRUSTED)
        hook.assert_not_called()
    finally:
        fx.m.set_loaded_hook(None)


def test_loaded_hook_exception_does_not_escape_on_loaded(fx):
    fx.m.logger = MagicMock()
    fx.m.set_loaded_hook(Mock(side_effect=RuntimeError("boom")))
    try:
        _load(fx, TRUSTED)
    finally:
        fx.m.set_loaded_hook(None)
    assert fx.api._page_kind == "server"
    assert any("RuntimeError" in c[0][0] for c in fx.m.logger.warning.call_args_list)


def test_loaded_hook_not_called_when_generation_advances_during_bridge_ready_signal(fx):
    hook = Mock()
    fx.m.set_loaded_hook(hook)

    def during_signal(js):
        if "oabridgeready" in js:
            fx.window.events.before_load.fire()  # 通知期間又一輪導航開始
        return TRUSTED

    fx.window.evaluate_js.side_effect = during_signal
    try:
        fx.window.events.before_load.fire()
        fx.window.events.loaded.fire()
    finally:
        fx.m.set_loaded_hook(None)
    assert fx.api._page_kind is None
    hook.assert_not_called()
