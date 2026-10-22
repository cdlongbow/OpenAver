# tests/unit/test_cf_transport_impl.py
"""
TDD-lite tests for windows/cf_transport_impl.py

Import strategy: sys.path.insert + sibling import (matches standalone.py runtime)
Structural guards: grep assertions for _wv_fetch module-level 與 javlibrary 不呼叫 navigate_and_settle。
（core⇏windows 已於 0.15.5 搬進 import-linter 契約，見 pyproject.toml；launcher purity 檢查追不到 sink 已刪除，見 spec-136b.md F1）
"""
import sys
import pathlib
import threading
import time

import pytest

# ──────────────────────────────────────────────────────────────
# sys.path setup — mirrors standalone.py L22-24
# ──────────────────────────────────────────────────────────────
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
WINDOWS_DIR = str(REPO_ROOT / 'windows')
if WINDOWS_DIR not in sys.path:
    sys.path.insert(0, WINDOWS_DIR)

import cf_transport_impl  # sibling import, same as standalone.py runtime
from cf_transport_impl import PyWebViewCfTransport, _wv_fetch
from core.cf_transport import CfChallengeRequired, CfTransportUnavailable
from core.scrapers.javlibrary import JAVLIBRARY_ORIGIN

# TASK-118a-T1 D-1: fixed constructor shape is dict[str, Window] + optional
# initial_urls seed. All 25 pre-existing single-window `PyWebViewCfTransport(win)`
# construction points become a one-line mechanical rewrite to `_jl_transport(win)`,
# with every assertion left unchanged.
JL_ORIGIN = JAVLIBRARY_ORIGIN


def _jl_transport(win):
    return PyWebViewCfTransport({'javlibrary': win}, {'javlibrary': JL_ORIGIN})


# ──────────────────────────────────────────────────────────────
# FakeWindow
# ──────────────────────────────────────────────────────────────
class FakeEvents:
    """
    Minimal stub for pywebview's EventContainer that supports `+=` handler registration.
    Registered handlers can be fired by calling fire().
    """

    def __init__(self):
        self._handlers: list = []

    def __iadd__(self, handler):
        self._handlers.append(handler)
        return self

    def fire(self):
        for h in self._handlers:
            h()


class FakeEvent:
    """Stub for a threading.Event-like pywebview lifecycle event.

    Defaults to set=True so `_bridge_ready()` reports ready and existing tests
    keep their pre-0.9.9c behavior. Tests that exercise the bridge-not-ready
    path can flip it via .clear()/.set()."""

    def __init__(self, initial: bool = True):
        self._set = initial
        self.wait_calls = 0

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def clear(self):
        self._set = False

    def wait(self, timeout=None):
        self.wait_calls += 1
        return self._set


class FakeWindowEvents:
    """Stub for window.events, with `closed`/`closing` + lifecycle events."""

    def __init__(self):
        self.closed = FakeEvents()
        self.closing = FakeEvents()
        # 0.9.9c/e: bridge-readiness events. Default set=True → bridge ready.
        self._pywebviewready = FakeEvent(initial=True)
        self.shown = FakeEvent(initial=True)
        self.loaded = FakeEvent(initial=True)


class FakeWindow:
    """
    Mock for webview.Window.

    evaluate_js behaviour:
      - With callback: call callback(self._eval_callback_result['default'])
        unless self._never_callback is True (for TimeoutError tests).
      - Without callback: return self._eval_results.get(code[:20], None).

    Records all method calls in self.calls as (method, *args).
    """

    def __init__(self):
        self.calls: list[tuple] = []
        # Sync return values, keyed by first 20 chars of JS code
        self._eval_results: dict = {}
        # Dict result passed to callback; default = clean fetch result
        self._eval_callback_result: dict = {
            'default': {'finalUrl': 'https://www.javlibrary.com/ja/', 'status': 200, 'html': '<html><title>JavLibrary</title></html>'}
        }
        # Set True to make evaluate_js never call the callback (→ TimeoutError)
        self._never_callback: bool = False
        # events stub for CD-70c-2 __init__ binding
        self.events = FakeWindowEvents()
        # D-2: get_current_url() is the source of navigate_and_settle()'s return
        # value. Defaults to tracking the last load_url() target (realistic
        # same-URL case); tests exercising an actual redirect can override
        # self._current_url after triggering navigation.
        self._current_url = None

    def show(self):
        self.calls.append(('show',))

    def hide(self):
        self.calls.append(('hide',))

    def load_url(self, url):
        self.calls.append(('load_url', url))
        self._current_url = url

    def get_current_url(self):
        self.calls.append(('get_current_url',))
        return self._current_url

    def evaluate_js(self, code, callback=None):
        self.calls.append(('evaluate_js', code, callback))
        if callback is not None:
            if not self._never_callback:
                result = self._eval_callback_result.get('default', {})
                callback(result)
            return None
        else:
            # Sync return (is_ready path)
            return self._eval_results.get(code[:20], None)


# ──────────────────────────────────────────────────────────────
# Tests: _wv_fetch
# ──────────────────────────────────────────────────────────────

