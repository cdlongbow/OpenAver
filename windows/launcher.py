"""
OpenAver Windows Launcher
使用 PyWebView 連接 WSL 後端服務
"""
import os
import sys

# 確保專案根目錄在 sys.path 中
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# 確保 windows 目錄也在 sys.path 中（for pywebview_api import）
WINDOWS_DIR = os.path.dirname(os.path.abspath(__file__))
if WINDOWS_DIR not in sys.path:
    sys.path.insert(0, WINDOWS_DIR)

from core import startup_trace   # 啟動計時基準：須早於所有重 import

import webview
from pywebview_api import api, bind_events
import pywebview_api
import window_state
from core.logger import setup_logging
from core import client_settings
from windows import restart, shell_boot

startup_trace.mark("modules_loaded")

if __name__ == '__main__':
    setup_logging()
    startup_trace.flush()
    restart.wait_for_parent_exit()
    shell_boot.install_webview_token_filter()

    saved = window_state.load_state()
    local_origin = 'http://localhost:8000'
    boot = shell_boot.resolve_boot(local_origin, client_settings.shell_kind())
    startup_trace.mark("client_preflight_done")
    api._set_trusted_origin(client_settings.server_origin(local_origin))
    if boot.kind == 'offline':
        api._set_offline_state(boot.offline.reason, boot.offline.failed_url)
        api._expect_offline()
    create_kwargs = dict(js_api=None, width=saved['width'], height=saved['height'])
    if saved['x'] is not None and saved['y'] is not None:
        create_kwargs['x'] = saved['x']
        create_kwargs['y'] = saved['y']

    window = webview.create_window(boot.title, boot.url, **create_kwargs)
    window.expose(*pywebview_api.exposed_functions())
    pywebview_api.set_restart_handler(lambda: restart.request_restart(window.destroy))
    pywebview_api.set_offline_text_provider(shell_boot.offline_texts)
    startup_trace.mark("main_window_created")

    def startup(w):
        def on_first_loaded():
            startup_trace.mark("first_page_loaded")

        w.events.loaded += on_first_loaded
        bind_events(w)
        live = window_state.attach(w, saved)
        if saved['maximized']:
            try:
                w.maximize()
            except Exception:
                # Codex P2: maximize 失敗時清 live state，否則 on_resized/on_moved
                # 永遠 early-return，下次啟動仍寫回 maximized=true 形成 sticky failure
                live["maximized"] = False

    try:
        webview.start(startup, window)
    finally:
        restart.spawn_if_requested()
