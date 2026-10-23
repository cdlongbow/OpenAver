"""core.public_target.check_public：公網目標判準的真值表（手寫字面）。"""

import pytest

from core.public_target import Violation, check_public

# (url, (reason, detail)；None＝放行)
TRUTH_TABLE = [
    ("http://127.0.0.1/", ("non_public", None)),
    ("http://faß.example/", ("non_ascii_host", None)),
    ("http://192.168.1.1\\@x.example/", ("bad_authority", None)),
    ("file:///etc/passwd", ("bad_scheme", None)),
    ("http://[::1", ("bad_url", None)),
    ("http://8.8.8.8/", None),
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
])
def test_ipv4_mapped_is_unwrapped(url):
    # 不解 ipv4_mapped 時，Py3.12 會把這兩個 mapped 位址誤判為全球位址
    got = check_public(url)
    assert got is not None and (got.reason, got.detail) == ("non_public", None)


@pytest.mark.parametrize("url", [
    "http://localhost./x",
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


@pytest.mark.parametrize("resolved", [[]])
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


def test_fake_ip_range_resolved_passes(public_resolver):
    resolve = public_resolver({"example.com": ["198.18.0.5"]})
    assert check_public("https://example.com/") is None
    assert resolve.calls == ["example.com"]


@pytest.mark.parametrize("url", ["http://198.51.100.1/", ])
def test_other_non_global_ranges_still_blocked(url):
    got = check_public(url)
    assert got is not None and got.reason == "non_public"
