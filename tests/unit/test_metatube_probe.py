"""
tests/unit/test_metatube_probe.py — TDD-lite tests for core.metatube.probe.

Mock strategy:
  - probe_provider: pass MagicMock client directly (no patch needed).
  - probe_all: patch 'core.metatube.probe.MetatubeHttpClient' (使用端！).
    Patching the definition side (core.metatube.client.MetatubeHttpClient) would
    leave probe.py's binding unchanged → mock silently fails (gotchas #1/#3).
"""

import pytest
from unittest.mock import MagicMock, call, patch

from core.metatube.errors import (
    MetatubeNotFound,
    MetatubeUnavailable,
    MetatubeProtocolError,
)
from core.metatube.probe import (
    METATUBE_PROBE_CANARIES,
    probe_provider,
    probe_all,
)
from core.metatube.state import MetatubeConnectionState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_state():
    """New MetatubeConnectionState, pre-connected with a set of providers."""
    s = MetatubeConnectionState()
    s.connect('http://localhost:8900', '', ['FANZA', 'HEYZO', 'JAV321', 'JavBus'])
    return s


@pytest.fixture
def mock_client():
    """A bare MagicMock acting as MetatubeHttpClient."""
    return MagicMock()


# ---------------------------------------------------------------------------
# canary map completeness
# ---------------------------------------------------------------------------

def test_canary_map_exactly_26_entries():
    """METATUBE_PROBE_CANARIES must have exactly 26 entries (no more, no less)."""
    assert len(METATUBE_PROBE_CANARIES) == 26


def test_canary_map_known_values():
    """Spot-check a selection of canary values against TASK-63poc-1 §4.1."""
    assert METATUBE_PROBE_CANARIES['JavBus'] == 'SSIS-001'
    assert METATUBE_PROBE_CANARIES['FANZA'] == '1stars00141'
    assert METATUBE_PROBE_CANARIES['MGS'] == 'SIRO-5251'
    assert METATUBE_PROBE_CANARIES['DUGA'] == 'dandy-0344'
    assert METATUBE_PROBE_CANARIES['AVE'] == '4319'
    assert METATUBE_PROBE_CANARIES['DAHLIA'] == 'dldss339'
    assert METATUBE_PROBE_CANARIES['FALENO'] == 'fsdss754'
    assert METATUBE_PROBE_CANARIES['Gcolle'] == '847256'
    assert METATUBE_PROBE_CANARIES['Getchu'] == '4018339'
    assert METATUBE_PROBE_CANARIES['HeyDouga'] == '4037-479'
    assert METATUBE_PROBE_CANARIES['JAVFREE'] == '243452-1151912'
    assert METATUBE_PROBE_CANARIES['Pcolle'] == '156785614478ab480db'
    assert METATUBE_PROBE_CANARIES['TOKYO-HOT'] == 'n1500'


def test_canary_map_uncoded_providers():
    """Check the 13 uncoded providers' canary values."""
    assert METATUBE_PROBE_CANARIES['HEYZO'] == 'HEYZO-2500'
    assert METATUBE_PROBE_CANARIES['1Pondo'] == '020125_001'
    # Caribbeancom uses dash, CaribbeancomPR uses underscore
    assert METATUBE_PROBE_CANARIES['Caribbeancom'] == '020125-001'
    assert METATUBE_PROBE_CANARIES['CaribbeancomPR'] == '020125_001'
    assert METATUBE_PROBE_CANARIES['10musume'] == '053026_01'
    assert METATUBE_PROBE_CANARIES['C0930'] == 'ki230101'
    assert METATUBE_PROBE_CANARIES['H0930'] == 'ori1643'
    assert METATUBE_PROBE_CANARIES['H4610'] == 'tk0047'
    assert METATUBE_PROBE_CANARIES['MURAMURA'] == '091522_959'
    assert METATUBE_PROBE_CANARIES['MYWIFE'] == '1542'
    assert METATUBE_PROBE_CANARIES['PACOPACOMAMA'] == '082107_257'
    assert METATUBE_PROBE_CANARIES['FC2'] == '2812904'
    assert METATUBE_PROBE_CANARIES['fc2hub'] == '1152468-2725031'


