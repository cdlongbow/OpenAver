"""Unit tests for core/metatube/state.py — MetatubeConnectionState singleton.

Covers:
1. connect bulk-true
2. disconnect bulk-false (keys preserved)
3. mark_failed single
4. mark_available restore
5. availability_map returns copy
6. is_available unknown id → False
7. repeated connect resets
8. thread-safe parallel mark_failed/mark_available (ThreadPoolExecutor)
9. availability_map no race during concurrent marks
"""
import pytest
from concurrent.futures import ThreadPoolExecutor

from core.metatube.state import MetatubeConnectionState


# ---------------------------------------------------------------------------
# Fixture: fresh state instance per test (avoids module-singleton pollution)
# ---------------------------------------------------------------------------

@pytest.fixture
def state():
    """Return a fresh MetatubeConnectionState for each test."""
    return MetatubeConnectionState()


# ---------------------------------------------------------------------------
# 1. connect bulk-true
# ---------------------------------------------------------------------------

def test_connect_bulk_true(state):
    state.connect('http://host', 'tok', ['FANZA', 'HEYZO'])
    assert state.is_available('metatube:FANZA') is True
    assert state.is_available('metatube:HEYZO') is True
    assert state.is_connected is True
    assert state.provider_count == 2
    assert state.base_url == 'http://host'
    assert state.token == 'tok'


# ---------------------------------------------------------------------------
# 2. disconnect bulk-false (keys preserved)
# ---------------------------------------------------------------------------

def test_disconnect_bulk_false_keys_preserved(state):
    state.connect('http://host', 'tok', ['FANZA', 'HEYZO'])
    state.disconnect()

    assert state.is_available('metatube:FANZA') is False
    assert state.is_available('metatube:HEYZO') is False
    assert state.is_connected is False
    assert state.base_url is None
    assert state.token is None

    # Keys must still be present in the map (for UI grey capsules)
    m = state.availability_map()
    assert 'metatube:FANZA' in m
    assert 'metatube:HEYZO' in m
    assert m['metatube:FANZA'] is False
    assert m['metatube:HEYZO'] is False


# ---------------------------------------------------------------------------
# 3. mark_failed single (does not affect other keys)
# ---------------------------------------------------------------------------

def test_mark_failed_single(state):
    state.connect('http://host', 'tok', ['FANZA', 'HEYZO'])
    state.mark_failed('metatube:FANZA')
    assert state.is_available('metatube:FANZA') is False
    assert state.is_available('metatube:HEYZO') is True  # unaffected


# ---------------------------------------------------------------------------
# 4. mark_available restores after mark_failed
# ---------------------------------------------------------------------------

def test_mark_available_restore(state):
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')
    assert state.is_available('metatube:FANZA') is False
    state.mark_available('metatube:FANZA')
    assert state.is_available('metatube:FANZA') is True


# ---------------------------------------------------------------------------
# 5. availability_map returns a copy (mutate does not affect internal state)
# ---------------------------------------------------------------------------

def test_availability_map_returns_copy(state):
    state.connect('http://host', 'tok', ['FANZA'])
    result = state.availability_map()
    assert result['metatube:FANZA'] is True

    # Mutate the returned dict
    result['metatube:FANZA'] = False

    # Internal state must be unchanged
    assert state.is_available('metatube:FANZA') is True


# ---------------------------------------------------------------------------
# 6. is_available unknown id → False
# ---------------------------------------------------------------------------

def test_is_available_unknown_id_false(state):
    # Before any connect — empty _availability
    assert state.is_available('metatube:UNKNOWN') is False

    # After connect with known providers — unknown id still False
    state.connect('http://host', 'tok', ['FANZA'])
    assert state.is_available('metatube:UNKNOWN') is False


# ---------------------------------------------------------------------------
# 7. repeated connect resets (bulk-true overwrites failed state)
# ---------------------------------------------------------------------------

