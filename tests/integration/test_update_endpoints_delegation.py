"""伺服器端 /api/trigger-update 真的 spawn 了 self_update.installer_argv 同一份 argv（168c-T1）。"""
import subprocess
import sys
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from core import self_update
from web.app import app


@pytest.mark.parametrize("platform,expect_flags", [("win32", 16), ("darwin", None)])
def test_trigger_update_endpoint_spawns_installer_argv(monkeypatch, platform, expect_flags):
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: platform == "win32")
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: platform == "darwin")
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    with mock.patch("web.app.subprocess.Popen") as popen:
        resp = client.post("/api/trigger-update",
                           headers={"X-OpenAver-Desktop-Action": "trigger-update"})
    assert resp.status_code == 200
    assert popen.call_count == 1
    args, kwargs = popen.call_args
    assert args == (self_update.installer_argv(platform),)
    if expect_flags is None:
        assert kwargs == {}
    else:
        assert kwargs == {"creationflags": expect_flags}