def test_canary_map_no_canary_providers_absent():
    """JAV321, SOD, FC2PPVDB, KIN8 must NOT appear in the canary map."""
    for provider in ('JAV321', 'SOD', 'FC2PPVDB', 'KIN8'):
        assert provider not in METATUBE_PROBE_CANARIES, (
            f"Provider {provider!r} should have no canary but was found in map"
        )


def test_caribbeancom_dash_vs_underscore():
    """
    Critical distinction: Caribbeancom uses dash (-), CaribbeancomPR uses underscore (_).
    A swap would cause probe failures.
    """
    assert '-' in METATUBE_PROBE_CANARIES['Caribbeancom']
    assert '_' in METATUBE_PROBE_CANARIES['CaribbeancomPR']
    assert '_' not in METATUBE_PROBE_CANARIES['Caribbeancom']
    assert '-' not in METATUBE_PROBE_CANARIES['CaribbeancomPR']


# ---------------------------------------------------------------------------
# probe_provider — success path
# ---------------------------------------------------------------------------

def test_probe_provider_success_returns_true(mock_client):
    """get_info returns dict → probe returns True."""
    mock_client.get_info.return_value = {'id': 'SSIS-001', 'provider': 'JavBus'}
    result = probe_provider(mock_client, 'JavBus')
    assert result is True


def test_probe_provider_success_calls_get_info_with_canary(mock_client):
    """probe_provider must call get_info(provider, canary) exactly once."""
    mock_client.get_info.return_value = {'id': '1stars00141'}
    probe_provider(mock_client, 'FANZA')
    mock_client.get_info.assert_called_once_with('FANZA', '1stars00141')


def test_probe_provider_success_get_info_returns_none(mock_client):
    """get_info returning None (data=null) is still a 200 → True."""
    mock_client.get_info.return_value = None
    result = probe_provider(mock_client, 'FANZA')
    assert result is True


# ---------------------------------------------------------------------------
# probe_provider — 404 = failure (MAJOR-3 / probe-404 vs routing-404)
# ---------------------------------------------------------------------------

def test_probe_provider_404_is_failure(mock_client):
    """
    probe-404 = 失敗（MAJOR-3）.

    This is the KEY semantic difference from routing:
    - routing: MetatubeNotFound(404) = movie simply absent, NOT a failure
    - probe:   MetatubeNotFound(404) = canary 404 means scraper broken → False
    """
    mock_client.get_info.side_effect = MetatubeNotFound("HTTP 404 canary not found")
    result = probe_provider(mock_client, 'FANZA')
    assert result is False


# ---------------------------------------------------------------------------
# probe_provider — other MetatubeError subclasses
# ---------------------------------------------------------------------------

def test_probe_provider_unavailable_returns_false(mock_client):
    """MetatubeUnavailable (timeout / 5xx) → False."""
    mock_client.get_info.side_effect = MetatubeUnavailable("Connection refused")
    result = probe_provider(mock_client, 'HEYZO')
    assert result is False


def test_probe_provider_protocol_error_returns_false(mock_client):
    """MetatubeProtocolError (bad JSON) → False."""
    mock_client.get_info.side_effect = MetatubeProtocolError("Invalid JSON")
    result = probe_provider(mock_client, 'JavBus')
    assert result is False


# ---------------------------------------------------------------------------
# probe_provider — no canary (JAV321 / SOD / FC2PPVDB / KIN8)
# ---------------------------------------------------------------------------

def test_probe_provider_no_canary_returns_false(mock_client):
    """Provider with no canary → False, no request sent."""
    result = probe_provider(mock_client, 'JAV321')
    assert result is False


def test_probe_provider_no_canary_does_not_call_get_info(mock_client):
    """No canary → get_info must NOT be called (no unnecessary request)."""
    probe_provider(mock_client, 'JAV321')
    mock_client.get_info.assert_not_called()


