"""core/client_settings.py 單元測試（168a-T2）。"""
import json
import os
import stat

import pytest

import core.config as core_config
from core import client_settings
from core.i18n import FALLBACK_LOCALE
from core.video_extensions import DEFAULT_VIDEO_EXTENSIONS, get_video_extensions

CLIENT_URL = "http://192.168.1.177:8000/foo/"
GETTERS = {"server_url", "path_map", "player_path", "video_extensions", "close_action", "tray_locale"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(core_config, "CONFIG_PATH", cfg)
    # BE-DATA-13：資料根需定版 config 才寫得進去
    (tmp_path / ".layout.json").write_text(json.dumps({"version": 1, "complete": True}), encoding="utf-8")
    return tmp_path


def _client(tmp, **over):
    d = {"version": 1, "server": {"url": CLIENT_URL, "token": ""}, "path_map": [],
         "player": "", "video_extensions": None, "close_action": "ask", "tray_locale": None}
    d.update(over)
    (tmp / "client.json").write_text(json.dumps(d), encoding="utf-8")


def _stat(p):
    return p.read_bytes(), p.stat().st_mtime_ns


def _decoy_config(tmp):
    cfg = tmp / "config.json"
    cfg.write_text(json.dumps({
        "showcase": {"player": "C:\\old\\p.exe"},
        "scraper": {"video_extensions": [".zzz"]},
        "general": {"close_action": "exit", "locale": "ja"},
    }), encoding="utf-8")
    os.utime(cfg, ns=(1_000_000_000, 1_000_000_000))
    return cfg


@pytest.mark.parametrize("content", [None, "", "{bad", "[1]", '{"version":2,"server":{"url":"http://a:1"}}',
                                     '{"version":1,"server":{"url":""}}',
                                     '{"version":1,"server":{"url":"ftp://x"}}',
                                     '{"version":1,"server":{"url":"http://"}}',
                                     '{"version":1,"server":{"url":"http://[::1"}}',
                                     '{"version":1,"server":{"url":"http://nas:99999"}}'])
def test_mode_is_local_when_client_json_missing_or_invalid(env, content):
    if content is not None:
        (env / "client.json").write_text(content, encoding="utf-8")
    assert client_settings.mode() == "local"


def test_mode_is_client_when_valid_and_takes_effect_immediately(env):
    assert client_settings.mode() == "local"
    _client(env)
    assert client_settings.mode() == "client"
    (env / "client.json").write_text("{bad", encoding="utf-8")
    assert client_settings.mode() == "local"


@pytest.mark.parametrize("raw", [{"scraper": {"video_extensions": ["MP4", " mkv"]}}, {"scraper": {"video_extensions": "mp4"}},
                                 {"scraper": {"video_extensions": []}}])
def test_local_video_extensions_match_old_logic(env, raw):
    (env / "config.json").write_text(json.dumps(raw), encoding="utf-8")
    with open(env / "config.json", encoding="utf-8") as f:
        expected = get_video_extensions(json.load(f))
    assert client_settings.video_extensions() == expected


def test_local_missing_or_bad_config_falls_back(env):
    assert client_settings.player_path() == ""
    assert client_settings.video_extensions() == set(DEFAULT_VIDEO_EXTENSIONS)
    (env / "config.json").write_text("{bad", encoding="utf-8")
    assert client_settings.player_path() == ""
    assert client_settings.video_extensions() == set(DEFAULT_VIDEO_EXTENSIONS)


def test_local_mode_reads_do_not_touch_config_or_create_client_json(env):
    cfg = _decoy_config(env)
    before = _stat(cfg)
    assert client_settings.player_path() == "C:\\old\\p.exe"
    assert client_settings.video_extensions() == {".zzz"}
    client_settings.server_origin("http://127.0.0.1:1")
    client_settings.shell_entry_url("http://127.0.0.1:1", "windows")
    client_settings.mode(), client_settings.server_url(), client_settings.path_map()
    assert _stat(cfg) == before
    assert not (env / "client.json").exists()


def test_local_close_action_and_locale_equal_plain_load_config(env, tmp_path_factory, monkeypatch):
    cfg = _decoy_config(env)
    twin_dir = tmp_path_factory.mktemp("twin")
    twin = twin_dir / "config.json"
    twin.write_bytes(cfg.read_bytes())
    assert client_settings.close_action() == "exit"
    assert client_settings.tray_locale() == "ja"
    assert not (env / "client.json").exists()
    mine = cfg.read_bytes()
    monkeypatch.setattr(core_config, "CONFIG_PATH", twin)
    core_config.load_config()
    assert twin.read_bytes() == mine


def test_client_mode_missing_keys_never_fall_back_to_local_config(env):
    cfg = _decoy_config(env)
    before = _stat(cfg)
    (env / "client.json").write_text(
        json.dumps({"version": 1, "server": {"url": CLIENT_URL}}), encoding="utf-8")
    assert client_settings.player_path() == ""
    assert client_settings.video_extensions() == set(DEFAULT_VIDEO_EXTENSIONS)
    assert client_settings.close_action() == "ask"
    assert client_settings.tray_locale() == FALLBACK_LOCALE
    assert client_settings.path_map() == []
    assert client_settings.server_url() == CLIENT_URL
    assert _stat(cfg) == before


def test_client_mode_reads_client_values(env):
    _client(env, player="P", video_extensions=["MP4", "mkv"], close_action="tray", tray_locale="ja",
            path_map=[{"server": "/a", "local": "Z:\\a"}], future_key=1)
    assert client_settings.player_path() == "P"
    assert client_settings.video_extensions() == {".mp4", ".mkv"}
    assert client_settings.close_action() == "tray"
    assert client_settings.tray_locale() == "ja"
    assert client_settings.path_map() == [{"server": "/a", "local": "Z:\\a"}]


@pytest.mark.parametrize("bad", ["bogus", None, 3])
def test_client_close_action_invalid_defaults_ask(env, bad):
    _client(env, close_action=bad)
    assert client_settings.close_action() == "ask"


@pytest.mark.parametrize("exts", [None, [], "mp4"])
def test_client_video_extensions_degenerate_defaults(env, exts):
    _client(env, video_extensions=exts)
    assert client_settings.video_extensions() == set(DEFAULT_VIDEO_EXTENSIONS)


def test_server_origin_client_mode_strips_path(env):
    _client(env)
    assert client_settings.server_origin("http://127.0.0.1:49152") == "http://192.168.1.177:8000"


def test_server_origin_local_mode_returns_input_verbatim(env):
    assert client_settings.server_origin("http://127.0.0.1:49152/") == "http://127.0.0.1:49152/"


@pytest.mark.parametrize("client", [False, True])
def test_shell_entry_url_origin_matches_server_origin(env, client):
    if client:
        _client(env)
    local = "http://127.0.0.1:49152"
    url = client_settings.shell_entry_url(local, "windows")
    assert url == client_settings.server_origin(local) + "/?oa_shell=windows"
    assert url.startswith("http://192.168.1.177:8000/" if client else local + "/")


def test_save_client_settings_respects_data_dir_and_perms(env):
    client_settings.save_client_settings({"version": 1, "x": "日"})
    p = env / "client.json"
    assert json.loads(p.read_text(encoding="utf-8")) == {"version": 1, "x": "日"}
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_set_close_action_local_mode_matches_old_mutator(env, tmp_path_factory, monkeypatch):
    cfg = _decoy_config(env)
    twin = tmp_path_factory.mktemp("twin") / "config.json"
    twin.write_bytes(cfg.read_bytes())
    client_settings.set_close_action("tray")
    mine = cfg.read_bytes()
    monkeypatch.setattr(core_config, "CONFIG_PATH", twin)

    def _mutator(c):
        c.setdefault("general", {})["close_action"] = "tray"
    core_config.mutate_config(_mutator)
    assert twin.read_bytes() == mine
    assert not (env / "client.json").exists()


def test_set_close_action_client_mode_writes_client_json_only(env):
    cfg = _decoy_config(env)
    before = _stat(cfg)
    _client(env, player="P", future_key={"a": 1})
    old = json.loads((env / "client.json").read_text(encoding="utf-8"))
    client_settings.set_close_action("tray")
    data = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert data["close_action"] == "tray"
    assert {k: v for k, v in data.items() if k != "close_action"} == {k: v for k, v in old.items() if k != "close_action"}
    assert stat.S_IMODE((env / "client.json").stat().st_mode) == 0o600
    assert _stat(cfg) == before


def test_local_machine_keys_match_accessors():
    assert {row[3] for row in client_settings.LOCAL_MACHINE_KEYS} == GETTERS
    assert len(client_settings.LOCAL_MACHINE_KEYS) == 6
    for row in client_settings.LOCAL_MACHINE_KEYS:
        assert len(row) == 4 and callable(getattr(client_settings, row[3]))
    assert "general.server_mode" in client_settings.SERVER_OWNED_NOTE


@pytest.mark.parametrize("url,expected", [
    ("http://NAS.local:8000", "http://nas.local:8000"),
    ("https://x.example:443", "https://x.example"),
    ("http://192.168.1.180:80", "http://192.168.1.180"),
    ("HTTP://Nas.Local/", "http://nas.local"),
    ("http://[::1]:8000", "http://[::1]:8000"),
    ("http://192.168.1.177:8000/foo/", "http://192.168.1.177:8000"),
    ("ftp://x", None),
    ("http://", None),
    ("http://[::1", None),
])
def test_normalize_origin_matches_browser_location_origin(url, expected):
    assert client_settings.normalize_origin(url) == expected


def test_server_origin_client_mode_is_normalized(env):
    _client(env)
    d = json.loads((env / "client.json").read_text(encoding="utf-8"))
    d["server"]["url"] = "HTTP://NAS.local:80/x"
    (env / "client.json").write_text(json.dumps(d), encoding="utf-8")
    assert client_settings.server_origin("http://127.0.0.1:49152") == "http://nas.local"