def test_repeated_connect_resets(state):
    state.connect('http://host1', 'tok1', ['FANZA'])
    state.mark_failed('metatube:FANZA')
    assert state.is_available('metatube:FANZA') is False

    # Second connect with updated URL and extended provider list
    state.connect('http://host2', 'tok2', ['FANZA', 'HEYZO'])
    assert state.is_available('metatube:FANZA') is True   # bulk-true overwrote
    assert state.is_available('metatube:HEYZO') is True
    assert state.base_url == 'http://host2'
    assert state.provider_count == 2


# ---------------------------------------------------------------------------
# 8a. Thread-safe: parallel toggle (mark_failed then mark_available) → all True
# ---------------------------------------------------------------------------

def test_parallel_toggle_all_available(state):
    providers = [f'P{i}' for i in range(20)]
    state.connect('http://host', '', providers)

    def toggle(name):
        sid = f'metatube:{name}'
        state.mark_failed(sid)
        state.mark_available(sid)

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(toggle, providers))

    for n in providers:
        assert state.is_available(f'metatube:{n}') is True


# ---------------------------------------------------------------------------
# 8b. Thread-safe: parallel mark_failed → all False
# ---------------------------------------------------------------------------

def test_parallel_mark_failed_all_false(state):
    providers = [f'Q{i}' for i in range(20)]
    state.connect('http://host', '', providers)

    def fail(name):
        state.mark_failed(f'metatube:{name}')

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(fail, providers))

    for n in providers:
        assert state.is_available(f'metatube:{n}') is False


# ---------------------------------------------------------------------------
# 9. availability_map does not raise during concurrent marks
# ---------------------------------------------------------------------------

def test_availability_map_no_race_concurrent(state):
    providers = [f'R{i}' for i in range(30)]
    state.connect('http://host', '', providers)

    exceptions = []

    def worker(name):
        try:
            sid = f'metatube:{name}'
            state.mark_failed(sid)
            _ = state.availability_map()  # concurrent snapshot
            state.mark_available(sid)
        except Exception as e:
            exceptions.append(e)

    with ThreadPoolExecutor(max_workers=15) as ex:
        list(ex.map(worker, providers))

    assert exceptions == [], f"Unexpected exceptions: {exceptions}"


# ---------------------------------------------------------------------------
# Extra: mark_failed / mark_available on unknown source_id (no raise)
# ---------------------------------------------------------------------------

def test_mark_unknown_source_id_no_raise(state):
    # Should not raise — just writes to dict
    state.mark_failed('metatube:NEWONE')
    assert state.is_available('metatube:NEWONE') is False
    state.mark_available('metatube:NEWONE')
    assert state.is_available('metatube:NEWONE') is True


# ---------------------------------------------------------------------------
# Extra: provider_count after disconnect is 0
# ---------------------------------------------------------------------------

def test_provider_count_after_disconnect(state):
    state.connect('http://host', 'tok', ['FANZA', 'HEYZO', 'FC2'])
    assert state.provider_count == 3
    state.disconnect()
    assert state.provider_count == 0


# ---------------------------------------------------------------------------
# Fix 2 (P1b): reconnect removes stale providers
# ---------------------------------------------------------------------------

def test_reconnect_removes_stale_providers(state):
    """connect() 清舊 _availability，重連到不含舊 provider 的 server 後不殘留"""
    state.connect('http://host', '', ['FANZA', 'HEYZO'])
    # 重連到只有 JavBus 的 server
    state.connect('http://host', '', ['JavBus'])

    # 舊 provider 不應在 map 裡（因 connect 清空再重建）
    availability = state.availability_map()
    assert 'metatube:FANZA' not in availability
    assert 'metatube:HEYZO' not in availability
    # 新 provider 應在 map 且為 True
    assert availability.get('metatube:JavBus') is True


# ===========================================================================
# CD-63b-2: probe progress setters + status_dict
# ===========================================================================

