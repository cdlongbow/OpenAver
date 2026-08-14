"""Live smoke canary — actress source health check (TASK-118a-T12).

Four independent sources: minnano_av / wiki_ja / graphis / gfriends. Each has
its own `test_{source}_canary` function; a dead source never drags down the
other three (owner hard constraint — see TASK-118a-T12 §技術要點).

This file deliberately does NOT import `tests/smoke/_canary_core.py` — owner
decision: the actress line writes its own simple per-source verdict logic
instead of generalizing the video-line quorum core for one more consumer
(TASK-118a-T12 §Test Strategy).

verdict semantics (self-contained here, mirrors `_canary_core.quorum_verdict`
in spirit but is its own independent implementation):
    >=1 pass              -> green (function returns normally, test passes)
    0 pass, >=1 fail       -> pytest.fail
    0 pass, all skip       -> pytest.skip

`usable()` is bound per-source to the exact field the orchestrator cascade
consumes (Opus 修正 ②, TASK-118a-T12) — NOT merely "is the result non-None".
For graphis specifically, `scrape_graphis_photo()` fail-opens its `model.php`
sub-parse (graphis.py:162-165), so a non-None return can still carry an empty
`prof_url`; `orchestrator.py:190` only ever consumes `prof_url`, so that is
what this canary checks too.

ZERO production scraper changes — this file only reads the four public
scrape/lookup entry points. Must NOT be collected by the standard PR command
(`--ignore=tests/smoke --ignore=tests/e2e -m "not smoke and not e2e"`).
"""
import pytest
import requests

from core.scrapers.actress.minnano_av import scrape_minnano_av
from core.scrapers.actress.wiki_ja import scrape_wiki_ja
from core.scrapers.actress.graphis import scrape_graphis_photo
from core.scrapers.actress.gfriends import lookup_gfriends
from core.scrapers.actress.orchestrator import _has_meaningful_text

pytestmark = pytest.mark.smoke

# Evergreen names — 2026-08-14 research: 12/12 live hits across all 4 sources
# (see TASK-118a-T12 §3×4 實測矩陣). No replacements needed at this time.
EVERGREEN_NAMES = ["三上悠亜", "波多野結衣", "明日花キララ"]

# Bare `requests` UA gets 403'd by minnano-av.com / ja.wikipedia.org (research
# finding, TASK-118a-T12 §探測設計) — probes must look like a real browser.
_BROWSER_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

_PROBE_TIMEOUT = 10  # seconds, matches tests/smoke/_probe.py convention

# gfriends probe target MUST be a repo file, not the Content/ directory root —
# jsDelivr 403s directory listings unconditionally (site-liveness-independent),
# so probing the dir root would misreport a healthy CDN as dead (research
# finding, TASK-118a-T12 §探測設計).
_GFRIENDS_PROBE_URL = "https://cdn.jsdelivr.net/gh/gfriends/gfriends@master/README.md"


# ========== Reachability probes (source-level, not per-name) ==========
# Each of the four sources is probed ONCE per test run (not once per
# EVERGREEN_NAMES entry) — reachability doesn't depend on which name is being
# queried, a site isn't down "for one specific name" (TASK-118a-T12 §探測設計,
# deliberately different from the per-number probes on the video canary line).
#
# CONTRACT: every probe below MUST NEVER raise. Any exception (DNS failure,
# connection refused, timeout, TLS error, ...) -> return False (=
# "unreachable" -> skip), never propagate.

def _probe_minnano_av() -> bool:
    try:
        resp = requests.get(
            "https://www.minnano-av.com", headers=_BROWSER_UA, timeout=_PROBE_TIMEOUT
        )
        return resp.status_code == 200
    except Exception:
        return False


def _probe_wiki_ja() -> bool:
    try:
        resp = requests.get(
            "https://ja.wikipedia.org/", headers=_BROWSER_UA, timeout=_PROBE_TIMEOUT
        )
        return resp.status_code == 200
    except Exception:
        return False


