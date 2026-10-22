"""自訂來源解譯器：scrape／scrape_detail／run_tests 的行為（全離線，FakeTransport）。"""

import dataclasses
import itertools

import pytest

from core.custom_source import schema
import core.custom_source.interpret as interpret
from core.custom_source.extract import parse_html
from core.custom_source.fetch import FetchError
from core.custom_source.interpret import accepts_number, format_results, run_tests, scrape, scrape_detail
from core.proxy_policy import ProxySettings
from core.scrapers.models import ScraperConfig
from tests.unit._custom_source_fake import FakeTransport, page, redirect
from tests.unit._custom_source_pages import FIXTURE_DIR, PAGES


@pytest.fixture(autouse=True)
def _no_real_dns_or_sleep(monkeypatch):
    monkeypatch.setattr("core.public_target.resolve_host", lambda host: ["8.8.8.8"])
    monkeypatch.setattr("core.custom_source.fetch.rate_limit", lambda delay=0: None)


def _txt(name):
    return PAGES[name]


def _pg(name):
    return page(_txt(name))


def _spec(name):
    return schema.load_file(FIXTURE_DIR / f"{name}.yaml")


def _hrefs(name, css):
    return [a["href"] for a in parse_html(_txt(name)).select(css)]


def _step0(name, **changes):
    spec = _spec(name)
    return dataclasses.replace(spec, steps=(dataclasses.replace(spec.steps[0], **changes), *spec.steps[1:]))


def _cands(*suffixes):
    return _step0("candidates", candidates=suffixes)


def _run(spec, number, routes):
    transport = FakeTransport(routes)
    return scrape(spec, number, CFG, transport), transport


CFG = ScraperConfig(proxy_settings=ProxySettings())
CAND = "https://candidates.example/video/chinese-subtitles/sone-205"
SOG = "https://single-og.example/sone-205"
TWO = "https://two-step.example/search/"
TEXT = "https://text.example/search/?q=FC2PPV"


def _routes_for(name):
    if name == "single-og":
        return {SOG: _pg("single-og"), "https://single-og.example/zzzz-999": page("", 404)}
    if name == "single-og-min":
        return {"https://single-og-min.example/videos/sone-205/": _pg("single-og-min"),
                "https://single-og-min.example/videos/zzzz-999/": page("", 404)}
    if name == "text":
        hit = _hrefs("text-search", ".card-video__title a")[0]
        return {TEXT + "2439990": _pg("text-search"), hit: _pg("text-detail"),
                TEXT + "9999999": _pg("text-search-empty")}
    if name == "two-step":
        uc, c = _hrefs("two-step-search", "h3.entry-title a")
        return {TWO + "SONE-205": _pg("two-step-search"), uc: _pg("two-step-detail-a"),
                c: _pg("two-step-detail-b"), TWO + "ZZZZ-999": _pg("two-step-empty")}
    if name == "fuzzy":
        hit = _hrefs("fuzzy-search", "h3.jeg_post_title a")[0]
        return {"https://fuzzy.example/?s=IPZZ-100": _pg("fuzzy-search"), hit: _pg("fuzzy-detail"),
                "https://fuzzy.example/?s=ZZZZ-999": _pg("fuzzy-search")}
    miss = CAND.replace("sone-205", "zzzz-999")
    return {CAND + "c/": _pg("two-step-detail-a"), CAND + "uc/": _pg("two-step-detail-b"),
            CAND + "/": redirect(CAND + "c/"),
            miss + "c/": page("", 404), miss + "uc/": page("", 404), miss + "/": page("", 404)}


@pytest.mark.parametrize("name, number", [("text", "SONE-205"), ])
def test_pattern_mismatch_skipped_without_requests(name, number):
    result, transport = _run(_spec(name), number, {})
    assert (result.status, transport.calls) == ("skipped", [])


@pytest.mark.parametrize("name, number, first_call", [
    ("single-og", "sone205", SOG),
    ("text", "fc2ppv2439990", TEXT + "2439990"),
    ("candidates", "sone-205", CAND + "c/"),
])
def test_template_placeholders_render_request_url(name, number, first_call):
    result, transport = _run(_spec(name), number, _routes_for(name) | _routes_for("fuzzy"))
    assert transport.calls[0] == first_call


@pytest.mark.parametrize("limit, expected_calls", [(5, 6), ])
def test_results_capped_at_max_detail_fetch(monkeypatch, limit, expected_calls):
    monkeypatch.setattr(interpret, "MAX_DETAIL_FETCH", limit)
    urls = [f"https://two-step.example/v/sone-205-{i}/" for i in range(20)]
    html = "".join(f'<h3 class="entry-title"><a href="{u}">SONE-205 v{i}</a></h3>' for i, u in enumerate(urls))
    routes = {TWO + "SONE-205": page(html)} | {u: _pg("two-step-detail-a") for u in urls}
    result, transport = _run(_spec("two-step"), "SONE-205", routes)
    assert (len(transport.calls), len(result.items)) == (expected_calls, expected_calls - 1)


