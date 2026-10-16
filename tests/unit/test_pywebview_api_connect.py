"""windows/pywebview_api.py 的 15 個連線／離線／剪貼簿 bridge 方法（168b-T4b）。

client_settings 用真的（寫在 tmp 資料根）；遠端 I/O（client_connect.*）、重啟處理器、
視窗、剪貼簿全換成 Mock。期望值一律字面寫死。
"""
import importlib.util
import json
import logging
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

import core.client_connect as client_connect
import core.client_settings as client_settings
import core.config as core_config
import core.self_update as self_update
from core.version import VERSION

SERVER = "http://192.168.1.50:8765"
OTHER = "http://192.168.1.60:8765"
TKN = "TKN-SENTINEL-9"
PIN = "PIN-SENTINEL-1"
UNTRUSTED = {"ok": False, "reason": "untrusted"}


def probe_reply(ok=True, reason=None, status="ok", auth_required=False, authed=True):
    return {"ok": ok, "reason": reason, "version": "0.17.7", "kind": "nas",
            "auth_required": auth_required, "authed": authed,
            "compat": client_connect.Compat(status, "")}


@pytest.fixture
def api_module(monkeypatch):
    mock_webview = MagicMock()
    monkeypatch.setitem(sys.modules, "webview", mock_webview)
    monkeypatch.setitem(sys.modules, "webview.dom", MagicMock())
    spec = importlib.util.spec_from_file_location(
        "pywebview_api_connect_test",
        Path(__file__).parent.parent.parent / "windows" / "pywebview_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    w = MagicMock()
    w.get_current_url.return_value = "http://127.0.0.1:8000/"
    module.set_window(w)
    module.api._seen_origin = "http://127.0.0.1:8000"
    yield module
    module.set_window(None)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core_config, "CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / ".layout.json").write_text(json.dumps({"version": 1, "complete": True}), encoding="utf-8")
    return tmp_path


def write_client(url=SERVER, token="", path_map=None, player="C:/p.exe"):
    client_settings.save_client_settings({
        "version": 1, "server": {"url": url, "token": token},
        "path_map": path_map if path_map is not None else [{"server": "/volume1/av", "local": "D:/av"}],
        "player": player, "video_extensions": None, "close_action": "ask", "tray_locale": None})


def client_bytes():
    p = client_settings._client_path()
    return p.read_bytes() if p.exists() else None


def config_bytes(root):
    p = root / "config.json"
    return p.read_bytes() if p.exists() else None


class CX:
    """一組已接好 Mock 的被測物"""


@pytest.fixture
def cx(api_module, root, monkeypatch):
    c = CX()
    c.m, c.api, c.root = api_module, api_module.api, root
    c.window = api_module.get_window()
    c.probe = Mock(return_value=probe_reply())
    c.login = Mock(return_value={"ok": True, "reason": None, "token": TKN})
    c.sources = Mock(return_value={"ok": True, "reason": None, "sources": [{"path": "/volume1/av"}]})
    c.preflight = Mock(return_value=client_connect.Preflight("ok", None, probe_reply()))
    monkeypatch.setattr(client_connect, "probe", c.probe)
    monkeypatch.setattr(client_connect, "login", c.login)
    monkeypatch.setattr(client_connect, "fetch_sources", c.sources)
    monkeypatch.setattr(client_connect, "preflight", c.preflight)
    c.restart = Mock(return_value=None)
    c.copy = Mock(return_value=True)
    monkeypatch.setattr(api_module.clipboard, "copy_text", c.copy)
    c.api._page_kind = "server"
    return c


@pytest.fixture
def with_handler(cx):
    cx.m.set_restart_handler(cx.restart)
    return cx


def as_offline(cx):
    cx.api._page_kind = "offline"


# ---------------------------------------------------------------------------
# connect_get_state / probe / login / sources
# ---------------------------------------------------------------------------

def test_get_state_local_mode(cx):
    assert cx.api.connect_get_state() == {
        "mode": "local", "url": "", "host": "", "has_token": False, "path_map": [],
        "version": client_connect.LOCAL_VERSION, "last_ok": None, "cf": None}


CF_STATUS = {"state": "ready", "reason": None, "proxy_note": None, "sites": ["javlibrary", "fc-javten"]}


def test_get_state_cf_comes_from_registered_provider(cx):
    cx.m.set_cf_status_provider(lambda: dict(CF_STATUS))
    assert cx.api.connect_get_state()["cf"] == CF_STATUS




@pytest.mark.parametrize("provider", [Mock(side_effect=RuntimeError("boom-detail-xyz")),
                                      lambda: ["not", "a", "dict"], lambda: None])
def test_get_state_cf_degrades_to_none(cx, provider, caplog):
    cx.m.set_cf_status_provider(provider)
    with caplog.at_level(logging.WARNING):
        assert cx.api.connect_get_state()["cf"] is None
    assert "boom-detail-xyz" not in caplog.text   # 只記例外型別


def test_get_state_with_real_provider_never_leaks_token(cx):
    write_client(token=TKN)
    cx.m.set_cf_status_provider(lambda: dict(CF_STATUS))
    state = cx.api.connect_get_state()
    assert state["cf"] == CF_STATUS
    assert TKN not in json.dumps(state)


def test_cf_provider_setter_is_not_exposed_to_the_page(cx):
    assert "set_cf_status_provider" not in [f.__name__ for f in cx.m.exposed_functions()]


def test_get_state_client_mode_exposes_has_token_not_token(cx):
    write_client(token=TKN)
    state = cx.api.connect_get_state()
    assert state["mode"] == "client" and state["url"] == SERVER
    assert state["host"] == "192.168.1.50:8765"
    assert state["has_token"] is True
    assert state["path_map"] == [{"server": "/volume1/av", "local": "D:/av"}]
    assert TKN not in json.dumps(state)
    assert state["last_ok"] is None
    client_settings.touch_last_ok()
    assert cx.api.connect_get_state()["last_ok"] == client_settings.server_last_ok() is not None


def test_get_state_after_switch_local_still_returns_saved_path_map(cx):
    write_client(token=TKN)
    client_settings.clear_connection()
    assert client_settings.mode() == "local"
    assert client_settings.path_map() == []  # 本機模式換算維持零規則
    state = cx.api.connect_get_state()
    assert state["mode"] == "local"
    assert state["path_map"] == [{"server": "/volume1/av", "local": "D:/av"}]


def test_probe_shape_and_compat_is_plain_dict(cx):
    reply = cx.api.connect_probe(SERVER + "/")
    assert reply == {"ok": True, "reason": None, "version": "0.17.7", "kind": "nas",
                     "auth_required": False, "authed": True,
                     "compat": {"status": "ok", "hint": ""}, "url": SERVER}
    json.dumps(reply)
    assert cx.probe.call_args.args[0] == SERVER


def test_probe_invalid_url_still_returns_shape(cx):
    cx.probe.return_value = probe_reply(ok=False, reason="unreachable", status="unparseable")
    reply = cx.api.connect_probe("not a url")
    assert reply["ok"] is False and reply["url"] == ""


def test_probe_token_order_draft_then_stored_then_none(cx):
    write_client(url=SERVER, token="STORED")
    cx.api.connect_probe(SERVER)
    assert cx.probe.call_args.args[1] == "STORED"          # url 等於已存網址 → 已存 token
    cx.api.connect_probe(OTHER)
    assert cx.probe.call_args.args[1] is None              # 別的主機 → 不帶 token
    cx.api.connect_login(SERVER, PIN)                      # draft = (SERVER, TKN)
    cx.api.connect_probe(SERVER)
    assert cx.probe.call_args.args[1] == TKN               # 同 origin 的 draft 優先
    cx.api.connect_probe(OTHER)
    assert cx.m._draft == {"origin": None, "token": None}  # 換 origin → 清掉


def test_login_success_returns_only_ok_and_keeps_token_in_python(cx):
    reply = cx.api.connect_login(SERVER, PIN)
    assert reply == {"ok": True, "reason": None}
    assert cx.m._draft == {"origin": SERVER, "token": TKN}
    assert cx.login.call_args.args == (SERVER, PIN)


def test_login_failure_does_not_write_draft(cx):
    cx.login.return_value = {"ok": False, "reason": "bad_pin", "token": None}
    assert cx.api.connect_login(SERVER, PIN) == {"ok": False, "reason": "bad_pin"}
    assert cx.m._draft == {"origin": None, "token": None}


def test_login_invalid_url_never_calls_remote(cx):
    assert cx.api.connect_login("a b", PIN)["ok"] is False
    cx.login.assert_not_called()


def test_sources_passes_token_and_returns_shape(cx):
    cx.api.connect_login(SERVER, PIN)
    reply = cx.api.connect_sources(SERVER)
    assert reply == {"ok": True, "reason": None, "sources": [{"path": "/volume1/av"}]}
    assert cx.sources.call_args.args == (SERVER, TKN)


# ---------------------------------------------------------------------------
# connect_test_row
# ---------------------------------------------------------------------------

def test_test_row_empty_and_no_sample(cx, monkeypatch):
    stat = Mock()
    monkeypatch.setattr(cx.m, "_stat_path", stat)
    assert cx.api.connect_test_row("/volume1/av", "  ", "/volume1/av/x.mp4") == {"state": "empty"}
    assert cx.api.connect_test_row("/volume1/av", "", None) == {"state": "empty"}
    assert cx.api.connect_test_row("/volume1/av", "D:/av", None) == {"state": "no_sample"}
    stat.assert_not_called()


def test_test_row_uncovered_never_stats_original_string(cx, monkeypatch):
    stat = Mock()
    monkeypatch.setattr(cx.m, "_stat_path", stat)
    assert cx.api.connect_test_row("/volume1/av", "D:/av", "/other/x.mp4") == {"state": "uncovered"}
    stat.assert_not_called()


def test_test_row_ok_stats_translated_path(cx, monkeypatch):
    stat = Mock(return_value=None)
    monkeypatch.setattr(cx.m, "_stat_path", stat)
    assert cx.api.connect_test_row("/volume1/av", "D:/av", "/volume1/av/s/x.mp4") == {"state": "ok"}
    assert stat.call_args.args == ("D:\\av\\s\\x.mp4",)


def test_test_row_quoted_local_stats_unquoted_path(cx, monkeypatch):
    stat = Mock(return_value=None)
    monkeypatch.setattr(cx.m, "_stat_path", stat)
    assert cx.api.connect_test_row("/volume1/av", '"D:/av"', "/volume1/av/x.mp4") == {"state": "ok"}
    assert stat.call_args.args == ("D:\\av\\x.mp4",)


def test_clean_rules_strips_wrapping_quotes(cx):
    out = cx.m._clean_rules([{"server": "/a", "local": '"' + r"\\nas\av" + '"'},
                             {"server": "/b", "local": '""'}])
    assert out == [{"server": "/a", "local": r"\\nas\av"}]


@pytest.mark.parametrize("exc", [FileNotFoundError, PermissionError, OSError])
def test_test_row_stat_errors_are_not_found_with_local_path(cx, monkeypatch, exc):
    monkeypatch.setattr(cx.m, "_stat_path", Mock(side_effect=exc("x")))
    assert cx.api.connect_test_row("/volume1/av", "D:/av", "/volume1/av/x.mp4") == {
        "state": "not_found", "local_path": "D:\\av\\x.mp4"}


def test_test_row_timeout_and_single_in_flight(cx, monkeypatch):
    release = threading.Event()
    stat = Mock(side_effect=lambda p: release.wait(5))
    monkeypatch.setattr(cx.m, "_stat_path", stat)
    monkeypatch.setattr(cx.m, "_ROW_TEST_TIMEOUT", 0.05)
    try:
        assert cx.api.connect_test_row("/volume1/av", "D:/av", "/volume1/av/x.mp4") == {"state": "timeout"}
        # 第一個還在飛：第二次直接 timeout、不再開 thread
        assert cx.api.connect_test_row("/volume1/av", "D:/av", "/volume1/av/y.mp4") == {"state": "timeout"}
        assert stat.call_count == 1
    finally:
        release.set()
    for t in threading.enumerate():
        if t.daemon and t is not threading.current_thread():
            t.join(1)
    stat.side_effect = None
    monkeypatch.setattr(cx.m, "_ROW_TEST_TIMEOUT", 2.0)
    assert cx.api.connect_test_row("/volume1/av", "D:/av", "/volume1/av/z.mp4") == {"state": "ok"}
    assert stat.call_count == 2


# ---------------------------------------------------------------------------
# connect_save_path_map / apply / switch local
# ---------------------------------------------------------------------------

def test_save_path_map_keeps_only_complete_rows(cx):
    write_client(path_map=[])
    rules = [{"server": "/a", "local": "D:/a"}, {"server": "/b", "local": ""},
             {"server": " ", "local": "D:/c"}, "junk"]
    assert cx.api.connect_save_path_map(rules) == {"ok": True, "reason": None}
    assert client_settings.path_map() == [{"server": "/a", "local": "D:/a"}]


def test_save_path_map_in_local_mode_is_not_client_and_writes_nothing(cx):
    assert cx.api.connect_save_path_map([{"server": "/a", "local": "D:/a"}]) == {"ok": False, "reason": "not_client"}
    assert client_bytes() is None


def assert_apply_refused(cx, root, reply, reason, before_client):
    assert reply == {"ok": False, "reason": reason}
    assert client_bytes() == before_client
    assert config_bytes(root) is None
    cx.restart.assert_not_called()


def test_apply_restart_refuses_invalid_url(with_handler, root):
    cx = with_handler
    assert_apply_refused(cx, root, cx.api.connect_apply_restart("a b", []), "invalid_url", None)
    cx.probe.assert_not_called()


def test_apply_restart_refuses_unreachable(with_handler, root):
    cx = with_handler
    cx.probe.return_value = probe_reply(ok=False, reason="unreachable", status="unparseable")
    assert_apply_refused(cx, root, cx.api.connect_apply_restart(SERVER, []), "unreachable", None)


def test_apply_restart_legacy_server_without_hello_is_incompatible(with_handler, root):
    cx = with_handler
    cx.probe.return_value = probe_reply(ok=False, reason=None, status="server_old")
    assert_apply_refused(cx, root, cx.api.connect_apply_restart(SERVER, []), "incompatible", None)


def test_apply_restart_refuses_incompatible_server_without_writing(with_handler, root):
    cx = with_handler
    write_client()
    before = client_bytes()
    cx.probe.return_value = probe_reply(status="server_old")
    assert_apply_refused(cx, root, cx.api.connect_apply_restart(OTHER, []), "incompatible", before)


def test_apply_restart_refuses_unauthenticated_without_writing(with_handler, root):
    cx = with_handler
    cx.probe.return_value = probe_reply(auth_required=True, authed=False)
    assert_apply_refused(cx, root, cx.api.connect_apply_restart(SERVER, []), "need_login", None)


def test_apply_restart_refuses_when_handler_missing(cx, root):
    assert_apply_refused(cx, root, cx.api.connect_apply_restart(SERVER, []), "restart_unavailable", None)


REAL_CONFIG = b'{"general": {"locale": "zh_TW", "server_mode": true}, "scraper": {"video_extensions": [".mp4"]}}'


def test_apply_restart_success_writes_once_and_restarts_once(with_handler, root):
    cx = with_handler
    (root / "config.json").write_bytes(REAL_CONFIG)
    cx.probe.return_value = probe_reply(auth_required=True, authed=True)
    cx.api.connect_login(SERVER, PIN)
    rules = [{"server": "/volume1/av", "local": "D:/av"}]
    assert cx.api.connect_apply_restart(SERVER + "/", rules) == {"ok": True, "reason": None}
    assert client_settings.mode() == "client"
    assert client_settings.server_url() == SERVER
    assert client_settings.server_token() == TKN
    assert client_settings.path_map() == rules
    assert cx.restart.call_count == 1
    assert config_bytes(root) == REAL_CONFIG
    assert cx.m._draft == {"origin": None, "token": None}


def test_switch_local_restart_keeps_path_map_and_player(with_handler, root):
    cx = with_handler
    (root / "config.json").write_bytes(REAL_CONFIG)
    write_client(token="T")
    assert cx.api.connect_switch_local_restart() == {"ok": True, "reason": None}
    assert config_bytes(root) == REAL_CONFIG
    assert client_settings.mode() == "local"
    data = json.loads(client_bytes())
    assert data["path_map"] == [{"server": "/volume1/av", "local": "D:/av"}]
    assert data["player"] == "C:/p.exe"
    assert data["server"] == {"url": "", "token": ""}
    assert cx.restart.call_count == 1


def test_switch_local_restart_without_handler_does_not_touch_file(cx):
    write_client()
    before = client_bytes()
    assert cx.api.connect_switch_local_restart() == {"ok": False, "reason": "restart_unavailable"}
    assert client_bytes() == before


def test_restart_handler_exception_is_swallowed_as_failure(cx):
    cx.m.set_restart_handler(Mock(side_effect=RuntimeError("x")))
    write_client()
    assert cx.api.connect_switch_local_restart()["ok"] is False


# ---------------------------------------------------------------------------
# connect_show_offline / copy_text
# ---------------------------------------------------------------------------

def test_show_offline_ignores_href_and_loads_offline_page(cx):
    write_client()
    cx.api._set_trusted_origin(SERVER)
    assert cx.api.connect_show_offline("http://evil.example/") == {"ok": True}
    cx.window.load_url.assert_called_once_with(cx.m.OFFLINE_PAGE)
    assert cx.api._offline_state["reason"] == "unreachable"
    assert cx.api.connect_show_offline() == {"ok": True}


def test_copy_text_boundaries(cx):
    assert cx.api.copy_text("a" * 65536) == {"ok": True}
    assert cx.api.copy_text("a" * 65537) == {"ok": False}
    assert cx.api.copy_text("中" * 30000) == {"ok": False}
    assert cx.api.copy_text(None) == {"ok": False}
    assert cx.api.copy_text(123) == {"ok": False}
    assert cx.copy.call_count == 1


def test_copy_text_reports_clipboard_failure(cx):
    cx.copy.return_value = False
    assert cx.api.copy_text("x") == {"ok": False}


# ---------------------------------------------------------------------------
# offline_*
# ---------------------------------------------------------------------------

OFFLINE_WRITERS = [
    ("offline_retry", ()), ("offline_save_url", (OTHER,)),
    ("offline_login", (PIN,)), ("offline_switch_local_restart", ()),
]


@pytest.mark.parametrize("name,args", OFFLINE_WRITERS)
def test_offline_methods_refuse_in_local_mode_without_writing(with_handler, root, name, args):
    cx = with_handler
    as_offline(cx)
    assert getattr(cx.api, name)(*args) == {"ok": False, "reason": "not_client"}
    assert client_bytes() is None
    assert config_bytes(root) is None
    cx.restart.assert_not_called()
    cx.window.load_url.assert_not_called()
    for mock in (cx.probe, cx.login, cx.sources, cx.preflight):
        mock.assert_not_called()


def test_offline_get_state_shape_and_text_provider(cx):
    as_offline(cx)
    write_client()
    assert cx.api.offline_get_state() == {"reason": None, "failed_url": "", "host_port": "", "texts": {}}
    cx.api._set_offline_state("unreachable", SERVER + "/?oa_token=" + TKN)
    provider = Mock(return_value={"title": "T"})
    cx.m.set_offline_text_provider(provider)
    assert cx.api.offline_get_state() == {
        "reason": "unreachable", "failed_url": SERVER, "host_port": "192.168.1.50:8765", "texts": {"title": "T"}}
    provider.assert_called_once_with("unreachable", "192.168.1.50:8765")
    provider.side_effect = RuntimeError("x")
    assert cx.api.offline_get_state()["texts"] == {}


def test_offline_retry_failure_updates_reason(cx):
    as_offline(cx)
    write_client(token="T")
    cx.api._set_offline_state("unreachable", SERVER)
    cx.preflight.return_value = client_connect.Preflight("offline", "relogin", probe_reply())
    assert cx.api.offline_retry() == {"ok": False, "reason": "relogin"}
    assert cx.api._offline_state["reason"] == "relogin"
    cx.window.load_url.assert_not_called()
    assert cx.preflight.call_args.args == (SERVER, "T")


def test_offline_retry_success_loads_entry_url_and_sets_title(cx):
    as_offline(cx)
    write_client(token="T")
    cx.api._set_offline_state("unreachable", SERVER)
    assert cx.api.offline_retry() == {"ok": True}
    assert cx.window.load_url.call_count == 1
    url = cx.window.load_url.call_args.args[0]
    assert url.startswith(SERVER + "/?oa_shell=") and "oa_mode=client" in url and "oa_token=T" in url
    title = cx.window.set_title.call_args.args[0]
    assert title == "OpenAver — 192.168.1.50"
    assert cx.api._trusted_origin == SERVER
    assert json.loads(client_bytes())["server"].get("last_ok")


def test_offline_save_url_same_origin_keeps_token_other_origin_drops_it(cx):
    as_offline(cx)
    write_client(token="T")
    cx.api._set_offline_state("unreachable", SERVER)
    assert cx.api.offline_save_url(SERVER + "/") == {"ok": True, "reason": None, "host_port": "192.168.1.50:8765"}
    assert client_settings.server_token() == "T"
    assert cx.api.offline_save_url(OTHER) == {"ok": True, "reason": None, "host_port": "192.168.1.60:8765"}
    assert client_settings.server_url() == OTHER and client_settings.server_token() == ""
    assert cx.api._trusted_origin == OTHER
    assert cx.api._offline_state["failed_url"] == OTHER
    assert client_settings.path_map() == []
    for mock in (cx.probe, cx.preflight, cx.login):
        mock.assert_not_called()


def test_offline_save_url_invalid_writes_nothing(cx):
    as_offline(cx)
    write_client()
    before = client_bytes()
    assert cx.api.offline_save_url("a b")["ok"] is False
    assert client_bytes() == before


@pytest.mark.parametrize("pin", ["", "   ", "\t\n"])
def test_offline_login_blank_pin_never_reaches_server(cx, pin):
    as_offline(cx)
    write_client()
    reply = cx.api.offline_login(pin)
    assert reply["ok"] is False
    assert cx.login.call_count == 0


def test_offline_login_success_saves_token_failure_does_not(cx):
    as_offline(cx)
    write_client()
    assert cx.api.offline_login(PIN) == {"ok": True, "reason": None}
    assert client_settings.server_token() == TKN
    cx.login.return_value = {"ok": False, "reason": "bad_pin", "token": None}
    before = client_bytes()
    assert cx.api.offline_login("0000") == {"ok": False, "reason": "bad_pin"}
    assert client_bytes() == before


def test_offline_switch_local_shares_implementation(with_handler):
    cx = with_handler
    as_offline(cx)
    write_client(token="T")
    assert cx.api.offline_switch_local_restart() == {"ok": True, "reason": None}
    assert client_settings.mode() == "local"
    assert cx.restart.call_count == 1


def test_offline_flow_runtime_observable(cx):
    """小頁 → 重試成功 → load_url 一次、標題含主機"""
    as_offline(cx)
    write_client(token="T")
    cx.api.offline_retry()
    cx.window.load_url.assert_called_once()
    assert "192.168.1.50" in cx.window.set_title.call_args.args[0]


# ---------------------------------------------------------------------------
# I-K：token／PIN 不離開 Python
# ---------------------------------------------------------------------------

def test_secrets_never_leave_python(with_handler, caplog):
    cx = with_handler
    caplog.set_level(logging.DEBUG)
    cx.probe.return_value = probe_reply(auth_required=True, authed=True)
    replies = []
    replies.append(cx.api.connect_get_state())
    replies.append(cx.api.connect_probe(SERVER))
    replies.append(cx.api.connect_login(SERVER, PIN))
    replies.append(cx.api.connect_sources(SERVER))
    replies.append(cx.api.connect_test_row("/volume1/av", "D:/av", "/volume1/av/x.mp4"))
    replies.append(cx.api.connect_save_path_map([]))
    replies.append(cx.api.connect_apply_restart(SERVER, [{"server": "/volume1/av", "local": "D:/av"}]))
    replies.append(cx.api.connect_get_state())
    replies.append(cx.api.copy_text("hello"))
    cx.api._set_offline_state("unreachable", SERVER + "/?oa_token=" + TKN)
    as_offline(cx)
    replies.append(cx.api.offline_get_state())
    replies.append(cx.api.offline_login(PIN))
    replies.append(cx.api.offline_save_url(SERVER))
    replies.append(cx.api.offline_retry())
    cx.api._page_kind = "server"
    replies.append(cx.api.connect_show_offline())
    # offline_retry 成功那一步的 load_url 引數（含入口票證）是例外，其餘 load_url 不得含
    for blob in [json.dumps(r) for r in replies] + [caplog.text] + [str(c) for c in cx.window.evaluate_js.call_args_list]:
        assert TKN not in blob and PIN not in blob
    load_args = [c.args[0] for c in cx.window.load_url.call_args_list]
    assert load_args[-1] == cx.m.OFFLINE_PAGE
    assert sum("oa_token" in a for a in load_args) == 1
    assert any(r.get("ok") for r in replies if isinstance(r, dict))


# ---------------------------------------------------------------------------
# 擷取後阻塞、遲到寫回：導航網址與票證必須同一份快照
# ---------------------------------------------------------------------------

def _blocking(cx, fn_name, ret):
    started, release = threading.Event(), threading.Event()

    def fake(*a, **k):
        started.set()
        release.wait(5)
        return ret
    setattr(cx, fn_name, Mock(side_effect=fake))
    return started, release


def test_offline_retry_does_not_navigate_when_target_changed_during_preflight(cx, monkeypatch):
    as_offline(cx)
    write_client(url=SERVER, token="TA-OLD-HOST")
    cx.api._set_offline_state("unreachable", SERVER)
    started, release = _blocking(cx, "preflight", client_connect.Preflight("ok", None, probe_reply()))
    monkeypatch.setattr(client_connect, "preflight", cx.preflight)
    out = []
    t = threading.Thread(target=lambda: out.append(cx.api.offline_retry()), daemon=True)
    t.start()
    try:
        assert started.wait(2)
        assert cx.api.offline_save_url(OTHER)["ok"] is True
    finally:
        release.set()
        t.join(3)
    assert out == [{"ok": False, "reason": "changed"}]
    cx.window.load_url.assert_not_called()
    cx.window.set_title.assert_not_called()
    assert client_settings.server_url() == OTHER
    assert cx.api._offline_state["failed_url"] == OTHER


def test_offline_login_does_not_write_token_when_origin_changed_during_login(cx, monkeypatch):
    as_offline(cx)
    write_client(url=SERVER)
    started, release = _blocking(cx, "login", {"ok": True, "reason": None, "token": TKN})
    monkeypatch.setattr(client_connect, "login", cx.login)
    out = []
    t = threading.Thread(target=lambda: out.append(cx.api.offline_login(PIN)), daemon=True)
    t.start()
    try:
        assert started.wait(2)
        cx.api.offline_save_url(OTHER)
    finally:
        release.set()
        t.join(3)
    assert out == [{"ok": False, "reason": "changed"}]
    assert client_settings.server_url() == OTHER
    assert client_settings.server_token() == ""


def test_offline_retry_entry_url_only_from_captured_snapshot(cx, monkeypatch):
    """比對通過之後、組網址之前使用者改存別台：票證只會跟原主機的 origin 一起出現"""
    as_offline(cx)
    write_client(url=SERVER, token="TA-OLD-HOST")
    cx.api._set_offline_state("unreachable", SERVER)
    real_kind = client_settings.shell_kind

    def kind_then_save():
        cx.api.offline_save_url(OTHER)
        return real_kind()
    monkeypatch.setattr(client_settings, "shell_kind", kind_then_save)
    cx.api.offline_retry()
    for call in cx.window.load_url.call_args_list:
        url = call.args[0]
        if "TA-OLD-HOST" in url:
            assert url.startswith(SERVER + "/"), url
        assert not (url.startswith(OTHER) and "TA-OLD-HOST" in url)


def test_offline_login_and_save_url_writes_are_serialised(cx, monkeypatch):
    """login 比對通過後 save_url 才開始：save_url 排在 login 寫回之後，最終是新網址配空 token"""
    as_offline(cx)
    write_client(url=SERVER)
    real = cx.m._origin_unchanged
    saver = []

    def check_then_race(origin):
        ok = real(origin)
        t = threading.Thread(target=lambda: saver.append(cx.api.offline_save_url(OTHER)), daemon=True)
        t.start()
        saver.append(t)
        t.join(0.3)  # 有鎖：save_url 卡在鎖上；無鎖：已經寫完
        return ok
    monkeypatch.setattr(cx.m, "_origin_unchanged", check_then_race)
    assert cx.api.offline_login(PIN) == {"ok": True, "reason": None}
    saver[0].join(3)
    assert client_settings.server_url() == OTHER
    assert client_settings.server_token() == ""


def test_offline_retry_reads_url_and_token_as_one_pair(cx, monkeypatch):
    """retry 路徑上 url 與 token 來自同一次 server_pair，不分兩次讀"""
    as_offline(cx)
    write_client(url=SERVER, token="TA")
    cx.api._set_offline_state("unreachable", SERVER)
    singles = Mock()
    real_pair = client_settings.server_pair
    pair_calls = []
    monkeypatch.setattr(client_settings, "server_url", lambda: singles("url") or "")
    monkeypatch.setattr(client_settings, "server_token", lambda: singles("token") or "")
    monkeypatch.setattr(client_settings, "server_pair", lambda: pair_calls.append(1) or real_pair())
    assert cx.api.offline_retry() == {"ok": True}
    singles.assert_not_called()
    assert pair_calls
    assert cx.preflight.call_args.args == (SERVER, "TA")


# ---------------------------------------------------------------------------
# 168c-T2：這台電腦的設定與更新（5 個新方法）
# ---------------------------------------------------------------------------
NEW_CALLS = {
    "local_settings_get": (),
    "local_settings_save": ({"player": "C:/x.exe"},),
    "update_check": (),
    "update_context": (),
    "update_run": (),
}
CHECK_OK = {"ok": True, "has_update": True, "current_version": "0.0.1",
            "latest_version": "9.9.9", "download_url": "https://example.test/r"}


@pytest.fixture
def ux(cx, monkeypatch):
    """新方法的外部口全換 Mock：check_latest／launch_installer／Popen"""
    cx.check = Mock(return_value=dict(CHECK_OK))
    cx.launch = Mock()
    cx.popen = Mock()
    monkeypatch.setattr(self_update, "check_latest", cx.check)
    monkeypatch.setattr(self_update, "launch_installer", cx.launch)
    monkeypatch.setattr(subprocess, "Popen", cx.popen)
    return cx


@pytest.mark.parametrize("method", sorted(NEW_CALLS))
def test_new_methods_in_local_mode_refuse_with_zero_side_effects(ux, root, method):
    cfg_before, client_before = config_bytes(root), client_bytes()
    assert client_before is None  # 本機模式：沒有 client.json
    assert getattr(ux.api, method)(*NEW_CALLS[method]) == {"ok": False, "reason": "not_client"}
    ux.popen.assert_not_called()
    ux.check.assert_not_called()
    ux.launch.assert_not_called()
    assert config_bytes(root) == cfg_before and client_bytes() == client_before


def test_local_settings_get_shape(ux):
    write_client(token=TKN, player="C:/p.exe")
    assert ux.api.local_settings_get() == {
        "ok": True, "player": "C:/p.exe", "close_action": "ask", "auto_check_update": True}


def test_local_settings_save_success_changes_only_that_key(ux):
    write_client(token=TKN)
    before = json.loads(client_bytes())
    assert ux.api.local_settings_save({"auto_check_update": False}) == {"ok": True, "reason": None}
    after = json.loads(client_bytes())
    assert after.pop("auto_check_update") is False
    assert after == before


@pytest.mark.parametrize("patch,reason", [
    ({"video_extensions": [".mp4"]}, "bad_key"),
    ({"tray_locale": "zh_TW"}, "bad_key"),
    ({"last_notified_update_version": "9.9.9"}, "bad_key"),
    ({"player": "C:/ok.exe", "video_extensions": [".mp4"]}, "bad_key"),  # 混合：整份拒、合法鍵也不寫
    ({"close_action": "explode"}, "bad_value"),
    (["player"], "bad_value"),
    (None, "bad_value"),
])
def test_local_settings_save_rejects_keys_the_page_may_not_write(ux, patch, reason):
    write_client(token=TKN)
    base = client_bytes()
    assert ux.api.local_settings_save(patch) == {"ok": False, "reason": reason}
    assert client_bytes() == base


def test_local_settings_save_reports_write_failed_when_client_json_unwritable(ux, monkeypatch):
    write_client(token=TKN)
    base = client_bytes()

    def boom(_d):
        raise OSError("read-only")

    monkeypatch.setattr(client_settings, "save_client_settings", boom)
    assert ux.api.local_settings_save({"auto_check_update": False}) == {"ok": False, "reason": "write_failed"}
    assert client_bytes() == base


def test_update_check_success_shape_uses_this_machines_version(ux):
    write_client(token=TKN)
    assert ux.api.update_check() == {
        "ok": True, "reason": None, "has_update": True, "current_version": VERSION,
        "latest_version": "9.9.9", "download_url": "https://example.test/r"}


@pytest.mark.parametrize("reason", ["timeout", "network", "bad_response"])
def test_update_check_failure_passes_reason_through(ux, reason):
    write_client(token=TKN)
    ux.check.return_value = {"ok": False, "reason": reason}
    assert ux.api.update_check() == {"ok": False, "reason": reason}


@pytest.mark.parametrize("default", [True, False])
def test_update_context_shape(ux, monkeypatch, default):
    write_client(token=TKN)
    monkeypatch.setattr(self_update, "is_default_install", lambda: default)
    assert ux.api.update_context() == {"ok": True, "is_default_path": default, "current_version": VERSION}


def test_update_run_spawns_the_shared_installer_argv(cx, monkeypatch, caplog):
    write_client(token=TKN)
    popen = Mock()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    monkeypatch.setattr(subprocess, "Popen", popen)
    cx.m.set_restart_handler(cx.restart)
    caplog.set_level(logging.DEBUG)
    assert cx.api.update_run() == {"ok": True, "reason": None}
    popen.assert_called_once_with(self_update.installer_argv("win32"), creationflags=16)
    cx.window.destroy.assert_not_called()
    cx.restart.assert_not_called()
    argv_text = " ".join(self_update.installer_argv("win32"))
    assert argv_text not in caplog.text and "irm" not in caplog.text


def test_update_run_launch_failure_reports_launch_failed_without_argv(ux, caplog):
    write_client(token=TKN)
    ux.launch.side_effect = FileNotFoundError("powershell.exe")
    caplog.set_level(logging.DEBUG)
    assert ux.api.update_run() == {"ok": False, "reason": "launch_failed"}
    assert "FileNotFoundError" in caplog.text and "powershell" not in caplog.text


def test_new_methods_never_leak_token(ux, caplog):
    write_client(token=TKN)
    caplog.set_level(logging.DEBUG)
    replies = [getattr(ux.api, m)(*a) for m, a in NEW_CALLS.items()]
    ux.launch.side_effect = RuntimeError("x")
    replies.append(ux.api.update_run())
    ux.check.return_value = {"ok": False, "reason": "network"}
    replies.append(ux.api.update_check())
    for blob in [json.dumps(r) for r in replies] + [caplog.text]:
        assert TKN not in blob
    assert all(r["ok"] for r in replies[:5])
