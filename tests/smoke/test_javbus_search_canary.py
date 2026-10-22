"""Live smoke canary — JavBus fuzzy search (TASK-175c-T11).

Guards the JavBus provider against site-side change AND against our own query
silently breaking: name -> entity resolve (actor / series), the full works list
of an entity (including titles without a magnet link), the `existmag=all`
cookie surviving a second page in the same session, the uncensored-prefix retry
(HEYZO), and names that contain a space.

Verdict: probe unreachable -> skip (reason starts with UNVERIFIED, which means
NOT verified, not passed). After the probe passes, ANY failure is a failure,
including SourceBlocked / SourceUnreachable (BE-PY-03). No retries. The first
403 / 429 (or a Cloudflare challenge page) stops the whole run: nothing more is
sent, every later cell fails (a block must never look like "unverified").

Live rules (owner 2026-10-22): every request goes through the proxy
http://192.168.1.177:8888/ via JavBusScraper's OWN session (BE-SCRAPER-08; a
bare `requests` call gets 200 without #waterfall), strictly serialized, >= 2.0 s
between two requests, hard cap 20 requests per pytest process. The throttle /
counter / recorder only measures and paces: it sits on the session's
`HTTPAdapter.send`, the one point every request actually sent passes through
(redirect hops included: `Session.resolve_redirects()` calls `Session.send()`
directly, so a wrapper around `session.get` would miss them), calls the real
send and returns its response untouched (it never mocks a response).

Self-contained: does not import tests/smoke/_canary_*.py. No site HTML/JSON is
stored; ids and counts come from the live site at run time and assertions only
compare what OUR code produced (ids, urls, cookie names, counts, strings).
"""
import threading
import time

import pytest

pytestmark = pytest.mark.smoke

_PROXY = "http://192.168.1.177:8888/"
_MIN_GAP = 2.0  # seconds from the end of one request to the start of the next
_MAX_CALLS = 20
_MIN_ITEMS = 20
_STOP_STATUS = frozenset({403, 429})
# Cloudflare interstitial markers. "challenge-platform" is deliberately NOT here: Cloudflare injects
# that script into normal pages too, so it would stop the run on a healthy 200.
_CHALLENGE_MARKERS = ("just a moment", "attention required! | cloudflare", "cf-browser-verification", "cf_chl_opt")

_STATE = {"calls": 0, "last_end": None, "min_gap": None, "stopped": None, "overflow": False, "armed": False,
          "actor_ref": None}
_LOG = []  # one dict per request actually sent (each redirect hop is its own entry): url, status, cookie, t0, t1  (no bodies)
_ERRORS = []  # (exception type, url) of every real send that raised after the probe
_CELLS = {}  # test name -> requests that cell sent
_LOCK = threading.Lock()


# ----------------------------------------------------------------------------- recorder / throttle
def _note_error(exc, url):
    """Remember a real exception of a request that was really sent (once per exception object)."""
    if not getattr(exc, "_canary_noted", False):
        _ERRORS.append((type(exc).__name__, url))
        exc._canary_noted = True


def _is_challenge(resp, stream):
    if resp.status_code != 200 or stream:
        return False
    text = resp.text.lower()
    return 'id="waterfall"' not in text and any(m in text for m in _CHALLENGE_MARKERS)


