"""
test_javdb_proxy.py - javdb 系統代理解析單元測試（TASK-132a-T1）

AC-1：_resolve_proxies() 四條分支
AC-2：_get_html() 有無代理時 proxies kwarg 形狀
AC-3：假 proxy socket 真的收到 CONNECT（＋ bypass 對照零連線）
"""

import contextlib
import socket
import threading
from unittest.mock import patch

import pytest

from core.scrapers import javdb
from core.scrapers.errors import SourceUnreachable


@pytest.fixture
def scraper():
    with patch("core.scrapers.javdb.rate_limit"):
        s = javdb.JavDBScraper()
        yield s


@pytest.fixture
def fake_connect_proxy():
    """Accept TCP, record the first request line (expect CONNECT), then close.

    Port is OS-assigned. hits is a thread-safe list of decoded first-lines.
    """
    stop = threading.Event()
    hits = []
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
            try:
                conn.settimeout(2.0)
                data = b""
                while b"\r\n" not in data and len(data) < 4096:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                first_line = data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
                with hits_lock:
                    hits.append(first_line)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()

    def _hit_count():
        with hits_lock:
            return len(hits)

    def _hit_lines():
        with hits_lock:
            return list(hits)

    yield {
        "port": port,
        "url": f"http://127.0.0.1:{port}",
        "hit_count": _hit_count,
        "hit_lines": _hit_lines,
    }
    stop.set()
    try:
        sock.close()
    except OSError:
        pass
    thread.join(timeout=2)


def _closed_loopback_port():
    """Bind then close an OS-assigned loopback port → guaranteed instant ECONNREFUSED.

    Why not a hardcoded low port: 127.0.0.1:1 does NOT refuse on WSL2 — the SYN is
    silently dropped and curl burns the full `timeout=30`, making this test the
    slowest unit test in the repo (measured 30.00s). A bind-then-close port refuses
    in 0.00s (measured).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _clear_proxy_env(monkeypatch):
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


# ============================================================
# AC-1：_resolve_proxies() 四條分支
# ============================================================


# ============================================================
# AC-2：_get_html() proxies kwarg 形狀
# ============================================================


# ============================================================
# AC-3：假 proxy 真行為（CONNECT 收到／bypass 零連線）
# ============================================================

class TestFakeProxyConnect:
    def test_get_html_connects_via_resolved_proxy(
        self, scraper, monkeypatch, fake_connect_proxy
    ):
        pytest.importorskip("curl_cffi")
        _clear_proxy_env(monkeypatch)
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        proxy_dict = {
            "http": fake_connect_proxy["url"],
            "https": fake_connect_proxy["url"],
        }
        monkeypatch.setattr(javdb, "getproxies", lambda: dict(proxy_dict), raising=False)
        monkeypatch.setattr(javdb, "proxy_bypass", lambda host: False, raising=False)

        # Real curl_cffi call — proxy will RST/close after CONNECT; we only need the hit.
        # T2 起連線層失敗會拋 SourceUnreachable；本測試的斷言是「假 proxy 收到 CONNECT」，
        # 不是回傳值，所以吞掉它（吞的是預期中的失敗，不是在掩蓋錯誤）。
        with contextlib.suppress(SourceUnreachable):
            scraper._get_html("https://javdb.com/v/Ww9zN8")

        lines = fake_connect_proxy["hit_lines"]()
        assert fake_connect_proxy["hit_count"]() >= 1, f"proxy got no hits; lines={lines}"
        assert any(
            line.lower().startswith("connect javdb.com:443") for line in lines
        ), f"expected CONNECT javdb.com:443, got {lines}"

    def test_bypass_skips_proxy_zero_hits(
        self, scraper, monkeypatch, fake_connect_proxy
    ):
        pytest.importorskip("curl_cffi")
        _clear_proxy_env(monkeypatch)
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        proxy_dict = {
            "http": fake_connect_proxy["url"],
            "https": fake_connect_proxy["url"],
        }
        monkeypatch.setattr(javdb, "getproxies", lambda: dict(proxy_dict), raising=False)
        monkeypatch.setattr(javdb, "proxy_bypass", lambda host: True, raising=False)

        # Direct to a closed loopback port — must not touch the fake proxy.
        with contextlib.suppress(SourceUnreachable):
            scraper._get_html(f"https://127.0.0.1:{_closed_loopback_port()}/")

        assert fake_connect_proxy["hit_count"]() == 0
