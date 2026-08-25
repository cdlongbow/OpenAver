"""
TASK-130a-T5: 真行為端對端測試（假 proxy 四格矩陣）

用真的 socket 證明根因修復有效：起一個「接了就 RST」的假 proxy ＋ 一個真的
HTTP server，跑「代理開／關」×「修前寫法／修後寫法」四格。

控制組（代理開 × 直呼 urllib.request.urlopen）必須真的失敗。它不是裝飾，它是
唯一能證明假 proxy 真的被走到的東西。沒有它，另外三格全綠可能只是因為假 proxy
根本沒生效（環境變數名稱寫錯、no_proxy 蓋掉、proxy 的 port 沒起來）——那種綠
什麼都沒證明。有人日後覺得「這格老是失敗很吵」把它刪掉，整支測試就變成永遠綠
的裝飾。

開發機或 CI 很可能已經設了 no_proxy=localhost,127.0.0.1 —— 那會讓 loopback
直接繞過代理，控制組就不會失敗。因此本檔對 no_proxy / NO_PROXY 一律 delenv，
絕不自行設定。

涵蓋範圍的誠實界線：
AC-1 講的兩條代理路線，**只有環境變數那條在 Linux CI 驗得到**。
登錄檔那條走 `urllib.request.getproxies_registry()`，**Windows-only，Linux 上根本不會被呼叫**。

⇒ **不得把 CI 全綠讀成「登錄檔路線也驗過了」。** 那半的證據是 plan「根因實測矩陣」那節的
真機 Windows 重現。`ProxyHandler({})` 對兩條路線都是無條件生效，所以**行為上沒有缺口，
缺的只是 CI 內的證據**。
"""
import socket
import struct
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from windows.health_probe import PROBE_OK, wait_for_server


class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal /api/health → 200 handler for the real HTTP side of the matrix."""

    def do_GET(self):
        if self.path == "/api/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


@pytest.fixture
def health_server():
    """ThreadingHTTPServer on 127.0.0.1:0 serving /api/health → 200.

    Port is OS-assigned (bind 0); teardown via yield so failures still clean up.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield {"server": server, "port": port, "url": f"http://127.0.0.1:{port}/api/health"}
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.fixture
def fake_rst_proxy():
    """Accept-then-RST listener on 127.0.0.1:0 (SO_LINGER l_onoff=1, l_linger=0).

    FIN would yield a clean EOF; RST is what reproduces ConnectionResetError.
    Accept loop must survive multiple connections (wait_for_server retries).
    """
    stop = threading.Event()
    hits = []          # 每一次真的被連上就 append 一筆；控制組靠它證明 proxy 有被走到
    hits_lock = threading.Lock()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    sock.settimeout(0.5)
    port = sock.getsockname()[1]

    def _loop():
        while not stop.is_set():
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with hits_lock:
                hits.append(1)
            try:
                conn.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_LINGER,
                    struct.pack("ii", 1, 0),
                )
            finally:
                conn.close()

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    def _hit_count():
        with hits_lock:
            return len(hits)

    yield {"port": port, "url": f"http://127.0.0.1:{port}", "hit_count": _hit_count}
    stop.set()
    try:
        sock.close()
    except OSError:
        pass
    thread.join(timeout=2)


@pytest.fixture
def alive_thread():
    """daemon thread that stays alive until fixture teardown (wait_for_server needs one)."""
    stop = threading.Event()

    def _spin():
        stop.wait(60)

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    assert t.is_alive()
    yield t
    stop.set()
    t.join(timeout=2)


def _enable_hostile_proxy(monkeypatch, proxy_url: str) -> None:
    """Point http(s)_proxy at the RST listener; strip no_proxy so loopback is not bypassed."""
    monkeypatch.setenv("http_proxy", proxy_url)
    monkeypatch.setenv("HTTP_PROXY", proxy_url)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)


