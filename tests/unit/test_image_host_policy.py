"""
Unit tests for core/image_host_policy.py (TASK-113c-T1).

Expectation values are hardcoded from plan §1.3 / task-card reconciliation
table (CD-113c-3). Do NOT derive them from IMAGE_HOSTS.
"""
from __future__ import annotations

from core.image_host_policy import (
    IMAGE_HOSTS,
    ImageHost,
    download_hosts_for,
    proxy_rules,
)


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
