"""
Unit tests for core/image_host_policy.py (TASK-113c-T1 / T3a).

Expectation values are hardcoded from plan §1.3 / task-card reconciliation
table (CD-113c-3). Do NOT derive them from IMAGE_HOSTS.
"""
from __future__ import annotations


import pytest

from core.image_host_policy import (
    download_hosts_for,
    nested_preview_target_allowed,
    proxy_dynamic_hosts,
)
from core.actress_photo import validate_photo_url
from core.metatube.state import metatube_state


# ---------------------------------------------------------------------------
# DoD-1: reconciliation table (hardcoded expectations)
# ---------------------------------------------------------------------------

def test_download_hosts_for_matches_reconciliation_table():
    """download_hosts_for() must match §1.3 download-side whitelist exactly."""
    assert download_hosts_for("graphis") == {
        "www.graphis.ne.jp",
        "graphis.ne.jp",
        "data.graphis.ne.jp",
    }
    assert download_hosts_for("gfriends") == {
        "cdn.jsdelivr.net",
        "raw.githubusercontent.com",
        "github.com",
    }
    assert download_hosts_for("wiki") == {
        "upload.wikimedia.org",
        "ja.wikipedia.org",
    }
    assert download_hosts_for("xcity") == {"faws.xcity.jp"}


# ---------------------------------------------------------------------------
# DoD-1b: schemes / field consistency on IMAGE_HOSTS
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DoD-3: mechanism differences preserved at export layer
# ---------------------------------------------------------------------------

def test_download_hosts_for_unknown_source_fail_closed():
    """Unknown photo_source → empty set (fail-closed), never None/raise."""
    result = download_hosts_for("nonexistent_source")
    assert result == set()
    assert isinstance(result, set)


# ---------------------------------------------------------------------------
# TASK-113c-T3a: proxy_dynamic_hosts() / AC5b / truth table / cf.javfree.me
# ---------------------------------------------------------------------------

def test_proxy_dynamic_hosts_returns_entry_when_connected():
    """Connected metatube → one proxy-only entry with path_prefix + port."""
    metatube_state.connect("http://127.0.0.1:8900", "", [])
    try:
        entries = proxy_dynamic_hosts()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.host == "127.0.0.1"
        assert entry.match == "exact"
        assert entry.schemes == ("http",)
        assert entry.consumers == ("proxy",)
        assert entry.photo_source is None
        assert entry.path_prefix == "/v1/images/"
        assert entry.port == 8900
    finally:
        metatube_state.disconnect()


def test_proxy_dynamic_hosts_empty_when_not_connected():
    """Never connected / after disconnect → empty tuple."""
    metatube_state.disconnect()  # ensure clean
    assert proxy_dynamic_hosts() == ()
    metatube_state.connect("http://127.0.0.1:8900", "", [])
    metatube_state.disconnect()
    assert proxy_dynamic_hosts() == ()


def test_proxy_dynamic_hosts_path_prefix_includes_reverse_proxy_base_path():
    """base_url with a path prefix → path_prefix = base_path + /v1/images/ (裁決 3)."""
    metatube_state.connect("http://host.example/metatube", "", [])
    try:
        entries = proxy_dynamic_hosts()
        assert len(entries) == 1
        assert entries[0].path_prefix == "/metatube/v1/images/"
    finally:
        metatube_state.disconnect()


def test_download_hosts_for_unaffected_by_metatube_connection():
    """AC5b: download_hosts_for() four sources unchanged while metatube is connected."""
    before = {
        src: download_hosts_for(src)
        for src in ("graphis", "gfriends", "wiki", "xcity")
    }
    metatube_state.connect("http://127.0.0.1:8900", "", ["FANZA"])
    try:
        for src, expected in before.items():
            assert download_hosts_for(src) == expected
    finally:
        metatube_state.disconnect()


