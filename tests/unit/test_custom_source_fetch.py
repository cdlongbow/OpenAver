"""自訂來源抓取層：逐跳守衛、transport 契約、body 上限、節流、解碼。"""

import sys
import types

import pytest
import requests

from core.custom_source.fetch import FetchError, RawResponse, fetch_page, make_transport
from core.proxy_policy import ProxySettings
from core.scrapers.models import ScraperConfig
from tests.unit._custom_source_fake import FakeTransport, redirect


@pytest.fixture(autouse=True)
def _no_real_dns_or_sleep(monkeypatch):
    monkeypatch.setattr("core.public_target.resolve_host", lambda host: ["8.8.8.8"])
    monkeypatch.setattr("core.custom_source.fetch.rate_limit", lambda delay=0: None)


def _cfg(**kw):
    kw.setdefault("proxy_settings", ProxySettings())
    return ScraperConfig(**kw)


A, B, C = "https://a.example/1", "https://b.example/2", "https://c.example/3"


# ---------- 逐跳守衛 ----------

def test_every_hop_is_guarded_before_request():
    # 首跳私網：零請求
    t = FakeTransport({})
    with pytest.raises(FetchError) as ei:
        fetch_page("http://192.168.1.1/", t, _cfg())
    assert ei.value.reason == "blocked_target"
    assert t.calls == []
    # 第 2 跳導向私網：只有第 1 跳送出
    t = FakeTransport({A: redirect("http://10.0.0.5/")})
    with pytest.raises(FetchError) as ei:
        fetch_page(A, t, _cfg())
    assert ei.value.reason == "blocked_target"
    assert t.calls == [A]
    # 第 3 跳 file:
    t = FakeTransport({A: redirect(B), B: redirect("file:///etc/passwd")})
    with pytest.raises(FetchError) as ei:
        fetch_page(A, t, _cfg())
    assert ei.value.reason == "blocked_target"
    assert t.calls == [A, B]
    # 導向 Tailscale 100.x
    t = FakeTransport({A: redirect("http://100.64.0.9/x")})
    with pytest.raises(FetchError):
        fetch_page(A, t, _cfg())
    assert t.calls == [A]


# ---------- 節流 ----------


# ---------- 解碼 ----------

@pytest.mark.parametrize("charset", ["euc-jp", ])
def test_declared_charset_decodes_japanese(charset):
    raw = RawResponse(200, {"content-type": f"text/html; charset={charset}"},
                      "日本語タイトル".encode(charset), None)
    assert fetch_page(A, FakeTransport({A: raw}), _cfg()).text == "日本語タイトル"


# ---------- FetchError ----------


# ---------- plain transport（Session 邊界） ----------

class _FakeResp:
    def __init__(self, chunks=(b"hi",), status=200, headers=None):
        self.status_code = status
        self.headers = headers or {"Content-Type": "text/html", "Location": "/x"}
        self._chunks = chunks
        self.closed = 0

    def iter_content(self, chunk_size=1):
        yield from self._chunks

    def close(self):
        self.closed += 1


def _patch_session(monkeypatch, resp=None, exc=None):
    seen = []

    def fake_request(self, method, url, **kwargs):
        seen.append((method, url, kwargs))
        if exc is not None:
            raise exc
        return resp

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return seen


def test_plain_transport_single_hop_contract(monkeypatch):
    resp = _FakeResp()
    seen = _patch_session(monkeypatch, resp)
    cfg = _cfg(timeout=7, proxy_settings=ProxySettings(url="http://127.0.0.1:7890", scope="all"))
    raw = make_transport("plain", "mysrc", cfg).request(A)
    _, url, kw = seen[0]
    assert url == A
    assert kw["allow_redirects"] is False
    assert kw["timeout"] == 7
    assert kw["stream"] is True
    assert kw["proxies"] == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
    assert raw.status == 200 and raw.body_bytes == b"hi"
    assert raw.headers["content-type"] == "text/html" and raw.location == "/x"
    assert resp.closed == 1


def test_plain_body_cap_closes_and_raises_too_large(monkeypatch):
    monkeypatch.setattr("core.custom_source.fetch.MAX_BODY_BYTES", 10)
    resp = _FakeResp(chunks=(b"x" * 6, b"y" * 6, b"z" * 6))
    _patch_session(monkeypatch, resp)
    with pytest.raises(FetchError) as ei:
        make_transport("plain", "s", _cfg()).request(A)
    assert ei.value.reason == "too_large"
    assert resp.closed == 1


# ---------- tls transport（假 curl_cffi 模組） ----------

class _CffiTimeout(Exception):
    pass


class _CffiRequestException(Exception):
    pass


class _TlsResp:
    def __init__(self, content=b"hello", status=200, headers=None):
        self.content = content
        self.status_code = status
        self.headers = headers or {"Content-Type": "text/html", "Location": "/y"}


def _install_fake_curl(monkeypatch, resp=None, exc=None):
    record = {"init": [], "gets": []}

    class Session:
        def __init__(self, **kw):
            record["init"].append(kw)

        def get(self, url, **kw):
            record["gets"].append((url, kw))
            if exc is not None:
                raise exc
            return resp

    fake_requests = types.SimpleNamespace(
        Session=Session,
        exceptions=types.SimpleNamespace(Timeout=_CffiTimeout, RequestException=_CffiRequestException),
    )
    fake_pkg = types.ModuleType("curl_cffi")
    fake_pkg.requests = fake_requests
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_pkg)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_requests)
    return record


def test_tls_transport_single_hop_contract(monkeypatch):
    rec = _install_fake_curl(monkeypatch, _TlsResp())
    cfg = _cfg(timeout=7, proxy_settings=ProxySettings(url="http://127.0.0.1:7890", scope="all"))
    raw = make_transport("tls", "mysrc", cfg).request(A)
    assert rec["init"] == [{"impersonate": "chrome"}]
    url, kw = rec["gets"][0]
    assert url == A
    assert kw["allow_redirects"] is False
    assert kw["timeout"] == 7
    assert "headers" not in kw
    assert kw["proxies"] == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
    assert raw.status == 200 and raw.body_bytes == b"hello" and raw.location == "/y"


