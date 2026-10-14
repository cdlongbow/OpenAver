"""CF 殼層代理（plan-168d CD-168d-3/6/7/8/9/10）。

殼（Windows／Mac 桌面 App）背景向伺服器領「抓頁／導航／開驗證視窗」工作，只執行網址屬於
JavLibrary／javten 兩站的，結果交回伺服器。本檔不碰 GUI 主緒、不建視窗、不自己導航——
一切視窗操作都在 ``PyWebViewCfTransport``（由 cf_windows 建立）裡。

執行緒模型：輪詢緒（daemon，跑 ``run()``）領到 job 就丟 worker pool 並立刻續輪詢；
worker 緒呼叫 transport 後 POST result。

安全不變式（測試守）：請求 URL 每次由 ``self._origin`` ＋固定路徑現組、不跟隨轉址、
不使用回應 body 內的任何網址；白名單只信 ``CF_SITE_ORIGINS``；token 只放 Authorization 標頭，
agent 不讀這台電腦的設定（本機模式 token 為 None ⇒ 零 Authorization）。log 不記 token／網址／內容。
"""
from __future__ import annotations

import contextlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx

from core.cf_handoff import CF_SITE_NETLOCS, CF_SITE_ORIGINS, HOLD_S
from core.cf_transport import CfChallengeRequired, CfTransportUnavailable
from core.desktop_env import desktop_kind
from core.logger import get_logger
from core.proxy_policy import cf_window_proxy_fingerprint

logger = get_logger(__name__)

POLL_PATH = '/api/cf/shell/poll'
RESULT_PATH = '/api/cf/shell/result'
BACKOFF_S = (1, 2, 4, 8, 10)
RESULT_TIMEOUT_S = 10
MAX_WORKERS = 4
_KINDS = ('is_ready', 'begin_solve', 'fetch', 'navigate_and_settle')

# 注入點：呼叫時才解析（測試可替換）
_sleep = time.sleep


def check_job(job) -> bool:
    """白名單（CD-10）：scheme＋完整 netloc 精確相等；不用 hostname／endswith／startswith。"""
    if not isinstance(job, dict):
        return False
    kind = job.get('kind')
    args = job.get('args')
    if not isinstance(kind, str) or kind not in _KINDS or not isinstance(args, dict):
        return False
    key = args.get('cache_key')
    if not isinstance(key, str) or key not in CF_SITE_ORIGINS:
        return False
    if kind == 'is_ready':
        return True
    url = args.get('origin_url' if kind == 'begin_solve' else 'url')
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    origin = urlsplit(CF_SITE_ORIGINS[key])
    return parts.scheme.lower() == origin.scheme and parts.netloc.lower() in CF_SITE_NETLOCS[key]


