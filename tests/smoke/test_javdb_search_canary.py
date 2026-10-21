"""Live smoke canary — JavDB fuzzy search (TASK-175b-T12).

Guards the JavDB provider against site-side change: entity lookup (actor /
maker / code), entity list pages + the membership guard, keyword search, and the
reverse canary (a wrongly-flagged filter silently returns the site-wide latest
page; the guard must classify it NOT_ANSWERABLE instead of showing it).

Verdict: probe unreachable -> skip (reason starts with UNVERIFIED, which means
NOT verified, not passed). After the probe passes, ANY failure is a failure,
including SourceBlocked / SourceUnreachable (BE-PY-03). No retries.

Request budget (pressure on JavDB): an autouse fixture wraps javdb_api.api_get
to count and throttle only (it calls the real function, never mocks a
response): >= 1.5 s between two requests, hard cap 24 calls per run. Detail
workers are thereby serialized. Actress names are NOT asserted (owner decision
2026-10-21: names stay as the detail page gives them).

No site HTML/JSON is stored; ids come from the live site at run time.
"""
import threading
import time

import pytest

pytestmark = pytest.mark.smoke

_MIN_GAP = 1.5  # seconds between two JavDB requests (end of previous -> start of next)
_MAX_CALLS = 24
_MIN_ITEMS = 20

_STATE = {"calls": 0, "last_end": None, "min_gap": None, "max_gap": None}
_ERRORS = []  # (exception type, endpoint path) of every api_get that raised after the probe
_LOCK = threading.Lock()


def _install_counter(monkeypatch):
    from core.scrapers import javdb_api

    real = javdb_api.api_get

    def counted(path, params=None, proxies=None):
        with _LOCK:
            if _STATE["calls"] >= _MAX_CALLS:
                pytest.fail("超出請求預算")
            _STATE["calls"] += 1
            if _STATE["last_end"] is not None:
                wait = _STATE["last_end"] + _MIN_GAP - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                gap = time.monotonic() - _STATE["last_end"]
                _STATE["min_gap"] = gap if _STATE["min_gap"] is None else min(_STATE["min_gap"], gap)
                _STATE["max_gap"] = gap if _STATE["max_gap"] is None else max(_STATE["max_gap"], gap)
            try:
                return real(path, params, proxies)
            except Exception as exc:
                _ERRORS.append((type(exc).__name__, path))
                raise
            finally:
                _STATE["last_end"] = time.monotonic()

    monkeypatch.setattr(javdb_api, "api_get", counted)


@pytest.fixture(autouse=True)
def _budget(monkeypatch):
    _install_counter(monkeypatch)
    start = len(_ERRORS)
    yield
    # verify_page swallows detail exceptions; any api_get error after the probe must still fail the cell
    if len(_ERRORS) > start:
        pytest.fail(f"探針後 api_get 拋例外（verify_page 會吞掉，這裡補抓）: {_ERRORS[start:]}")


@pytest.fixture(scope="module", autouse=True)
def _report():
    yield
    print(
        f"\n[javdb canary] api_get calls={_STATE['calls']} (cap {_MAX_CALLS}) "
        f"min_gap={_STATE['min_gap']} max_gap={_STATE['max_gap']} (floor {_MIN_GAP}s)"
    )


@pytest.fixture(scope="module")
def provider():
    """One provider for the whole module; probes once with check (1)'s resolve."""
    from core.scrapers.errors import SourceBlocked, SourceUnreachable
    from core.search_providers.javdb import JavDBProvider
    from core.search_providers.types import Kind

    mp = pytest.MonkeyPatch()
    _install_counter(mp)
    p = JavDBProvider()
    try:
        ref = p.resolve(Kind.ACTOR, "三上悠亞")
    except (SourceBlocked, SourceUnreachable, ConnectionError, TimeoutError, OSError) as exc:
        mp.undo()
        pytest.skip(f"UNVERIFIED: JavDB unreachable, probe resolve raised {type(exc).__name__}: {exc}")
    mp.undo()
    _ERRORS.clear()  # only post-probe errors count
    assert ref is not None, "探針 resolve(ACTOR,'三上悠亞') 查無（站可達但實體查詢失效）"
    return p