class TestWvFetch:

    def test_retry_then_succeed(self):
        """
        1st attempt: callback never fires → timeout.
        2nd attempt: callback fires with valid result → returns correct tuple.
        Asserts recovery on attempt 2 with no actual wait.
        """
        call_count = [0]
        captured_callbacks: list = []
        GOOD_RESULT = {
            'finalUrl': 'https://www.javlibrary.com/ja/vl_movie.php?v=START492',
            'status': 200,
            'html': '<html><title>START-492</title></html>',
        }

        class RetryFakeWindow(FakeWindow):
            def evaluate_js(self, code, callback=None):
                self.calls.append(('evaluate_js', code, callback))
                call_count[0] += 1
                if callback is not None:
                    if call_count[0] == 1:
                        # 1st attempt: do nothing → timeout
                        captured_callbacks.append(callback)
                    else:
                        # 2nd attempt onwards: call callback with good result
                        callback(GOOD_RESULT)
                return None

        win = RetryFakeWindow()
        result = _wv_fetch(win, 'https://www.javlibrary.com/ja/', timeout=0.05, attempts=3, retry_delay=0)

        assert isinstance(result, tuple)
        final_url, status, html = result
        assert final_url == GOOD_RESULT['finalUrl']
        assert status == 200
        assert html == GOOD_RESULT['html']
        # evaluate_js called exactly twice: 1 timed-out + 1 successful
        eval_calls = [c for c in win.calls if c[0] == 'evaluate_js']
        assert len(eval_calls) == 2, f"Expected 2 evaluate_js calls, got {len(eval_calls)}"


    def test_stale_callback_isolation(self):
        """
        Stale-callback isolation: the 1st attempt's callback fires LATE (injected
        at the start of the 2nd evaluate_js call, into the 1st attempt's queue).
        The 2nd attempt supplies its OWN correct result.
        Assert that the returned html belongs to attempt 2, not the stale result.

        Implementation note: each attempt captures its OWN `result_q` via the
        default-argument closure `_q=result_q`.  The stale callback fires into
        the 1st (abandoned) queue; the 2nd attempt's queue receives the fresh
        result.  This verifies the per-attempt queue isolation design.
        """
        STALE_RESULT = {
            'finalUrl': 'https://www.javlibrary.com/ja/stale',
            'status': 200,
            'html': '<html><title>STALE</title></html>',
        }
        FRESH_RESULT = {
            'finalUrl': 'https://www.javlibrary.com/ja/fresh',
            'status': 200,
            'html': '<html><title>FRESH</title></html>',
        }

        stale_cb_holder: list = []
        call_count = [0]

        class StaleCallbackWindow(FakeWindow):
            def evaluate_js(self, code, callback=None):
                self.calls.append(('evaluate_js', code, callback))
                call_count[0] += 1
                if callback is not None:
                    if call_count[0] == 1:
                        # 1st attempt: store callback, never invoke → timeout
                        stale_cb_holder.append(callback)
                    elif call_count[0] == 2:
                        # 2nd attempt: first fire the stale 1st-attempt callback
                        # (simulates late arrival after the retry started)
                        if stale_cb_holder:
                            stale_cb_holder[0](STALE_RESULT)
                        # Then fire THIS attempt's fresh callback
                        callback(FRESH_RESULT)
                return None

        win = StaleCallbackWindow()
        result = _wv_fetch(win, 'https://www.javlibrary.com/ja/', timeout=0.05, attempts=3, retry_delay=0)

        final_url, status, html = result
        assert html == FRESH_RESULT['html'], (
            f"Expected fresh result html, got: {html!r} (stale callback must not contaminate)"
        )
        assert final_url == FRESH_RESULT['finalUrl']


# ──────────────────────────────────────────────────────────────
# Tests: fetch()
# ──────────────────────────────────────────────────────────────

NORMAL_HTML = '<html><head><title>JavLibrary</title></head><body>content</body></html>'


