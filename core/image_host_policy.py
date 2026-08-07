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


@dataclass(frozen=True, slots=True)
class ImageHost:
    host: str
    match: str  # "exact" | "root"
    schemes: tuple[str, ...]
    consumers: tuple[str, ...]  # "download" | "proxy" (any non-empty subset)
    photo_source: str | None  # download consumer only; proxy-only → None


# Static translation of the two pre-T1 whitelists (zero behavior change).
# Dynamic entries (metatube) and new hosts (cf.javfree.me) are later tasks.
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