def _probe_graphis() -> bool:
    try:
        resp = requests.get(
            "https://graphis.ne.jp/", headers=_BROWSER_UA, timeout=_PROBE_TIMEOUT
        )
        return resp.status_code == 200
    except Exception:
        return False


def _probe_gfriends() -> bool:
    try:
        resp = requests.get(_GFRIENDS_PROBE_URL, timeout=_PROBE_TIMEOUT)
        return resp.status_code == 200
    except Exception:
        return False


# ========== Self-contained verdict (NOT imported from _canary_core) ==========

def _classify(result, usable_fn, probe_reachable: bool) -> str:
    """One EVERGREEN_NAMES entry -> "pass" / "fail" / "skip"."""
    if usable_fn(result):
        return "pass"
    return "fail" if probe_reachable else "skip"


def _verdict(results, source_label: str, probe_desc: str) -> None:
    """Turn a list of "pass"/"fail"/"skip" into a pytest outcome.

    >=1 pass            -> green, just return (test passes)
    0 pass, >=1 fail     -> pytest.fail
    0 pass, all skip     -> pytest.skip

    The skip reason MUST carry `probe_desc` (the probe URL) — Opus 修正 ③:
    this canary's only real failure mode is the probe target itself rotting
    (e.g. the gfriends README.md getting renamed), which would silently and
    permanently skip that source forever while looking "fine". `pytest -rs`
    must be able to surface the URL so a human can tell "probe is broken"
    from "site is broken".
    """
    if "pass" in results:
        return
    if "fail" in results:
        pytest.fail(
            f"{source_label}: 0/{len(results)} pass, probe reachable "
            f"({probe_desc}) — 常青名字全部解析為空，可能站方改版或名字被下架"
        )
    pytest.skip(
        f"{source_label}: probe unreachable — 探測目標 {probe_desc} 連不上，"
        f"可能是站真的掛了，也可能探測目標本身壞了（需人工確認）"
    )


def _run_actress_canary(source_label, probe_fn, probe_desc, fetch_fn, usable_fn) -> None:
    """Shared per-source shape: probe once -> loop names -> classify -> verdict."""
    probe_reachable = probe_fn()
    results = [
        _classify(fetch_fn(name), usable_fn, probe_reachable)
        for name in EVERGREEN_NAMES
    ]
    _verdict(results, source_label, probe_desc)


# ========== Per-source canaries (four independent functions, no parametrize —
# a dead source must not drag down the other three) ==========

def test_minnano_av_canary():
    _run_actress_canary(
        "minnano_av",
        probe_fn=_probe_minnano_av,
        probe_desc="https://www.minnano-av.com",
        fetch_fn=scrape_minnano_av,
        usable_fn=_has_meaningful_text,
    )


def test_wiki_ja_canary():
    _run_actress_canary(
        "wiki_ja",
        probe_fn=_probe_wiki_ja,
        probe_desc="https://ja.wikipedia.org/",
        fetch_fn=scrape_wiki_ja,
        usable_fn=_has_meaningful_text,
    )


def test_graphis_canary():
    _run_actress_canary(
        "graphis",
        probe_fn=_probe_graphis,
        probe_desc="https://graphis.ne.jp/",
        # graphis fail-opens its model.php sub-parse — the photo cascade
        # (orchestrator.py:190) only ever consumes `prof_url`, so that is the
        # only field this canary treats as "usable" (Opus 修正 ②).
        fetch_fn=scrape_graphis_photo,
        usable_fn=lambda result: bool(result and result.get("prof_url")),
    )


def test_gfriends_canary():
    _run_actress_canary(
        "gfriends",
        probe_fn=_probe_gfriends,
        probe_desc=_GFRIENDS_PROBE_URL,
        # lookup_gfriends returns a bare URL string (or None) — not a dict
        # like the other three sources.
        fetch_fn=lookup_gfriends,
        usable_fn=lambda result: bool(result),
    )