class TestFetch:


    def test_fetch_bridge_not_ready_raises_cf_no_side_effects(self, monkeypatch):
        """
        Bridge gate (0.9.9c): when _pywebviewready is unset (bridge not ready),
        fetch() must:
          - raise CfChallengeRequired immediately
          - NOT call _wv_fetch (no JS fetch attempted on broken bridge)
          - NOT call evaluate_js (over18 cookie NOT set — bridge gate fires first)
          - record _cf_url = url (so begin_solve can navigate to the right page)
        """
        wv_fetch_calls = []

        def spy_wv_fetch(window, url, **kwargs):
            wv_fetch_calls.append(url)
            return (url, 200, NORMAL_HTML)

        monkeypatch.setattr(cf_transport_impl, '_wv_fetch', spy_wv_fetch)

        win = FakeWindow()
        # Bridge not ready: clear the _pywebviewready event
        win.events._pywebviewready.clear()
        transport = _jl_transport(win)

        url = 'https://www.javlibrary.com/ja/vl_searchbyid.php?keyword=START-578'
        with pytest.raises(CfChallengeRequired):
            transport.fetch(url)

        # _wv_fetch must NOT have been called (bridge gate fires before it)
        assert wv_fetch_calls == [], (
            f"_wv_fetch must not be called when bridge is not ready; got calls: {wv_fetch_calls}"
        )

        # evaluate_js must NOT have been called (over18 cookie path is after bridge gate)
        eval_calls = [c for c in win.calls if c[0] == 'evaluate_js']
        assert eval_calls == [], (
            f"evaluate_js must not be called when bridge is not ready; got: {eval_calls}"
        )

        # _cf_urls['javlibrary'] must record the challenged URL for begin_solve
        assert transport._cf_urls['javlibrary'] == url, (
            f"_cf_urls['javlibrary'] must be set to {url!r} when bridge not ready; "
            f"got {transport._cf_urls['javlibrary']!r}"
        )

    def test_fetch_cross_origin_raises_challenge_without_wv_fetch(self):
        """
        INV-1 (CD-118a-3) — the most important test in T1: a transport window
        recorded (seeded) at a DIFFERENT origin than the requested URL must
        route into the challenge/navigate flow WITHOUT ever calling _wv_fetch
        (i.e. zero evaluate_js calls — _wv_fetch is evaluate_js(callback=...)).

        mutation: remove the origin gate in fetch() → this test must go red
        (load_calls becomes empty and/or evaluate_js calls appear).
        """
        win = FakeWindow()
        # This window's recorded origin is fc-javten's — a mismatch for the
        # javlibrary URL fetched below under the 'javlibrary' key.
        transport = PyWebViewCfTransport(
            {'javlibrary': win},
            {'javlibrary': 'https://javten.com/'},
        )
        url = 'https://www.javlibrary.com/ja/vl_searchbyid.php?keyword=START-578'

        with pytest.raises(CfChallengeRequired):
            transport.fetch(url, 'javlibrary')

        load_calls = [c for c in win.calls if c[0] == 'load_url']
        assert load_calls and load_calls[-1][1] == url, (
            f"origin mismatch must trigger load_url({url!r}); got {load_calls}"
        )

        eval_calls = [c for c in win.calls if c[0] == 'evaluate_js']
        assert eval_calls == [], (
            f"_wv_fetch (evaluate_js) must NOT be called on origin mismatch; got {eval_calls}"
        )


    def test_javlibrary_fetch_still_sets_age_gate_and_cookie(self, monkeypatch):
        """
        Regression lock (reverse of the test above): javlibrary's fetch() must
        keep calling _is_age_gate and setting the over18 cookie — zero
        regression from introducing the per-site behaviour table.
        """
        age_gate_calls = []
        monkeypatch.setattr(
            cf_transport_impl, '_is_age_gate',
            lambda html: (age_gate_calls.append(html), False)[1],
        )
        win = FakeWindow()
        win._eval_callback_result['default'] = {
            'finalUrl': 'https://www.javlibrary.com/ja/',
            'status': 200,
            'html': NORMAL_HTML,
        }
        transport = _jl_transport(win)

        result = transport.fetch('https://www.javlibrary.com/ja/')
        assert isinstance(result, str)

        assert len(age_gate_calls) == 1, (
            f"_is_age_gate must be called exactly once for javlibrary; got {age_gate_calls}"
        )
        over18_calls = [c for c in win.calls if c[0] == 'evaluate_js' and 'over18' in c[1]]
        assert over18_calls, "over18 cookie must be set for javlibrary"


# ──────────────────────────────────────────────────────────────
# Tests: fetch() cross-origin redirect rejection (TASK-118a-T10 / F-2)
# ──────────────────────────────────────────────────────────────

class TestFetchOriginPin:
    """
    T10/F-2: _wv_fetch's finalUrl (r.url, post-redirect) must land on the same
    origin as the requested url for sites pinned in _SITE_FETCH_ORIGIN_PIN.
    javten is a third-party mirror we don't control — a same-origin request
    that redirects to a different host must be rejected outright, not parsed
    as this video's data (same sink as T6-P3-2).

    mutation (per DoD): drop `_SITE_FETCH_ORIGIN_PIN.get(key, False) and` from
    the guard in fetch() (→ always-on) — test 4 (javlibrary) must go red;
    tests 1-3 must stay green.
    """

    JAVTEN_URL = 'https://javten.com/tw/video/2100980/id4938117/slug'

    def _javten_transport(self, win):
        return PyWebViewCfTransport(
            {'fc-javten': win}, {'fc-javten': self.JAVTEN_URL},
        )

    @pytest.mark.parametrize("final_url", [
        'https://evil-mirror.example/tw/video/2100980/id4938117/slug',  # 不同主機
    ])
    def test_1_cross_origin_final_url_raises_and_returns_no_html(self, final_url):
        """final_url lands on a different origin (other host or scheme downgrade) → RuntimeError, no HTML surfaced."""
        win = FakeWindow()
        win._eval_callback_result['default'] = {
            'finalUrl': final_url,
            'status': 200,
            'html': '<html><title>not javten</title></html>',
        }
        transport = self._javten_transport(win)

        with pytest.raises(RuntimeError, match='cross-origin redirect rejected'):
            transport.fetch(self.JAVTEN_URL, 'fc-javten')


# ──────────────────────────────────────────────────────────────
# Tests: begin_solve()
# ──────────────────────────────────────────────────────────────