def _gate_session_adapters(scraper):
    """Gate EVERY request this scraper's own session actually sends: count, budget, stop flag, pacing, proxy check, record.

    The gate is on each mounted adapter's `send` (not on `session.get`): redirect hops go Session.resolve_redirects()
    -> Session.send() -> adapter.send() and never touch `session.get`, so they would bypass a get() wrapper.

    Layered on top, an outer wrapper around the WHOLE `session.request` only records exceptions (no counting, no pacing):
    requests reads the body AFTER adapter.send returned (and `_is_challenge` reads it inside the gate, outside its try),
    so a body transfer error / read timeout would never reach `_ERRORS`, and the provider layers swallow it (verify_page,
    _enrich_entity) - the cell would still pass.
    """
    from urllib.parse import urlparse

    from core.scrapers.errors import SourceBlocked

    def gate(real_send):
        def gated_send(request, **kwargs):
            with _LOCK:  # holds the whole real send: detail workers of verify_page / run_window are serialized
                if _STATE["stopped"]:
                    blocked = SourceBlocked(f"canary stopped, nothing more is sent: {_STATE['stopped']}")
                    blocked._canary_noted = True  # the stop flag already fails the cell; not also a "swallowed error"
                    raise blocked
                if _STATE["calls"] >= _MAX_CALLS:
                    _STATE["overflow"] = True
                    pytest.fail(f"超出請求預算 (cap {_MAX_CALLS})")
                # the home IP must never reach JavBus directly: refuse to send unless THIS request carries the proxy
                scheme = urlparse(request.url).scheme
                assert (kwargs.get("proxies") or {}).get(scheme) == _PROXY, (
                    "request is not routed through the proxy", request.url, kwargs.get("proxies"))
                _STATE["calls"] += 1
                if _STATE["last_end"] is not None:
                    wait = _STATE["last_end"] + _MIN_GAP - time.monotonic()
                    if wait > 0:
                        time.sleep(wait)
                t0 = time.monotonic()
                if _STATE["last_end"] is not None:
                    gap = t0 - _STATE["last_end"]
                    _STATE["min_gap"] = gap if _STATE["min_gap"] is None else min(_STATE["min_gap"], gap)
                try:
                    resp = real_send(request, **kwargs)
                except Exception as exc:
                    _note_error(exc, request.url)
                    _STATE["last_end"] = time.monotonic()
                    raise
                _STATE["last_end"] = time.monotonic()
                _LOG.append({
                    "url": request.url, "status": resp.status_code,
                    "cookie": request.headers.get("Cookie"), "t0": t0, "t1": _STATE["last_end"],
                })
                if resp.status_code in _STOP_STATUS or _is_challenge(resp, kwargs.get("stream")):
                    _STATE["stopped"] = f"HTTP {resp.status_code} {request.url}"
                return resp

        return gated_send

    for adapter in list(scraper._session.adapters.values()):
        adapter.send = gate(adapter.send)

    real_request = scraper._session.request

    def recorded_request(method, url, *args, **kwargs):
        try:
            return real_request(method, url, *args, **kwargs)
        except Exception as exc:  # recorded for the cell guard, then re-raised untouched
            _note_error(exc, url)
            raise

    scraper._session.request = recorded_request


@pytest.fixture(scope="module", autouse=True)
def _inject():
    """Swap core.scraper.JavBusScraper (use-site binding, BE-TEST-01) for a forced-proxy, recording subclass."""
    import core.scraper as scraper_mod
    from core.proxy_policy import ProxySettings
    from core.scrapers.javbus import JavBusScraper
    from core.scrapers.models import ScraperConfig

    class _ProxiedRecordingScraper(JavBusScraper):
        def __init__(self, config=None, lang="zh-tw"):
            super().__init__(ScraperConfig(proxy_settings=ProxySettings(url=_PROXY, scope="all")), lang=lang)
            _gate_session_adapters(self)

    mp = pytest.MonkeyPatch()
    mp.setattr(scraper_mod, "JavBusScraper", _ProxiedRecordingScraper)
    yield
    mp.undo()


@pytest.fixture(scope="module", autouse=True)
def _report(_inject):
    yield
    gap = _STATE["min_gap"]
    print(
        f"\n[javbus canary] requests={_STATE['calls']} (cap {_MAX_CALLS}) "
        f"min_gap={'n/a' if gap is None else f'{gap:.3f}s'} (floor {_MIN_GAP}s) "
        f"stopped={_STATE['stopped']} overflow={_STATE['overflow']} proxy={_PROXY} "
        f"per_cell={_CELLS}"
    )


