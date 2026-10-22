"""core/client_settings.py 單元測試（168a-T2）。"""
import json
import os
import stat
import threading

import pytest

import core.config as core_config
from core import client_settings
from core.video_extensions import get_video_extensions

CLIENT_URL = "http://192.168.1.177:8000/foo/"


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


@pytest.mark.parametrize("content", [None, "{bad"])
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


@pytest.mark.parametrize("raw", [{"scraper": {"video_extensions": ["MP4", " mkv"]}}])
def test_local_video_extensions_match_old_logic(env, raw):
    (env / "config.json").write_text(json.dumps(raw), encoding="utf-8")
    with open(env / "config.json", encoding="utf-8") as f:
        expected = get_video_extensions(json.load(f))
    assert client_settings.video_extensions() == expected


def test_client_mode_reads_client_values(env):
    _client(env, player="P", video_extensions=["MP4", "mkv"], close_action="tray", tray_locale="ja",
            path_map=[{"server": "/a", "local": "Z:\\a"}], future_key=1)
    assert client_settings.player_path() == "P"
    assert client_settings.video_extensions() == {".mp4", ".mkv"}
    assert client_settings.close_action() == "tray"
    assert client_settings.tray_locale() == "ja"
    assert client_settings.path_map() == [{"server": "/a", "local": "Z:\\a"}]


@pytest.mark.parametrize("url,expected", [
    ("http://NAS.local:8000", "http://nas.local:8000"),
    ("ftp://x", None),
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
    ("http://x:80/a/b?q=1#f", "http://x"),
    ("ftp://x", None), ("http://u:p@x", None),
])
def test_canonical_server_url_truth_table(raw, expected):
    got = client_settings.canonical_server_url(raw)
    assert got == expected
    if got is not None:
        assert client_settings.normalize_origin(got) == got


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


_MAP = [{"server": "/volume1/video", "local": "D:/video"}]


@pytest.mark.parametrize("new_url", [
    "http://192.168.1.178:8000",    # host
])
def test_apply_connection_other_origin_clears_path_map(env, new_url):
    _client(env, path_map=list(_MAP))
    assert client_settings.path_map() == _MAP
    client_settings.apply_connection(new_url, "T", None)
    assert client_settings.path_map() == []


@pytest.mark.parametrize("old_url,new_url", [
    ("http://192.168.1.177:8000/foo/", "http://192.168.1.177:8000"),
])
def test_apply_connection_same_origin_keeps_path_map(env, old_url, new_url):
    _client(env, server={"url": old_url, "token": ""}, path_map=list(_MAP))
    assert client_settings.path_map() == _MAP
    client_settings.apply_connection(new_url, "T", None)
    assert client_settings.path_map() == _MAP


@pytest.mark.parametrize("rules", [[{"server": "/b", "local": "Y:/b"}]])
def test_apply_connection_other_origin_explicit_list_written_as_is(env, rules):
    _client(env, path_map=list(_MAP))
    client_settings.apply_connection("http://192.168.1.190:8765", "T", rules)
    assert client_settings.path_map() == rules


def test_save_path_map_strips_wrapping_quotes(env):
    _client(env)
    client_settings.save_path_map([{"server": "/a", "local": '"' + r"\\nas\av" + '"'},
                                   {"server": "/b", "local": '""'}])
    assert client_settings.path_map() == [{"server": "/a", "local": r"\\nas\av"}]


def test_min_server_version_not_above_shipped_version():
    """MIN_SERVER_VERSION 是連線功能首次出貨版，不得高於本版（168b-T8）。"""
    from core.version import VERSION

    shipped = tuple(int(x) for x in VERSION.split(".")[:3])
    assert shipped >= client_settings.MIN_SERVER_VERSION


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
    ({"player": 5}, "bad_value"),
])
def test_update_local_settings_rejects_whole_patch(env, patch, reason):
    _client(env, player="old")
    cj = env / "client.json"
    before = _stat(cj)
    # 搭一個合法鍵，證明「整份拒、不寫」
    r = client_settings.update_local_settings({**patch, "close_action": patch.get("close_action", "tray")})
    assert r == {"ok": False, "reason": reason}
    assert _stat(cj) == before


@pytest.mark.parametrize("cfg,expect", [
    ({"general": {"auto_check_update": False}}, False),
])
def test_auto_check_update_local_accessor(env, cfg, expect):
    if cfg is not None:
        (env / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert client_settings.auto_check_update() is expect
    assert client_settings.last_notified_update_version() == ""


@pytest.mark.parametrize("extra,expect", [({"auto_check_update": False}, False)])
def test_auto_check_update_client_accessor_ignores_config(env, extra, expect):
    (env / "config.json").write_text(json.dumps({"general": {"auto_check_update": not expect}}), encoding="utf-8")
    _client(env, **extra)
    assert client_settings.auto_check_update() is expect
    assert client_settings.last_notified_update_version() == ""


def test_migrate_auto_check_update_false_is_kept(env):
    _cfg_bytes(env)
    assert client_settings.migrate_local_settings({})["auto_check_update"] is False