class TestBeginSolve:
    def test_calls_show_then_load_url_no_blocking_eval(self):
        """begin_solve → show() + load_url(origin) only — NO evaluate_js.

        ROOT-CAUSE FIX (0.9.9c): setting the over18 cookie via evaluate_js right
        after load_url to a CF-challenged origin blocks ~20s on _pywebviewready and
        raises WebViewException, stranding the bridge. over18 is set in
        fetch()/is_ready() instead. begin_solve must stay show + navigate only.

        Note: this test passes `_cf_url=None` (default), so begin_solve falls back to
        the origin argument; when `_cf_url` is set it takes priority — see
        TestBeginSolveTargetsCfUrl.
        """
        win = FakeWindow()
        transport = _jl_transport(win)
        origin = 'https://www.javlibrary.com/ja/'
        transport.begin_solve(origin)

        method_calls = [c[0] for c in win.calls]
        assert 'show' in method_calls
        assert 'load_url' in method_calls
        assert 'evaluate_js' not in method_calls, (
            "begin_solve must not call evaluate_js — it blocks on a CF page and "
            "strands the pywebview bridge (0.9.9b repro)"
        )

        # Check order: show before load_url
        show_idx = next(i for i, c in enumerate(win.calls) if c[0] == 'show')
        load_idx = next(i for i, c in enumerate(win.calls) if c[0] == 'load_url')
        assert show_idx < load_idx

        # load_url gets the origin
        load_call = next(c for c in win.calls if c[0] == 'load_url')
        assert load_call[1] == origin


# ──────────────────────────────────────────────────────────────
# Tests: is_ready()
# ──────────────────────────────────────────────────────────────

READY_TITLE = 'JavLibrary'
READY_HEAD = '<html><head><title>JavLibrary</title></head>'


class FakeWindowIsReady(FakeWindow):
    """
    FakeWindow variant that maps specific document.title and
    document.documentElement.outerHTML.slice(0, 4000) JS codes
    to configured return values.
    """

    def __init__(self, title: str, head: str):
        super().__init__()  # inherits self.events = FakeWindowEvents()
        self._title = title
        self._head = head

    def evaluate_js(self, code, callback=None):
        self.calls.append(('evaluate_js', code, callback))
        if callback is not None:
            # _wv_fetch path (not relevant for is_ready tests)
            if not self._never_callback:
                result = self._eval_callback_result.get('default', {})
                callback(result)
            return None
        # Sync returns (is_ready path)
        if 'document.title' in code:
            return self._title
        if 'outerHTML' in code:
            return self._head
        return None


class TestIsReady:
    def test_blank_or_navigating_page_returns_false_no_hide(self):
        """
        FIX-P2A: 導航中頁面（document.title 回空字串）→ is_ready() 回 False，
        視窗不 hide，避免慢載入時誤判 ready 並提前關閉彈窗。
        """
        # Empty title simulates page still navigating (evaluate_js returns "" or None)
        win = FakeWindowIsReady("", READY_HEAD)
        transport = _jl_transport(win)
        result = transport.is_ready()
        assert result is False, (
            "導航中/空 title 頁面 is_ready() 應回 False（loaded-page guard）"
        )
        hide_calls = [c for c in win.calls if c[0] == 'hide']
        assert len(hide_calls) == 0, "空 title 時不應 hide()，視窗須保留"


# ──────────────────────────────────────────────────────────────
# Structural guards
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# CD-70c-2 Layer 2: dead-flag fail-fast tests
# ──────────────────────────────────────────────────────────────

class TestDeadFlagFailFast:
    """
    CD-70c-2 Layer 2 backstop: once the transport is dead (window destroyed),
    fetch / begin_solve / is_ready must each raise CfTransportUnavailable immediately
    rather than operating on a dead window.
    """


    def test_dead_via_on_closed_then_fetch_raises(self):
        """Full path: window closed event fires → _dead=True → fetch raises with restart hint."""
        win = FakeWindow()
        transport = _jl_transport(win)
        # Simulate window being destroyed by OS / crash
        win.events.closed.fire()
        with pytest.raises(CfTransportUnavailable, match="restart OpenAver"):
            transport.fetch('https://www.javlibrary.com/ja/')

    def test_dead_window_isolated_per_site(self):
        """
        _dead must be per-site: killing site A's window must not affect site B.

        mutation: make _dead a single shared bool again → this test must go red
        (fc-javten's fetch/is_ready would start raising CfTransportUnavailable too).
        """
        win_a = FakeWindow()
        win_b = FakeWindowIsReady(READY_TITLE, READY_HEAD)
        # T10/F-2: fc-javten is pinned in _SITE_FETCH_ORIGIN_PIN, so _wv_fetch's
        # finalUrl must land on javten's own origin — the base FakeWindow default
        # ('https://www.javlibrary.com/ja/') would now (correctly) be rejected as
        # a cross-origin redirect, which is not what this test is exercising.
        win_b._eval_callback_result['default'] = {
            'finalUrl': 'https://javten.com/',
            'status': 200,
            'html': '<html><head><title>JavTen</title></head><body>content</body></html>',
        }
        transport = PyWebViewCfTransport(
            {'javlibrary': win_a, 'fc-javten': win_b},
            {'javlibrary': JL_ORIGIN, 'fc-javten': 'https://javten.com/'},
        )

        win_a.events.closed.fire()
        assert transport._dead['javlibrary'] is True
        assert transport._dead['fc-javten'] is False

        with pytest.raises(CfTransportUnavailable):
            transport.fetch(JL_ORIGIN, 'javlibrary')

        # fc-javten must remain fully operable despite javlibrary's window dying
        result = transport.fetch('https://javten.com/', 'fc-javten')
        assert isinstance(result, str)
        assert transport.is_ready('fc-javten') is True


# ──────────────────────────────────────────────────────────────
# Tests: 0.9.9g begin_solve navigates to CF-challenged URL
# ──────────────────────────────────────────────────────────────

