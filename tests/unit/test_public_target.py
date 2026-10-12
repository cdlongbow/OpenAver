"""core.public_target.check_public：公網目標判準的真值表（手寫字面）。"""

import subprocess
import sys
from pathlib import Path

import pytest

from core.public_target import Violation, check_public

ROOT = Path(__file__).resolve().parents[2]

# (url, (reason, detail)；None＝放行)
TRUTH_TABLE = [
    ("http://127.0.0.1/", ("non_public", None)),
    ("http://10.0.0.5/", ("non_public", None)),
    ("http://100.64.0.1/", ("non_public", None)),
    ("http://224.0.0.1/", ("non_public", None)),
    ("http://[::1]/", ("non_public", None)),
    ("http://[::ffff:127.0.0.1]/", ("non_public", None)),
    ("http://faß.example/", ("non_ascii_host", None)),
    ("http://192.168.1.1\\@x.example/", ("bad_authority", None)),
    ("http://x.example\\@127.0.0.1/", ("bad_authority", None)),
    ("ftp://example.com/", ("bad_scheme", None)),
    ("file:///etc/passwd", ("bad_scheme", None)),
    ("http:///x", ("bad_host", "missing_host")),
    ("http://localhost/", ("bad_host", "blocked_name")),
    ("http://localhost./x", ("bad_host", "blocked_name")),
    ("http://svc.localhost/", ("bad_host", "blocked_name")),
    ("http://x.internal/", ("bad_host", "blocked_name")),
    ("http://nas.local/", ("bad_host", "blocked_name")),
    ("http://[::1", ("bad_url", None)),
    ("http://example.com:99999/", ("bad_url", None)),
    ("http://example.com:abc/", ("bad_url", None)),
    ("http://8.8.8.8/", None),
    ("https://1.1.1.1/", None),
    ("http://[::ffff:8.8.8.8]/", None),
    ("http://xn--fa-hia.example/", None),
    ("https://example.com:8443/path?q=1", None),
]


@pytest.mark.parametrize("url,expected", TRUTH_TABLE)
def test_check_public_truth_table(public_resolver, url, expected):
    public_resolver()
    got = check_public(url)
    if expected is None:
        assert got is None
        return
    assert isinstance(got, Violation)
    assert (got.reason, got.detail) == expected


@pytest.mark.parametrize("url", [
    "http://[::ffff:224.0.0.1]/",
    "http://[::ffff:100.64.0.1]/",
])
def test_ipv4_mapped_is_unwrapped(url):
    # 不解 ipv4_mapped 時，Py3.12 會把這兩個 mapped 位址誤判為全球位址
    got = check_public(url)
    assert got is not None and (got.reason, got.detail) == ("non_public", None)


def test_ipv4_mapped_public_passes():
    assert check_public("http://[::ffff:8.8.8.8]/") is None


@pytest.mark.parametrize("url", [
    "http://localhost./x",
    "http://x.internal/",
    "http://svc.localhost/",
    "http://LOCALHOST/",
])
def test_blocked_name_rejected_before_dns(public_resolver, url):
    resolve = public_resolver()  # 預設回公網位址：名稱擋失效就會被放行
    got = check_public(url)
    assert got is not None and (got.reason, got.detail) == ("bad_host", "blocked_name")
    assert resolve.calls == []


def test_domain_resolving_to_private_is_blocked_and_resolver_called(public_resolver):
    resolve = public_resolver({"example.com": ["10.0.0.5"]})
    got = check_public("http://example.com/")
    assert got is not None and got.reason == "non_public"
    assert resolve.calls == ["example.com"]


def test_domain_resolving_to_public_passes(public_resolver):
    resolve = public_resolver({"example.com": ["8.8.8.8", "1.1.1.1"]})
    assert check_public("https://example.com/") is None
    assert resolve.calls == ["example.com"]


@pytest.mark.parametrize("resolved", [[], ["not-an-ip"]])
def test_unresolvable(public_resolver, resolved):
    public_resolver({"example.com": resolved})
    got = check_public("http://example.com/")
    assert got is not None and got.reason == "unresolvable"


def test_violation_carries_no_user_input(public_resolver):
    public_resolver()
    got = check_public("http://user:pw@127.0.0.1/x?token=1")
    text = repr(got)
    for secret in ("pw", "token", "user", "127.0.0.1", "/x"):
        assert secret not in text


def test_import_pulls_in_no_custom_source():
    code = (
        f"import sys; sys.path.insert(0, {str(ROOT)!r}); import core.public_target; "
        "assert not [m for m in sys.modules if m.startswith('core.custom_source')]"
    )
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
