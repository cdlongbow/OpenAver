"""
OpenAver Windows 伺服器生命週期與探活模組

提供 uvicorn 伺服器啟動 (run_server) 與本機 loopback 探活 (wait_for_server)。
脫離 pywebview 依賴，可在無 GUI / Linux 環境下進行獨立測試。
"""
import time
import urllib.error
import urllib.request

from core.logger import get_logger

logger = get_logger(__name__)

# 配置
CLIENT_HOST = "127.0.0.1"  # 桌面 App 自連：find_free_port、health 探活、WebView URL（loopback only）
STARTUP_TIMEOUT = 30  # 最多等待 30 秒


def wait_for_server(port, timeout=STARTUP_TIMEOUT):
    """等待伺服器啟動"""
    url = f"http://{CLIENT_HOST}:{port}/api/health"
    start_time = time.monotonic()
    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    while time.monotonic() - start_time < timeout:
        try:
            with _opener.open(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionRefusedError):
            pass
        time.sleep(0.2)

    return False


def run_server(port, debug_mode=False):
    """在背景執行 uvicorn 伺服器"""
    import uvicorn
    from web.app import app

    # Debug 模式顯示完整 HTTP 請求 log
    if debug_mode:
        log_level = "debug"
        access_log = True
    else:
        log_level = "warning"
        access_log = False

    config = uvicorn.Config(
        app,
        host=CLIENT_HOST,
        port=port,
        log_level=log_level,
        access_log=access_log,
    )
    server = uvicorn.Server(config)
    server.run()
