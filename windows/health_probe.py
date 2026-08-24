"""
OpenAver Windows 伺服器生命週期與探活模組

提供 uvicorn 伺服器啟動 (run_server) 與本機 loopback 探活 (wait_for_server)。
脫離 pywebview 依賴，可在無 GUI / Linux 環境下進行獨立測試。
"""
import http.client
import time
import urllib.error
import urllib.request

from core.logger import get_logger

logger = get_logger(__name__)

# 配置
CLIENT_HOST = "127.0.0.1"  # 桌面 App 自連：find_free_port、health 探活、WebView URL（loopback only）
STARTUP_TIMEOUT = 30  # 最多等待 30 秒

PROBE_OK = "ok"
PROBE_TIMEOUT = "timeout"
PROBE_THREAD_DIED = "thread_died"


def wait_for_server(port, server_thread, timeout=STARTUP_TIMEOUT) -> str:
    """等待伺服器啟動；回傳 PROBE_OK / PROBE_TIMEOUT / PROBE_THREAD_DIED。"""
    url = f"http://{CLIENT_HOST}:{port}/api/health"
    start_time = time.monotonic()
    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last_exc = None

    while True:
        # 先查 thread 存活，再查逾時（死掉 × 已逾時 → thread_died）
        if not server_thread.is_alive():
            if last_exc is not None:
                logger.warning(
                    "伺服器 thread 已中止，最後一次探活失敗：%s: %s",
                    type(last_exc).__name__,
                    last_exc,
                )
            else:
                logger.warning("伺服器 thread 已中止")
            return PROBE_THREAD_DIED

        if time.monotonic() - start_time >= timeout:
            if last_exc is not None:
                logger.warning("探活未成功，最後一次失敗：%s: %s", type(last_exc).__name__, last_exc)
            return PROBE_TIMEOUT

        try:
            with _opener.open(url, timeout=1) as response:
                if response.status == 200:
                    return PROBE_OK
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, http.client.HTTPException) as exc:
            last_exc = exc
        time.sleep(0.2)


def format_startup_message(result, port) -> str:
    """依探活結局產出啟動失敗文案（純函式；不含原始例外）。"""
    if result == PROBE_OK:
        return ""
    if result == PROBE_THREAD_DIED:
        return (
            "伺服器程序已中止，無法完成啟動。\n\n"
            "請查看 debug.log 以了解詳細原因。"
        )
    # PROBE_TIMEOUT 與值域外 → 逾時文案（fail-safe）
    return (
        f"伺服器啟動逾時（端口 {port}）。\n\n"
        "請查看 debug.log 以了解詳細原因。"
    )


def run_server(port, debug_mode=False):
    """在背景執行 uvicorn 伺服器"""
    try:
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
    except Exception:
        logger.exception("伺服器 thread 發生未預期例外")
