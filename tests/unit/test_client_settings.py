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
    mode = "client" if client else "local"
    assert url == client_settings.server_origin(local) + f"/?oa_shell=windows&oa_mode={mode}"
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


# ---------------------------------------------------------------- 168b-T1

def test_shell_kind_by_platform(monkeypatch):
    monkeypatch.setattr(client_settings.sys, "platform", "win32")
    assert client_settings.shell_kind() == "windows"
    monkeypatch.setattr(client_settings.sys, "platform", "darwin")
    assert client_settings.shell_kind() == "mac"


def test_shell_entry_url_token_rules(env):
    local = "http://127.0.0.1:49152"
    assert client_settings.shell_entry_url(local, "windows") == local + "/?oa_shell=windows&oa_mode=local"
    # 本機模式忽略 token（不外漏到本機伺服器 log）
    assert "oa_token" not in client_settings.shell_entry_url(local, "windows", token="SECRET")
    _client(env)
    url = client_settings.shell_entry_url(local, "mac", token="a b/+")
    assert url == "http://192.168.1.177:8000/?oa_shell=mac&oa_mode=client&oa_token=a%20b%2F%2B"
    assert "oa_token" not in client_settings.shell_entry_url(local, "mac")
    assert "oa_token" not in client_settings.shell_entry_url(local, "mac", token="")


@pytest.mark.parametrize("raw,expected", [
    ("192.168.1.190:8765", "http://192.168.1.190:8765"),
    ("HTTP://Host.LAN/", "http://host.lan"),
    ("http://[0:0:0:0:0:0:0:1]:8000", "http://[::1]:8000"),
    ("[2001:0db8:0000:0000:0000:0000:0000:0001]", "http://[2001:db8::1]"),
    ("https://x:443", "https://x"),
    ("http://x:80/a/b?q=1#f", "http://x"),
    ("  nas.local:8000  ", "http://nas.local:8000"),
    ("ftp://x", None), ("http://", None), ("http://u:p@x", None), ("", None), ("a b", None),
    ("http://[::1", None), (None, None), (5, None),
])
def test_canonical_server_url_truth_table(raw, expected):
    got = client_settings.canonical_server_url(raw)
    assert got == expected
    if got is not None:
        assert client_settings.normalize_origin(got) == got


@pytest.mark.parametrize("url,with_port,expected", [
    ("http://192.168.1.190:8765", False, "192.168.1.190"),
    ("http://192.168.1.190:8765", True, "192.168.1.190:8765"),
    ("http://nas.local", True, "nas.local"),
    ("https://nas.local:443/x", True, "nas.local"),
    ("http://[::1]:8000", False, "[::1]"),
    ("http://[::1]:8000", True, "[::1]:8000"),
    ("http://[2001:db8::1]", True, "[2001:db8::1]"),
])
def test_display_host(url, with_port, expected):
    assert client_settings.display_host(url, with_port=with_port) == expected


def test_apply_connection_creates_client_json_0600(env):
    client_settings.apply_connection("http://192.168.1.190:8765", "T", [])
    p = env / "client.json"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert client_settings.mode() == "client"
    assert client_settings.server_token() == "T"
    assert client_settings.server_url() == "http://192.168.1.190:8765"
    assert client_settings.path_map() == []


def test_apply_connection_migrates_local_settings_once(env):
    cfg = _decoy_config(env)
    local_player = client_settings.player_path()
    local_exts = client_settings.video_extensions()
    local_close = client_settings.close_action()
    local_locale = client_settings.tray_locale()
    # 本機 close_action()／tray_locale() 走 load_config()（既有行為，會補齊預設鍵）；基準取在 apply 之前
    os.utime(cfg, ns=(1_000_000_000, 1_000_000_000))
    before = _stat(cfg)
    client_settings.apply_connection("http://192.168.1.190:8765", "T", None)
    data = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert data["player"] == "C:\\old\\p.exe"
    assert data["video_extensions"] == [".zzz"]
    assert data["close_action"] == "exit"
    assert data["tray_locale"] == "ja"
    # I-M：切換前後回值相同
    assert client_settings.mode() == "client"
    assert client_settings.player_path() == local_player
    assert client_settings.video_extensions() == local_exts
    assert client_settings.close_action() == local_close
    assert client_settings.tray_locale() == local_locale
    assert _stat(cfg) == before