class TestBeginSolveNavReset:
    """
    TASK-118a-T6 / F-2: begin_solve() hits the SAME WebView2 stall as
    navigate_and_settle(). Real-machine log 2026-08-14 14:59:33 → 15:01:04:
    begin_solve navigated and the bridge never became ready for 90 seconds, so
    the user stared at the previous page instead of the Cloudflare challenge.
    The about:blank hop must therefore be applied at BOTH navigation entry
    points — fixing only one leaves half the bug.
    """

    JAVTEN_URL = 'https://javten.com/search?kw=4938117'

    def test_begin_solve_blanks_before_target_for_fc_javten(self, monkeypatch):
        monkeypatch.setattr(cf_transport_impl, 'NAV_RESET_TIMEOUT_S', 0.05)
        win = FakeWindow()
        transport = PyWebViewCfTransport({'fc-javten': win}, None)

        transport.begin_solve(self.JAVTEN_URL, 'fc-javten')

        loads = [c[1] for c in win.calls if c[0] == 'load_url']
        assert loads == [cf_transport_impl.NAV_RESET_URL, self.JAVTEN_URL], (
            f"begin_solve must reset via about:blank for fc-javten; got {loads}"
        )
        assert [c[0] for c in win.calls if c[0] == 'evaluate_js'] == [], (
            "begin_solve must still never call evaluate_js (0.9.9c): waiting on "
            "the bridge Event is fine, touching evaluate_js strands the bridge"
        )


class TestBeginSolveTargetsCfUrl:
    """
    0.9.9g: begin_solve must navigate to the exact URL that triggered CF
    (self._cf_urls[key]) so the user sees the real Turnstile challenge
    immediately, rather than the homepage which has no CF challenge.
    """

    CF_SEARCH_URL = 'https://www.javlibrary.com/ja/vl_searchbyid.php?keyword=START-578'
    ORIGIN_URL = 'https://www.javlibrary.com/ja/'

    def test_begin_solve_navigates_to_remembered_cf_url(self):
        """When _cf_urls['javlibrary'] is set, begin_solve navigates to it (not origin)."""
        win = FakeWindow()
        transport = _jl_transport(win)
        # Simulate a CF fetch having recorded the challenged URL
        transport._cf_urls['javlibrary'] = self.CF_SEARCH_URL

        transport.begin_solve(self.ORIGIN_URL)

        load_calls = [c for c in win.calls if c[0] == 'load_url']
        assert len(load_calls) == 1
        assert load_calls[0][1] == self.CF_SEARCH_URL, (
            f"begin_solve must navigate to _cf_urls['javlibrary'] ({self.CF_SEARCH_URL!r}), "
            f"not origin ({self.ORIGIN_URL!r}); got {load_calls[0][1]!r}"
        )


# ──────────────────────────────────────────────────────────────
# Tests: navigate_and_settle() (TASK-118a-T1 / CD-118a-18)
# ──────────────────────────────────────────────────────────────

class FakeWindowNavigate(FakeWindow):
    """
    FakeWindow variant for navigate_and_settle(): supports sync evaluate_js
    reads for document.title / outerHTML (same convention as FakeWindowIsReady),
    on top of the base class's load_url()/get_current_url()/show()/hide().
    """

    def __init__(self, title: str = 'JavTen', head: str = '<html><head><title>JavTen</title></head>',
                 href=None):
        super().__init__()
        self._title = title
        self._head = head
        # T6/F-1: location.href is the ONLY trustworthy settled-URL source on
        # WebView2 (get_current_url() returns the *requested* url, not the one a
        # redirect landed on — measured on the real stack, see TASK-118a-T6).
        # None → mirror the last load_url() target (the realistic "no redirect"
        # case); tests exercising a redirect set an explicit value.
        self._href = href

    def evaluate_js(self, code, callback=None):
        self.calls.append(('evaluate_js', code, callback))
        if callback is not None:
            if not self._never_callback:
                result = self._eval_callback_result.get('default', {})
                callback(result)
            return None
        if 'document.title' in code:
            return self._title
        if 'location.href' in code:
            return self._current_url if self._href is None else self._href
        if 'outerHTML' in code:
            return self._head
        return None


class RealDelayedEvent:
    """Thin wrapper over a real threading.Event, used only for the
    "bridge becomes ready after a short delay" blocking test — FakeEvent's
    wait() is intentionally non-blocking (instant), so it can't model a
    background thread calling set() a few milliseconds later."""

    def __init__(self, initial: bool = False):
        self._evt = threading.Event()
        if initial:
            self._evt.set()

    def is_set(self):
        return self._evt.is_set()

    def set(self):
        self._evt.set()

    def clear(self):
        self._evt.clear()

    def wait(self, timeout=None):
        return self._evt.wait(timeout)