def test_probe_provider_no_canary_sod(mock_client):
    """SOD has no canary → False, no request."""
    result = probe_provider(mock_client, 'SOD')
    assert result is False
    mock_client.get_info.assert_not_called()


def test_probe_provider_no_canary_fc2ppvdb(mock_client):
    """FC2PPVDB has no canary → False, no request."""
    result = probe_provider(mock_client, 'FC2PPVDB')
    assert result is False
    mock_client.get_info.assert_not_called()


def test_probe_provider_no_canary_kin8(mock_client):
    """KIN8 has no canary → False, no request."""
    result = probe_provider(mock_client, 'KIN8')
    assert result is False
    mock_client.get_info.assert_not_called()


def test_probe_provider_unknown_provider_returns_false(mock_client):
    """Completely unknown provider name → False, no request."""
    result = probe_provider(mock_client, 'NONEXISTENT_PROVIDER_XYZ')
    assert result is False
    mock_client.get_info.assert_not_called()


# ---------------------------------------------------------------------------
# probe_all — mock patch target: core.metatube.probe.MetatubeHttpClient
# ---------------------------------------------------------------------------

def test_probe_all_each_worker_creates_own_client():
    """
    Each worker creates its own MetatubeHttpClient instance (not shared).
    Patching the USE SITE (core.metatube.probe.MetatubeHttpClient) not the
    definition site (core.metatube.client.MetatubeHttpClient).
    """
    state = MetatubeConnectionState()
    state.connect('http://localhost:8900', '', ['FANZA', 'HEYZO'])

    with patch('core.metatube.probe.MetatubeHttpClient') as MockClient:
        MockClient.return_value.get_info.return_value = {'id': 'x'}
        probe_all('http://localhost:8900', '', state, ['FANZA', 'HEYZO'])
        # 2 providers → MetatubeHttpClient() instantiated exactly 2 times
        assert MockClient.call_count == 2


def test_probe_all_mixed_results_correct_state(fresh_state):
    """
    probe_all with mixed results correctly updates state:
    - FANZA succeeds (200) → mark_available
    - HEYZO fails (404) → mark_failed
    """
    with patch('core.metatube.probe.MetatubeHttpClient') as MockClient:
        def get_info_side_effect(provider, movie_id):
            if provider == 'FANZA':
                return {'id': '1stars00141'}
            raise MetatubeNotFound(f"404 for {provider}")

        MockClient.return_value.get_info.side_effect = get_info_side_effect

        result = probe_all(
            'http://localhost:8900', '', fresh_state, ['FANZA', 'HEYZO']
        )

    assert result['FANZA'] is True
    assert result['HEYZO'] is False
    assert fresh_state.is_available('metatube:FANZA') is True
    assert fresh_state.is_available('metatube:HEYZO') is False


def test_probe_all_returns_complete_dict(fresh_state):
    """probe_all must return a dict with all requested provider names as keys."""
    providers = ['FANZA', 'HEYZO', 'JAV321', 'JavBus']

    with patch('core.metatube.probe.MetatubeHttpClient') as MockClient:
        MockClient.return_value.get_info.return_value = {'id': 'x'}
        result = probe_all('http://localhost:8900', '', fresh_state, providers)

    assert set(result.keys()) == set(providers)


def test_probe_all_on_progress_called_once_per_provider(fresh_state):
    """on_progress callback must be called exactly once per provider."""
    providers = ['FANZA', 'HEYZO', 'JavBus']
    progress_calls = []

    def on_prog(done, total):
        progress_calls.append((done, total))

    with patch('core.metatube.probe.MetatubeHttpClient') as MockClient:
        MockClient.return_value.get_info.return_value = {'id': 'x'}
        probe_all('http://localhost:8900', '', fresh_state, providers,
                  on_progress=on_prog)

    assert len(progress_calls) == 3
    # All calls have total=3
    for done, total in progress_calls:
        assert total == 3
    # Last call must be (3, 3)
    assert progress_calls[-1] == (3, 3)
    # done values must be 1, 2, 3 in some order (sorted since all arrive)
    assert sorted(d for d, _ in progress_calls) == [1, 2, 3]


