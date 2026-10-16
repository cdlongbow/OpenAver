"""core/client_settings.py 單元測試（168a-T2）。"""
import json
import os
import stat
import threading

import pytest

import core.config as core_config
from core import client_settings
from core.i18n import FALLBACK_LOCALE
from core.video_extensions import DEFAULT_VIDEO_EXTENSIONS, get_video_extensions

CLIENT_URL = "http://192.168.1.177:8000/foo/"
GETTERS = {"server_url", "path_map", "player_path", "video_extensions", "close_action", "tray_locale",
           "auto_check_update"}


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
    assert len(client_settings.LOCAL_MACHINE_KEYS) == 7
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
    client_settings.apply_connection("http://192.168.1.177:8000", "T", None)
    assert client_settings.path_map() == [{"server": "/a", "local": "Z:\\a"}]
    client_settings.apply_connection("http://192.168.1.190:8765", "T", [{"server": "/b", "local": "Y:\\b"}])
    assert client_settings.path_map() == [{"server": "/b", "local": "Y:\\b"}]


_MAP = [{"server": "/volume1/video", "local": "D:/video"}]


@pytest.mark.parametrize("new_url", [
    "https://192.168.1.177:8000",   # scheme
    "http://192.168.1.178:8000",    # host
    "http://192.168.1.177:8001",    # port
])
def test_apply_connection_other_origin_clears_path_map(env, new_url):
    _client(env, path_map=list(_MAP))
    assert client_settings.path_map() == _MAP
    client_settings.apply_connection(new_url, "T", None)
    assert client_settings.path_map() == []


@pytest.mark.parametrize("old_url,new_url", [
    ("http://192.168.1.177:8000/foo/", "http://192.168.1.177:8000"),
    ("HTTP://192.168.1.177:8000/x/", "http://192.168.1.177:8000/"),
    ("http://nas.lan", "http://nas.lan:80"),
    ("http://nas.lan:80", "http://nas.lan"),
])
def test_apply_connection_same_origin_keeps_path_map(env, old_url, new_url):
    _client(env, server={"url": old_url, "token": ""}, path_map=list(_MAP))
    assert client_settings.path_map() == _MAP
    client_settings.apply_connection(new_url, "T", None)
    assert client_settings.path_map() == _MAP


@pytest.mark.parametrize("rules", [[], [{"server": "/b", "local": "Y:/b"}]])
def test_apply_connection_other_origin_explicit_list_written_as_is(env, rules):
    _client(env, path_map=list(_MAP))
    client_settings.apply_connection("http://192.168.1.190:8765", "T", rules)
    assert client_settings.path_map() == rules


def test_apply_connection_old_url_empty_keeps_path_map(env):
    _client(env, path_map=list(_MAP))
    client_settings.clear_connection()
    assert client_settings.mode() == "local"
    raw = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert raw["server"]["url"] == "" and raw["path_map"] == _MAP
    client_settings.apply_connection("http://192.168.1.190:8765", "T", None)
    assert client_settings.path_map() == _MAP


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


def test_save_path_map_strips_wrapping_quotes(env):
    _client(env)
    client_settings.save_path_map([{"server": "/a", "local": '"' + r"\\nas\av" + '"'},
                                   {"server": "/b", "local": '""'}])
    assert client_settings.path_map() == [{"server": "/a", "local": r"\\nas\av"}]


def test_apply_connection_never_touches_config(env):
    cfg = _decoy_config(env)
    before = _stat(cfg)
    client_settings.apply_connection("http://192.168.1.190:8765", "T", [])
    client_settings.clear_connection()
    assert _stat(cfg) == before


def test_min_server_version_not_above_shipped_version():
    """MIN_SERVER_VERSION 是連線功能首次出貨版，不得高於本版（168b-T8）。"""
    from core.version import VERSION

    shipped = tuple(int(x) for x in VERSION.split(".")[:3])
    assert shipped >= client_settings.MIN_SERVER_VERSION


def test_saved_path_map_survives_clear_connection_but_path_map_is_empty(env):
    rules = [{"server": "/a", "local": "Z:\\a"}]
    _client(env, path_map=rules)
    client_settings.clear_connection()
    assert client_settings.path_map() == []
    assert client_settings.saved_path_map() == rules


def test_saved_path_map_missing_or_malformed_is_empty(env):
    assert client_settings.saved_path_map() == []
    _client(env, path_map="oops")
    assert client_settings.saved_path_map() == []


# ───────────────────────── 168c-T1：_rmw 收斂／update_local_settings ─────────────────────────