def test_probe_initial_state():
    """Fresh instance: probe_done=True, probe_progress=0."""
    s = MetatubeConnectionState()
    assert s.probe_done is True
    assert s.probe_progress == 0


def test_probe_set_started():
    """set_probe_started() → probe_done=False, probe_progress=0."""
    s = MetatubeConnectionState()
    s.set_probe_started()
    assert s.probe_done is False
    assert s.probe_progress == 0


def test_probe_set_progress():
    """set_probe_progress(5, 30) → probe_progress==5."""
    s = MetatubeConnectionState()
    s.set_probe_started()
    s.set_probe_progress(5, 30)
    assert s.probe_progress == 5
    assert s.probe_done is False  # still in progress


def test_probe_set_done():
    """set_probe_done() → probe_done=True."""
    s = MetatubeConnectionState()
    s.set_probe_started()
    s.set_probe_progress(5, 30)
    s.set_probe_done()
    assert s.probe_done is True


def test_probe_setter_sequence_no_deadlock():
    """Single-threaded setter sequence completes without deadlock."""
    s = MetatubeConnectionState()
    # initial
    assert s.probe_done is True
    assert s.probe_progress == 0
    # start
    s.set_probe_started()
    assert s.probe_done is False
    assert s.probe_progress == 0
    # progress
    s.set_probe_progress(5, 30)
    assert s.probe_progress == 5
    # done
    s.set_probe_done()
    assert s.probe_done is True


def test_status_dict_shape():
    """status_dict() returns all required keys."""
    s = MetatubeConnectionState()
    d = s.status_dict()
    assert set(d.keys()) == {"connected", "base_url", "probe_done", "probe_progress", "providers"}
    assert isinstance(d["connected"], bool)
    assert d["base_url"] is None  # not connected
    assert isinstance(d["probe_done"], bool)
    assert isinstance(d["probe_progress"], int)
    assert isinstance(d["providers"], list)


def test_status_dict_after_connect_reflects_providers():
    """status_dict() providers reflects availability_map after connect()."""
    s = MetatubeConnectionState()
    s.connect('http://host', 'tok', ['FANZA', 'HEYZO'])
    d = s.status_dict()

    assert d["connected"] is True
    assert d["base_url"] == 'http://host'
    # providers list has entries for FANZA and HEYZO
    provider_ids = {p["id"] for p in d["providers"]}
    assert 'metatube:FANZA' in provider_ids
    assert 'metatube:HEYZO' in provider_ids
    # all available=True right after connect
    for p in d["providers"]:
        assert p["available"] is True


def test_status_dict_probe_flags():
    """status_dict() probe_done/probe_progress update with setters."""
    s = MetatubeConnectionState()
    s.set_probe_started()
    s.set_probe_progress(3, 10)
    d = s.status_dict()
    assert d["probe_done"] is False
    assert d["probe_progress"] == 3

    s.set_probe_done()
    d2 = s.status_dict()
    assert d2["probe_done"] is True


# ===========================================================================
# FIX 3: generation guard tests
# ===========================================================================

def test_connect_bumps_generation(state):
    """connect() must increment _generation."""
    gen_before = state.generation
    state.connect('http://host', 'tok', ['FANZA'])
    assert state.generation == gen_before + 1


def test_connect_returns_new_generation(state):
    """66 Codex P2: connect() 必須回傳它所設的 generation（lock 內原子取得）。

    這是 _connect_sync 的契約——它把此值帶給 _fire_probe，避免在 await 後重讀
    state.generation 而拿到並發 connect/disconnect 推進後的錯誤值。
    """
    gen0 = state.generation
    returned = state.connect('http://host', 'tok', ['FANZA'])
    assert returned == gen0 + 1
    assert returned == state.generation  # 單執行緒測試下與 property 一致