@pytest.mark.parametrize("number, hit, status, calls", [
    ("SONE-205C", "", "not_found", 1),
])
def test_empty_filter_string_matches_nothing(number, hit, status, calls):
    html = "".join(f'<div class="card-video__title"><a href="/v/n{i}">Title {i}</a></div>' for i in range(5)) + hit
    spec = dataclasses.replace(_step0("text", url="https://text.example/search/?q={number}"), number_pattern="[A-Z0-9-]+")
    routes = {"https://text.example/search/?q=" + number: page(html), "https://text.example/v/1234": _pg("text-detail")}
    result, transport = _run(spec, number, routes)
    assert (result.status, len(transport.calls)) == (status, calls)


@pytest.mark.parametrize("name, number, requested", [
    ("candidates", "ABC-123-C", False),
])
def test_empty_url_placeholder_skips_request(name, number, requested):
    spec = dataclasses.replace(_step0(name, url="https://a.example/v/{number_digits}"), number_pattern="[A-Z0-9-]+")
    result, transport = _run(spec, number, {"https://a.example/v/123": page("", 404)})
    assert bool(transport.calls) is requested
    assert requested or result.status == "not_found"


def test_number_mismatch_candidate_dropped():
    spec = _spec("candidates")
    other = page(_txt("two-step-detail-a").replace("SONE-205", "SONE-999"))
    routes = {CAND.replace("205", "206") + s: _pg("two-step-detail-a") for s in ("c/", "uc/", "/")}
    result, _ = _run(spec, "SONE-206", routes)
    assert result.status == "not_found"
    result, _ = _run(spec, "SONE-205", {CAND + "c/": _pg("two-step-detail-a"), CAND + "uc/": other, CAND + "/": page("", 404)})
    assert (result.status, [i.detail_url for i in result.items], result.items[0].fields["number"]) == ("ok", [CAND + "c/"], "SONE-205")


def test_body_contains_hit_is_not_found():
    result, transport = _run(_step0("two-step", not_found_body="sone-205c"), "SONE-205", _routes_for("two-step"))
    assert (result.status, transport.calls) == ("not_found", [TWO + "SONE-205"])
    result, _ = _run(_step0("single-og", not_found_body="<h1"), "SONE-205", _routes_for("single-og"))
    assert result.status == "not_found"


@pytest.mark.parametrize("routes, reason, status", [
    pytest.param({SOG: page("", 503)}, "http_status", 503, id="http503"),
])
def test_error_reasons(routes, reason, status):
    result, _ = _run(_spec("single-og"), "SONE-205", routes)
    assert (result.status, result.reason, result.http_status) == ("error", reason, status)


@pytest.mark.parametrize("c_route, uc_route, status, reason, count", [
    (_pg("two-step-detail-a"), page("", 500), "ok", None, 1),
    (page("", 500), page("", 500), "error", "http_status", 0),
])
def test_partial_failure_returns_successes(c_route, uc_route, status, reason, count):
    result, _ = _run(_cands("c", "uc"), "SONE-205", {CAND + "c/": c_route, CAND + "uc/": uc_route})
    assert (result.status, result.reason, len(result.items)) == (status, reason, count)


def _boundary_hit(keep, prefix, suffix):
    blocked = "abcdefghijklmnopqrstuvwxyz" if keep[0].isalpha() else "0123456789"
    return not (prefix and prefix[-1] in blocked) and not (suffix and suffix[0] in "0123456789")


@pytest.mark.parametrize("keep, prefix, suffix", [
    ("sone-205", "", "c"), ("sone-205", "", "0"), ("sone-205", "x", ""), ("2439990", "x", ""), ("2439990", "1", "")])
def test_link_match_respects_number_boundaries(keep, prefix, suffix):
    hit = _boundary_hit(keep, prefix, suffix)
    assert interpret._link_matches(keep, prefix + keep + suffix, "") is hit
    assert interpret._link_matches(keep, "/v/123", (prefix + keep + suffix).upper()) is hit


@pytest.mark.parametrize("routes, calls, status, reason, count", [
    ({"a": FetchError("timeout")}, 1, "error", "timeout", 0),
])
def test_outage_stops_remaining_candidates(routes, calls, status, reason, count):
    result, transport = _run(_cands("a", "b", "c"), "SONE-205", {f"{CAND}{k}/": v for k, v in routes.items()})
    assert (len(transport.calls), result.status, result.reason, len(result.items)) == (calls, status, reason, count)


