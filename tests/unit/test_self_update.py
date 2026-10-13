"""core/self_update.py 單元測試（168c-T1）。不連網、不存 GitHub 檔案。"""
import subprocess
import sys
from pathlib import Path
from unittest import mock

import httpx
import pytest

from core import self_update


@pytest.mark.parametrize("latest,current,expected", [
    ("0.10.0", "0.9.0", True),
    ("0.9.0", "0.10.0", False),
    ("0.17.8", "0.17.7", True),
    ("0.17.7", "0.17.7", False),
    ("1.0.0", "0.99.99", True),
    ("0.18.0-rc1", "0.17.7", True),
    ("", "0.17.7", False),
    ("abc", "0.17.7", False),
    ("0.17.7", "abc", False),
    (None, "0.17.7", False),
])
def test_is_newer_truth_table(latest, current, expected):
    assert self_update.is_newer(latest, current) is expected


def _transport(handler):
    return httpx.MockTransport(handler)


def test_check_latest_200_has_update():
    def h(req):
        assert req.url == httpx.URL(self_update.GITHUB_LATEST_API)
        return httpx.Response(200, json={"tag_name": "v0.10.0", "html_url": "https://x/r"})
    r = self_update.check_latest("0.9.0", transport=_transport(h))
    assert r == {"ok": True, "has_update": True, "current_version": "0.9.0",
                 "latest_version": "0.10.0", "download_url": "https://x/r"}
    # 同版本 ⇒ 不提示更新
    same = self_update.check_latest("0.9.0", transport=_transport(
        lambda req: httpx.Response(200, json={"tag_name": "v0.9.0"})))
    assert same["ok"] is True and same["has_update"] is False


def test_check_latest_404_means_no_release():
    r = self_update.check_latest("0.9.0", transport=_transport(lambda req: httpx.Response(404)))
    assert r == {"ok": True, "has_update": False, "current_version": "0.9.0"}


def _raise(exc):
    def h(req):
        raise exc
    return h


@pytest.mark.parametrize("handler,reason", [
    (_raise(httpx.ReadTimeout("t")), "timeout"),
    (_raise(httpx.ConnectError("c")), "network"),
    (lambda req: httpx.Response(500), "bad_response"),
    (lambda req: httpx.Response(403), "bad_response"),
    (lambda req: httpx.Response(200, content=b"not json"), "bad_response"),
    (lambda req: httpx.Response(200, json=[1]), "bad_response"),
])
def test_check_latest_failures(handler, reason):
    r = self_update.check_latest("0.9.0", transport=_transport(handler))
    assert r == {"ok": False, "reason": reason}


def test_installer_argv_matches_official_scripts():
    # 字面值抄自舊 web/app.py trigger_update；改 URL 必須讓這支紅
    assert self_update.installer_argv("win32") == [
        "powershell.exe", "-ExecutionPolicy", "Bypass", "-NoProfile", "-Command",
        "irm https://raw.githubusercontent.com/slive777/OpenAver/main/install.ps1 | iex"]
    assert self_update.installer_argv("darwin") == [
        "osascript", "-e",
        "tell application \"Terminal\" to do script "
        "\"curl -fsSL https://raw.githubusercontent.com/slive777/OpenAver/main/install.sh | bash\""]


@pytest.mark.parametrize("platform,kwargs", [("win32", {"creationflags": 16}), ("darwin", {})])
def test_launch_installer_win32_uses_new_console(monkeypatch, platform, kwargs):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    with mock.patch("core.self_update.subprocess.Popen") as popen:
        self_update.launch_installer()
    # win32 開新主控台；darwin 單純 Popen
    popen.assert_called_once_with(self_update.installer_argv(platform), **kwargs)


def test_launch_installer_popen_error_propagates(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    with mock.patch("core.self_update.subprocess.Popen", side_effect=OSError("boom")):
        with pytest.raises(OSError):
            self_update.launch_installer()


@pytest.mark.parametrize("platform,exe,home,expected", [
    ("win32", "/h/OpenAver/python/pythonw.exe", "/h", True),
    ("win32", "/x/Other/python/pythonw.exe", "/h", False),
    ("darwin", "/h/OpenAver/python/bin/python3", "/h", True),
    ("darwin", "/x/Other/python/bin/python3", "/h", False),
    ("linux", "/h/OpenAver/python/python3", "/h", True),
    ("linux", "/x/Other/python/python3", "/h", False),
])
def test_is_default_install(monkeypatch, platform, exe, home, expected):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "executable", exe)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path(home)))
    assert self_update.is_default_install() is expected
