"""windows/shell_boot.py 單元測試（168b-T5a）。"""
import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from core import client_connect, client_settings
from windows import shell_boot

ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "TKN-SENTINEL-9"
ORIGIN = "http://127.0.0.1:8000"
SERVER = "http://192.168.1.180:8000"


@pytest.fixture(autouse=True)
def _data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _clean_filters():
    def _strip():
        lg = logging.Logger.manager.getLogger("pywebview")
        for f in list(lg.filters):
            if type(f).__name__ == "_TokenRedactFilter":
                lg.removeFilter(f)
    _strip()
    yield
    _strip()


def _client_json(tmp_path):
    client_settings.save_client_settings(
        {"version": 1, "server": {"url": SERVER, "token": SENTINEL}})


# ---- resolve_boot ----

def test_resolve_boot_local_never_touches_network(monkeypatch, tmp_path):
    boom = Mock(side_effect=AssertionError("local mode must not touch network"))
    for name in ("preflight", "probe", "login", "fetch_sources"):
        monkeypatch.setattr(client_connect, name, boom)
    monkeypatch.setattr(client_settings, "touch_last_ok", boom)
    boot = shell_boot.resolve_boot(ORIGIN, "windows")
    assert boot.kind == "local"
    assert boot.url == client_settings.shell_entry_url(ORIGIN, "windows")
    assert boot.offline is None
    assert boot.title == "OpenAver"
    assert not (tmp_path / "client.json").exists()
    boom.assert_not_called()


def test_resolve_boot_client_ok(monkeypatch, tmp_path):
    _client_json(tmp_path)
    touch = Mock()
    monkeypatch.setattr(client_settings, "touch_last_ok", touch)
    seen = {}

    def fake(url, token):
        seen["args"] = (url, token)
        return client_connect.Preflight("ok", None, {})

    monkeypatch.setattr(client_connect, "preflight", fake)
    boot = shell_boot.resolve_boot(ORIGIN, "windows")
    assert seen["args"] == (SERVER, SENTINEL)
    assert boot.kind == "client"
    assert f"oa_token={SENTINEL}" in boot.url
    assert "192.168.1.180" in boot.title
    assert boot.offline is None
    touch.assert_called_once()


@pytest.mark.parametrize("reason", ["unreachable", "lan_forbidden", "incompatible", "relogin"])
def test_resolve_boot_offline_reason_follows_preflight(monkeypatch, tmp_path, reason):
    _client_json(tmp_path)
    touch = Mock()
    monkeypatch.setattr(client_settings, "touch_last_ok", touch)
    monkeypatch.setattr(client_connect, "preflight",
                        lambda url, token: client_connect.Preflight("offline", reason, {}))
    boot = shell_boot.resolve_boot(ORIGIN, "windows")
    assert boot.kind == "offline"
    assert boot.url == shell_boot.OFFLINE_PAGE
    assert boot.offline.reason == reason
    assert boot.offline.failed_url == SERVER
    assert SENTINEL not in repr(boot)
    touch.assert_not_called()


# ---- offline_texts ----

@pytest.mark.parametrize("reason", ["unreachable", "lan_forbidden", "incompatible", "relogin", "weird"])
def test_offline_texts_complete(reason):
    texts = shell_boot.offline_texts(reason, "192.168.1.180:8000")
    assert set(texts) == {"message", "url_label", "retry", "retrying", "switch_local",
                          "password_label", "submit", "bad_url", "bad_pin",
                          "login_failed", "retry_failed"}
    for v in texts.values():
        assert isinstance(v, str) and v and not v.startswith("[") and "[desktop." not in v
    assert "{host}" not in texts["message"]
    if reason in ("unreachable", "lan_forbidden", "incompatible"):
        assert "192.168.1.180:8000" in texts["message"]


def test_offline_texts_unknown_reason_falls_back_to_unreachable():
    assert (shell_boot.offline_texts("weird", "h:1")["message"]
            == shell_boot.offline_texts("unreachable", "h:1")["message"])