class TestNavigateAndSettle:
    """
    navigate_and_settle(url, key) — CD-118a-18: navigate the site's window,
    wait (bounded) for the pywebview bridge, then return the settled URL.
    Never calls evaluate_js before the bridge is ready (0.9.9c).
    """

    JAVTEN_URL = 'https://javten.com/search?kw=4938117'

    # ── TASK-118a-T6 / F-1: location.href is the settled-URL source ──────────
    # Real-machine measurement (POC5, WebView2): after load_url('/search?kw=…')
    # the bridge goes ready with document.title ALREADY the video page's title
    # and location.href ALREADY the video URL, while get_current_url() still
    # reports the *requested* /search url. Trusting get_current_url() makes the
    # scraper's hit predicate miss → user searches a film that exists and the
    # screen says "not found".

    def test_navigate_and_settle_returns_location_href_not_get_current_url(self, monkeypatch):
        """
        get_current_url() lies (returns the requested /search url) while
        location.href holds the URL the redirect actually landed on.
        navigate_and_settle must return the latter.

        mutation: read the settled url from get_current_url() → this test goes red.
        """
        monkeypatch.setattr(cf_transport_impl, 'NAVIGATE_BRIDGE_TIMEOUT_S', 0.05)
        landed = 'https://javten.com/tw/video/2100980/id4938117/slug'
        win = FakeWindowNavigate(href=landed)
        win.events._pywebviewready = FakeEvent(initial=True)
        # get_current_url() keeps reporting the requested search url (the real
        # WebView2 behaviour this task exists to work around).
        win.get_current_url = lambda: self.JAVTEN_URL
        transport = PyWebViewCfTransport({'fc-javten': win}, None)

        result = transport.navigate_and_settle(self.JAVTEN_URL, 'fc-javten')

        assert result == landed, (
            "navigate_and_settle must return location.href (the URL the redirect "
            f"landed on), not get_current_url(); got {result!r}"
        )


    # ── TASK-118a-T6 / F-2: about:blank reset before navigating ──────────────
    # Real-machine measurement (POC6/POC7/POC8, WebView2): the SECOND load_url()
    # of a javten URL in the same window never fires NavigationCompleted and never
    # recovers (bridge stays unready forever; not a Python-side deadlock —
    # _expose_lock measured unlocked). Navigating to about:blank first (~0.1s)
    # resets it: 3/3 green in POC8.

    def test_navigate_and_settle_blanks_before_target_for_fc_javten(self, monkeypatch):
        """fc-javten navigations must be preceded by an about:blank reset."""
        monkeypatch.setattr(cf_transport_impl, 'NAVIGATE_BRIDGE_TIMEOUT_S', 0.05)
        monkeypatch.setattr(cf_transport_impl, 'NAV_RESET_TIMEOUT_S', 0.05)
        win = FakeWindowNavigate()
        win.events._pywebviewready = FakeEvent(initial=True)
        transport = PyWebViewCfTransport({'fc-javten': win}, None)

        transport.navigate_and_settle(self.JAVTEN_URL, 'fc-javten')

        loads = [c[1] for c in win.calls if c[0] == 'load_url']
        assert loads == [cf_transport_impl.NAV_RESET_URL, self.JAVTEN_URL], (
            "fc-javten must navigate to about:blank before the real target "
            f"(WebView2 stops completing repeat same-site navigations); got {loads}"
        )


    # NOTE: an "origins survive the blank hop" test was written here and then
    # deleted. It asserted the END state of _origins, which the final
    # _record_origin(key, final_url) restores unconditionally — so it stayed
    # green under BOTH the "reset removed" and the "reset in the wrong order"
    # mutations. Its docstring claimed an invariant it could not falsify. The
    # invariant it named is really pinned by
    # test_navigate_and_settle_records_landed_origin_not_requested_origin
    # (cross-origin, mutation-verified). Pinning the *transient* about: origin
    # instead would test implementation minutiae with no user-visible sink.


    def test_navigate_and_settle_waits_for_bridge_then_returns_url(self, monkeypatch):
        """
        Bridge becomes ready ~50ms after navigation (a background thread calls
        set() on a real threading.Event) → navigate_and_settle must wait for it
        and return the settled URL, and must NEVER call show()/begin_solve.

        mutation: replace the bounded wait with fetch()'s "not ready → raise
        immediately" snapshot gate → this test must go red (it would raise
        instead of returning, since the event isn't set() yet at call time).
        """
        monkeypatch.setattr(cf_transport_impl, 'NAVIGATE_BRIDGE_TIMEOUT_S', 2.0)
        win = FakeWindowNavigate(title='JavTen', head='<html><head><title>JavTen</title></head>')
        win.events._pywebviewready = RealDelayedEvent(initial=False)
        transport = PyWebViewCfTransport({'fc-javten': win}, None)

        def _delayed_set():
            time.sleep(0.05)
            win.events._pywebviewready.set()

        threading.Thread(target=_delayed_set, daemon=True).start()

        result = transport.navigate_and_settle(self.JAVTEN_URL, 'fc-javten')

        assert result == self.JAVTEN_URL, (
            f"navigate_and_settle must return the settled URL once the bridge "
            f"becomes ready; got {result!r}"
        )
        show_calls = [c for c in win.calls if c[0] == 'show']
        assert show_calls == [], (
            "navigate_and_settle must never call show()/begin_solve; "
            f"got show() calls: {show_calls}"
        )

    def test_navigate_and_settle_records_landed_origin_not_requested_origin(self, monkeypatch):
        """
        The search step is a redirect chain we do not control. If it settles on a
        DIFFERENT origin than the one we requested, the origin bookkeeping must
        follow the window, not our request — otherwise the very next fetch() misses
        the INV-1 gate and pops the CF window although Cloudflare never challenged.

        User-visible symptom if this regresses: every single fc-javten query opens
        the CF window (the exact thing CD-118a-18 exists to prevent).

        mutation: record the origin from the requested url only (drop the
        _record_origin(key, final_url) call after the settled URL is read) → this
        test must go red with CfChallengeRequired.
        """
        monkeypatch.setattr(cf_transport_impl, 'NAVIGATE_BRIDGE_TIMEOUT_S', 0.05)
        landed = 'https://www.javten.com/video/12345/id4938117/slug'
        # requested host javten.com → settles on www.javten.com (cross-origin
        # redirect). T6/F-1: the landing is observed via location.href, because
        # WebView2's get_current_url() does not follow the redirect.
        win = FakeWindowNavigate(href=landed)
        win.events._pywebviewready = FakeEvent(initial=True)
        transport = PyWebViewCfTransport({'fc-javten': win}, None)
        result = transport.navigate_and_settle(self.JAVTEN_URL, 'fc-javten')
        assert result == landed

        # The follow-up fetch() of the settled page must pass the origin gate:
        # no re-navigation, no CF challenge — it must actually reach _wv_fetch.
        fetched = []
        monkeypatch.setattr(
            cf_transport_impl, '_wv_fetch',
            lambda w, u: (fetched.append(u), (u, 200, '<html><title>ok</title><body>x</body></html>'))[1],
        )
        loads_before = len([c for c in win.calls if c[0] == 'load_url'])

        transport.fetch(landed, 'fc-javten')

        assert fetched == [landed], (
            "fetch() of the settled URL must reach _wv_fetch; the origin gate "
            f"compared against a stale origin instead. _wv_fetch calls: {fetched}"
        )
        loads_after = len([c for c in win.calls if c[0] == 'load_url'])
        assert loads_after == loads_before, (
            "fetch() must not re-navigate after navigate_and_settle already "
            f"settled there; load_url calls went {loads_before} → {loads_after}"
        )


    def test_navigate_and_settle_waits_for_nonempty_title_before_reading_url(self, monkeypatch):
        """
        Bridge ready, title starts empty (still navigating), then becomes
        nonempty → return the final URL. get_current_url() must be read
        only AFTER the first nonempty title (a mid-redirect URL is stale).

        mutation: drop the empty-title wait (go back to get_current_url
        immediately after the bridge is ready) → this test must go red.
        """
        monkeypatch.setattr(cf_transport_impl, 'SETTLE_TITLE_TIMEOUT_S', 0.2)
        monkeypatch.setattr(cf_transport_impl, 'SETTLE_TITLE_POLL_S', 0.001)

        class DelayedTitleWindow(FakeWindowNavigate):
            def __init__(self):
                super().__init__(title='')
                self._title_reads = 0
                self.title_became_nonempty = False
                self.url_read_after_nonempty_title = None

            def evaluate_js(self, code, callback=None):
                self.calls.append(('evaluate_js', code, callback))
                if callback is not None:
                    if not self._never_callback:
                        callback(self._eval_callback_result.get('default', {}))
                    return None
                if 'document.title' in code:
                    self._title_reads += 1
                    if self._title_reads >= 2:
                        self._title = 'JavTen'
                        self.title_became_nonempty = True
                    return self._title
                # T6/F-1: the settled URL is now read from location.href (WebView2's
                # get_current_url() does not follow redirects), so the ordering probe
                # moved here. The assertion's intent is unchanged: the URL must not be
                # read while the page is still navigating.
                if 'location.href' in code:
                    self.url_read_after_nonempty_title = self.title_became_nonempty
                    return self._current_url
                if 'outerHTML' in code:
                    return self._head
                return None

        win = DelayedTitleWindow()
        win.events._pywebviewready = FakeEvent(initial=True)
        transport = PyWebViewCfTransport({'fc-javten': win}, None)

        result = transport.navigate_and_settle(self.JAVTEN_URL, 'fc-javten')

        assert result == self.JAVTEN_URL
        assert win.title_became_nonempty is True, (
            "title must have become nonempty during the settle wait"
        )
        assert win.url_read_after_nonempty_title is True, (
            "the settled URL (location.href) must be read only after document.title "
            f"is nonempty; call log: {win.calls}"
        )


