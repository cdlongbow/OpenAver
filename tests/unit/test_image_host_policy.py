"""
Unit tests for core/image_host_policy.py (TASK-113c-T1 / T3a).

Expectation values are hardcoded from plan §1.3 / task-card reconciliation
table (CD-113c-3). Do NOT derive them from IMAGE_HOSTS.
"""
from __future__ import annotations

from urllib.parse import urlparse

from core.image_host_policy import (
    IMAGE_HOSTS,
    ImageHost,
    download_hosts_for,
    proxy_dynamic_hosts,
    proxy_rules,
)
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
    assert download_hosts_for("minnano") == {
        "www.minnano-av.com",
        "minnano-av.com",
    }


def test_proxy_rules_matches_reconciliation_table():
    """proxy_rules() must match §1.3 proxy-side exact + root sets exactly."""
    exact, roots = proxy_rules()

    assert exact == frozenset({
        "pics.dmm.co.jp",
        "awsimgsrc.dmm.co.jp",
        "www.dmm.co.jp",
        "javdb.com",
        "cdn.jsdelivr.net",
        "upload.wikimedia.org",
        "data.graphis.ne.jp",
        "www.graphis.ne.jp",
        "graphis.ne.jp",
        "www.minnano-av.com",
        "minnano-av.com",
        "file.netcdn.space",
        "cf.javfree.me",  # TASK-113c-T3a: §1.4 sole enumerated new host
    })
    assert set(roots) == {
        "javbus.com",
        "jav321.com",
        "heyzo.com",
        "caribbeancom.com",
        "1pondo.tv",
        "10musume.com",
        "avsox.click",
        "avsox.monster",
        "avsox.website",
        "javten.com",
        "fc2.com",
        "jdbstatic.com",
    }
    # roots must be a tuple (stable export shape), not a set
    assert isinstance(roots, tuple)
    assert isinstance(exact, frozenset)


# ---------------------------------------------------------------------------
# DoD-1b: schemes / field consistency on IMAGE_HOSTS
# ---------------------------------------------------------------------------

def test_image_hosts_schemes_and_field_consistency():
    """Declarative fields must not silently drift from consumer policies."""
    assert len(IMAGE_HOSTS) > 0
    for entry in IMAGE_HOSTS:
        assert isinstance(entry, ImageHost)
        assert entry.match in ("exact", "root")

        if "proxy" in entry.consumers:
            assert "https" in entry.schemes

        if "download" in entry.consumers:
            assert {"http", "https"} <= set(entry.schemes)
            assert entry.match == "exact"

        # photo_source is None iff download is not a consumer
        if entry.photo_source is None:
            assert "download" not in entry.consumers
        else:
            assert "download" in entry.consumers


# ---------------------------------------------------------------------------
# DoD-3: mechanism differences preserved at export layer
# ---------------------------------------------------------------------------

def test_download_hosts_for_unknown_source_fail_closed():
    """Unknown photo_source → empty set (fail-closed), never None/raise."""
    result = download_hosts_for("nonexistent_source")
    assert result == set()
    assert isinstance(result, set)


def test_download_hosts_for_exact_only_no_root_match():
    """Every download-side host comes from match=='exact' entries only."""
    for source in ("graphis", "gfriends", "wiki", "minnano"):
        hosts = download_hosts_for(source)
        for host in hosts:
            matching = [
                e for e in IMAGE_HOSTS
                if e.host == host
                and "download" in e.consumers
                and e.photo_source == source
            ]
            assert matching, f"no download entry for {source}/{host}"
            assert all(e.match == "exact" for e in matching)


def test_proxy_rules_exports_root_domains_for_boundary_matching():
    """proxy_rules() must export root domains used by endswith boundary match."""
    exact, roots = proxy_rules()
    # root-domain info present (not collapsed into exact)
    assert "fc2.com" in roots
    assert "javbus.com" in roots
    assert "jdbstatic.com" in roots
    # lookalike-sensitive exact hosts stay exact-only
    assert "file.netcdn.space" in exact
    assert "file.netcdn.space" not in roots
    # no accidental overlap between exact and root exports
    assert exact.isdisjoint(set(roots))


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