class CfShellAgent:
    check_job = staticmethod(check_job)

    def __init__(self, origin, token, windows, *, shell=None, server_remote=False,
                 supported=True, http_transport=None, executor=None):
        self._origin = origin
        self._token = token
        self._windows = windows
        self._shell = shell if shell is not None else ('windows' if desktop_kind() == 'windows' else 'mac')
        self._server_remote = bool(server_remote)
        self._supported = bool(supported)
        self._http_transport = http_transport
        self._executor = executor
        self._http = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._terminal = None      # None | 'server_old' | 'unauthorized'
        self._last_ok = None       # None（尚無回應）| True | False（最近一次失敗，重試中）

    # ---- HTTP ----
    def _make_client(self):
        return httpx.Client(
            transport=self._http_transport,
            follow_redirects=False,
            trust_env=self._server_remote,
        )

    def _client(self):
        with self._lock:
            if self._http is None:
                self._http = self._make_client()
            return self._http

    def _pool(self):
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
            return self._executor

    def _headers(self):
        return {'Authorization': f'Bearer {self._token}'} if self._token else {}

    def _exchange(self, path, body, timeout):
        """送一次請求並分類：回 ('ok', dict) | ('terminal', None) | ('retry', None)。"""
        try:
            resp = self._client().post(self._origin + path, json=body, headers=self._headers(), timeout=timeout)
        except Exception as e:                                       # noqa: BLE001
            logger.warning("CF shell request failed: %s", type(e).__name__)
            self._last_ok = False
            return 'retry', None
        status = resp.status_code
        if status in (404, 405):
            self._terminal = 'server_old'
            logger.warning("CF shell: server has no handoff endpoint (status=%s), poller stops", status)
            return 'terminal', None
        if status in (401, 403) or 300 <= status < 400:
            self._terminal = 'unauthorized'
            logger.warning("CF shell: server refused the shell (status=%s), poller stops", status)
            return 'terminal', None
        if status != 200:
            logger.warning("CF shell: unexpected status %s, will retry", status)
            self._last_ok = False
            return 'retry', None
        try:
            data = resp.json()
        except ValueError:
            data = None
        if not isinstance(data, dict) or data.get('ok') is not True:
            logger.warning("CF shell: unexpected response body, will retry")
            self._last_ok = False
            return 'retry', None
        return 'ok', data

    def _poll_body(self, hold):
        windows = self._windows
        transport = windows.transport
        return {
            'shell': self._shell,
            'sites': list(transport.available_sites()) if transport is not None else [],
            'applied_proxy': (cf_window_proxy_fingerprint(windows.proxy_spec)
                              if self._shell == 'windows' else None),
            'server_remote': self._server_remote,
            'hold': hold,
        }

    def _poll_once(self, hold):
        timeout = HOLD_S + 10 if hold > 0 else RESULT_TIMEOUT_S
        kind, data = self._exchange(POLL_PATH, self._poll_body(hold), timeout)
        if kind != 'ok':
            return kind
        job = data.get('job')
        if job is not None and not isinstance(job, dict):
            logger.warning("CF shell: malformed job in response, will retry")
            self._last_ok = False
            return 'retry'
        self._last_ok = True
        if job is not None:
            try:
                self._pool().submit(self._execute, job)
            except Exception as e:                                   # noqa: BLE001
                logger.warning("CF shell: could not dispatch job: %s", type(e).__name__)
        return 'ok'

    # ---- job 執行 ----
    def _execute(self, job):
        job_id = job.get('id')
        if not isinstance(job_id, str):
            logger.warning("CF shell: job without id ignored")
            return
        if not check_job(job):
            logger.warning("CF shell: job rejected (kind=%s)", job.get('kind') if isinstance(job.get('kind'), str) else '?')
            self._send_result({'id': job_id, 'ok': False, 'error': 'error', 'message': 'rejected'})
            return
        kind = job['kind']
        args = job['args']
        key = args['cache_key']
        impl = self._windows.transport
        try:
            if impl is None:
                raise CfTransportUnavailable('no CF transport')
            if kind == 'is_ready':
                value = bool(impl.is_ready(key))
            elif kind == 'begin_solve':
                impl.begin_solve(args['origin_url'], key)
                value = True
            elif kind == 'fetch':
                value = impl.fetch(args['url'], key)
            else:
                value = impl.navigate_and_settle(args['url'], key)
            if kind in ('fetch', 'navigate_and_settle') and not isinstance(value, str):
                raise TypeError('transport returned a non-string value')
            body = {'id': job_id, 'ok': True, 'value': value}
        except CfChallengeRequired as e:
            body = self._error_body(job_id, 'challenge', e)
        except CfTransportUnavailable as e:
            body = self._error_body(job_id, 'unavailable', e)
        except TimeoutError as e:
            body = self._error_body(job_id, 'timeout', e)
        except Exception as e:                                       # noqa: BLE001
            body = self._error_body(job_id, 'error', e)
        logger.info("CF shell job done: kind=%s cache_key=%s ok=%s", kind, key, body['ok'])
        self._send_result(body)

    @staticmethod
    def _error_body(job_id, error, exc):
        return {'id': job_id, 'ok': False, 'error': error, 'message': str(exc)[:500]}

    def _send_result(self, body):
        """result 送失敗只 log、不重送（伺服器端有 exec 逾時兜底）。"""
        try:
            resp = self._client().post(self._origin + RESULT_PATH, json=body, headers=self._headers(),
                                       timeout=RESULT_TIMEOUT_S)
            if resp.status_code != 200:
                logger.warning("CF shell: result post answered status %s", resp.status_code)
        except Exception as e:                                       # noqa: BLE001
            logger.warning("CF shell: result post failed: %s", type(e).__name__)

    # ---- 生命週期 ----
    def announce(self) -> bool:
        """同步 hold=0 登記一次；失敗不致命。"""
        if not self._supported or self._terminal is not None:
            return False
        return self._poll_once(0) == 'ok'

    def start(self):
        if not self._supported or self._terminal is not None:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self.run, name='cf-shell-poller', daemon=True)
            thread = self._thread
        thread.start()

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)
        with self._lock:
            executor = self._executor
        if executor is not None:
            with contextlib.suppress(Exception):
                executor.shutdown(wait=False, cancel_futures=True)

    def run(self):
        """輪詢迴圈本體：阻塞至 stop() 或終態。"""
        fails = 0
        while not self._stop.is_set() and self._terminal is None:
            outcome = self._poll_once(HOLD_S)
            if outcome == 'ok':
                fails = 0
                continue
            if outcome == 'terminal':
                break
            fails += 1
            delay = BACKOFF_S[min(fails - 1, len(BACKOFF_S) - 1)]
            _sleep(delay)
        with self._lock:
            client, self._http = self._http, None
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()

    # ---- 狀態 ----
    def public_status(self) -> dict:
        windows = self._windows
        transport = windows.transport
        sites = list(transport.available_sites()) if transport is not None else []
        proxy_note = None
        spec = windows.proxy_spec if self._shell == 'windows' else None
        spec_unusable = spec is not None and not spec.usable
        if self._shell == 'windows':
            if windows.local_direct:
                proxy_note = 'server_local_direct'
            elif spec is not None and windows.proxy_ok and not spec_unusable:
                proxy_note = 'applied'

        def _st(state, reason):
            return {'state': state, 'reason': reason, 'proxy_note': proxy_note, 'sites': sites}

        if not self._supported:
            return {'state': 'unsupported', 'reason': None, 'proxy_note': None, 'sites': []}
        if not windows.proxy_ok or spec_unusable:
            return _st('not_ready', 'proxy_unusable')
        if windows.jl_win is None and windows.javten_win is None:
            return _st('not_ready', 'no_windows')
        if self._terminal is not None:
            return _st('not_ready', self._terminal)
        if self._last_ok is False:
            return _st('not_ready', 'unreachable')
        if self._last_ok is None or not sites:
            return _st('not_ready', 'starting')
        return _st('ready', None)
