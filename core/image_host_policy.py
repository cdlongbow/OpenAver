"""
Declarative image-host policy registry (TASK-113c-T1 / CD-113c-1).

Single source of truth for which hosts may be used by the download consumer
(core/actress_photo.py) and/or the proxy consumer (web/routers/search.py).

Consumers export their own minimal-permission views via download_hosts_for()
and proxy_rules(). Matching mechanism differences (exact-only vs exact+root,
http+https vs https-only, photo_source binding) stay at the call sites —
this module only declares hosts, it does not evaluate URLs.

`match="exact"` 不允子域是刻意的（**CD-60-1**：CDN / 女優照片的固定 host 嚴格匹配）；
`match="root"` 才走呼叫端的 `host == root or host.endswith("." + root)` 邊界比對。
兩端的允許集合**本來就不相等**（CD-113c-2）——registry 的價值是讓「不相等」變成
被宣告的，不是把它們統一。
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ImageHost:
    host: str
    match: str  # "exact" | "root"
    schemes: tuple[str, ...]
    consumers: tuple[str, ...]  # "download" | "proxy" (any non-empty subset)
    photo_source: str | None  # download consumer only; proxy-only → None
    # T3a: optional constraints for dynamic (and future) entries. Static rows
    # keep defaults — path_prefix/port None means "no extra check".
    path_prefix: str | None = None
    port: int | None = None


# Static translation of the two pre-T1 whitelists (+ T3a cf.javfree.me).
# Dynamic metatube entries come from proxy_dynamic_hosts(), not this tuple.
IMAGE_HOSTS: tuple[ImageHost, ...] = (
    # ---- download + proxy (shared exact hosts; schemes upper-bound) ----
    ImageHost(
        host="www.graphis.ne.jp",
        match="exact",
        schemes=("http", "https"),
        consumers=("download", "proxy"),
        photo_source="graphis",
    ),
    ImageHost(
        host="graphis.ne.jp",
        match="exact",
        schemes=("http", "https"),
        consumers=("download", "proxy"),
        photo_source="graphis",
    ),
    ImageHost(
        host="data.graphis.ne.jp",
        match="exact",
        schemes=("http", "https"),
        consumers=("download", "proxy"),
        photo_source="graphis",
    ),
    ImageHost(
        host="cdn.jsdelivr.net",
        match="exact",
        schemes=("http", "https"),
        consumers=("download", "proxy"),
        photo_source="gfriends",
    ),
    ImageHost(
        host="upload.wikimedia.org",
        match="exact",
        schemes=("http", "https"),
        consumers=("download", "proxy"),
        photo_source="wiki",
    ),
    ImageHost(
        host="www.minnano-av.com",
        match="exact",
        schemes=("http", "https"),
        consumers=("download", "proxy"),
        photo_source="minnano",
    ),
    ImageHost(
        host="minnano-av.com",
        match="exact",
        schemes=("http", "https"),
        consumers=("download", "proxy"),
        photo_source="minnano",
    ),
    # ---- download-only (exact; not proxied) ----
    ImageHost(
        host="raw.githubusercontent.com",
        match="exact",
        schemes=("http", "https"),
        consumers=("download",),
        photo_source="gfriends",
    ),
    ImageHost(
        host="github.com",
        match="exact",
        schemes=("http", "https"),
        consumers=("download",),
        photo_source="gfriends",
    ),
    ImageHost(
        host="ja.wikipedia.org",
        match="exact",
        schemes=("http", "https"),
        consumers=("download",),
        photo_source="wiki",
    ),
    # ---- proxy-only exact ----
    ImageHost(
        host="pics.dmm.co.jp",
        match="exact",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="awsimgsrc.dmm.co.jp",
        match="exact",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="www.dmm.co.jp",
        match="exact",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="javdb.com",
        match="exact",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="file.netcdn.space",  # AVSOX 圖床（caribbean / 1pondo / heyzo 封面 CDN）
        match="exact",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    # ---- proxy-only root domains (subdomain boundary match at call site) ----
    ImageHost(
        host="javbus.com",
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="jav321.com",
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="heyzo.com",
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="caribbeancom.com",
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="1pondo.tv",
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="10musume.com",
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="avsox.click",
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="avsox.monster",
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="avsox.website",
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="javten.com",
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="fc2.com",  # FC2 圖床（contents-thumbnail2 / live-storage / storage<NNN>.contents 數字子域）
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    ImageHost(
        host="jdbstatic.com",  # JavDB CDN root（c0/c1/c2 numbered subdomains）
        match="root",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
    # ---- T3a: sole §1.4-enumerated new host (exact CDN subdomain only) ----
    ImageHost(
        host="cf.javfree.me",
        match="exact",
        schemes=("https",),
        consumers=("proxy",),
        photo_source=None,
    ),
)


def download_hosts_for(photo_source: str) -> set[str]:
    """Hosts allowed for actress-photo download for a given photo_source.

    Unknown photo_source → empty set (fail-closed). Scheme filtering stays
    in validate_photo_url(); this returns host names only.
    """
    return {
        entry.host
        for entry in IMAGE_HOSTS
        if "download" in entry.consumers and entry.photo_source == photo_source
    }


def proxy_rules() -> tuple[frozenset[str], tuple[str, ...]]:
    """Return (exact_hosts, root_domains) for the image proxy allowlist.

    Recomputed on every call (no module-level cache) so later dynamic
    entries can be attached without stale snapshots. Scheme enforcement
    (https-only) stays in _is_allowed_image_url().
    """
    exact: set[str] = set()
    roots: list[str] = []
    for entry in IMAGE_HOSTS:
        if "proxy" not in entry.consumers:
            continue
        if entry.match == "exact":
            exact.add(entry.host)
        elif entry.match == "root":
            roots.append(entry.host)
    return frozenset(exact), tuple(roots)


def proxy_dynamic_hosts() -> tuple[ImageHost, ...]:
    """Dynamic proxy-only entries whose value comes from live connection
    state (currently: the connected metatube server, if any).

    Recomputed on every call — no caching — so a mid-request disconnect
    immediately withdraws the entry (plan §5 residual-6: intentional).
    Empty tuple when connected_base_url() is None (never connected /
    connect() called with an empty base_url / after disconnect()).
    """
    # Local import keeps module import graph free of state-side effects at
    # import time; registry is the only allowed consumer of this accessor.
    from core.metatube.state import metatube_state

    base = metatube_state.connected_base_url()
    if not base:
        return ()
    try:
        parsed = urlparse(base)
    except Exception:
        return ()
    host = (parsed.hostname or "").lower()
    if not host:
        return ()
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return ()
    # `.port` raises ValueError on a malformed port even when urlparse()
    # succeeded (BE-SEC-01 family). A base_url we cannot pin to a port must
    # not become an entry at all — fail-closed beats "any port on that host".
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return ()
    base_path = parsed.path or ""
    # 裁決 3: reverse-proxy base_url may carry a path prefix.
    path_prefix = base_path.rstrip("/") + "/v1/images/"
    return (
        ImageHost(
            host=host,
            match="exact",
            schemes=(scheme,),
            consumers=("proxy",),
            photo_source=None,
            path_prefix=path_prefix,
            port=port,
        ),
    )
