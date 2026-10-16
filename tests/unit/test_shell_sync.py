"""TASK-168c-T3: 殼載入同步（托盤語系＋副檔名自動抄）。全部假件，不連網。"""
import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from core import client_connect, client_settings
from core import config as core_config

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DIR = REPO_ROOT / "windows"
if str(WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(WINDOWS_DIR))

from windows import shell_sync  # noqa: E402

SERVER = "http://192.168.1.180:8000"
TOKEN = "TKN-SENTINEL-T3-SYNC"
BASELINE = ["mp4"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core_config, "CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / ".layout.json").write_text(json.dumps({"version": 1, "complete": True}), encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(shell_sync, "_state", {"synced": False, "probe": None, "in_settings": False})
    monkeypatch.setattr(shell_sync, "_run_async", lambda fn, *a: fn(*a))


def _client(**over):
    d = {"version": 1, "server": {"url": SERVER, "token": TOKEN}, "video_extensions": BASELINE}
    d.update(over)
    client_settings.save_client_settings(d)


def _fake_api(kind="server", gen=1):
    return types.SimpleNamespace(set_loaded_hook=Mock(),
                                 api=types.SimpleNamespace(_page_kind=kind, _nav_gen=gen))


def _win(lang=""):
    w = MagicMock()
    w.evaluate_js.return_value = lang
    return w


def _bytes(env):
    return {p.name: p.read_bytes() for p in env.iterdir() if p.is_file()}


@pytest.mark.parametrize("fetch_result", [
    {"ok": False, "reason": "unreachable", "extensions": []},
    {"ok": False, "reason": "timeout"},
    {"ok": True},
    TimeoutError("fetch timed out"),
])
def test_extension_copy_failure_keeps_old_value(env, monkeypatch, fetch_result):
    _client()
    before = (env / "client.json").read_bytes()
    assert client_settings.video_extensions() == {".mp4"}
    fetch = Mock(side_effect=fetch_result) if isinstance(fetch_result, Exception) else Mock(return_value=fetch_result)
    monkeypatch.setattr(client_connect, "fetch_video_extensions", fetch)
    fake = _fake_api()
    shell_sync.install(fake)
    shell_sync.on_page_loaded("server", _win(), 1)
    fetch.assert_called_once()
    assert (env / "client.json").read_bytes() == before
    assert client_settings.video_extensions() == {".mp4"}
    assert shell_sync._state["synced"] is False


def test_extension_copy_success_writes_and_sets_flag(env, monkeypatch):
    _client()
    fetch = Mock(return_value={"ok": True, "reason": None, "extensions": [".m2ts", ".mp4"]})
    monkeypatch.setattr(client_connect, "fetch_video_extensions", fetch)
    shell_sync.install(_fake_api())
    shell_sync.on_page_loaded("server", _win(), 1)
    assert client_settings.video_extensions() == {".m2ts", ".mp4"}
    assert shell_sync._state["synced"] is True


def test_extension_copy_empty_server_list_clears_old_custom(env, monkeypatch):
    """伺服器清空 ＝ 用預設；client.json 的舊自訂清單必須被清掉並立旗標。"""
    _client()
    fetch = Mock(return_value={"ok": True, "reason": None, "extensions": []})
    monkeypatch.setattr(client_connect, "fetch_video_extensions", fetch)
    shell_sync.install(_fake_api())
    shell_sync.on_page_loaded("server", _win(), 1)
    assert json.loads((env / "client.json").read_text(encoding="utf-8"))["video_extensions"] == []
    assert shell_sync._state["synced"] is True


def test_extension_copy_stale_probe_writes_nothing(env, monkeypatch):
    _client()
    before = _bytes(env)
    fake = _fake_api(gen=1)

    def fetch(url, token):   # fetch 進行中頁面換世代
        fake.api._nav_gen = 2
        return {"ok": True, "reason": None, "extensions": [".m2ts"]}

    monkeypatch.setattr(client_connect, "fetch_video_extensions", fetch)
    shell_sync.install(fake)
    shell_sync.on_page_loaded("server", _win(), 1)
    assert _bytes(env) == before
    assert shell_sync._state["synced"] is False


@pytest.mark.parametrize("kind", ["server", "offline", "other"])
@pytest.mark.parametrize("empty_url", [False, True])
def test_local_mode_is_inert(env, monkeypatch, kind, empty_url):
    if empty_url:
        client_settings.save_client_settings({"version": 1, "server": {"url": "", "token": ""}})
    (env / "config.json").write_text(json.dumps({"general": {"locale": "en"}}), encoding="utf-8")
    assert client_settings.mode() == "local"
    before = _bytes(env)
    fetch = Mock()
    monkeypatch.setattr(client_connect, "fetch_video_extensions", fetch)
    write = Mock()
    monkeypatch.setattr(client_settings, "update_local_settings", write)
    shown = Mock()
    monkeypatch.setattr(shell_sync.update_notice, "try_show", shown)
    shell_sync.install(_fake_api())
    w = _win("ja")
    shell_sync.on_page_loaded(kind, w, 1)
    w.evaluate_js.assert_not_called()
    fetch.assert_not_called()
    write.assert_not_called()
    shown.assert_not_called()
    assert _bytes(env) == before


def test_server_page_hands_off_to_update_notice(env, monkeypatch):
    _client()
    monkeypatch.setattr(client_connect, "fetch_video_extensions", Mock(return_value={"ok": False}))
    shown = Mock()
    monkeypatch.setattr(shell_sync.update_notice, "try_show", shown)
    shell_sync.install(_fake_api())
    w = _win()
    shell_sync.on_page_loaded("server", w, 1)
    shown.assert_called_once()
    assert shown.call_args.args[:2] == (w, 1)
    assert shown.call_args.args[2]() is True


def test_probe_is_wired_to_real_api(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", MagicMock())
    monkeypatch.setitem(sys.modules, "webview.dom", MagicMock())
    spec = importlib.util.spec_from_file_location("pywebview_api_shell_sync_test", WINDOWS_DIR / "pywebview_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    shell_sync.install(module)
    assert module._loaded_hook is shell_sync.on_page_loaded
    module.api._page_kind, module.api._nav_gen = "server", 5
    probe = shell_sync._state["probe"]
    assert probe(5) is True
    assert probe(6) is False
    module.api._page_kind = None
    assert probe(5) is False


# ---- 168e-T15：E7 離開設定頁重抄副檔名 ----

def _path_win(path, lang=""):
    """依 script 分流：pathname 查詢回 path（Exception 實例則拋），其餘回 lang。"""
    w = MagicMock()

    def _js(script):
        if script == "location.pathname":
            if isinstance(path, Exception):
                raise path
            return path
        return lang

    w.evaluate_js.side_effect = _js
    return w


def _setup_copy(env, monkeypatch, exts=(".m2ts", ".mp4")):
    _client()
    fetch = Mock(return_value={"ok": True, "reason": None, "extensions": list(exts)})
    monkeypatch.setattr(client_connect, "fetch_video_extensions", fetch)
    shell_sync.install(_fake_api())
    return fetch


def test_leaving_settings_page_recopies_extensions(env, monkeypatch):
    fetch = _setup_copy(env, monkeypatch)
    shell_sync.on_page_loaded("server", _path_win("/"), 1)
    assert fetch.call_count == 1 and shell_sync._state["synced"] is True
    shell_sync.on_page_loaded("server", _path_win("/settings"), 1)
    assert fetch.call_count == 1  # 進設定頁本身不重抄
    shell_sync.on_page_loaded("server", _path_win("/search"), 1)
    assert fetch.call_count == 2
    assert client_settings.video_extensions() == {".m2ts", ".mp4"}


def test_non_settings_to_non_settings_does_not_recopy(env, monkeypatch):
    fetch = _setup_copy(env, monkeypatch)
    shell_sync.on_page_loaded("server", _path_win("/"), 1)
    shell_sync.on_page_loaded("server", _path_win("/search"), 1)
    assert fetch.call_count == 1


def test_settings_to_settings_does_not_recopy(env, monkeypatch):
    fetch = _setup_copy(env, monkeypatch)
    shell_sync.on_page_loaded("server", _path_win("/settings"), 1)
    first = fetch.call_count
    shell_sync.on_page_loaded("server", _path_win("/settings/"), 1)
    assert fetch.call_count == first


def test_pathname_read_failure_neither_resets_nor_raises(env, monkeypatch):
    fetch = _setup_copy(env, monkeypatch)
    shell_sync.on_page_loaded("server", _path_win("/settings"), 1)
    assert shell_sync._state["synced"] is True and fetch.call_count == 1
    shell_sync.on_page_loaded("server", _path_win(RuntimeError("boom")), 1)
    assert shell_sync._state["synced"] is True and shell_sync._state["in_settings"] is True
    assert fetch.call_count == 1
    shell_sync.on_page_loaded("server", _path_win("/search"), 1)  # 下一次讀得到再判
    assert fetch.call_count == 2


def test_offline_resets_in_settings(env):
    _client()
    shell_sync._state["in_settings"] = True
    shell_sync.on_page_loaded("offline", _win(), 1)
    assert shell_sync._state["in_settings"] is False


# ---- 168e-T15：E6 閘門頁不污染托盤語系 ----

def test_gate_page_marker_returns_none_tray_locale_unchanged(env):
    _client(tray_locale="zh-TW")
    shell_sync.sync_tray_locale(_win(None))  # 閘門頁：JS 回 null
    assert client_settings.tray_locale() == "zh-TW"


def test_normal_page_lang_ja_still_syncs(env):
    _client(tray_locale="zh-TW")
    shell_sync.sync_tray_locale(_win("ja"))
    assert client_settings.tray_locale() == "ja"


def test_sync_sends_page_lang_js_constant(env):
    _client()
    w = _win("en")
    shell_sync.sync_tray_locale(w)
    w.evaluate_js.assert_called_once_with(shell_sync.PAGE_LANG_JS)


def test_page_lang_js_gate_marker_contract():
    js = shell_sync.PAGE_LANG_JS
    assert "dataset.oaGate==='1' ? null :" in js
    assert js.endswith("document.documentElement.lang")
