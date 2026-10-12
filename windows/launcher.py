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

startup_trace.mark("modules_loaded")

if __name__ == '__main__':
    setup_logging()
    startup_trace.flush()

    saved = window_state.load_state()
    local_origin = 'http://localhost:8000'
    shell_kind = 'windows' if sys.platform == 'win32' else 'mac'
    api._set_trusted_origin(client_settings.server_origin(local_origin))
    create_kwargs = dict(js_api=None, width=saved['width'], height=saved['height'])
    if saved['x'] is not None and saved['y'] is not None:
        create_kwargs['x'] = saved['x']
        create_kwargs['y'] = saved['y']

    window = webview.create_window(
        'OpenAver',
        client_settings.shell_entry_url(local_origin, shell_kind),
        **create_kwargs,
    )
    window.expose(*pywebview_api.exposed_functions())
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

    webview.start(startup, window)