def test_zh_tw_new_keys_present():
    data = json.loads((ROOT / "locales" / "zh_TW.json").read_text(encoding="utf-8"))
    off = data["desktop"]["offline"]
    assert set(off["message"]) == {"unreachable", "lan_forbidden", "incompatible", "relogin"}
    for k in ("url_label", "retry", "retrying", "switch_local", "password_label", "submit",
              "bad_url", "bad_pin", "login_failed", "retry_failed"):
        assert off[k]
    assert data["desktop"]["restart"]["spawn_failed"]


# ---- token filter ----

def test_webview_logger_never_emits_oa_token(caplog):
    shell_boot.install_webview_token_filter()
    shell_boot.install_webview_token_filter()
    lg = logging.Logger.manager.getLogger("pywebview")
    assert sum(type(f).__name__ == "_TokenRedactFilter" for f in lg.filters) == 1
    caplog.set_level(logging.DEBUG, logger="pywebview")
    url = f"{SERVER}/?oa_shell=windows&oa_mode=client&oa_token={SENTINEL}&x=1"
    lg.debug(f"Loading URL: {url}")
    lg.debug("Loading URL: %s", url)
    lg.debug("Loading URL: %(u)s", {"u": url})
    lg.debug("no ticket here %s", "plain")
    assert SENTINEL not in caplog.text
    for r in caplog.records:
        assert SENTINEL not in r.getMessage()
    assert "oa_token=<redacted>" in caplog.text
    assert "no ticket here plain" in caplog.text
    assert "&x=1" in caplog.text


# ---- OFFLINE_PAGE / .gitignore ----

def test_offline_page_not_gitignored():
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", "windows/offline/offline.html"],
                       cwd=ROOT, capture_output=True, text=True, check=False)
    assert r.returncode == 1, f"rc={r.returncode} stderr={r.stderr!r}"


def test_offline_page_exists_and_is_local_url():
    from webview.util import is_local_url
    assert os.path.isfile(shell_boot.OFFLINE_PAGE)
    assert is_local_url(shell_boot.OFFLINE_PAGE)


def test_offline_page_equals_pywebview_api_constant(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", MagicMock())
    monkeypatch.setitem(sys.modules, "webview.dom", MagicMock())
    spec = importlib.util.spec_from_file_location(
        "pywebview_api_offline_const", ROOT / "windows" / "pywebview_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.OFFLINE_PAGE == shell_boot.OFFLINE_PAGE


# ---- 168e-T15 E44：小頁文案跟隨托盤語系 ----

def _fake_en_locale(monkeypatch, tree):
    import core.i18n as i18n
    real = i18n.load_locale

    def fake(lang):
        return tree if lang == "en" else real(lang)

    monkeypatch.setattr(i18n, "load_locale", fake)


def test_offline_texts_follow_tray_locale_en(monkeypatch):
    names = ("url_label", "retry", "retrying", "switch_local", "password_label", "submit",
             "bad_url", "bad_pin", "login_failed", "retry_failed")
    tree = {"desktop": {"offline": {"message": {k: f"EN-{k} {{host}}" for k in
                                                ("unreachable", "lan_forbidden", "incompatible", "relogin")},
                                    **{n: f"EN-{n}" for n in names}}}}
    _fake_en_locale(monkeypatch, tree)
    monkeypatch.setattr(client_settings, "tray_locale", lambda: "en")
    texts = shell_boot.offline_texts("unreachable", "h:1")
    assert texts["message"] == "EN-unreachable h:1"
    assert texts["retry"] == "EN-retry"


def test_offline_texts_en_missing_keys_fall_back_to_zh_tw(monkeypatch):
    monkeypatch.setattr(client_settings, "tray_locale", lambda: "en")
    zh = shell_boot.offline_texts("unreachable", "h:1")
    monkeypatch.setattr(client_settings, "tray_locale", lambda: "zh-TW")
    assert zh == shell_boot.offline_texts("unreachable", "h:1")
    assert all(not v.startswith("[") for v in zh.values())