@pytest.fixture(autouse=True)
def _cell_guard(request):
    """Per cell: count its requests; after the run, a stop / overflow / swallowed error that appeared DURING this cell fails it."""
    calls0, errors0 = _STATE["calls"], len(_ERRORS)
    was_stopped, was_overflow = bool(_STATE["stopped"]), _STATE["overflow"]
    yield
    _CELLS[request.node.name] = _STATE["calls"] - calls0
    if not _STATE["armed"]:
        return
    if _STATE["overflow"] and not was_overflow:
        pytest.fail(f"超出請求預算 (cap {_MAX_CALLS})")
    if _STATE["stopped"] and not was_stopped:
        pytest.fail(f"停手: 第一次被擋 {_STATE['stopped']}（其後不再送出任何請求；被擋不是未驗證）")
    if len(_ERRORS) > errors0:
        # verify_page / run_window / search_jav swallow per-detail exceptions; a real get() error after the probe must still fail
        pytest.fail(f"探針後 adapter.send 拋例外（上層會吞掉，這裡補抓）: {_ERRORS[errors0:]}")


def _require_live():
    """First line of every cell: once a block was seen nothing else is sent and the cell fails (never skips)."""
    if _STATE["stopped"]:
        pytest.fail(f"停手: 先前已被擋 {_STATE['stopped']}，本格不送任何請求")


def _no_encoded_space(records):
    # requests encodes a bare space to %20 when it prepares the URL, so checking the prepared (really sent) URL covers both
    bad = [r["url"] for r in records if "%20" in r["url"] or " " in r["url"]]
    assert not bad, f"請求網址含 %20 或裸空白（站方對 %20 回 403）: {bad}"


# ----------------------------------------------------------------------------- probe
@pytest.fixture(scope="module")
def provider(_inject):
    """One provider for the whole module. Probe (J1): the very first live request is resolve(ACTOR, '三上悠亜').

    Unreachable / blocked HERE -> skip UNVERIFIED for every cell (all cells depend on this fixture); afterwards nothing may skip.
    """
    import requests

    from core.scrapers.errors import SourceBlocked, SourceUnreachable
    from core.search_providers.javbus import JavBusProvider
    from core.search_providers.types import Kind

    p = JavBusProvider()
    try:
        ref = p.resolve(Kind.ACTOR, "三上悠亜")
    except (SourceBlocked, SourceUnreachable, requests.RequestException, ConnectionError, TimeoutError, OSError) as exc:
        pytest.skip(f"UNVERIFIED: JavBus unreachable/blocked via proxy, probe resolve raised {type(exc).__name__}: {exc}")
    _ERRORS.clear()  # only post-probe errors count
    _STATE["armed"] = True
    _CELLS["probe(j1)"] = _STATE["calls"]
    assert ref is not None, "探針 resolve(ACTOR,'三上悠亜') 查無（站可達但實體查詢失效）"
    _STATE["actor_ref"] = ref
    return p


@pytest.fixture(scope="module")
def actor_ref(provider):
    return _STATE["actor_ref"]


# ----------------------------------------------------------------------------- cells
def test_j1_actor_resolves_to_known_star(actor_ref):
    """J1: typing an actress name must land on her page, not on 'titles that contain her name'."""
    _require_live()
    assert actor_ref.id == "star/okq", actor_ref


def test_j2_actor_list_first_page_passes_guard(provider, actor_ref):
    """J2: the list parses and the membership guard accepts it (else JavBus is skipped as a whole)."""
    _require_live()
    from core.search_providers import pipeline
    from core.search_providers.types import Window

    page = provider.list_entity(actor_ref, Window(0, _MIN_ITEMS))
    assert len(page.items) >= _MIN_ITEMS, f"actor list parsed {len(page.items)} items, expected >= {_MIN_ITEMS}"
    verdict = pipeline.verify_page(provider, page.items[: pipeline.GUARD_SIZE], actor_ref)
    assert verdict.passed is True, verdict


def test_j3_existmag_all_reaches_page_eight(provider, actor_ref):
    """J3: with existmag=all her list has 8+ pages; the mag-only list stops at page 7 (so page 8 existing proves the cookie works)."""
    _require_live()
    from core.search_providers.types import Window

    mark = len(_LOG)
    page = provider.list_entity(actor_ref, Window(210, _MIN_ITEMS))  # offset 210 / page size 30 -> page 8
    urls = [r["url"] for r in _LOG[mark:]]
    assert any(u.endswith("/star/okq/8") for u in urls), f"沒有打到第 8 頁: {urls}"
    assert len(page.items) >= 1, f"page 8 returned {len(page.items)} items (existmag=all not in effect?) urls={urls}"