@pytest.fixture(scope="module")
def actor_ref(provider):
    from core.search_providers.types import Kind

    mp = pytest.MonkeyPatch()
    _install_counter(mp)
    try:
        return provider.resolve(Kind.ACTOR, "三上悠亞")  # module cache hit, no request
    finally:
        mp.undo()


def _guard(provider, items, ref):
    from core.search_providers import pipeline

    return pipeline.verify_page(provider, items[: pipeline.GUARD_SIZE], ref)


def test_actor_trad_and_romaji_same_id(provider, actor_ref):
    from core.search_providers.types import Kind

    other = provider.resolve(Kind.ACTOR, "Yua Mikami")
    assert other is not None, "resolve(ACTOR,'Yua Mikami') 查無"
    assert other.id == actor_ref.id, (actor_ref.id, other.id)


def test_actor_list_first_page_passes_guard(provider, actor_ref):
    from core.search_providers.types import Window

    page = provider.list_entity(actor_ref, Window(0, _MIN_ITEMS))
    assert len(page.items) >= _MIN_ITEMS, f"actor list parsed {len(page.items)} items, expected >= {_MIN_ITEMS}"
    verdict = _guard(provider, page.items, actor_ref)
    assert verdict.passed is True, verdict


@pytest.fixture(scope="module")
def maker_ref(provider):
    from core.search_providers.types import Kind

    mp = pytest.MonkeyPatch()
    _install_counter(mp)
    try:
        return provider.resolve(Kind.MAKER, "カリビアンコム")
    finally:
        mp.undo()


def test_maker_resolves(maker_ref):
    assert maker_ref is not None, "resolve(MAKER,'カリビアンコム') 查無"


def test_maker_list_first_page_passes_guard(provider, maker_ref):
    from core.search_providers.types import Window

    assert maker_ref is not None, "resolve(MAKER,'カリビアンコム') 查無"
    page = provider.list_entity(maker_ref, Window(0, _MIN_ITEMS))
    assert len(page.items) >= _MIN_ITEMS, f"maker list parsed {len(page.items)} items, expected >= {_MIN_ITEMS}"
    verdict = _guard(provider, page.items, maker_ref)
    assert verdict.passed is True, verdict


def test_code_prefix_resolves(provider):
    from core.search_providers.types import Kind

    assert provider.resolve(Kind.CODE, "MIDV") is not None, "resolve(CODE,'MIDV') 查無"


def test_keyword_search_has_results(provider):
    from core.search_providers.types import Window

    page = provider.search_keyword("温泉", Window(0, _MIN_ITEMS))
    assert len(page.items) >= 1, "search_keyword('温泉') 0 筆"


def test_reverse_wrong_filter_is_not_answerable(provider, maker_ref):
    """Real maker id + deliberately wrong flag ('t') -> site silently returns the site-wide latest page.
    The guard must refuse it (NOT_ANSWERABLE), not show it as the maker's works."""
    from core.scrapers import javdb_api
    from core.search_providers import javdb
    from core.search_providers.types import Outcome

    assert maker_ref is not None, "resolve(MAKER,'カリビアンコム') 查無"
    rows = javdb_api.api_list_tags(f"0:t:{maker_ref.id}", 1, proxies=provider._proxies())
    items = javdb.parse_list_rows(rows)
    if len(items) < _MIN_ITEMS:
        pytest.fail(
            f"前提失效：錯誤 flag 只回 {len(items)} 筆（<{_MIN_ITEMS}），站方可能不再靜默回全站最新，金絲雀需重新設計"
        )
    verdict = _guard(provider, items, maker_ref)
    assert verdict.passed is False, verdict
    assert verdict.outcome is Outcome.NOT_ANSWERABLE, verdict.outcome