def _disable_proxy(monkeypatch) -> None:
    """Clear proxy env vars and no_proxy so urlopen goes direct to loopback."""
    for key in (
        "http_proxy",
        "HTTP_PROXY",
        "https_proxy",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
        "no_proxy",
        "NO_PROXY",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _restore_urlopen_opener_cache():
    """把 urllib.request 的 module-level opener 快取在每支測試後還原。

    本檔的控制組會 install_opener(None) 逼 urlopen 重建 opener 以讀到新設的環境變數
    （見 _clear_urlopen_opener_cache）。但那是**改 process 全域狀態**：跑完之後
    urllib.request._opener 裡留著一顆指向「已經關掉的假 proxy port」的 opener。
    同一個 pytest session 裡後面任何一支測試若呼叫 urlopen，就會拿到那顆死 opener。

    這支 autouse fixture 讓那個副作用止於本檔的每一支測試。
    （grok-4.5 於 T5 review 提出；它同時指出用 -x 提前中止或改變收集順序時，
    檔內原本靠「D3 會重建」的隱性依賴就不成立了。）
    """
    saved = urllib.request._opener
    yield
    urllib.request._opener = saved


def _clear_urlopen_opener_cache() -> None:
    """Drop urllib.request's module-level cached opener so new env vars are read.

    urlopen caches build_opener() into urllib.request._opener on first use in the
    process. A prior test that called urlopen would otherwise ignore freshly set
    http_proxy / no_proxy deletions. install_opener(None) forces rebuild.
    """
    urllib.request.install_opener(None)


# ----- D1 control cell: proxy ON × raw urlopen MUST raise -----

def test_raw_urlopen_raises_with_hostile_proxy(health_server, fake_rst_proxy, monkeypatch):
    """控制組：代理開 × 修前寫法 → ConnectionResetError / URLError / OSError。

    這一格若沒拋，整支測試作廢——代表假 proxy 根本沒被走到。
    必須直呼 urlopen，不得經 wait_for_server（後者會吞例外重試）。

    ⚠️ 光靠 `pytest.raises` 不夠：`ConnectionResetError` 與 `URLError` 都是 `OSError` 子類，
    所以那個斷言實際上等於 `raises(OSError)` —— 假 server 沒起來、port 被佔、任何一種
    無關的 I/O 失敗都會讓它「通過」。真正證明「請求被送去 proxy 了」的是**假 proxy 的連線計數**。
    """
    _enable_hostile_proxy(monkeypatch, fake_rst_proxy["url"])
    _clear_urlopen_opener_cache()

    before = fake_rst_proxy["hit_count"]()
    with pytest.raises((ConnectionResetError, urllib.error.URLError, OSError)):
        urllib.request.urlopen(health_server["url"], timeout=2)

    assert fake_rst_proxy["hit_count"]() > before, (
        "假 proxy 一次連線都沒收到 —— 例外不是它造成的，這一格是假的控制組。"
        "檢查 http_proxy 環境變數名稱、no_proxy 是否被設回來、以及 urlopen 的 opener 快取。"
    )


# ----- D2: proxy ON × wait_for_server → PROBE_OK (the branch's fix) -----

def test_probe_succeeds_with_hostile_proxy_configured(
    health_server, fake_rst_proxy, alive_thread, monkeypatch
):
    """代理開 × 修後寫法：空 ProxyHandler 繞過敵意 proxy → PROBE_OK。

    除了回傳值，還斷言**假 proxy 一次連線都沒收到**。那比 PROBE_OK 更強：
    PROBE_OK 只說「最後拿到 200」，零連線說的是「這個請求從頭到尾根本沒經過代理」，
    也就是 D-130a-1「連自己的 loopback 本來就不該經過代理」那句話的直接證據。
    """
    _enable_hostile_proxy(monkeypatch, fake_rst_proxy["url"])
    before = fake_rst_proxy["hit_count"]()

    result = wait_for_server(health_server["port"], alive_thread, timeout=3)

    assert result == PROBE_OK
    assert fake_rst_proxy["hit_count"]() == before, (
        f"探活請求跑去敲了假 proxy {fake_rst_proxy['hit_count']() - before} 次 —— "
        "ProxyHandler({}) 沒有生效，代理攔截那個崩潰隨時會回來。"
    )


# ----- D3: proxy OFF × raw urlopen → HTTP 200 -----

def test_raw_urlopen_succeeds_without_proxy(health_server, monkeypatch):
    """代理關 × 修前寫法 → HTTP 200（真 server 本身是好的）。"""
    _disable_proxy(monkeypatch)
    _clear_urlopen_opener_cache()

    with urllib.request.urlopen(health_server["url"], timeout=2) as response:
        assert response.status == 200


# ----- D4: proxy OFF × wait_for_server → PROBE_OK -----

def test_probe_succeeds_without_proxy(health_server, alive_thread, monkeypatch):
    """代理關 × 修後寫法 → PROBE_OK。"""
    _disable_proxy(monkeypatch)
    result = wait_for_server(health_server["port"], alive_thread, timeout=3)
    assert result == PROBE_OK