def test_probe_all_on_progress_none_does_not_raise(fresh_state):
    """on_progress=None (default) must not raise any exception."""
    with patch('core.metatube.probe.MetatubeHttpClient') as MockClient:
        MockClient.return_value.get_info.return_value = {'id': 'x'}
        # Should not raise
        result = probe_all(
            'http://localhost:8900', '', fresh_state, ['FANZA'], on_progress=None
        )
    assert 'FANZA' in result


def test_probe_all_all_succeed_state_all_available():
    """All providers succeed → all marked available in state."""
    state = MetatubeConnectionState()
    state.connect('http://localhost:8900', '', ['FANZA', 'JavBus', 'HEYZO'])

    with patch('core.metatube.probe.MetatubeHttpClient') as MockClient:
        MockClient.return_value.get_info.return_value = {'id': 'x'}
        result = probe_all(
            'http://localhost:8900', '',
            state, ['FANZA', 'JavBus', 'HEYZO']
        )

    assert all(v is True for v in result.values())
    assert state.is_available('metatube:FANZA') is True
    assert state.is_available('metatube:JavBus') is True
    assert state.is_available('metatube:HEYZO') is True


def test_probe_all_all_fail_state_all_unavailable():
    """All providers fail → all marked unavailable in state."""
    state = MetatubeConnectionState()
    state.connect('http://localhost:8900', '', ['FANZA', 'HEYZO'])

    with patch('core.metatube.probe.MetatubeHttpClient') as MockClient:
        MockClient.return_value.get_info.side_effect = MetatubeUnavailable("down")
        result = probe_all(
            'http://localhost:8900', '', state, ['FANZA', 'HEYZO']
        )

    assert all(v is False for v in result.values())
    assert state.is_available('metatube:FANZA') is False
    assert state.is_available('metatube:HEYZO') is False


def test_probe_all_no_canary_provider_marked_failed():
    """
    Provider with no canary (JAV321) included in provider_names:
    - probe returns False (no request sent to metatube)
    - state marks it as failed
    """
    state = MetatubeConnectionState()
    state.connect('http://localhost:8900', '', ['JAV321'])

    with patch('core.metatube.probe.MetatubeHttpClient') as MockClient:
        result = probe_all('http://localhost:8900', '', state, ['JAV321'])
        # No client instantiation should happen for a no-canary provider
        # (but the worker does create a client — it's the probe_provider logic
        # that decides not to call get_info, not probe_all; client may be created)

    assert result['JAV321'] is False
    assert state.is_available('metatube:JAV321') is False


def test_probe_all_client_created_with_correct_args():
    """MetatubeHttpClient must be created with (base_url, token)."""
    state = MetatubeConnectionState()
    state.connect('http://test-server:9000', 'mytoken', ['FANZA'])

    with patch('core.metatube.probe.MetatubeHttpClient') as MockClient:
        MockClient.return_value.get_info.return_value = {'id': 'x'}
        probe_all('http://test-server:9000', 'mytoken', state, ['FANZA'])

    # The client must have been instantiated with base_url and token
    MockClient.assert_called_with('http://test-server:9000', 'mytoken')


def test_probe_all_empty_provider_list():
    """Empty provider_names → returns empty dict, no errors."""
    state = MetatubeConnectionState()
    state.connect('http://localhost:8900', '', [])

    with patch('core.metatube.probe.MetatubeHttpClient'):
        result = probe_all('http://localhost:8900', '', state, [])

    assert result == {}


def test_probe_all_single_provider_progress():
    """Single provider: on_progress called once with (1, 1)."""
    state = MetatubeConnectionState()
    state.connect('http://localhost:8900', '', ['FANZA'])
    progress_calls = []

    with patch('core.metatube.probe.MetatubeHttpClient') as MockClient:
        MockClient.return_value.get_info.return_value = {'id': 'x'}
        probe_all('http://localhost:8900', '', state, ['FANZA'],
                  on_progress=lambda d, t: progress_calls.append((d, t)))

    assert progress_calls == [(1, 1)]