def test_proxy_dynamic_hosts_scheme_matches_base_url_scheme_http():
    """schemes is a single-value tuple of the live base_url scheme (http)."""
    metatube_state.connect("http://192.168.1.10:8900", "", [])
    try:
        entries = proxy_dynamic_hosts()
        assert len(entries) == 1
        assert entries[0].schemes == ("http",)
    finally:
        metatube_state.disconnect()


def test_proxy_dynamic_hosts_scheme_matches_base_url_scheme_https():
    """schemes is a single-value tuple of the live base_url scheme (https)."""
    metatube_state.connect("https://mt.example.com:8443", "", [])
    try:
        entries = proxy_dynamic_hosts()
        assert len(entries) == 1
        assert entries[0].schemes == ("https",)
        assert entries[0].host == "mt.example.com"
        assert entries[0].port == 8443
    finally:
        metatube_state.disconnect()


def test_proxy_dynamic_hosts_path_prefix_includes_reverse_proxy_base_path():
    """base_url with a path prefix → path_prefix = base_path + /v1/images/ (裁決 3)."""
    metatube_state.connect("http://host.example/metatube", "", [])
    try:
        entries = proxy_dynamic_hosts()
        assert len(entries) == 1
        assert entries[0].path_prefix == "/metatube/v1/images/"
    finally:
        metatube_state.disconnect()


def test_proxy_dynamic_hosts_path_prefix_strips_trailing_slash_on_base():
    """base_url ending with / → rstrip before appending /v1/images/."""
    metatube_state.connect("http://host.example/metatube/", "", [])
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
        for src in ("graphis", "gfriends", "wiki", "minnano")
    }
    metatube_state.connect("http://127.0.0.1:8900", "", ["FANZA"])
    try:
        for src, expected in before.items():
            assert download_hosts_for(src) == expected
    finally:
        metatube_state.disconnect()


def test_static_image_hosts_never_have_path_prefix_or_port():
    """IMAGE_HOSTS static entries keep path_prefix/port defaults (None)."""
    for entry in IMAGE_HOSTS:
        assert entry.path_prefix is None
        assert entry.port is None


def test_cf_javfree_me_in_static_proxy_exact():
    """cf.javfree.me is the sole §1.4 new host: proxy exact, https-only."""
    matches = [e for e in IMAGE_HOSTS if e.host == "cf.javfree.me"]
    assert len(matches) == 1
    entry = matches[0]
    assert entry.match == "exact"
    assert entry.schemes == ("https",)
    assert entry.consumers == ("proxy",)
    assert entry.photo_source is None
    exact, roots = proxy_rules()
    assert "cf.javfree.me" in exact
    assert "cf.javfree.me" not in roots


def test_registry_truth_table_download_and_proxy_consumers():
    """Walk every IMAGE_HOSTS row × (download, proxy) + one live dynamic row."""
    assert len(IMAGE_HOSTS) == 28

    for entry in IMAGE_HOSTS:
        download_allowed = "download" in entry.consumers
        proxy_allowed = "proxy" in entry.consumers

        if download_allowed:
            assert entry.photo_source is not None
            assert entry.host in download_hosts_for(entry.photo_source)
        else:
            # not selected by any known photo_source download view
            for src in ("graphis", "gfriends", "wiki", "minnano"):
                assert entry.host not in download_hosts_for(src)

        exact, roots = proxy_rules()
        if proxy_allowed:
            if entry.match == "exact":
                assert entry.host in exact
            else:
                assert entry.host in roots
        else:
            assert entry.host not in exact
            assert entry.host not in roots

    # Dynamic metatube row (not in IMAGE_HOSTS): proxy-only, download never
    metatube_state.connect("http://10.0.0.5:8900", "", [])
    try:
        dyn = proxy_dynamic_hosts()
        assert len(dyn) == 1
        d = dyn[0]
        assert "proxy" in d.consumers
        assert "download" not in d.consumers
        for src in ("graphis", "gfriends", "wiki", "minnano"):
            assert d.host not in download_hosts_for(src)
        # not in static proxy_rules host strings (hostname alone may collide
        # only if a static entry used the same host — 10.0.0.5 won't)
        exact, roots = proxy_rules()
        assert d.host not in exact or d.port is not None
        assert d.path_prefix == "/v1/images/"
        assert d.port == 8900
        assert d.schemes == ("http",)
        # sanity: hostname of connected base matches
        assert d.host == urlparse("http://10.0.0.5:8900").hostname
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