def test_j4_same_session_second_page_keeps_single_existmag(provider, actor_ref):
    """J4 (T2 objection 3): page 1 then page 2 in ONE session; the second request must carry exactly one existmag cookie = all."""
    _require_live()
    from core.search_providers.types import Window

    mark = len(_LOG)
    page = provider.list_entity(actor_ref, Window(20, _MIN_ITEMS))  # offset 20, limit 20 -> pages 1 and 2
    records = _LOG[mark:]
    first = [r for r in records if r["url"].endswith("/star/okq")]
    second = [r for r in records if r["url"].endswith("/star/okq/2")]
    assert first and second, f"頁 1／頁 2 的請求紀錄必須兩筆都在: {[r['url'] for r in records]}"
    cookie = second[0]["cookie"] or ""
    values = [value for name, _, value in (part.strip().partition("=") for part in cookie.split(";")) if name == "existmag"]
    assert values == ["all"], f"第二頁 Cookie 標頭應恰一個 existmag=all，實得 {values}；Cookie 標頭原文={cookie!r}；頁 1 Cookie={first[0]['cookie']!r}"
    assert len(page.items) >= 1, f"window (20, 20) returned {len(page.items)} items"


def test_j5_uncensored_prefix_heyzo_returns_titled_cards(provider):
    """J5 (T5 -> T11): HEYZO used to be a 404 'not found'; the uncensored retry must run AND the detail pages must give titles."""
    _require_live()
    mark = len(_LOG)
    seeds, events = [], []

    def status_cb(source, message):
        events.append((source, message))

    def result_cb(slot, payload):
        if slot == -1:
            seeds.append(list(payload))

    cards = provider.run_prefix("HEYZO", 2, 0, status_cb, result_cb, False)  # 2 detail pages at most
    urls = [r["url"] for r in _LOG[mark:]]
    assert any("/uncensored/search/HEYZO" in u for u in urls), f"無碼重試沒有走到: {urls}"
    assert seeds and seeds[0], f"seed（result_cb(-1, …)）番號清單為空: seeds={seeds} events={events}"
    assert all(n.upper().startswith("HEYZO") for n in seeds[0]), seeds
    assert len(cards) >= 1, f"HEYZO 前綴 0 張卡: events={events} urls={urls}"
    for card in cards:
        assert card.get("title"), f"HEYZO 卡沒有標題（空殼卡）: number={card.get('number')!r}"
        assert str(card.get("number", "")).upper().startswith("HEYZO"), card.get("number")


def test_j6_actor_name_with_space_resolves_and_searches(provider):
    """J6: a name typed with a space must still resolve (space -> '+'; the site answers %20 with 403)."""
    _require_live()
    from core.search_providers.types import Kind, Window

    before = _STATE["calls"]
    ref = provider.resolve(Kind.ACTOR, "三上 悠亜")
    assert _STATE["calls"] - before >= 1, "resolve 沒有發出 searchstar 請求（快取命中會讓這格變空殼）"
    assert ref is not None and ref.id == "star/okq", ref
    page = provider.search_keyword("三上 悠亜", Window(0, _MIN_ITEMS))
    assert len(page.items) >= 1, "search_keyword('三上 悠亜') 0 筆"
    _no_encoded_space(_LOG)  # every request this file has sent so far


def test_j7_series_name_resolves_to_series_page(provider):
    """J7 (T3 G1): typing a series name must land on the series page (series is searched with the general search, not type=5)."""
    _require_live()
    from core.search_providers.types import Kind

    mark = len(_LOG)
    ref = provider.resolve(Kind.SERIES, "PLATINUM SOAP")
    assert ref is not None and ref.id == "series/rvz", ref
    _no_encoded_space(_LOG[mark:])
