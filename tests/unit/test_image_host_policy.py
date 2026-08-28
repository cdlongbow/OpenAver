"""
Unit tests for core/image_host_policy.py (TASK-113c-T1 / T3a).

Expectation values are hardcoded from plan §1.3 / task-card reconciliation
table (CD-113c-3). Do NOT derive them from IMAGE_HOSTS.
"""
from __future__ import annotations

from urllib.parse import urlparse

import pytest

from core.image_host_policy import (
    IMAGE_HOSTS,
    ImageHost,
    download_hosts_for,
    nested_preview_target_allowed,
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
        "tp.spfcas.com",  # TASK-132b-T4: javdb App API image host
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
    assert len(IMAGE_HOSTS) == 29  # +1 tp.spfcas.com (TASK-132b-T4)

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
    ("key 順序不同", "quality=100&url=https%3A%2F%2Fcdn.example.com%2Fa.jpg&ratio=0"),
    # 實測：metatube 不帶 `?url=` 時自己從 DB 查封面並回 200（878KB）。
    # 這兩個形狀**沒有巢狀抓取**，本閘門無事可管——擋它們只會誤殺 T3a 的正向對照。
    ("空 query（無巢狀目標）", ""),
    ("只有 ratio/quality（無巢狀目標）", "ratio=0&quality=100"),
]

_NESTED_DENY = [
    ("loopback", "url=http%3A%2F%2F127.0.0.1%3A6379%2F&ratio=0&quality=100"),
    ("127.0.0.0/8 其餘位址", "url=http%3A%2F%2F127.5.5.5%2Fx.png&ratio=0&quality=100"),
    ("私有網段", "url=http%3A%2F%2F192.168.1.1%2Fadmin.png&ratio=0&quality=100"),
    ("私有網段 10/8", "url=http%3A%2F%2F10.0.0.5%3A8080%2Fx.png&ratio=0&quality=100"),
    ("IPv6 loopback", "url=http%3A%2F%2F%5B%3A%3A1%5D%2Fx.png&ratio=0&quality=100"),
    # `ipaddress.ip_address('::ffff:127.0.0.1').is_loopback` 是 False——不解回
    # IPv4 就會漏掉（同 web/app.py:264 的教訓）
    ("IPv4-mapped IPv6",
     "url=http%3A%2F%2F%5B%3A%3Affff%3A127.0.0.1%5D%2Fx.png&ratio=0&quality=100"),
    ("link-local（雲端 metadata 服務的經典目標）",
     "url=http%3A%2F%2F169.254.169.254%2Flatest%2Fmeta-data&ratio=0&quality=100"),
    ("裸內網主機名（公開 CDN 一定帶點）",
     "url=http%3A%2F%2Fnas%2Fphoto.jpg&ratio=0&quality=100"),
    ("localhost 字面", "url=http%3A%2F%2Flocalhost%3A8080%2Fx.png&ratio=0&quality=100"),
    ("file scheme", "url=file%3A%2F%2F%2Fetc%2Fpasswd&ratio=0&quality=100"),
    ("data scheme", "url=data%3Atext%2Fplain%2Chi&ratio=0&quality=100"),
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


def test_nested_preview_target_residual_dns_name_resolving_private_is_not_covered():
    """**明示殘留**：解析成私有位址的公開網域名擋不掉（這裡不做 DNS 解析）。

    寫成一條會過的測試而不是留在註解裡，是為了讓這個缺口**被宣告**——
    哪天有人補了 DNS 檢查（或改成簽章預覽 URL），這條會轉紅並指向該重寫的地方。
    """
    q = "url=https%3A%2F%2Finternal.example.com%2Fx.png&ratio=0&quality=100"
    assert nested_preview_target_allowed(q) is True, (
        "若這條轉紅，代表已經加了 DNS 解析或簽章——請更新本測試與 "
        "nested_preview_target_allowed() 的殘留說明"
    )
