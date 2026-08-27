"""Live smoke canary — 8 source health check (TASK-73b-T3).

Wires the T1 pure decision-core (`classify_one` / `quorum_verdict`) and the T2
evergreen number list (`CANARY_NUMBERS`) into a live smoke suite: one
`test_{source}_canary` per source, each running the real `search()` over its
numbers, adding a reachability probe for Group A, and turning the quorum verdict
into pytest pass / skip / fail.

ZERO production scraper changes. The deterministic judgement logic is covered by
`tests/unit/test_source_canary_logic.py` (runs in CI, no network). This file is
the live shell only — it must NOT be collected by the standard PR command
(`--ignore=tests/smoke -m "not smoke and not e2e"`).

verdict mapping:
  green -> pass (source alive)
  skip  -> pytest.skip (unreachable / known-dead / proxy not configured)
  red   -> pytest.fail (200-but-empty parse, or returned wrong/empty Video)
"""
import pytest

from tests.smoke._canary_core import classify_one, quorum_verdict, GROUP_A
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from tests.smoke._canary_numbers import CANARY_NUMBERS
from tests.smoke._probe import _probe_reachable
from core.scrapers import (
    JavBusScraper,
    JAV321Scraper,
    HEYZOScraper,
    D2PassScraper,
    FC2OfficialScraper,
    JavDBScraper,
    AVSOXScraper,
    DMMScraper,
)

pytestmark = pytest.mark.smoke


def _run_canary(source: str, scraper, note: str = "", method: str = "search") -> None:
    """Run the canary for one source: loop numbers -> classify -> quorum -> verdict.

    quorum needs every number's result before deciding, so this is a per-source
    loop (NOT pytest.parametrize).

    `note` (optional) prepends a source-specific hint to the skip/fail reason so a
    human reading `pytest -r s` can tell an *expected* skip (avsox known-dead,
    javdb CF-ban) from an incidental one — without touching the pure T1 core.

    `method` is the scraper method name to call (string + getattr on purpose:
    a typo surfaces as AttributeError instead of a silent wrong lambda).
    """
    results = []
    for number in CANARY_NUMBERS[source]:
        try:
            video = getattr(scraper, method)(number)
        except TimeoutError as e:
            # Feed the exception instance (not None) so classify_one row 1 -> skip.
            results.append(classify_one(e, None, number, source))
            continue
        except (SourceUnreachable, SourceBlocked):
            # Transport-level failure (CF ban / cannot connect). Until 0.15.1 these
            # were swallowed into `None` inside javdb's `_get_html`; typed exceptions
            # (TASK-132a-T2) made them escape `search()` and blow straight past the
            # `except TimeoutError` above, turning the *expected* javdb CF-ban skip
            # into a hard ERROR. Collapsing to `video = None` restores the pre-0.15.1
            # input shape EXACTLY — including the Group A probe below, so a Group A
            # source keeps its row-4 (reachable but empty -> fail) verdict rather
            # than being silently downgraded to skip.
            #
            # NOTE for 132b: this restores the *input*, it does NOT hand out the
            # "all skip = normal" exemption — that comes from Group B membership in
            # `_canary_core.GROUP_B`. The new API canary must NOT join Group B
            # (spec-132 F5: it never touches CF, so all-skip means it is really dead).
            video = None
        probe = _probe_reachable(source, number, scraper) if source in GROUP_A else None
        results.append(classify_one(video, probe, number, source))

    verdict, reason = quorum_verdict(results)
    if verdict == "green":
        return
    hint = f"{note} — " if note else ""
    if verdict == "skip":
        pytest.skip(f"{source}: {hint}{reason}")
    pytest.fail(f"{source}: {hint}{reason}")


# ========== Group A (probe-backed) ==========

def test_javbus_canary():
    _run_canary("javbus", JavBusScraper())


def test_jav321_canary():
    _run_canary("jav321", JAV321Scraper())


def test_heyzo_canary():
    _run_canary("heyzo", HEYZOScraper())


def test_d2pass_canary():
    _run_canary("d2pass", D2PassScraper())


def test_avsox_canary():
    # Group A (probe-backed): _ensure_session() probe distinguishes site-down (skip)
    # from 200-but-empty-parse (fail). avsox revived via JSON API (US5).
    _run_canary("avsox", AVSOXScraper(), note="avsox revived (JSON API)")


# ========== Group B (quorum-only, no probe) ==========

def test_fc2_canary():
    _run_canary("fc2", FC2OfficialScraper())


def test_javdb_canary():
    # javdb needs curl_cffi (CF bypass). Numbers are deliberately few -> all-skip
    # must not fail (Group B quorum: None probe -> row 6 skip).
    # Hits search_via_html only — the API path has its own canary (Group A).
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        pytest.skip("curl_cffi not installed")
    _run_canary(
        "javdb",
        JavDBScraper(),
        note="javdb all-skip likely CF-banned",
        method="search_via_html",
    )


def test_javdb_api_canary():
    # Group A: never touches Cloudflare, so all-skip means the API path is dead.
    _run_canary("javdb-api", JavDBScraper(), method="search_via_api")

    # 判綠之後才做：抓一張封面 → 走 production 的 host→codec 對應解碼 → 驗魔數。
    # 「解碼規則／host 對應壞了」在 runtime 沒有偵測器（CD-132b-7 說明了為什麼不在
    # 搜尋時驗），這顆燈就是那個偵測器。沒有它，使用者會是第一個發現的人。
    from urllib.parse import urlparse

    import requests

    from core.image_codec import decode_image_payload, looks_like_image

    video = JavDBScraper().search_via_api(CANARY_NUMBERS["javdb-api"][0])
    if video is None or not video.cover_url:
        pytest.skip("javdb-api: 拿不到封面網址（上面的 quorum 已經判過了）")
    host = urlparse(video.cover_url).hostname or ""
    try:
        raw = requests.get(video.cover_url, timeout=20).content
    except requests.exceptions.RequestException as e:
        # 連不到圖床是**站方／網路**問題，不是「我們的解碼規則壞了」。
        # 不 try/except 的話這裡會變成 pytest ERROR，人工讀報表時分不出是哪一種（review P3）。
        pytest.skip(f"javdb-api: 連不到圖床（{type(e).__name__}）——非解碼問題")
    payload = decode_image_payload(host, raw)
    if not looks_like_image(payload):
        pytest.fail(
            f"javdb-api: 封面解不開（host={host}, raw={len(raw)}B, payload={len(payload)}B）"
            " — host→codec 對應或解碼規則可能失效"
        )


# ========== dmm (proxy-gated, 4-way) ==========

def test_dmm_canary():
    from core.config import load_config
    from core.scraper import _dmm_proxy_url, _is_dmm_enabled
    from core.scrapers.models import ScraperConfig

    raw = (load_config().get("search") or {}).get("proxy_url") or ""
    if not _is_dmm_enabled(raw):
        pytest.skip("dmm proxy 未設定")
    scraper = DMMScraper(ScraperConfig(proxy_url=_dmm_proxy_url(raw)))
    _run_canary("dmm", scraper)
