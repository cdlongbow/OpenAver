"""
tests/unit/test_metatube_validation.py

TDD-lite tests for core.metatube.validation.validate_metatube_url.
All DNS resolution is mocked — no real network calls.
"""

from unittest.mock import patch

import pytest

from core.metatube.validation import validate_metatube_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gai_result(ip_str: str):
    """Return a minimal getaddrinfo result list for a single IP address."""
    # (family, type, proto, canonname, sockaddr)  — sockaddr[0] is the IP
    return [(2, 1, 6, "", (ip_str, 0))]


# ---------------------------------------------------------------------------
# Scheme blocking
# ---------------------------------------------------------------------------

class TestSchemeBlocking:
    def test_file_scheme_blocked(self):
        result = validate_metatube_url("file:///etc/passwd")
        assert isinstance(result, str) and result, "file:// should be blocked"

    def test_gopher_scheme_blocked(self):
        result = validate_metatube_url("gopher://evil.com")
        assert isinstance(result, str) and result, "gopher:// should be blocked"


# ---------------------------------------------------------------------------
# Empty / malformed host
# ---------------------------------------------------------------------------

class TestEmptyHost:
    def test_empty_url_blocked(self):
        result = validate_metatube_url("")
        assert isinstance(result, str) and result, "empty URL should be blocked"


# ---------------------------------------------------------------------------
# Localhost / .localhost (step 3 — always block, allow_lan does NOT bypass)
# ---------------------------------------------------------------------------

class TestLocalhostBlocking:
    def test_localhost_blocked(self):
        # getaddrinfo must NOT be called for literal 'localhost'
        with patch("core.metatube.validation.socket.getaddrinfo") as mock_gai:
            result = validate_metatube_url("http://localhost:8080")
            mock_gai.assert_not_called()
        assert isinstance(result, str) and result
        assert "localhost" not in result.lower(), "Should not leak hostname in error"

    def test_sub_localhost_blocked(self):
        with patch("core.metatube.validation.socket.getaddrinfo") as mock_gai:
            result = validate_metatube_url("http://sub.localhost:8080")
            mock_gai.assert_not_called()
        assert isinstance(result, str) and result

    def test_localhost_allow_lan_still_blocked(self):
        """allow_lan=True must NOT bypass localhost."""
        with patch("core.metatube.validation.socket.getaddrinfo") as mock_gai:
            result = validate_metatube_url("http://localhost:8080", allow_lan=True)
            mock_gai.assert_not_called()
        assert isinstance(result, str) and result


# ---------------------------------------------------------------------------
# .local mDNS — always block
# ---------------------------------------------------------------------------

class TestDotLocalBlocking:
    def test_host_dot_local_blocked(self):
        result = validate_metatube_url("http://host.local")
        assert isinstance(result, str) and result


# ---------------------------------------------------------------------------
# IP literal — loopback (always block, allow_lan does NOT bypass)
# ---------------------------------------------------------------------------

class TestLoopbackBlocking:
    def test_127_blocked(self):
        # IP literal path — getaddrinfo NOT called
        with patch("core.metatube.validation.socket.getaddrinfo") as mock_gai:
            result = validate_metatube_url("http://127.0.0.1:8080")
            mock_gai.assert_not_called()
        assert isinstance(result, str) and result

    def test_127_allow_lan_still_blocked(self):
        with patch("core.metatube.validation.socket.getaddrinfo") as mock_gai:
            result = validate_metatube_url("http://127.0.0.1:8080", allow_lan=True)
            mock_gai.assert_not_called()
        assert isinstance(result, str) and result
        assert "127" not in result, "Should not leak IP in error"

    def test_ipv6_loopback_blocked(self):
        # http://[::1]:8080 → urlparse hostname = '::1'
        with patch("core.metatube.validation.socket.getaddrinfo") as mock_gai:
            result = validate_metatube_url("http://[::1]:8080")
            mock_gai.assert_not_called()
        assert isinstance(result, str) and result


# ---------------------------------------------------------------------------
# IP literal — link-local (always block)
# ---------------------------------------------------------------------------

class TestLinkLocalBlocking:
    def test_169_254_blocked(self):
        with patch("core.metatube.validation.socket.getaddrinfo") as mock_gai:
            result = validate_metatube_url("http://169.254.0.1")
            mock_gai.assert_not_called()
        assert isinstance(result, str) and result


# ---------------------------------------------------------------------------
# IP literal — RFC1918 private (gated by allow_lan)
# ---------------------------------------------------------------------------

