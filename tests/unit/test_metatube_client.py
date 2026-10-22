"""
test_metatube_client.py — Unit tests for MetatubeHttpClient + pick_movie_result.

Test strategy: TDD-lite + mock HTTP (monkeypatch on client._session.get).
No real network calls. No requests-mock dependency.
House style: unittest.mock (MagicMock), plain assert, pytest fixtures.
"""

import pytest
import requests
from unittest.mock import MagicMock, patch

from core.metatube.errors import (
    MetatubeUnavailable,
    MetatubeNotFound,
    MetatubeAuthError,
    MetatubeClientError,
    MetatubeProtocolError,
)
from core.metatube.client import MetatubeHttpClient, pick_movie_result


# ============================================================
# Helpers
# ============================================================

def make_json_response(body: dict, status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response that returns JSON."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


def make_client(base_url: str = "http://localhost:8900", token=None) -> MetatubeHttpClient:
    return MetatubeHttpClient(base_url, token=token)


# ============================================================
# TC-3: search — provider param & data=null
# ============================================================

class TestSearch:

    def test_search_always_sends_provider_param(self):
        """params must contain 'provider' to avoid triggering SearchMovieAll broadcast."""
        client = make_client()
        client._session.get = MagicMock(
            return_value=make_json_response({"data": []})
        )
        client.search("FANZA", "ssis-001")
        call_kwargs = client._session.get.call_args
        # params can be positional or keyword
        if call_kwargs.kwargs.get("params"):
            params = call_kwargs.kwargs["params"]
        else:
            # find params in args
            params = call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
            params = call_kwargs.kwargs.get("params", params)
        assert "provider" in params
        assert params["provider"] == "FANZA"

    def test_search_sends_fallback_false(self):
        """params must contain fallback=false to enforce source isolation (Codex P2):
        upstream metatube defaults Fallback=true, so a no-match provider-scoped search
        would otherwise return a foreign provider's hit, corrupting US8 / auto fan-out."""
        client = make_client()
        client._session.get = MagicMock(
            return_value=make_json_response({"data": []})
        )
        client.search("SOD", "ssis-001")
        params = client._session.get.call_args.kwargs.get("params") or {}
        assert params.get("fallback") == "false"
        # must be the lowercase string, not Python bool False (requests → "False")
        assert isinstance(params.get("fallback"), str)


# ============================================================
# TC-4: token header (have / none / empty string)
# ============================================================

class TestTokenHeader:

    def test_token_none_no_authorization_header(self):
        client = MetatubeHttpClient("http://localhost:8900", token=None)
        assert "Authorization" not in client._session.headers

    def test_token_set_has_bearer_header(self):
        client = MetatubeHttpClient("http://localhost:8900", token="secret")
        assert client._session.headers.get("Authorization") == "Bearer secret"

    def test_token_empty_string_no_authorization_header(self):
        """Empty string is falsy — must not send Authorization header."""
        client = MetatubeHttpClient("http://localhost:8900", token="")
        assert "Authorization" not in client._session.headers


# ============================================================
# TC-5: pick_movie_result — 5 boundary cases
# ============================================================

class TestPickMovieResult:

    def test_empty_list_returns_none(self):
        assert pick_movie_result([]) is None

    def test_picks_video_dmm_homepage_over_first(self):
        """3 results: second has video.dmm.co.jp homepage — should be picked."""
        results = [
            {"id": "a", "homepage": "https://www.dmm.co.jp/mono/dvd/"},
            {"id": "b", "homepage": "https://video.dmm.co.jp/product/detail/1stars00141/"},
            {"id": "c", "homepage": "https://www.dmm.co.jp/digital/"},
        ]
        picked = pick_movie_result(results)
        assert picked is not None
        assert picked["id"] == "b"

    def test_no_video_dmm_returns_first(self):
        """3 results, none with video.dmm.co.jp → return results[0]."""
        results = [
            {"id": "first", "homepage": "https://other.example.com/"},
            {"id": "second", "homepage": "https://another.example.com/"},
            {"id": "third"},
        ]
        picked = pick_movie_result(results)
        assert picked["id"] == "first"

    def test_single_result_with_video_dmm_returns_it(self):
        """1 result with video.dmm.co.jp homepage → return it (overlap of rule 1 and first)."""
        results = [{"id": "only", "homepage": "https://video.dmm.co.jp/product/detail/x/"}]
        picked = pick_movie_result(results)
        assert picked["id"] == "only"

    def test_single_result_no_homepage_key_returns_it(self):
        """1 result without homepage key → r.get('homepage', '') is safe → returns results[0]."""
        results = [{"id": "nopage", "title": "Some Title"}]
        picked = pick_movie_result(results)
        assert picked["id"] == "nopage"


# ============================================================
# TC-6: movie_id URL quoting in get_info
# ============================================================

class TestMovieIdQuoting:

    def _get_called_url(self, client: MetatubeHttpClient) -> str:
        """Extract the URL from the last session.get call."""
        call = client._session.get.call_args
        if call.args:
            return call.args[0]
        return call.kwargs.get("url", "")

    def test_underscore_id_not_mangled(self):
        """020125_001 — underscore is valid URL char; path must contain it unchanged."""
        client = make_client()
        client._session.get = MagicMock(
            return_value=make_json_response({"data": {"number": "020125_001"}})
        )
        client.get_info("1Pondo", "020125_001")
        url = self._get_called_url(client)
        assert "020125_001" in url

    def test_alphanumeric_id_not_mangled(self):
        """156785614478ab480db — pure alphanum, path unchanged."""
        client = make_client()
        client._session.get = MagicMock(
            return_value=make_json_response({"data": {"number": "156785614478ab480db"}})
        )
        client.get_info("Pcolle", "156785614478ab480db")
        url = self._get_called_url(client)
        assert "156785614478ab480db" in url

    def test_lowercase_id_not_mangled(self):
        """1stars00141 — all lower-case alphanum, path unchanged."""
        client = make_client()
        client._session.get = MagicMock(
            return_value=make_json_response({"data": {"number": "1stars00141"}})
        )
        client.get_info("FANZA", "1stars00141")
        url = self._get_called_url(client)
        assert "1stars00141" in url

    def test_no_double_slash_in_url(self):
        """base_url with trailing slash must not produce double slashes."""
        client = MetatubeHttpClient("http://localhost:8900/", token=None)
        client._session.get = MagicMock(
            return_value=make_json_response({"data": {}})
        )
        client.get_info("FANZA", "1stars00141")
        url = self._get_called_url(client)
        # After the scheme+host, path should start with single /v1
        assert "//v1" not in url.replace("http://", "").replace("https://", "")


# ============================================================
# TC-9: SSRF redirect guard (Codex P1) — 3xx must NOT be followed
# A validated public host could 30x-redirect to loopback / internal;
# validate_metatube_url() only checks the original URL, so the client
# must refuse redirects (allow_redirects=False) and reject any 3xx.
# ============================================================

class TestRedirectBlocking:
    # Two cases are enough: pin the allow_redirects=False contract, and confirm
    # a 3xx surfaces as MetatubeProtocolError (not followed). The redirect block
    # lives in the shared _get_data path, so per-method / per-target-IP matrices
    # add no coverage — they were enterprise-SSRF audit padding (A2 trim).

    def test_session_get_called_with_allow_redirects_false(self):
        """Pin the contract: allow_redirects=False must be passed (regression guard)."""
        client = make_client()
        client._session.get = MagicMock(
            return_value=make_json_response({"data": None}, status_code=200)
        )
        client.get_info("FANZA", "1stars00141")
        assert client._session.get.call_args.kwargs.get("allow_redirects") is False, (
            "MetatubeHttpClient must pass allow_redirects=False to prevent SSRF via redirects"
        )

    def test_3xx_redirect_raises_protocol_error(self):
        """A 3xx response → MetatubeProtocolError, not followed."""
        client = make_client()
        resp = make_json_response({}, status_code=302)
        resp.headers = {"Location": "http://127.0.0.1:8080/admin"}
        client._session.get = MagicMock(return_value=resp)
        with pytest.raises(MetatubeProtocolError):
            client.get_info("FANZA", "1stars00141")


# ============================================================
# 憑證不得進 log／例外訊息（Codex PR review 三審 P1 的**根因**層）
# ============================================================

_SECRET_URL = "http://admin:S3cr3tPass@10.0.0.5:8900"
_SECRETS = ("S3cr3tPass", "admin@", "tok_ABC123")


def _client_with_secret_url():
    from core.metatube.client import MetatubeHttpClient
    return MetatubeHttpClient(_SECRET_URL, "tok_ABC123")


@pytest.mark.parametrize("status,exc_type", [
    (401, MetatubeAuthError),
    (404, MetatubeNotFound),
    (418, MetatubeClientError),
    (302, MetatubeProtocolError),
    (500, MetatubeUnavailable),
])
def test_error_messages_never_embed_credentials(status, exc_type):
    """**這支是整組修正的核心鎖。**

    修正前 `_get_data()` 用 `f"{self._base_url}{path}"` 組**每一個** `MetatubeError`
    的訊息，於是任何下游 `logger.exception(...)` / `logger.X("%s", exc)` 都會洩漏
    userinfo——`probe.py`、`core/scraper.py::_MetatubeShim`、`settings_metatube.py`
    全是這種形狀。逐個 log 點修永遠修不完，所以鎖在訊息**生成**的源頭。

    正向＋負向配對：同時斷言 host 有出現（證明訊息確實帶了可診斷的位置資訊，
    而不是被整段抽空造成的假綠）。
    """
    c = _client_with_secret_url()
    resp = MagicMock()
    resp.status_code = status
    with patch.object(c._session, "get", return_value=resp):
        with pytest.raises(exc_type) as ei:
            c._get_data("/v1/movies/FANZA/SSIS-001", None)
    msg = str(ei.value)
    assert "10.0.0.5:8900" in msg
    for secret in _SECRETS:
        assert secret not in msg, f"HTTP {status} 的例外訊息洩漏 {secret!r}：{msg}"


def test_invalid_json_error_message_never_embeds_credentials():
    c = _client_with_secret_url()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = ValueError("bad json")
    with patch.object(c._session, "get", return_value=resp):
        with pytest.raises(MetatubeProtocolError) as ei:
            c._get_data("/v1/providers", None)
    msg = str(ei.value)
    assert "10.0.0.5:8900" in msg
    for secret in _SECRETS:
        assert secret not in msg


def test_request_logs_never_leak_credentials(caplog):
    """`_get_data()` 的 GET debug log 與 unavailable warning 兩條都要乾淨。

    前者**每一次請求**都會記，後者在伺服器連不上時記——都是高頻路徑。
    """
    import logging

    c = _client_with_secret_url()
    with caplog.at_level(logging.DEBUG, logger="OpenAver.core.metatube.client"):
        with patch.object(c._session, "get",
                          side_effect=requests.ConnectionError("boom")):
            with pytest.raises(MetatubeUnavailable):
                c._get_data("/v1/providers", None)

    assert "metatube GET" in caplog.text          # 正向：debug 這條真的跑到了
    assert "metatube unavailable" in caplog.text  # 正向：warning 這條也是
    assert "10.0.0.5:8900" in caplog.text
    for secret in _SECRETS:
        assert secret not in caplog.text, f"client log 洩漏 {secret!r}"