def test_returned_generation_fences_superseded_probe(state):
    """66 Codex P2: 用 connect() 回傳的 generation 帶探測，被後續 connect 取代時
    其寫入會被 generation guard 正確擋下（不污染現役連線的 availability）。"""
    # 模擬請求 A connect，捕捉回傳 generation
    gen_a = state.connect('http://serverA', 'tokA', ['HEYZO'])
    # 模擬並發請求 B 取代 A
    gen_b = state.connect('http://serverB', 'tokB', ['HEYZO'])
    assert gen_b > gen_a
    # A 的 stale 探測（帶 gen_a）對現役 B 連線的寫入應被擋下
    state.mark_failed('metatube:HEYZO', generation=gen_a)
    assert state.is_available('metatube:HEYZO') is True  # 未被 A 污染
    # B 自己的探測（帶 gen_b，當前 generation）正常生效
    state.mark_failed('metatube:HEYZO', generation=gen_b)
    assert state.is_available('metatube:HEYZO') is False


def test_disconnect_bumps_generation(state):
    """disconnect() must increment _generation."""
    state.connect('http://host', 'tok', ['FANZA'])
    gen_after_connect = state.generation
    state.disconnect()
    assert state.generation == gen_after_connect + 1


def test_mark_available_stale_generation_is_noop(state):
    """mark_available with a stale generation must not mutate availability_map."""
    state.connect('http://host', 'tok', ['FANZA'])
    gen1 = state.generation
    # Mark FANZA as failed (current state)
    state.mark_failed('metatube:FANZA')
    assert state.is_available('metatube:FANZA') is False
    # Second connect bumps generation
    state.connect('http://host2', 'tok', ['FANZA'])
    # Try to mark_available with the old (gen1) — must be ignored
    state.mark_available('metatube:FANZA', generation=gen1)
    # FANZA was set to True by the second connect() bulk-true; stale write must not corrupt
    assert state.is_available('metatube:FANZA') is True


def test_mark_failed_stale_generation_is_noop(state):
    """mark_failed with a stale generation must not mutate availability_map."""
    state.connect('http://hostA', 'tok', ['FANZA'])
    gen1 = state.generation
    # Reconnect (new server, new generation)
    state.connect('http://hostB', 'tok', ['FANZA'])
    # Stale probe from gen1 tries to mark FANZA failed → must be ignored
    state.mark_failed('metatube:FANZA', generation=gen1)
    # FANZA should still be True (set by the second connect bulk-true)
    assert state.is_available('metatube:FANZA') is True


def test_set_probe_done_stale_generation_is_noop(state):
    """set_probe_done with a stale generation must not flip probe_done.

    Isolate the stale guard via a second connect() (which bumps generation
    without touching probe_done), so disconnect()'s own probe_done reset
    doesn't mask the guard behavior.
    """
    state.connect('http://serverA', 'tok', ['FANZA'])
    gen1 = state.generation
    state.set_probe_started(generation=gen1)   # probe_done=False (current gen)
    assert state.probe_done is False
    # A second connect bumps generation (invalidates gen1) without resetting probe_done
    state.connect('http://serverB', 'tok', ['FANZA'])
    # Stale set_probe_done from gen1 must be ignored → probe_done stays False
    state.set_probe_done(generation=gen1)
    assert state.probe_done is False
    # Current-generation set_probe_done still works
    state.set_probe_done(generation=state.generation)
    assert state.probe_done is True


def test_disconnect_resets_probe_done(state):
    """disconnect() must reset probe_done=True + probe_progress=0 (Codex P2).

    Because disconnect bumps generation, an in-flight probe's
    set_probe_done(generation=old) is generation-guarded out; disconnect must
    itself clear the flag, else /status reports probe_done=false forever after
    a disconnect during an active probe.
    """
    state.connect('http://host', 'tok', ['FANZA'])
    gen = state.generation
    state.set_probe_started(generation=gen)
    state.set_probe_progress(3, 30, generation=gen)
    assert state.probe_done is False
    assert state.probe_progress == 3
    # Disconnect mid-probe
    state.disconnect()
    assert state.probe_done is True
    assert state.probe_progress == 0
    # The stale probe finishing afterward is a no-op (generation bumped)
    state.set_probe_done(generation=gen)
    assert state.probe_done is True