def _cfg_bytes(tmp):
    cfg = tmp / "config.json"
    cfg.write_text(json.dumps({"general": {"auto_check_update": False}}), encoding="utf-8")
    os.utime(cfg, ns=(1_000_000_000, 1_000_000_000))
    return cfg


def test_concurrent_writers_lose_no_keys(env, monkeypatch):
    """4 個寫入器交錯寫；讀→寫縫隙在讀檔後讓出（有上限、不等別 thread），任何一鍵都不得被舊內容蓋回。"""
    _client(env)
    real_load = client_settings._load_raw
    gap = threading.Event()

    def slow_load():
        data = real_load()
        gap.wait(timeout=0.003)  # 只讓出時間片，不等別人；鎖內持有者最多多等 3ms
        return data

    monkeypatch.setattr(client_settings, "_load_raw", slow_load)
    rounds = 20
    stop = threading.Event()
    bad_reads = []

    def reader():
        path = env / "client.json"
        while not stop.is_set():
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                bad_reads.append(repr(e))

    def w_update():
        for i in range(rounds):
            client_settings.update_local_settings({"player": f"p{i}"})

    def w_touch():
        for _ in range(rounds):
            client_settings.touch_last_ok()

    def w_map():
        for i in range(rounds):
            client_settings.save_path_map([{"server": f"/s{i}", "local": f"/l{i}"}])

    def w_close():
        for i in range(rounds):
            client_settings.set_close_action(("tray", "exit")[i % 2])

    rt = threading.Thread(target=reader)
    rt.start()
    ts = [threading.Thread(target=f) for f in (w_update, w_touch, w_map, w_close)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    stop.set()
    rt.join(timeout=5)
    assert not any(t.is_alive() for t in ts)
    assert bad_reads == []
    data = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert data["player"] == f"p{rounds - 1}"
    assert data["path_map"] == [{"server": f"/s{rounds - 1}", "local": f"/l{rounds - 1}"}]
    assert data["close_action"] == "exit"
    assert data["server"].get("last_ok")


def test_update_local_settings_in_local_mode_writes_nothing(env):
    # 純本機（無 client.json）與「切回本機後 client.json 仍在、url 為空」兩種
    cfg = _cfg_bytes(env)
    cfg_before = _stat(cfg)
    assert client_settings.update_local_settings({"player": "x"}) == {"ok": False, "reason": "not_client"}
    assert not (env / "client.json").exists()
    _client(env, server={"url": "", "token": ""})
    assert client_settings.mode() == "local"
    cj = env / "client.json"
    cj_before = _stat(cj)
    assert client_settings.update_local_settings({"player": "x"}) == {"ok": False, "reason": "not_client"}
    assert _stat(cj) == cj_before and _stat(cfg) == cfg_before


def test_update_local_settings_writes_and_reports_changed(env):
    _client(env, player="old")
    r = client_settings.update_local_settings({
        "player": "  mpv  ", "close_action": "tray", "auto_check_update": False,
        "video_extensions": ["MP4", ".mkv", "mp4"], "tray_locale": "ja",
        "last_notified_update_version": "0.18.0"})
    assert r["ok"] is True
    assert set(r["changed"]) == {"player", "close_action", "auto_check_update", "video_extensions",
                                 "tray_locale", "last_notified_update_version"}
    data = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert data["player"] == "mpv" and data["close_action"] == "tray"
    assert data["auto_check_update"] is False
    assert data["video_extensions"] == [".mkv", ".mp4"]
    assert data["tray_locale"] == "ja" and data["last_notified_update_version"] == "0.18.0"
    assert client_settings.auto_check_update() is False
    assert client_settings.last_notified_update_version() == "0.18.0"
    # 只變一鍵 ⇒ changed 只含該鍵
    assert client_settings.update_local_settings({"player": "mpv", "close_action": "exit"}) == \
        {"ok": True, "changed": ["close_action"]}
    # 值相同／空 patch ⇒ changed 為空；缺鍵的 client.json 視為不同
    assert client_settings.update_local_settings({"player": "mpv", "close_action": "exit", "auto_check_update": False}) == \
        {"ok": True, "changed": []}
    assert client_settings.update_local_settings({}) == {"ok": True, "changed": []}
    _client(env)
    assert client_settings.update_local_settings({"auto_check_update": True}) == \
        {"ok": True, "changed": ["auto_check_update"]}


@pytest.mark.parametrize("patch,reason", [
    ({"nope": 1}, "bad_key"),
    ({"player": "ok", "nope": 1}, "bad_key"),
    ({"player": 5}, "bad_value"),
    ({"player": "x" * 1025}, "bad_value"),
    ({"close_action": "x"}, "bad_value"),
    ({"auto_check_update": "false"}, "bad_value"),
    ({"auto_check_update": 0}, "bad_value"),
    ({"video_extensions": [1]}, "bad_value"),
    ({"video_extensions": "mp4"}, "bad_value"),
    ({"tray_locale": "xx"}, "bad_value"),
    ({"last_notified_update_version": "1.2.x"}, "bad_value"),
    ({"last_notified_update_version": 1}, "bad_value"),
])
def test_update_local_settings_rejects_whole_patch(env, patch, reason):
    _client(env, player="old")
    cj = env / "client.json"
    before = _stat(cj)
    # 搭一個合法鍵，證明「整份拒、不寫」
    r = client_settings.update_local_settings({**patch, "close_action": patch.get("close_action", "tray")})
    assert r == {"ok": False, "reason": reason}
    assert _stat(cj) == before


def test_update_local_settings_empty_video_extensions_means_default(env):
    _client(env, video_extensions=[".zzz"])
    assert client_settings.video_extensions() == {".zzz"}
    assert client_settings.update_local_settings({"video_extensions": []}) == \
        {"ok": True, "changed": ["video_extensions"]}
    data = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert data["video_extensions"] == []
    assert client_settings.video_extensions() == set(DEFAULT_VIDEO_EXTENSIONS)


def test_update_local_settings_video_extensions_drops_blank_elements(env):
    _client(env, video_extensions=[".zzz"])
    assert client_settings.update_local_settings({"video_extensions": [""]}) == \
        {"ok": True, "changed": ["video_extensions"]}
    data = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert data["video_extensions"] == []
    assert client_settings.update_local_settings({"video_extensions": ["", "  ", "mp4"]})["ok"] is True
    data = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert data["video_extensions"] == [".mp4"]


def test_rmw_writers_do_not_create_file(env):
    client_settings.touch_last_ok()
    client_settings.clear_connection()
    client_settings.save_path_map([])
    client_settings.set_close_action("tray")  # 本機分支寫 config.json，不建 client.json
    assert not (env / "client.json").exists()
    (env / "client.json").write_text("{bad", encoding="utf-8")
    client_settings.clear_connection()
    assert (env / "client.json").read_text(encoding="utf-8") == "{bad"


@pytest.mark.parametrize("cfg,expect", [
    (None, True),
    ({"general": {}}, True),
    ({"general": {"auto_check_update": "no"}}, True),
    ({"general": {"auto_check_update": False}}, False),
    ({"general": {"auto_check_update": True}}, True),
])
def test_auto_check_update_local_accessor(env, cfg, expect):
    if cfg is not None:
        (env / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert client_settings.auto_check_update() is expect
    assert client_settings.last_notified_update_version() == ""


@pytest.mark.parametrize("extra,expect", [({}, True), ({"auto_check_update": "x"}, True),
                                          ({"auto_check_update": False}, False)])
def test_auto_check_update_client_accessor_ignores_config(env, extra, expect):
    (env / "config.json").write_text(json.dumps({"general": {"auto_check_update": not expect}}), encoding="utf-8")
    _client(env, **extra)
    assert client_settings.auto_check_update() is expect
    assert client_settings.last_notified_update_version() == ""


def test_migrate_auto_check_update_false_is_kept(env):
    _cfg_bytes(env)
    assert client_settings.migrate_local_settings({})["auto_check_update"] is False


def test_migrate_auto_check_update_does_not_overwrite(env):
    _cfg_bytes(env)
    assert client_settings.migrate_local_settings({"auto_check_update": True})["auto_check_update"] is True
    (env / "config.json").write_text(json.dumps({"general": {"auto_check_update": "x"}}), encoding="utf-8")
    assert "auto_check_update" not in client_settings.migrate_local_settings({})


def test_update_local_settings_mode_flip_between_check_and_write(env, monkeypatch):
    """模式判斷後、進鎖前被 clear_connection 切回本機 → 不得寫入已停用的 client.json。"""
    _client(env, player="old")
    real_mode = client_settings.mode
    fired = []

    def mode_then_clear():
        m = real_mode()
        if m == "client" and not fired:
            fired.append(1)
            client_settings.clear_connection()
        return m

    monkeypatch.setattr(client_settings, "mode", mode_then_clear)
    r = client_settings.update_local_settings({"player": "new", "close_action": "exit"})
    assert fired
    assert r == {"ok": False, "reason": "not_client"}
    data = json.loads((env / "client.json").read_text(encoding="utf-8"))
    assert data["player"] == "old" and data["close_action"] == "ask"
    assert data["server"]["url"] == ""