# ──────────────────────────────────────────────────────────────
# Tests: navigate_and_settle() concurrency (TASK-118a-T10 / F-1 / INV-2)
# ──────────────────────────────────────────────────────────────

class FakeWindowConcurrent(FakeWindowNavigate):
    """Shared window used to build a deterministic two-thread race for INV-2
    (T10) oracle-1: models "one video window, only one current URL" —
    load_url() overwrites _current_url, and location.href always mirrors it
    (href=None inherited from FakeWindowNavigate keeps that mirroring — no
    explicit redirect target is configured here).

    Two hooks let a test choreograph the exact interleaving TASK-118a-T10
    describes, without any bare sleep:
      after_navigate[url] — fires the instant load_url(url) completes. Used
        to release the OTHER thread only once THIS thread has actually issued
        its own load_url, so "who goes first" does not depend on OS thread
        scheduling.
      before_href_read — fires every time location.href is read, right
        before the read. Used to make thread A wait (bounded) on an Event
        thread B sets when it completes ITS OWN load_url — the exact
        oracle-1 hook point the task card specifies.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.after_navigate: dict[str, "callable"] = {}
        self.before_href_read = None

    def load_url(self, url):
        super().load_url(url)
        cb = self.after_navigate.get(url)
        if cb is not None:
            cb()

    def evaluate_js(self, code, callback=None):
        if callback is None and 'location.href' in code and self.before_href_read is not None:
            self.before_href_read()
        return super().evaluate_js(code, callback)


class TestNavigateAndSettleConcurrency:
    """
    TASK-118a-T10 / F-1 — INV-2: per-site navigation lock. Both oracles use
    threading.Event for deterministic interleaving (CLAUDE.md: barrier-driven,
    not bare-sleep-driven). The only real-time wait is the 0.5s the card
    specifies for oracle-1's "has the other thread clobbered me yet?" probe.
    """

    URL_A = 'https://javten.com/search?kw=AAA'
    URL_B = 'https://javten.com/search?kw=BBB'

    def test_oracle_1_concurrent_calls_each_return_their_own_url(self):
        """
        oracle-1: two threads call navigate_and_settle(url, 'fc-javten')
        concurrently on the SAME shared window with DIFFERENT keywords. Each
        must get back its own URL.

        Deterministic interleaving:
          - B only starts its own navigate_and_settle after A has issued ITS
            OWN load_url (a_navigated Event) — fixes "who goes first" without
            depending on OS thread scheduling.
          - A waits (timeout=0.5s) on b_loaded — set the instant B completes
            ITS OWN load_url — right before reading location.href.

        With the per-site lock (current code): B blocks trying to acquire the
        lock for as long as A holds it, so b_loaded never fires within 0.5s →
        A times out and reads its OWN url.
        Without the lock (mutation target): B runs immediately, overwrites
        the shared window's current URL, and sets b_loaded well within 0.5s →
        A reads B's url instead of its own → FAIL.
        """
        win = FakeWindowConcurrent()
        transport = PyWebViewCfTransport({'fc-javten': win}, None)

        a_navigated = threading.Event()
        b_loaded = threading.Event()
        win.after_navigate[self.URL_A] = a_navigated.set
        win.after_navigate[self.URL_B] = b_loaded.set
        win.before_href_read = lambda: b_loaded.wait(timeout=0.5)

        results: dict = {}
        errors: list = []

        def run_a():
            try:
                results['a'] = transport.navigate_and_settle(self.URL_A, 'fc-javten')
            except BaseException as e:
                errors.append(e)

        def run_b():
            # Scaffolding for THIS TEST's determinism (who starts first), not
            # the thing under test — the lock inside navigate_and_settle is.
            a_navigated.wait(timeout=5.0)
            try:
                results['b'] = transport.navigate_and_settle(self.URL_B, 'fc-javten')
            except BaseException as e:
                errors.append(e)

        t_a = threading.Thread(target=run_a, name='oracle1-A')
        t_b = threading.Thread(target=run_b, name='oracle1-B')
        t_a.start()
        t_b.start()
        t_a.join(timeout=5.0)
        t_b.join(timeout=5.0)

        assert not t_a.is_alive() and not t_b.is_alive(), "threads did not finish within the join timeout"
        if errors:
            raise errors[0]

        assert results.get('a') == self.URL_A, (
            f"thread A must read back its OWN url; got {results.get('a')!r} "
            "(getting url_b means the per-site nav lock is missing/ineffective)"
        )
        assert results.get('b') == self.URL_B, (
            f"thread B must read back its OWN url; got {results.get('b')!r}"
        )


# ──────────────────────────────────────────────────────────────
# Tests: available_sites() (TASK-118a-T9)
# ──────────────────────────────────────────────────────────────


class TestPendingConfirmReady:
    """TASK-163b-T7a I-B'-1: pending 的 key 在 confirm_ready 之前不可用；關閉後不復活。"""

    @staticmethod
    def _pending_transport(wins=None):
        wins = wins or {'javlibrary': FakeWindow(), 'fc-javten': FakeWindow()}
        t = PyWebViewCfTransport(
            wins,
            {},
            pending={'javlibrary', 'fc-javten'},
        )
        return t, wins

    def test_pending_site_is_unavailable_until_confirmed(self):
        t, wins = self._pending_transport()
        assert t.available_sites() == []
        for call in (
            lambda: t.fetch('https://www.javlibrary.com/ja/', 'javlibrary'),
            lambda: t.begin_solve('https://www.javlibrary.com/', 'javlibrary'),
            lambda: t.is_ready('javlibrary'),
            lambda: t.navigate_and_settle('https://javten.com/', 'fc-javten'),
        ):
            with pytest.raises(CfTransportUnavailable):
                call()
        for w in wins.values():
            assert [c for c in w.calls if c[0] == 'load_url'] == []
        t.confirm_ready('javlibrary')
        assert t.available_sites() == ['javlibrary']
        t.confirm_ready('fc-javten')
        assert t.available_sites() == ['fc-javten', 'javlibrary']


    def test_mark_failed_leaves_pending_and_records_failed(self):
        """168e-T13 CD-4：WebView2 初始化失敗的站不再算「準備中」，改記為失敗。"""
        t, wins = self._pending_transport()
        events = []
        t.set_change_listener(lambda: events.append(1))
        t.mark_failed('javlibrary')
        assert t.preparing_sites() == ['fc-javten']
        assert t.failed_sites() == ['javlibrary']
        assert t.available_sites() == []
        assert events == [1]
        with pytest.raises(CfTransportUnavailable):
            t.is_ready('javlibrary')


