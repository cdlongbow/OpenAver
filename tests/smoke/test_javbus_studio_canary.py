"""Live smoke canary — JavBus studio pages (TASK-173-T14).

Guards "latest works by studio" against JavBus layout changes: list-page
structure (#waterfall / number extraction) and detail-page studio link form.

Verdict: probe unreachable -> skip (reason starts with UNVERIFIED, which means
NOT verified, not passed). After the probe passes, ANY failure is pytest.fail,
including SourceBlocked / SourceUnreachable (200 without #waterfall). Never
turn those into skip (BE-PY-03).

Self-contained: does not import tests/smoke/_canary_*.py. All live requests go
through JavBusScraper's own session (bare requests get 200 without #waterfall).
No site HTML/JSON is stored; codes and thresholds are constants, fix them
against the live site if a title is delisted.
"""
import time

import pytest

pytestmark = pytest.mark.smoke

_THROTTLE = 1.0  # seconds before every JavBus request
_MIN_IDS = 20


@pytest.fixture(scope="module")
def scraper():
    """One scraper (one session) shared by the whole module; probes once."""
    from core.scrapers.javbus import JavBusScraper

    s = JavBusScraper(lang="zh-tw")
    probe_url = f"{s.BASE_URL}{s._get_lang_prefix()}/"
    try:
        time.sleep(_THROTTLE)
        reachable = s._session.get(probe_url, timeout=10).status_code == 200
    except Exception:
        reachable = False
    if not reachable:
        pytest.skip(f"UNVERIFIED: JavBus unreachable, probe GET {probe_url} did not return 200")
    return s


def _list_ids(scraper, ref):
    time.sleep(_THROTTLE)
    try:
        return scraper.get_ids_from_studio(ref)
    except Exception as exc:
        pytest.fail(f"get_ids_from_studio{ref} raised {type(exc).__name__}: {exc}")


def _sample(scraper, number):
    time.sleep(_THROTTLE)
    return scraper.fetch_studio_sample(number)


def test_studio_list_censored_7q(scraper):
    ids = _list_ids(scraper, ("censored", "7q"))
    assert len(ids) >= _MIN_IDS, f"/studio/7q parsed {len(ids)} ids, expected >= {_MIN_IDS}"


def test_studio_list_uncensored_3a(scraper):
    ids = _list_ids(scraper, ("uncensored", "3a"))
    assert len(ids) >= _MIN_IDS, f"/uncensored/studio/3a parsed {len(ids)} ids, expected >= {_MIN_IDS}"


def test_studio_sample_censored_sone205(scraper):
    result = _sample(scraper, "SONE-205")
    assert result == ("censored", "7q"), result


def test_studio_sample_uncensored_heyzo1000(scraper):
    result = _sample(scraper, "HEYZO-1000")
    assert result == ("uncensored", "3a"), result
