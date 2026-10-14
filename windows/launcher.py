"""
OpenAver Windows Launcher
使用 PyWebView 連接 WSL 後端服務
"""
import contextlib
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
from core.logger import get_logger, setup_logging
from core import client_settings
from windows import cf_shell, cf_windows, restart, shell_boot, shell_sync, update_notice

startup_trace.mark("modules_loaded")

# CF 視窗的關閉攔截器看這個旗標：為真才放行（否則隱藏視窗會取消關閉、GUI 迴圈不返回）
_cf_quitting = {"v": False}


def _destroy_all_windows():
    """重啟的退出動作：關掉全部視窗（含隱藏視窗），GUI 迴圈才會返回。"""
    _cf_quitting["v"] = True      # 先放行 CF 視窗的攔截器，再逐一銷毀
    for w in list(webview.windows):
        with contextlib.suppress(Exception):
            w.destroy()


def _wire_main_closing(window, cf_set, quitting):
    """主視窗關閉＝先讓 CF 視窗放行，再銷毀它們（隱藏視窗不銷毀，視窗計數不歸零、行程殘留）。"""
    def _on_main_closing():
        quitting["v"] = True
        for cf_win in (cf_set.jl_win, cf_set.javten_win):
            if cf_win is not None:
                with contextlib.suppress(Exception):
                    cf_win.destroy()

    window.events.closing += _on_main_closing


def _cf_agent_for(cf_set, origin, token, server_remote, supported):
    agent = cf_shell.CfShellAgent(origin=origin, token=token, windows=cf_set,
                                  server_remote=server_remote, supported=supported)
    pywebview_api.set_cf_status_provider(agent.public_status)
    return cf_set, agent


def _wire_cf_shell(logger, boot, local_origin):
    """dev 殼的 CF 接線（168d CD-6）：回 ``(cf_set, cf_agent 或 None)``。

    dev 殼與伺服器是不同行程，所以本機模式也向 ``local_origin`` 抓代理設定（不讀這個行程的 config）；
    本機模式 token 一律為 None（即使 client.json 殘留 token）。離線啟動／抓不到設定＝不建窗。
    """
    if boot.kind == "offline":
        reason = "offline_boot"
    else:
        if boot.kind == "client":
            server_url, token = client_settings.server_pair()
            server_origin = client_settings.server_origin(local_origin)
        else:
            server_url, token, server_origin = local_origin, None, local_origin
        if not cf_windows.cf_shell_supported():
            return _cf_agent_for(cf_windows.CfWindowSet(), server_origin, token, False, False)
        ok, reason, eff_settings, local_direct, server_remote = cf_windows.fetch_client_cf(
            server_url, token, server_origin)
        if ok:
            cf_set = cf_windows.build_cf_windows(logger, eff_settings, local_direct)
            return _cf_agent_for(cf_set, server_origin, token, server_remote, True)
        logger.warning("CF settings unavailable (%s), CF windows not built", reason)
    pywebview_api.set_cf_status_provider(lambda: cf_windows.cf_status_static(reason))
    return cf_windows.CfWindowSet(), None


if __name__ == '__main__':
    # dev 殼不跑 web 程式碼，這個變數只影響殼端的代理判斷與 agent 的 shell 欄；
    # 只能在這裡設（模組層設值會污染 import launcher 的測試行程）
    os.environ["OPENAVER_STANDALONE"] = "1"
    setup_logging()
    logger = get_logger('launcher')
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
    pywebview_api.set_restart_handler(lambda: restart.request_restart(_destroy_all_windows))
    pywebview_api.set_offline_text_provider(shell_boot.offline_texts)
    shell_sync.install(pywebview_api)
    startup_trace.mark("main_window_created")

    cf_set, cf_agent = _wire_cf_shell(logger, boot, local_origin)
    cf_windows.attach_close_guards(cf_set, lambda: _cf_quitting["v"])
    _wire_main_closing(window, cf_set, _cf_quitting)
    if cf_agent is not None:
        cf_agent.announce()      # webview.start() 之前：首頁渲染時註冊表已有這台殼

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
        if cf_agent is not None:
            cf_agent.start()
        update_notice.start_background_check()

    try:
        webview.start(startup, window)
    finally:
        if cf_agent is not None:
            cf_agent.stop()
        restart.spawn_if_requested()