def test_generation_race_scenario(state):
    """Simulate the connect-A → connect-B → stale probe-A marks_failed race.

    connect A (gen1), connect B (gen2 — rebuilds all-True for B's providers),
    then call mark_failed('metatube:BProvider', generation=gen1) → must be ignored.
    B's provider stays True.
    """
    state.connect('http://serverA', 'tokA', ['FANZA'])
    gen1 = state.generation

    state.connect('http://serverB', 'tokB', ['FANZA', 'HEYZO'])
    # gen2 = state.generation; both providers bulk-true
    assert state.is_available('metatube:FANZA') is True
    assert state.is_available('metatube:HEYZO') is True

    # Stale probe from A's session tries to mark B's provider as failed
    state.mark_failed('metatube:HEYZO', generation=gen1)
    # Must be ignored — HEYZO stays True
    assert state.is_available('metatube:HEYZO') is True

    # Current-gen mark_failed still works
    gen2 = state.generation
    state.mark_failed('metatube:HEYZO', generation=gen2)
    assert state.is_available('metatube:HEYZO') is False


def test_mark_available_current_generation_works(state):
    """mark_available/mark_failed with current generation must still work normally."""
    state.connect('http://host', 'tok', ['FANZA'])
    gen = state.generation
    state.mark_failed('metatube:FANZA', generation=gen)
    assert state.is_available('metatube:FANZA') is False
    state.mark_available('metatube:FANZA', generation=gen)
    assert state.is_available('metatube:FANZA') is True


def test_mark_no_generation_arg_backward_compatible(state):
    """Callers passing no generation (None) must still work as before."""
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')  # no generation arg
    assert state.is_available('metatube:FANZA') is False
    state.mark_available('metatube:FANZA')  # no generation arg
    assert state.is_available('metatube:FANZA') is True


# ===========================================================================
# CD-66b-3: probe_snapshot() — atomic (names, gen, base_url, token)
# ===========================================================================

def test_probe_snapshot_after_connect(state):
    """probe_snapshot() returns connected names/gen/url/token in one atomic read."""
    state.connect('http://host:8080', 'tok', ['FANZA', 'HEYZO'])
    names, gen, url, token = state.probe_snapshot()
    assert set(names) == {'FANZA', 'HEYZO'}
    assert gen == state.generation
    assert url == 'http://host:8080'
    assert token == 'tok'


def test_probe_snapshot_none_to_empty_string(state):
    """Fresh state (no connect): base_url/token None map to '', names empty, gen 0."""
    names, gen, url, token = state.probe_snapshot()
    assert names == []
    assert url == ''
    assert token == ''
    assert gen == 0


def test_probe_snapshot_names_from_availability_not_providers(state):
    """CD-66b-3: after disconnect, names still come from _availability keys.

    disconnect() clears _providers but keeps _availability keys (set False), so
    /test must still list previously-known providers. base_url/token are cleared.
    """
    state.connect('http://host:8080', 'tok', ['FANZA', 'HEYZO'])
    state.disconnect()
    names, gen, url, token = state.probe_snapshot()
    # _providers is now empty, but _availability keys are preserved
    assert set(names) == {'FANZA', 'HEYZO'}
    # disconnect cleared base_url/token → ''
    assert url == ''
    assert token == ''


def test_probe_snapshot_names_stripped_prefix(state):
    """names are stripped of the 'metatube:' prefix."""
    state.connect('http://host:8080', 'tok', ['FANZA'])
    names, _gen, _url, _token = state.probe_snapshot()
    assert 'metatube:FANZA' not in names
    assert 'FANZA' in names