class TestPrivateIPLiteral:
    def test_192168_no_lan_blocked(self):
        with patch("core.metatube.validation.socket.getaddrinfo") as mock_gai:
            result = validate_metatube_url("http://192.168.1.50:8080", allow_lan=False)
            mock_gai.assert_not_called()
        assert isinstance(result, str) and result
        assert "192.168" not in result, "Should not leak IP in error"

    def test_192168_allow_lan_passes(self):
        with patch("core.metatube.validation.socket.getaddrinfo") as mock_gai:
            result = validate_metatube_url("http://192.168.1.50:8080", allow_lan=True)
            mock_gai.assert_not_called()
        assert result is None

    def test_10_0_0_1_no_lan_blocked(self):
        with patch("core.metatube.validation.socket.getaddrinfo") as mock_gai:
            result = validate_metatube_url("http://10.0.0.1:8080", allow_lan=False)
            mock_gai.assert_not_called()
        assert isinstance(result, str) and result

    def test_172_16_0_1_no_lan_blocked(self):
        with patch("core.metatube.validation.socket.getaddrinfo") as mock_gai:
            result = validate_metatube_url("http://172.16.0.1:8080", allow_lan=False)
            mock_gai.assert_not_called()
        assert isinstance(result, str) and result


# ---------------------------------------------------------------------------
# Hostname resolution (step 6)
# ---------------------------------------------------------------------------

class TestHostnameResolution:
    def test_public_domain_passes(self):
        """A domain resolving to a public IP should pass."""
        # Use 1.1.1.1 (Cloudflare) — genuinely global, not TEST-NET
        with patch(
            "core.metatube.validation.socket.getaddrinfo",
            return_value=_make_gai_result("1.1.1.1"),
        ):
            result = validate_metatube_url("https://metatube.example.com:8080")
        assert result is None

    def test_domain_resolves_to_loopback_blocked(self):
        """Domain pointing at 127.0.0.1 must be blocked (basic SSRF guard)."""
        with patch(
            "core.metatube.validation.socket.getaddrinfo",
            return_value=_make_gai_result("127.0.0.1"),
        ):
            result = validate_metatube_url("http://evil.internal")
        assert isinstance(result, str) and result

    def test_domain_resolves_to_private_no_lan_blocked(self):
        with patch(
            "core.metatube.validation.socket.getaddrinfo",
            return_value=_make_gai_result("192.168.1.1"),
        ):
            result = validate_metatube_url("http://corp.example.com", allow_lan=False)
        assert isinstance(result, str) and result

    def test_domain_resolves_to_private_allow_lan_passes(self):
        with patch(
            "core.metatube.validation.socket.getaddrinfo",
            return_value=_make_gai_result("192.168.1.1"),
        ):
            result = validate_metatube_url("http://corp.example.com", allow_lan=True)
        assert result is None

    def test_resolution_failure_blocked(self):
        """OSError during getaddrinfo → block (conservative)."""
        with patch(
            "core.metatube.validation.socket.getaddrinfo",
            side_effect=OSError("Name or service not known"),
        ):
            result = validate_metatube_url("http://resolve-fail.internal")
        assert isinstance(result, str) and result


# ---------------------------------------------------------------------------
# Port validation (FIX 1a)
# ---------------------------------------------------------------------------

class TestPortValidation:
    def test_malformed_port_alpha_blocked(self):
        """http://1.1.1.1:abc — non-numeric port must return port-error string."""
        result = validate_metatube_url("http://1.1.1.1:abc")
        assert isinstance(result, str) and result, "Malformed port ':abc' should be blocked"
        # Must not leak internal details
        assert "abc" not in result

    def test_port_out_of_range_blocked(self):
        """http://1.1.1.1:99999 — out-of-range port (>65535) must be blocked."""
        result = validate_metatube_url("http://1.1.1.1:99999")
        assert isinstance(result, str) and result, "Out-of-range port ':99999' should be blocked"

    def test_valid_port_passes(self):
        """http://1.1.1.1:8900 — valid port on a public IP literal must pass (None)."""
        # 1.1.1.1 is a public IP literal — no DNS resolution needed; passes without allow_lan
        result = validate_metatube_url("http://1.1.1.1:8900")
        assert result is None, f"Valid public IP+port should pass, got: {result!r}"


# ============================================================
# redact_metatube_url —— log／例外訊息的單一渲染所有者
# （Codex PR review 三輪同根因，2026-08-07）
# ============================================================

@pytest.mark.parametrize("raw,expected", [
    ("http://admin:S3cr3tPass@10.0.0.5:8900", "10.0.0.5:8900"),  # userinfo 丟掉、host:port 保留
    ("https://u:p@example.com", "example.com"),                  # 預設 port 不加後綴
    ("http://127.0.0.1:8900", "127.0.0.1:8900"),
    ("http://host/p?token=secret#frag", "host"),                 # path/query/fragment 全丟
    ("http://127.0.0.1:99999/x?token=s", "127.0.0.1"),           # 畸形 port：.port 拋 ValueError → 只回 host
    ("", "<empty>"),
    ("not a url", "<unparseable>"),                              # 解析不出 host **不得**回退成原字串
])
def test_redact_metatube_url(raw, expected):
    from core.metatube.validation import redact_metatube_url
    assert redact_metatube_url(raw) == expected


def test_redact_metatube_url_never_returns_input_on_garbage():
    """畸形輸入時**不回退成原字串**——那等於在最需要保護的輸入上放棄保護。"""
    from core.metatube.validation import redact_metatube_url
    garbage = "user:pass@@@not-a-url"
    out = redact_metatube_url(garbage)
    assert "pass" not in out and out != garbage