@pytest.mark.parametrize("url, routes, secrets", [
    ("https://a.example/v/x?apikey=SECRET1#frag", {"https://a.example/v/x?apikey=SECRET1#frag": page("", 500)}, ("SECRET1", "apikey", "frag")),
    ("https://a.example/v/y", {"https://a.example/v/y": redirect("https://a.example/z?token=SECRET2"),
                              "https://a.example/z?token=SECRET2": page("")}, ("SECRET2", "token")),
])
def test_failure_log_drops_query_and_fragment(caplog, url, routes, secrets):
    caplog.set_level("INFO")
    result, _ = _run(_step0("single-og", url=url), "SONE-205", routes)
    assert result.status == "error" and "a.example/" in caplog.text
    assert not any(word in caplog.text for word in secrets)


@pytest.mark.parametrize("spec_name, number, route, status, calls", [
    ("single-og", "SONE-205", _pg("single-og"), "ok", 1),
])
def test_scrape_detail(spec_name, number, route, status, calls):
    transport = FakeTransport({SOG: route})
    result = scrape_detail(_spec(spec_name), SOG, number, CFG, transport)
    assert (result.status, len(transport.calls)) == (status, calls)


@pytest.mark.parametrize("name", ["single-og", ])
def test_fixture_tests_all_pass(name):
    results = run_tests(_spec(name), CFG, FakeTransport(_routes_for(name)))
    assert results and all(r.passed for r in results), format_results(results)


def _with_cases(*cases):
    spec = _spec("single-og")
    return dataclasses.replace(spec, tests=tuple(schema.Case("SONE-205", "ok", c) for c in cases))


@pytest.mark.parametrize("expect, key, expected, actual_of", [
    ((("title", "WRONG"),), "title", "WRONG", lambda f: f["title"]),
    ((("tags_max", 0),), "tags_max", 0, lambda f: len(f["tags"])),
])
def test_run_tests_reports_key_expected_actual(expect, key, expected, actual_of):
    fields = _run(_spec("single-og"), "SONE-205", _routes_for("single-og"))[0].items[0].fields
    if key == "tags_exclude":
        expect = ((key, (fields["tags"][0],)),)
        expected = [fields["tags"][0]]
    results = run_tests(_with_cases((("tags_max", 99),), expect), CFG, FakeTransport(_routes_for("single-og")))
    assert results[0].passed and results[1].index == 2 and not results[1].passed
    mismatch = results[1].mismatches[0]
    assert (mismatch.key, mismatch.expected) == (key, expected)
    assert mismatch.actual == actual_of(fields)
    assert mismatch.url == SOG


# ---------- 165-T2：detail_host / public_url / nf_step / 預算 / accepts_number ----------

def test_run_tests_flags_cross_domain_detail_host():
    other = "https://detail.other.test/x"
    routes = {SOG: redirect(other), other: _pg("single-og")}
    spec = _with_cases((("title_contains", "Sample Title One"),))
    results = run_tests(spec, CFG, FakeTransport(routes))
    assert not results[0].passed
    assert results[0].mismatches == (interpret.Mismatch("detail_host", "同站 host", "detail.other.test", other),)


def _userinfo_routes():
    import re
    target = "https://alice:secret@single-og.example/x"
    body = re.sub(r'(og:image"\s+content=")[^"]*', r'\1/cover.jpg', _txt("single-og"))
    assert 'content="/cover.jpg"' in body
    return target, {SOG: redirect(target), target: page(body)}


def test_to_video_images_from_credentialed_template_have_no_userinfo():
    from core.custom_source.scraper import CustomScraper
    _, routes = _userinfo_routes()
    spec = _spec("single-og")
    result = scrape(spec, "SONE-205", CFG, FakeTransport(routes))
    video = CustomScraper(spec, "c", CFG)._to_video(result.items[0], "SONE-205")
    assert video.cover_url == "https://single-og.example/cover.jpg"
    assert "alice:secret@" not in repr(video.__dict__)


def _fake_clock(monkeypatch, step=10):
    ticks = itertools.count(0, step)
    monkeypatch.setattr("core.custom_source.fetch._now", lambda: next(ticks))


def test_budget_stops_requests_after_deadline(monkeypatch):
    _fake_clock(monkeypatch)
    transport = FakeTransport(_routes_for("candidates"))
    result = scrape(_spec("candidates"), "SONE-205", CFG, transport, budget_s=25)
    assert len(transport.calls) == 2
    assert result.status in ("ok", "multiple")


@pytest.mark.parametrize("number, expected", [
    ("DA003", True),
])
def test_accepts_number_without_pattern(number, expected):
    spec = dataclasses.replace(_spec("single-og"), number_pattern=None)
    assert accepts_number(spec, number) is expected


@pytest.mark.parametrize("placeholder, expected", [
    ("{number_compact}", "MD0317"),
])
def test_compact_placeholder_in_request_url(placeholder, expected):
    url = "https://a.example/search?q=" + expected
    spec = dataclasses.replace(_step0("single-og", url="https://a.example/search?q=" + placeholder),
                               number_pattern="[A-Z0-9-]+")
    result, transport = _run(spec, "MD-0317", {url: _pg("single-og")})
    assert transport.calls[0] == url
    assert "{" not in transport.calls[0]