def test_proxy_dynamic_hosts_malformed_port_in_base_url_yields_no_entry():
    """base_url 的 port 畸形時，`.port` 會拋 ValueError（urlparse 本身不會）。

    fail-closed：那台 metatube 我們釘不出 port，就不該產生條目——否則退化成
    「該 host 上任意 port 都放行」，正是裁決 1 要堵的形狀。
    """
    from unittest.mock import patch
    for bad in ("http://127.0.0.1:99999", "http://127.0.0.1:abc"):
        with patch("core.metatube.state.metatube_state.connected_base_url",
                   return_value=bad):
            assert proxy_dynamic_hosts() == (), bad


# ---------------------------------------------------------------------------
# 巢狀抓取目標（Codex PR#128 round-2 P3）
# ---------------------------------------------------------------------------
# metatube 的 /v1/images/ 端點會**自己去抓** `?url=` 指的目標，外層白名單看不到
# 那一層。這組鎖的是「哪些巢狀目標可以放行」——判準的單一所有者在 registry。

_REAL_PREVIEW_QUERY = (
    "url=https%3A%2F%2Fmy.cdn.tokyo-hot.com%2Fmedia%2Fn1749%2Fjacket%2Fn1749.jpg"
    "&ratio=0&quality=100"
)

_NESTED_ALLOW = [
    ("真實 preview URL 的 query（實跑 metatube 產出的那一份，不可誤殺）",
     _REAL_PREVIEW_QUERY),
    ("公開 http 圖床（並非只放行 https——provider 圖床不保證 https）",
     "url=http%3A%2F%2Fcdn.example.com%2Fa.jpg&ratio=0&quality=100"),
    # 實測：metatube 不帶 `?url=` 時自己從 DB 查封面並回 200（878KB）。
    # 這兩個形狀**沒有巢狀抓取**，本閘門無事可管——擋它們只會誤殺 T3a 的正向對照。
    ("空 query（無巢狀目標）", ""),
]

_NESTED_DENY = [
    ("loopback", "url=http%3A%2F%2F127.0.0.1%3A6379%2F&ratio=0&quality=100"),
    # `ipaddress.ip_address('::ffff:127.0.0.1').is_loopback` 是 False——不解回
    # IPv4 就會漏掉（同 web/app.py:264 的教訓）
    ("IPv4-mapped IPv6",
     "url=http%3A%2F%2F%5B%3A%3Affff%3A127.0.0.1%5D%2Fx.png&ratio=0&quality=100"),
    ("裸內網主機名（公開 CDN 一定帶點）",
     "url=http%3A%2F%2Fnas%2Fphoto.jpg&ratio=0&quality=100"),
    ("file scheme", "url=file%3A%2F%2F%2Fetc%2Fpasswd&ratio=0&quality=100"),
    # 只放行「我們自己會產生的形狀」比列舉危險 key 可證偽（同 T3a 正向字元集）
    ("多餘的 key", _REAL_PREVIEW_QUERY + "&evil=1"),
    ("兩個 url（第二個夾帶內網目標）",
     _REAL_PREVIEW_QUERY + "&url=http%3A%2F%2F127.0.0.1%2F"),
]


@pytest.mark.parametrize("label,query", _NESTED_ALLOW, ids=[c[0] for c in _NESTED_ALLOW])
def test_nested_preview_target_allowed_accepts_real_shapes(label, query):
    """正向那半：誤殺會讓破圖修復本身失效，所以第一條餵的是實跑產出的真 query。"""
    assert nested_preview_target_allowed(query) is True, label


@pytest.mark.parametrize("label,query", _NESTED_DENY, ids=[c[0] for c in _NESTED_DENY])
def test_nested_preview_target_rejects_non_public_targets(label, query):
    """反向那半：擋的是「metatube 綁 loopback ＋ OpenAver 開區網」那條橋。"""
    assert nested_preview_target_allowed(query) is False, label


def test_validate_photo_url_xcity():
    """TASK-157-T2: validate_photo_url 對 xcity host 正確放行/拒絕。"""
    assert validate_photo_url(
        "https://faws.xcity.jp/actress/large/image/person/12345.jpg", "xcity"
    ) is True
    assert validate_photo_url("https://evil.example.com/x.jpg", "xcity") is False