def test_apply_connection_migration_does_not_overwrite_existing(env):
    _decoy_config(env)
    _client(env, player="P", close_action="tray")
    # 已是 client 模式 → 不遷移也不覆蓋
    client_settings.apply_connection("http://192.168.1.190:8765", "T", None)
    data = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert data["player"] == "P" and data["close_action"] == "tray"
    assert data["tray_locale"] is None


def test_migrate_local_settings_fills_only_missing(env):
    _decoy_config(env)
    d = client_settings.migrate_local_settings({"player": "P", "close_action": "", "video_extensions": []})
    assert d["player"] == "P"
    assert d["close_action"] == "exit"
    assert d["video_extensions"] == [".zzz"]
    assert d["tray_locale"] == "ja"


def test_migrate_local_settings_bad_or_missing_config(env):
    assert client_settings.migrate_local_settings({}) == {}
    (env / "config.json").write_text("{bad", encoding="utf-8")
    assert client_settings.migrate_local_settings({"player": "P"}) == {"player": "P"}


def test_apply_connection_does_not_migrate_when_already_client(env):
    _decoy_config(env)
    _client(env)
    client_settings.apply_connection("http://192.168.1.190:8765", "T", None)
    data = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert data["player"] == "" and data["close_action"] == "ask"


def test_clear_connection_then_apply_keeps_preserved_keys(env):
    _client(env, player="P", close_action="tray", path_map=[{"server": "/a", "local": "Z:\\a"}])
    client_settings.clear_connection()
    assert client_settings.mode() == "local"
    data = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert data["server"] == {"url": "", "token": ""}
    assert data["player"] == "P" and "path_map" in data
    client_settings.apply_connection("http://192.168.1.190:8765", "T2", None)
    assert client_settings.mode() == "client"
    assert client_settings.player_path() == "P"
    assert client_settings.close_action() == "tray"
    assert client_settings.path_map() == [{"server": "/a", "local": "Z:\\a"}]


def test_apply_connection_path_map_none_keeps_list_replaces(env):
    _client(env, path_map=[{"server": "/a", "local": "Z:\\a"}])
    client_settings.apply_connection("http://192.168.1.190:8765", "T", None)
    assert client_settings.path_map() == [{"server": "/a", "local": "Z:\\a"}]
    client_settings.apply_connection("http://192.168.1.190:8765", "T", [{"server": "/b", "local": "Y:\\b"}])
    assert client_settings.path_map() == [{"server": "/b", "local": "Y:\\b"}]


def test_apply_connection_canonicalizes_url(env):
    client_settings.apply_connection("HTTP://Nas.LAN:80/x", "T", [])
    assert client_settings.server_url() == "http://nas.lan"


def test_local_mode_mutators_are_noops(env):
    cfg = _decoy_config(env)
    before = _stat(cfg)
    client_settings.touch_last_ok()
    client_settings.save_path_map([{"server": "/a", "local": "Z:\\a"}])
    assert client_settings.server_token() == ""
    assert client_settings.server_last_ok() is None
    assert not (env / "client.json").exists()
    assert _stat(cfg) == before


def test_save_path_map_filters_blank_rows_and_touch_last_ok(env):
    _client(env)
    client_settings.save_path_map([{"server": "/a", "local": "Z:\\a"}, {"server": " ", "local": "x"},
                                   {"server": "/b", "local": ""}, {"server": "/c"}])
    assert client_settings.path_map() == [{"server": "/a", "local": "Z:\\a"}]
    assert client_settings.server_last_ok() is None
    client_settings.touch_last_ok()
    last = client_settings.server_last_ok()
    assert isinstance(last, str) and last.endswith(("Z", "+00:00"))
    assert client_settings.mode() == "client"


def test_apply_connection_never_touches_config(env):
    cfg = _decoy_config(env)
    before = _stat(cfg)
    client_settings.apply_connection("http://192.168.1.190:8765", "T", [])
    client_settings.clear_connection()
    assert _stat(cfg) == before
