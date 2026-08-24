"""
TASK-130a-T1: windows/health_probe.py 邊界與獨立性契約測試

驗證：
1. windows.health_probe 在無 webview 套件的環境下可獨立 import。
2. import windows.health_probe 不會拉起 FastAPI (web.app)。
3. windows/health_probe.py 單向依賴，不 import standalone。
4. 探活 opener 顯式使用 ProxyHandler({})，不讀取系統/環境代理。
5. 全檔無 urllib.request.urlopen。
6. 使用 time.monotonic()，全檔無 time.time()。
"""
import ast
import pathlib
import subprocess
import sys
import threading
import urllib.request

import pytest

HEALTH_PROBE_PATH = pathlib.Path(__file__).parents[2] / "windows" / "health_probe.py"


@pytest.fixture
def alive_thread():
    """一個活著的 daemon thread（wait_for_server 只會對它呼叫 is_alive()）。

    TASK-130a-T3 起 `wait_for_server` 的 `server_thread` 是必填參數且**沒有預設值**
    （刻意的：給 None 預設值等於開一條永遠回不了 PROBE_THREAD_DIED 的路徑）。
    這裡用真 thread 而不是 stub，是因為「忘了 start() 的 thread 也回報 is_alive() == False」
    正是這支 API 最容易寫出假 PROBE_THREAD_DIED 的地方——用真的才測得到那個陷阱。
    """
    stop = threading.Event()

    def _spin():
        stop.wait(60)

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    assert t.is_alive()
    yield t
    stop.set()
    t.join(timeout=5)


def test_health_probe_imports_without_webview():
    """import windows.health_probe 成功（在無 webview 環境下可 import）"""
    import windows.health_probe
    assert windows.health_probe is not None


def test_importing_health_probe_does_not_pull_in_fastapi_app():
    """在乾淨的 subprocess 中 import windows.health_probe，確認 web.app 未被載入"""
    code = (
        "import sys, windows.health_probe; "
        "assert 'web.app' not in sys.modules, f'web.app in sys.modules: {list(sys.modules.keys())}'; "
        "assert 'webview' not in sys.modules, 'webview in sys.modules'; "
        "print('OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "OK" in result.stdout


def test_health_probe_does_not_import_standalone():
    """windows/health_probe.py 不得 import standalone 或 windows.standalone"""
    assert HEALTH_PROBE_PATH.exists(), f"{HEALTH_PROBE_PATH} 不存在"
    src = HEALTH_PROBE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(HEALTH_PROBE_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "standalone" and alias.name != "windows.standalone", (
                    f"health_probe.py 包含 forbidden import: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "standalone" and node.module != "windows.standalone", (
                f"health_probe.py 包含 forbidden import from: {node.module}"
            )
            for alias in node.names:
                assert alias.name != "standalone", (
                    f"health_probe.py 包含 forbidden import name: {alias.name}"
                )


def test_prober_opener_has_no_proxy_handler_with_env_proxy_set(alive_thread, monkeypatch):
    """
    驗證探活 opener 顯式配置 ProxyHandler({})，不受 http_proxy / HTTP_PROXY 環境變數干擾。
    若拿掉 ProxyHandler({})，build_opener() 預設會讀環境變數或建立無參數 ProxyHandler(proxies=None)。
    """
    assert HEALTH_PROBE_PATH.exists(), f"{HEALTH_PROBE_PATH} 不存在"
    import windows.health_probe

    captured_openers = []
    real_build_opener = urllib.request.build_opener

    def fake_build_opener(*handlers):
        opener = real_build_opener(*handlers)
        captured_openers.append((handlers, opener))
        return opener

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    monkeypatch.setenv("http_proxy", "http://127.0.0.99:9999")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.99:9999")
    monkeypatch.setenv("all_proxy", "http://127.0.0.99:9999")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.99:9999")

    # 執行 wait_for_server（timeout=0 短路：thread 活著 → 立刻走逾時分支，不發任何請求）
    # opener 在 while 迴圈之前就建好，所以 timeout=0 仍捕捉得到它。
    windows.health_probe.wait_for_server(49152, alive_thread, timeout=0)

    assert len(captured_openers) >= 1, "wait_for_server 應呼叫 urllib.request.build_opener"
    handlers, opener = captured_openers[0]

    # 必須顯式傳入 ProxyHandler({})
    proxy_handlers = [h for h in handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert proxy_handlers, "build_opener 未傳入 ProxyHandler 實例"
    assert proxy_handlers[0].proxies == {}, f"ProxyHandler.proxies 必須為空字典 {{}}，實際為: {proxy_handlers[0].proxies}"

    # 同時檢查 opener 的 handler 鏈中無 default ProxyHandler(proxies=None)
    for h in opener.handlers:
        if isinstance(h, urllib.request.ProxyHandler):
            assert h.proxies == {}, f"opener handler 鏈中的 ProxyHandler.proxies 必須為 {{}}，實際為: {h.proxies}"

    # 原始碼靜態雙重鎖定
    src = HEALTH_PROBE_PATH.read_text(encoding="utf-8")
    assert "ProxyHandler({})" in src, "windows/health_probe.py 原始碼必須包含 ProxyHandler({})"


def test_no_urlopen_in_health_probe():
    """windows/health_probe.py 全檔無 urllib.request.urlopen("""
    assert HEALTH_PROBE_PATH.exists(), f"{HEALTH_PROBE_PATH} 不存在"
    src = HEALTH_PROBE_PATH.read_text(encoding="utf-8")
    assert "urllib.request.urlopen(" not in src, (
        "windows/health_probe.py 包含 urllib.request.urlopen(，應改用 build_opener(ProxyHandler({}))"
    )
    assert "urlopen(" not in src, (
        "windows/health_probe.py 包含 urlopen(，應改用 build_opener(ProxyHandler({}))"
    )


def test_uses_monotonic_not_wall_clock():
    """windows/health_probe.py 使用 time.monotonic()，且全檔無 time.time()"""
    assert HEALTH_PROBE_PATH.exists(), f"{HEALTH_PROBE_PATH} 不存在"
    src = HEALTH_PROBE_PATH.read_text(encoding="utf-8")
    assert "time.monotonic()" in src, "windows/health_probe.py 應使用 time.monotonic()"
    assert "time.time()" not in src, "windows/health_probe.py 不得使用 time.time()"
