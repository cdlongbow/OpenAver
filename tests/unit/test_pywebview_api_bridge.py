"""windows/pywebview_api.py bridge 翻譯接線測試（168a-T3a）。

本機模式零回歸 + client 模式正向／反向翻譯 + uncovered/not_found 分流 + AC-168a-9（DB 不被動）。
期望值的本機路徑只用 uri_to_fs_path 現算，不借被測的 bridge helper。
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

import core.client_settings as client_settings
import core.config as core_config
from core.path_translate import Uncovered
from core.path_utils import uri_to_fs_path

URI_INPUTS = [
    "file:///C:/Users/a/x.mp4",
    "file:///D:/AV/x.mp4",
    "file://///nas/s/x.mp4",
    "file:////volume1/av/x.mp4",
    "file:///D:/AV/a%20b.mp4",
    "file:///D:/AV/a b.mp4",
    "C:\\Users\\a\\x.mp4",
    "D:/AV/x.mp4",
    "\\\\nas\\s\\x.mp4",
    "",
    "relative/x.mp4",
    "not a path ::",
]

SERVER_URI = "file:////volume1/av/x.mp4"


@pytest.fixture
def api_module(monkeypatch):
    mock_webview = MagicMock()
    mock_webview.OPEN_DIALOG = 10
    mock_webview.FOLDER_DIALOG = 20
    monkeypatch.setitem(sys.modules, "webview", mock_webview)
    monkeypatch.setitem(sys.modules, "webview.dom", MagicMock())
    spec = importlib.util.spec_from_file_location(
        "pywebview_api_bridge_test",
        Path(__file__).parent.parent.parent / "windows" / "pywebview_api.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    w = MagicMock()
    w.get_current_url.return_value = "http://127.0.0.1:8000/"
    module.set_window(w)
    module.api._seen_origin = "http://127.0.0.1:8000"
    module.api._trusted = True
    yield module
    module.set_window(None)


@pytest.fixture
def local_env(tmp_path, monkeypatch):
    """本機模式：資料根在 tmp、沒有 client.json、config.json 不存在"""
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core_config, "CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / ".layout.json").write_text(json.dumps({"version": 1, "complete": True}), encoding="utf-8")
    return tmp_path


@pytest.fixture
def client_env(local_env):
    """client 模式：/volume1/av <-> tmp/av，tmp/av 內有真檔"""
    av = local_env / "av"
    av.mkdir()
    (av / "x.mp4").write_bytes(b"v")
    (av / "doc.txt").write_bytes(b"t")
    (av / "sub").mkdir()
    (av / "sub" / "a.mp4").write_bytes(b"v")
    (av / "sub" / "b.mkv").write_bytes(b"v")
    (av / "sub" / "c.txt").write_bytes(b"t")
    other = local_env / "other"
    other.mkdir()
    (other / "y.mp4").write_bytes(b"v")
    set_client(local_env)
    return local_env


def set_client(tmp, **over):
    d = {"version": 1, "server": {"url": "http://192.168.1.177:8000/", "token": ""},
         "path_map": [{"server": "/volume1/av", "local": str(tmp / "av")}],
         "player": "", "video_extensions": None, "close_action": "ask", "tray_locale": None}
    d.update(over)
    client_settings.save_client_settings(d)


@pytest.fixture
def no_launch(api_module, monkeypatch):
    """所有「真的開檔」的出口換成 Mock；回傳 dict 供斷言零呼叫"""
    monkeypatch.setattr(sys, "platform", "win32")
    m = {
        "Popen": Mock(), "run": Mock(), "startfile": Mock(),
    }
    monkeypatch.setattr(api_module.subprocess, "Popen", m["Popen"])
    monkeypatch.setattr(api_module.subprocess, "run", m["run"])
    monkeypatch.setattr(api_module.os, "startfile", m["startfile"], raising=False)
    return m


def _assert_nothing_launched(m):
    for mock in m.values():
        mock.assert_not_called()


# ---------------------------------------------------------------------------
# oracle (a)：本機模式 bridge_resolve == uri_to_fs_path
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", URI_INPUTS)
def test_bridge_resolve_local_mode_equals_uri_to_fs_path(api_module, local_env, value):
    assert api_module.bridge_resolve(value) == uri_to_fs_path(value)  # uri-no-reverse: oracle
    assert api_module.bridge_unresolve(value) == value


def test_bridge_resolve_client_uncovered_is_not_a_string(api_module, client_env):
    got = api_module.bridge_resolve("file:////media/elsewhere/x.mp4")
    assert isinstance(got, Uncovered)
    assert not isinstance(got, str)
    back = api_module.bridge_unresolve(str(client_env / "nowhere" / "x.mp4"))
    assert isinstance(back, Uncovered)


def test_bridge_resolve_client_maps_server_to_local(api_module, client_env):
    assert api_module.bridge_resolve(SERVER_URI) == str(client_env / "av" / "x.mp4")
    assert api_module.bridge_unresolve(str(client_env / "av" / "x.mp4")) == "/volume1/av/x.mp4"


def test_path_map_is_rebuilt_every_call(api_module, client_env):
    assert not isinstance(api_module.bridge_resolve(SERVER_URI), Uncovered)
    set_client(client_env, path_map=[])
    assert isinstance(api_module.bridge_resolve(SERVER_URI), Uncovered)


# ---------------------------------------------------------------------------
# 正向：open_file / open_folder
# ---------------------------------------------------------------------------
def test_open_file_local_mode_success_and_not_found(api_module, local_env, no_launch, monkeypatch):
    video = local_env / "v.mp4"
    video.write_bytes(b"v")
    ok = api_module.api.open_file(str(video))
    assert ok == {"ok": True, "reason": None, "local_path": uri_to_fs_path(str(video)),
                  "server_path": str(video)}
    no_launch["startfile"].assert_called_once()
    # 本機模式「看起來未對映」的路徑 → not_found，不是 uncovered
    for uri in (SERVER_URI, "file:///Z:/nowhere/x.mp4"):
        r = api_module.api.open_file(uri)
        assert r["ok"] is False and r["reason"] == "not_found"
        assert r["local_path"] == uri_to_fs_path(uri)


def test_open_file_client_covered_opens_translated_path(api_module, client_env, no_launch):
    r = api_module.api.open_file(SERVER_URI)
    assert r["ok"] is True and r["reason"] is None
    assert r["local_path"] == str(client_env / "av" / "x.mp4")
    assert r["server_path"] == "/volume1/av/x.mp4"
    no_launch["startfile"].assert_called_once_with(str(client_env / "av" / "x.mp4"))


@pytest.mark.parametrize("method", ["open_file", "open_folder"])
def test_forward_uncovered_never_touches_filesystem(api_module, client_env, no_launch, monkeypatch, method):
    real_exists = api_module.os.path.exists
    exists = Mock(side_effect=real_exists)
    monkeypatch.setattr(api_module.os.path, "exists", exists)
    r = getattr(api_module.api, method)("file:////media/elsewhere/x.mp4")
    assert r["ok"] is False and r["reason"] == "uncovered"
    assert r["local_path"] is None and r["server_path"] == "/media/elsewhere/x.mp4"
    # os.path 是全域的：全套測試時 logger 檔案 handler 會呼叫 exists(*.log)，那不是被測路徑
    stray = [c for c in exists.call_args_list if not str(c.args[0]).endswith(".log")]
    assert stray == []
    _assert_nothing_launched(no_launch)


@pytest.mark.parametrize("method", ["open_file", "open_folder"])
def test_forward_uncovered_and_not_found_are_distinct(api_module, client_env, no_launch, method):
    # uncovered：路徑不在表內
    unc = getattr(api_module.api, method)("file:////media/elsewhere/gone.mp4")
    # not_found：在表內但檔不在（獨立 fixture：另一個路徑）
    nf = getattr(api_module.api, method)("file:////volume1/av/missing/gone.mp4")
    assert unc["reason"] == "uncovered" and unc["local_path"] is None
    assert nf["reason"] == "not_found"
    assert nf["local_path"] == str(client_env / "av" / "missing" / "gone.mp4")
    assert unc["reason"] != nf["reason"]
    _assert_nothing_launched(no_launch)


def test_open_file_rejects_non_video_without_launching(api_module, client_env, no_launch):
    r = api_module.api.open_file("file:////volume1/av/doc.txt")
    assert r["ok"] is False and r["reason"] == "not_video"
    assert r["local_path"] == str(client_env / "av" / "doc.txt")
    # 副檔名先於存在檢查
    r2 = api_module.api.open_file("file:////volume1/av/missing.txt")
    assert r2["reason"] == "not_video"
    _assert_nothing_launched(no_launch)


def test_open_file_rejects_non_video_local_mode(api_module, local_env, no_launch):
    exe = local_env / "evil.exe"
    exe.write_bytes(b"x")
    r = api_module.api.open_file(str(exe))
    assert r["reason"] == "not_video"
    _assert_nothing_launched(no_launch)


def test_open_file_extension_follows_user_config(api_module, local_env, no_launch):
    (local_env / "config.json").write_text(
        json.dumps({"scraper": {"video_extensions": [".xyz"]}}), encoding="utf-8")
    xyz = local_env / "a.xyz"
    xyz.write_bytes(b"x")
    mp4 = local_env / "a.mp4"
    mp4.write_bytes(b"x")
    assert api_module.api.open_file(str(xyz))["ok"] is True
    assert api_module.api.open_file(str(mp4))["reason"] == "not_video"


def test_open_file_extension_follows_client_config(api_module, client_env, no_launch):
    set_client(client_env, video_extensions=[".txt"])
    assert api_module.api.open_file("file:////volume1/av/doc.txt")["ok"] is True
    assert api_module.api.open_file(SERVER_URI)["reason"] == "not_video"


def test_open_folder_not_found_falls_back_to_parent(api_module, client_env, no_launch, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    r = api_module.api.open_folder("file:////volume1/av/sub/missing.mp4")
    assert r["ok"] is True
    # local_path 仍報原路徑，不報父層
    assert r["local_path"] == str(client_env / "av" / "sub" / "missing.mp4")
    no_launch["Popen"].assert_called_once_with(["explorer", "/select,", str(client_env / "av" / "sub")])
    r2 = api_module.api.open_folder("file:////volume1/av/nodir/missing.mp4")
    assert r2["reason"] == "not_found"


def test_open_url_still_returns_bool(api_module, local_env, no_launch):
    assert api_module.api.open_url("https://example.com") is True
    assert api_module.api.open_url("ftp://x") is False


# ---------------------------------------------------------------------------
# log 形狀
# ---------------------------------------------------------------------------
def test_refused_log_line_shape_and_failed_has_no_refused_line(api_module, client_env, no_launch, monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(api_module, "logger", mock_logger)
    api_module.api.open_file("file:////media/elsewhere/x.mp4")
    assert mock_logger.warning.call_args[0][0] == (
        "[pywebview] open_file refused reason=uncovered server='/media/elsewhere/x.mp4' local=None")
    api_module.api.open_file("file:////volume1/av/missing/gone.mp4")
    last = mock_logger.warning.call_args[0][0]
    assert "reason=not_found" in last and "server='/volume1/av/missing/gone.mp4'" in last
    # 成功路徑沒有新 warning
    mock_logger.reset_mock()
    assert api_module.api.open_file(SERVER_URI)["ok"] is True
    mock_logger.warning.assert_not_called()
    # failed：只有 logger.error，沒有 refused 行
    no_launch["startfile"].side_effect = OSError("boom")
    r = api_module.api.open_file(SERVER_URI)
    assert r["reason"] == "failed"
    mock_logger.error.assert_called_once()
    mock_logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# 反向出口
# ---------------------------------------------------------------------------
def _setup_exit(api_module, exit_name, local_paths):
    """回 (呼叫出口的 callable)；local_paths 為該次選／拖的本機路徑"""
    window = api_module.get_window()
    window.evaluate_js.reset_mock()
    if exit_name == "select_files":
        window.create_file_dialog.return_value = list(local_paths)
        return api_module.api.select_files
    if exit_name == "select_folder":
        window.create_file_dialog.return_value = [local_paths[0]]
        return api_module.api.select_folder
    if exit_name == "select_folder_path":
        window.create_file_dialog.return_value = [local_paths[0]]
        return api_module.api.select_folder_path
    if exit_name == "on_drop_file":
        ev = {"dataTransfer": {"files": [{"pywebviewFullPath": p} for p in local_paths]}}
        return lambda: api_module.on_drop(ev)
    ev = {"dataTransfer": {"files": [{"pywebviewFullPath": p} for p in local_paths]}}
    return lambda: api_module.on_drop(ev)


def _js_calls(window):
    return [c[0][0] for c in window.evaluate_js.call_args_list]


def _uncovered_calls(window):
    return [s for s in _js_calls(window) if "handleBridgeUncovered" in s]


EXITS = ["select_files", "select_folder", "select_folder_path", "on_drop_file", "on_drop_folder"]


def _unc_path(env, exit_name):
    return str(env / "other") if exit_name in ("select_folder", "select_folder_path", "on_drop_folder") \
        else str(env / "other" / "y.mp4")


@pytest.mark.parametrize("exit_name", EXITS)
def test_reverse_exits_never_emit_uncovered_path(api_module, client_env, exit_name):
    unc = _unc_path(client_env, exit_name)
    call = _setup_exit(api_module, exit_name, [unc])
    ret = call()
    window = api_module.get_window()
    blob = json.dumps(ret) + "".join(s for s in _js_calls(window) if "handleBridgeUncovered" not in s)
    assert unc not in blob and json.dumps(unc) not in blob
    notes = _uncovered_calls(window)
    assert len(notes) == 1 and json.dumps([unc]) in notes[0]
    if exit_name in ("select_folder", "select_folder_path"):
        assert ret is None
    if exit_name == "select_files":
        assert ret == []


@pytest.mark.parametrize("exit_name", EXITS)
def test_reverse_exits_covered_translate_without_notice(api_module, client_env, exit_name):
    av = client_env / "av"
    covered = {
        "select_files": [str(av / "x.mp4")],
        "select_folder": [str(av / "sub")],
        "select_folder_path": [str(av / "sub")],
        "on_drop_file": [str(av / "x.mp4")],
        "on_drop_folder": [str(av / "sub")],
    }[exit_name]
    call = _setup_exit(api_module, exit_name, covered)
    ret = call()
    window = api_module.get_window()
    assert _uncovered_calls(window) == []
    if exit_name == "select_files":
        assert ret == ["/volume1/av/x.mp4"]
    elif exit_name == "select_folder":
        assert ret["folder"] == "/volume1/av/sub"
        assert sorted(ret["files"]) == ["/volume1/av/sub/a.mp4", "/volume1/av/sub/b.mkv"]
    elif exit_name == "select_folder_path":
        assert ret == "/volume1/av/sub"
    elif exit_name == "on_drop_file":
        assert any("handlePyWebViewDrop" in s and "/volume1/av/x.mp4" in s for s in _js_calls(window))
    else:
        calls = _js_calls(window)
        assert any("handleFolderDrop" in s and json.dumps(["/volume1/av/sub"]) in s for s in calls)
        drop = [s for s in calls if "handlePyWebViewDrop" in s][0]
        assert "/volume1/av/sub/a.mp4" in drop and "c.txt" not in drop


def test_mixed_covered_and_uncovered_select_files(api_module, client_env):
    av, other = client_env / "av", client_env / "other"
    paths = [str(av / "x.mp4"), str(av / "sub" / "a.mp4"), str(av / "sub" / "b.mkv"), str(other / "y.mp4")]
    ret = _setup_exit(api_module, "select_files", paths)()
    assert ret == ["/volume1/av/x.mp4", "/volume1/av/sub/a.mp4", "/volume1/av/sub/b.mkv"]
    notes = _uncovered_calls(api_module.get_window())
    assert len(notes) == 1 and json.dumps([str(other / "y.mp4")]) in notes[0]


def test_on_drop_mixed_notifies_once(api_module, client_env):
    av, other = client_env / "av", client_env / "other"
    paths = [str(av / "x.mp4"), str(other / "y.mp4"), str(other)]
    _setup_exit(api_module, "on_drop_file", paths)()
    window = api_module.get_window()
    notes = _uncovered_calls(window)
    assert len(notes) == 1
    assert json.dumps([str(other / "y.mp4"), str(other)]) in notes[0]
    pushes = "".join(s for s in _js_calls(window) if "handleBridgeUncovered" not in s)
    assert "/volume1/av/x.mp4" in pushes and str(other) not in pushes


def test_uncovered_each_path_logged_one_line(api_module, client_env, monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(api_module, "logger", mock_logger)
    other = client_env / "other"
    _setup_exit(api_module, "select_files", [str(other / "y.mp4"), str(other / "y.mp4"), str(other / "z.mp4")])()
    lines = [c[0][0] for c in mock_logger.warning.call_args_list]
    assert len(lines) == 2  # 保序去重
    assert lines[0] == f"[pywebview] select_files refused reason=uncovered server=None local={str(other / 'y.mp4')!r}"


# 本機模式：回傳與改前逐字相同、通知零呼叫（舊邏輯留在測試內當 oracle）
def _old_listing(folder, exts):
    import os
    return [os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f)) and os.path.splitext(f)[1].lower() in exts]


def _old_drop_pushes(paths, exts):
    """改前 on_drop 的推送字串（完整 oracle）"""
    import os
    expanded, folders = [], []
    for p in paths:
        if os.path.isdir(p):
            folders.append(p)
            expanded.extend(_old_listing(p, exts))
        else:
            expanded.append(p)
    out = []
    if expanded:
        out.append(f'if(typeof handlePyWebViewDrop === "function") handlePyWebViewDrop({json.dumps(expanded)})')
    if folders:
        out.append(f'if(typeof handleFolderDrop === "function") handleFolderDrop({json.dumps(folders)})')
    return out


def _old_select_folder(folder, exts):
    return {"folder": folder, "files": _old_listing(folder, exts)}


@pytest.mark.parametrize("exit_name", EXITS)
def test_local_mode_reverse_exits_unchanged(api_module, local_env, exit_name):
    d = local_env / "lib"
    d.mkdir()
    (d / "a.mp4").write_bytes(b"v")
    (d / "b.txt").write_bytes(b"t")
    exts = client_settings.video_extensions()
    window = api_module.get_window()
    file_in = [str(d / "a.mp4"), "C:\\whatever\\z.mp4"]
    inputs = {"select_files": file_in, "select_folder": [str(d)], "select_folder_path": [str(d)],
              "on_drop_file": file_in, "on_drop_folder": [str(d)]}[exit_name]
    ret = _setup_exit(api_module, exit_name, inputs)()
    assert _uncovered_calls(window) == []  # 每次出口呼叫後立即斷言
    if exit_name == "select_files":
        assert ret == inputs
    elif exit_name == "select_folder":
        assert ret == _old_select_folder(str(d), exts)
    elif exit_name == "select_folder_path":
        assert ret == str(d)
    else:
        assert _js_calls(window) == _old_drop_pushes(inputs, exts)


def test_local_mode_empty_dialogs_unchanged(api_module, local_env):
    window = api_module.get_window()
    window.create_file_dialog.return_value = []
    assert api_module.api.select_files() == []
    assert _uncovered_calls(window) == []
    assert api_module.api.select_folder() is None
    assert _uncovered_calls(window) == []


# ---------------------------------------------------------------------------
# AC-168a-9：bridge 全部出入口跑完，DB 逐字不變
# ---------------------------------------------------------------------------
def _run_all_exits(api_module, env, covered_uri, uncovered_uri, covered_local, uncovered_local, folder_local):
    for uri in (covered_uri, uncovered_uri):
        api_module.api.open_file(uri)
        api_module.api.open_folder(uri)
    _setup_exit(api_module, "select_files", [covered_local, uncovered_local])()
    _setup_exit(api_module, "select_folder", [folder_local])()
    _setup_exit(api_module, "select_folder", [str(Path(uncovered_local).parent)])()
    _setup_exit(api_module, "select_folder_path", [folder_local])()
    _setup_exit(api_module, "select_folder_path", [str(Path(uncovered_local).parent)])()
    _setup_exit(api_module, "on_drop_file", [covered_local, uncovered_local])()
    _setup_exit(api_module, "on_drop_folder", [folder_local, str(Path(uncovered_local).parent)])()


def test_bridge_flows_leave_database_untouched(api_module, client_env, no_launch):
    from core.database.connection import get_db_path, init_db

    # 資料根＝client_env（OPENAVER_DATA_DIR），所以這就是 production get_connection() 預設連的庫
    init_db()
    db = get_db_path()
    assert db.parent == client_env
    conn = sqlite3.connect(db)
    av = "file:////volume1/av"
    conn.execute("INSERT INTO videos (path, cover_path, output_dir, sample_images) VALUES (?,?,?,?)",
                 (f"{av}/x.mp4", f"{av}/x.jpg", f"{av}/out", json.dumps([f"{av}/s1.jpg"])))
    conn.execute("INSERT INTO actresses (name, photo_fp_path) VALUES (?,?)", ("A", f"{av}/a.jpg"))
    conn.execute("INSERT INTO wishlist (number, cover_path, sample_images, preview_sample_images) VALUES (?,?,?,?)",
                 ("ABC-1", f"{av}/w.jpg", json.dumps([f"{av}/w1.jpg"]), json.dumps([f"{av}/p1.jpg"])))
    conn.execute("INSERT INTO organize_failures (key, reason, number, duplicate_target, last_failed_at) VALUES (?,?,?,?,?)",
                 (f"{av}/x.mp4", "dup", "ABC-1", f"{av}/dup.mp4", 1.0))
    conn.commit()
    for table, col in [
        ("videos", "path"), ("videos", "cover_path"), ("videos", "output_dir"), ("videos", "sample_images"),
        ("actresses", "photo_fp_path"), ("wishlist", "cover_path"), ("wishlist", "sample_images"),
        ("wishlist", "preview_sample_images"), ("organize_failures", "duplicate_target"),
    ]:
        assert conn.execute(f"SELECT {col} FROM {table}").fetchone()[0], (table, col)  # 非空，否則恆真

    def dump():
        return "\n".join(conn.iterdump())

    before = dump()
    local_av = client_env / "av"
    other = client_env / "other"
    # client 命中＋未涵蓋
    _run_all_exits(api_module, client_env, SERVER_URI, "file:////media/elsewhere/x.mp4",
                   str(local_av / "x.mp4"), str(other / "y.mp4"), str(local_av / "sub"))
    assert dump() == before
    # 本機模式（移除 client.json）：同樣跑完全部出口
    (client_env / "client.json").unlink()
    assert client_settings.mode() == "local"
    _run_all_exits(api_module, client_env, str(local_av / "x.mp4"), str(other / "missing.mp4"),
                   str(local_av / "x.mp4"), str(other / "y.mp4"), str(local_av / "sub"))
    assert dump() == before
    conn.close()


# ---------------------------------------------------------------------------
# 168e-T8: FS 呼叫計數鎖（被擋提示依對象；判斷種類不得新增任何檔案系統呼叫）
# ---------------------------------------------------------------------------
def _run_with_fs_spy(api_module, monkeypatch, call):
    """只在出口呼叫那一段包 spy：isdir／isfile／listdir 記錄後轉呼叫真函式，其餘 FS 函式被呼叫即 fail"""
    import os
    real = {"isdir": os.path.isdir, "isfile": os.path.isfile, "listdir": os.listdir, "stat": os.stat}
    seen = {"isdir": [], "isfile": [], "listdir": [], "stat": []}
    state = {"inside": 0}

    def wrap(name):
        def spy(p, *a, **k):
            seen[name].append(str(p))
            state["inside"] += 1
            try:
                return real[name](p, *a, **k)
            finally:
                state["inside"] -= 1
        return spy

    def forbid(name):
        def f(*a, **k):
            pytest.fail(f"unexpected FS call: {name}{a!r}")
        return f

    def guarded_stat(*a, **k):
        if state["inside"] == 0:
            seen["stat"].append(Path(a[0]).name)  # 設定檔讀取（修前即有），只記檔名
        return real["stat"](*a, **k)

    monkeypatch.setattr(api_module, "logger", MagicMock())
    with monkeypatch.context() as m:
        m.setattr(os.path, "isdir", wrap("isdir"))
        m.setattr(os.path, "isfile", wrap("isfile"))
        m.setattr(os, "listdir", wrap("listdir"))
        m.setattr(os.path, "exists", forbid("exists"))
        m.setattr(os.path, "islink", forbid("islink"))
        m.setattr(os, "scandir", forbid("scandir"))
        m.setattr(os, "access", forbid("access"))
        m.setattr(os, "stat", guarded_stat)
        call()
    assert set(seen["stat"]) <= {"client.json"}, seen["stat"]
    return seen


def test_reverse_exits_fs_call_set_unchanged(api_module, client_env, monkeypatch):
    av, other = client_env / "av", client_env / "other"
    # select_folder：資料夾涵蓋，列出內部檔案
    call = _setup_exit(api_module, "select_folder", [str(av / "sub")])
    s = _run_with_fs_spy(api_module, monkeypatch, call)
    assert s["listdir"] == [str(av / "sub")]
    assert len(s["isfile"]) == len(__import__("os").listdir(av / "sub"))
    assert s["isdir"] == []
    # on_drop 混合：被擋檔案＋被擋資料夾＋涵蓋資料夾
    call = _setup_exit(api_module, "on_drop_file", [str(other / "y.mp4"), str(other), str(av / "sub")])
    s = _run_with_fs_spy(api_module, monkeypatch, call)
    assert s["isdir"] == [str(other / "y.mp4"), str(other), str(av / "sub")]
    assert s["listdir"] == [str(av / "sub")]
    assert len(s["isfile"]) == len(__import__("os").listdir(av / "sub"))
    # 被擋出口不額外探測
    call = _setup_exit(api_module, "select_files", [str(other / "y.mp4")])
    s = _run_with_fs_spy(api_module, monkeypatch, call)
    assert (s["isdir"], s["isfile"], s["listdir"], set(s["stat"]) - {"client.json"}) == ([], [], [], set())
    call = _setup_exit(api_module, "select_folder", [str(other)])
    s = _run_with_fs_spy(api_module, monkeypatch, call)
    assert (s["isdir"], s["isfile"], s["listdir"], set(s["stat"]) - {"client.json"}) == ([], [], [], set())


# ---------------------------------------------------------------------------
# 168e-T8: 被擋提示的 kind（file／folder／any）
# ---------------------------------------------------------------------------
def _kind_of(note):
    """從推給 JS 的腳本字串取第二參數字面（逐字比對結尾，不用 `in`）"""
    for k in ("file", "folder", "any"):
        if note.endswith(f', "{k}")'):
            return k
    return None


def test_select_files_blocked_notifies_kind_file(api_module, client_env):
    unc = str(client_env / "other" / "y.mp4")
    _setup_exit(api_module, "select_files", [unc])()
    notes = _uncovered_calls(api_module.get_window())
    assert len(notes) == 1 and _kind_of(notes[0]) == "file"


def test_select_folder_blocked_notifies_kind_folder(api_module, client_env):
    _setup_exit(api_module, "select_folder", [str(client_env / "other")])()
    notes = _uncovered_calls(api_module.get_window())
    assert len(notes) == 1 and _kind_of(notes[0]) == "folder"


def test_select_folder_path_blocked_notifies_kind_folder(api_module, client_env):
    _setup_exit(api_module, "select_folder_path", [str(client_env / "other")])()
    notes = _uncovered_calls(api_module.get_window())
    assert len(notes) == 1 and _kind_of(notes[0]) == "folder"


def test_select_folder_covered_but_inner_video_blocked_notifies_kind_file(api_module, client_env, monkeypatch):
    sub = client_env / "av" / "sub"
    real = api_module.bridge_unresolve

    def fake(p):
        return Uncovered() if str(p).endswith("a.mp4") else real(p)

    monkeypatch.setattr(api_module, "bridge_unresolve", fake)
    ret = _setup_exit(api_module, "select_folder", [str(sub)])()
    assert ret["folder"] == "/volume1/av/sub"
    notes = _uncovered_calls(api_module.get_window())
    assert len(notes) == 1 and _kind_of(notes[0]) == "file"


def test_on_drop_only_blocked_file_notifies_kind_file(api_module, client_env):
    _setup_exit(api_module, "on_drop_file", [str(client_env / "other" / "y.mp4")])()
    assert _kind_of(_uncovered_calls(api_module.get_window())[0]) == "file"


def test_on_drop_only_blocked_folder_notifies_kind_folder(api_module, client_env):
    _setup_exit(api_module, "on_drop_folder", [str(client_env / "other")])()
    assert _kind_of(_uncovered_calls(api_module.get_window())[0]) == "folder"


def test_on_drop_mixed_file_and_folder_notifies_kind_any(api_module, client_env):
    other = client_env / "other"
    _setup_exit(api_module, "on_drop_file", [str(other / "y.mp4"), str(other)])()
    notes = _uncovered_calls(api_module.get_window())
    assert len(notes) == 1 and _kind_of(notes[0]) == "any"


def test_on_drop_covered_items_do_not_affect_kind(api_module, client_env):
    av, other = client_env / "av", client_env / "other"
    _setup_exit(api_module, "on_drop_file", [str(av / "x.mp4"), str(av / "sub"), str(other)])()
    notes = _uncovered_calls(api_module.get_window())
    assert len(notes) == 1 and _kind_of(notes[0]) == "folder"


def test_merge_uncovered_kind_pure(api_module):
    assert api_module._merge_uncovered_kind({"file"}) == "file"
    assert api_module._merge_uncovered_kind({"folder"}) == "folder"
    assert api_module._merge_uncovered_kind({"file", "folder"}) == "any"
