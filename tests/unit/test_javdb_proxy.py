"""
test_javdb_proxy.py - javdb 系統代理解析單元測試（TASK-132a-T1）

AC-1：_resolve_proxies() 四條分支
AC-2：_get_html() 有無代理時 proxies kwarg 形狀
AC-3：假 proxy socket 真的收到 CONNECT（＋ bypass 對照零連線）
"""

import contextlib
import socket
import threading
from unittest.mock import MagicMock, patch

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

class TestResolveProxies:
    def test_getproxies_https_returns_same_dict(self, monkeypatch):
        proxies = {"https": "http://127.0.0.1:7890"}
        monkeypatch.setattr(javdb, "getproxies", lambda: dict(proxies), raising=False)
        monkeypatch.setattr(javdb, "proxy_bypass", lambda host: False, raising=False)
        assert javdb._resolve_proxies("https://javdb.com/search") == proxies

    def test_bypass_host_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            javdb, "getproxies", lambda: {"https": "http://127.0.0.1:7890"}, raising=False
        )
        monkeypatch.setattr(javdb, "proxy_bypass", lambda host: True, raising=False)
        assert javdb._resolve_proxies("https://javdb.com/search") is None

    def test_empty_getproxies_returns_none(self, monkeypatch):
        monkeypatch.setattr(javdb, "getproxies", lambda: {}, raising=False)
        monkeypatch.setattr(javdb, "proxy_bypass", lambda host: False, raising=False)
        assert javdb._resolve_proxies("https://javdb.com/search") is None

    def test_malformed_url_skips_bypass_and_still_resolves(self, monkeypatch):
        """畸形 URL → hostname 為 None → 不呼叫 proxy_bypass，但仍取得代理值。

        反向鎖：`if host and ...` 的左半若被刪掉，proxy_bypass(None) 會被呼叫。
        """
        called = []
        monkeypatch.setattr(
            javdb, "getproxies", lambda: {"https": "http://127.0.0.1:7890"}, raising=False
        )
        monkeypatch.setattr(
            javdb, "proxy_bypass", lambda host: called.append(host) or True, raising=False
        )
        assert javdb._resolve_proxies("not a url") == {"https": "http://127.0.0.1:7890"}
        assert called == [], f"proxy_bypass 不該被呼叫，卻收到 {called}"

    def test_http_only_is_passed_through(self, monkeypatch):
        """只有 http 沒有 https → 原樣傳（由 curl 自己挑），不得被過濾成 None。"""
        monkeypatch.setattr(
            javdb, "getproxies", lambda: {"http": "http://127.0.0.1:7890"}, raising=False
        )
        monkeypatch.setattr(javdb, "proxy_bypass", lambda host: False, raising=False)
        assert javdb._resolve_proxies("https://javdb.com/search") == {
            "http": "http://127.0.0.1:7890"
        }

    def test_only_no_key_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            javdb, "getproxies", lambda: {"no": "localhost"}, raising=False
        )
        monkeypatch.setattr(javdb, "proxy_bypass", lambda host: False, raising=False)
        assert javdb._resolve_proxies("https://javdb.com/search") is None


# ============================================================
# AC-2：_get_html() proxies kwarg 形狀
# ============================================================

class TestGetHtmlProxiesKwarg:
    def test_get_html_passes_proxies_kwarg(self, scraper, monkeypatch):
        pytest.importorskip("curl_cffi")
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        proxies = {"https": "http://127.0.0.1:7890"}
        monkeypatch.setattr(javdb, "_resolve_proxies", lambda url: proxies, raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html></html>"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        result = scraper._get_html("https://javdb.com/v/Ww9zN8")

        assert result == "<html></html>"
        assert mock_get.call_args.kwargs["proxies"] == proxies

    def test_get_html_omits_proxies_when_none(self, scraper, monkeypatch):
        pytest.importorskip("curl_cffi")
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        monkeypatch.setattr(javdb, "_resolve_proxies", lambda url: None, raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html></html>"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        result = scraper._get_html("https://javdb.com/v/Ww9zN8")

        assert result == "<html></html>"
        assert "proxies" not in mock_get.call_args.kwargs

    def test_get_html_proxies_orthogonal_with_curl_options(self, scraper, monkeypatch):
        """proxies 與 curl_options（CAINFO）可同時存在。"""
        pytest.importorskip("curl_cffi")
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        proxies = {"https": "http://127.0.0.1:7890"}
        monkeypatch.setattr(javdb, "_resolve_proxies", lambda url: proxies, raising=False)
        ca_bytes = b"C:\\fake\\cacert.pem"
        monkeypatch.setattr(javdb, "_cainfo_override_bytes", lambda: ca_bytes)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html></html>"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        result = scraper._get_html("https://javdb.com/v/Ww9zN8")

        assert result == "<html></html>"
        assert mock_get.call_args.kwargs["proxies"] == proxies
        assert mock_get.call_args.kwargs["curl_options"] == {
            javdb.CurlOpt.CAINFO: ca_bytes
        }


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
