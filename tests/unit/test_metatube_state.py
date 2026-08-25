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
    # base_url 已於 Codex 二審 P1 移除（憑證外洩：validator 不擋 userinfo、
    # server_mode 下同網段可讀）。key-set 全等斷言在此同時擔任「不得回歸」的鎖。
    assert set(d.keys()) == {"connected", "probe_done", "probe_progress", "providers"}
    assert isinstance(d["connected"], bool)
    assert isinstance(d["probe_done"], bool)
    assert isinstance(d["probe_progress"], int)
    assert isinstance(d["providers"], list)


def test_status_dict_after_connect_reflects_providers():
    """status_dict() providers reflects availability_map after connect()."""
    s = MetatubeConnectionState()
    s.connect('http://host', 'tok', ['FANZA', 'HEYZO'])
    d = s.status_dict()

    assert d["connected"] is True
    assert "base_url" not in d  # Codex 二審 P1：連線後也不得回傳 base_url
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


# ===========================================================================
# TASK-113c-T3a: connected_base_url() — atomic (connected + base_url)
# ===========================================================================

def test_connected_base_url_happy_path(state):
    """Connected with non-empty base_url → returns that base_url."""
    state.connect('http://127.0.0.1:8900', 'tok', ['FANZA'])
    assert state.connected_base_url() == 'http://127.0.0.1:8900'


def test_connected_base_url_never_connected_returns_none(state):
    """Fresh state (never connect) → None."""
    assert state.connected_base_url() is None


def test_connected_base_url_connect_with_empty_base_url_returns_none(state):
    """connect() with empty base_url leaves connected=True but value is useless → None."""
    state.connect('', 'tok', ['FANZA'])
    assert state.is_connected is True
    assert state.base_url == ''
    assert state.connected_base_url() is None


def test_connected_base_url_after_disconnect_returns_none(state):
    """After disconnect() → None (connected=False, base_url=None)."""
    state.connect('http://127.0.0.1:8900', 'tok', ['FANZA'])
    state.disconnect()
    assert state.connected_base_url() is None


def test_connected_base_url_atomic_no_race(state):
    """Structurally-green under correct impl: hooks is_connected to disconnect mid-read.

    Correct connected_base_url() reads connected + base_url under a single _lock
    and never calls is_connected, so the hook never fires and the base_url is
    returned.  A two-step 'if is_connected: return base_url' impl would fire the
    hook, disconnect, and either return None or a stale host — that mutation
    must turn this test red (DoD-1a / BE-TEST-05 mirror shape).
    """
    state.connect('http://127.0.0.1:8900', 'tok', ['FANZA'])

    real_is_connected = MetatubeConnectionState.is_connected

    def _hook(_self):
        # Property getter: return True then immediately disconnect so a
        # subsequent unlocked base_url read would observe None.
        result = real_is_connected.fget(_self)
        if result:
            _self.disconnect()
        return result

    # Patch the property on the class so any is_connected access is hooked.
    MetatubeConnectionState.is_connected = property(_hook)
    try:
        assert state.connected_base_url() == 'http://127.0.0.1:8900'
    finally:
        MetatubeConnectionState.is_connected = real_is_connected


def test_status_dict_never_leaks_userinfo_credentials():
    """回歸鎖（Codex PR review 二審 P1，2026-08-07）。

    `validate_metatube_url()` 只看 scheme／hostname／port，**從不檢查 userinfo**，
    所以 `http://user:pass@host` 是通得過設定的。而 `status_dict()` 就是
    `GET /api/settings/metatube/status` 的完整回應——`general.server_mode` 開啟時
    區網任何裝置都能直接 GET 到它，沒有額外身份驗證（`web/app.py` 的
    `lan_access_gate` 只判 loopback 或 server_mode）。

    這支鎖的是**序列化後的整包**而不只是「有沒有 base_url 這個 key」：未來若有人
    以別的欄位名把連線目標放回去，這裡一樣會紅。
    """
    import json

    s = MetatubeConnectionState()
    s.connect('http://leakuser:leakpass@10.0.0.5:8900', 'tok', ['FANZA'])
    blob = json.dumps(s.status_dict(), ensure_ascii=False)
    for secret in ('leakuser', 'leakpass', '10.0.0.5', '@'):
        assert secret not in blob, f"status_dict() 洩漏 {secret!r}：{blob}"


def test_connect_log_does_not_leak_userinfo(caplog):
    """`connect()` 的 debug log 不得記完整 base_url（Codex 三審 P1）。

    正向＋負向配對：光斷言「不含帳密」在 caplog 沒抓到任何 record 時**永遠成立**，
    所以同時斷言 host 有被記到——那證明這條 log 真的跑到了。
    """
    import logging

    s = MetatubeConnectionState()
    with caplog.at_level(logging.DEBUG, logger='OpenAver.core.metatube.state'):
        s.connect('http://admin:S3cr3tPass@10.0.0.5:8900', 'tok_ABC123', ['FANZA'])

    assert '10.0.0.5:8900' in caplog.text          # 正向：log 真的有記，且保留診斷用的 host
    for secret in ('S3cr3tPass', 'admin', 'tok_ABC123'):
        assert secret not in caplog.text, f"connect log 洩漏 {secret!r}"


# ---------------------------------------------------------------------------
# TASK-130b-T1: _failed_at timestamp tracking & lifecycle
# ---------------------------------------------------------------------------


def test_failed_at_initialized_empty(state):
    """MetatubeConnectionState starts with an empty _failed_at dictionary."""
    assert hasattr(state, '_failed_at')
    assert state._failed_at == {}


def test_mark_failed_records_timestamp(state, monkeypatch):
    """mark_failed records the timestamp returned by _now()."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.5)
    state.connect('http://host', 'tok', ['FANZA', 'HEYZO'])
    state.mark_failed('metatube:FANZA')

    assert state.is_available('metatube:FANZA') is False
    assert hasattr(state, '_failed_at')
    assert state._failed_at.get('metatube:FANZA') == 100.5
    assert 'metatube:HEYZO' not in state._failed_at


def test_mark_available_clears_timestamp(state, monkeypatch):
    """mark_available clears the failure timestamp from _failed_at."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.5)
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')
    assert state._failed_at.get('metatube:FANZA') == 100.5

    state.mark_available('metatube:FANZA')
    assert state.is_available('metatube:FANZA') is True
    assert 'metatube:FANZA' not in state._failed_at


def test_disconnect_clears_failed_at(state, monkeypatch):
    """disconnect resets _failed_at to an empty dict while retaining provider keys."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.5)
    state.connect('http://host', 'tok', ['FANZA', 'HEYZO'])
    state.mark_failed('metatube:FANZA')
    assert 'metatube:FANZA' in state._failed_at

    state.disconnect()
    assert state._failed_at == {}
    assert state.is_available('metatube:FANZA') is False
    # Keys still in availability_map (grey capsules requirement)
    assert 'metatube:FANZA' in state.availability_map()


def test_connect_clears_failed_at(state, monkeypatch):
    """connect wipes _failed_at so stale timestamps do not carry over across servers."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.5)
    state.connect('http://server1', 'tok1', ['FANZA'])
    state.mark_failed('metatube:FANZA')
    assert 'metatube:FANZA' in state._failed_at

    state.connect('http://server2', 'tok2', ['FANZA', 'HEYZO'])
    assert state._failed_at == {}
    assert state.is_available('metatube:FANZA') is True


def test_mark_failed_stale_generation_skipped(state, monkeypatch):
    """mark_failed ignores writes when generation does not match current generation."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.5)
    gen = state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA', generation=gen + 999)

    assert state.is_available('metatube:FANZA') is True
    assert 'metatube:FANZA' not in state._failed_at


def test_mark_available_stale_generation_skipped(state, monkeypatch):
    """mark_available ignores writes and clears when generation does not match."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.5)
    gen = state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA', generation=gen)
    assert state._failed_at.get('metatube:FANZA') == 100.5

    state.mark_available('metatube:FANZA', generation=gen + 999)
    assert state.is_available('metatube:FANZA') is False
    assert state._failed_at.get('metatube:FANZA') == 100.5


def test_mark_failed_consecutive_overwrites_timestamp(state, monkeypatch):
    """Consecutive mark_failed calls update the timestamp to the latest time."""
    t = 100.0
    monkeypatch.setattr('core.metatube.state._now', lambda: t)
    state.connect('http://host', 'tok', ['FANZA'])

    state.mark_failed('metatube:FANZA')
    assert state._failed_at.get('metatube:FANZA') == 100.0

    t = 250.0
    state.mark_failed('metatube:FANZA')
    assert state._failed_at.get('metatube:FANZA') == 250.0


def test_mark_available_unknown_source_no_error(state):
    """mark_available on unknown source creates available entry and does not raise."""
    state.mark_available('metatube:UNKNOWN_SOURCE')
    assert state.is_available('metatube:UNKNOWN_SOURCE') is True
    assert 'metatube:UNKNOWN_SOURCE' not in state._failed_at


def test_mark_failed_unknown_source_records_timestamp(state, monkeypatch):
    """mark_failed on unknown source creates unavailable entry and records timestamp."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 77.7)
    state.mark_failed('metatube:UNKNOWN_SOURCE')
    assert state.is_available('metatube:UNKNOWN_SOURCE') is False
    assert state._failed_at.get('metatube:UNKNOWN_SOURCE') == 77.7


# ---------------------------------------------------------------------------
# TASK-130b-T2: routing_availability_map() optimistic failure cooldown
# ---------------------------------------------------------------------------


def test_routing_map_happy_path_all_available(state):
    """When all providers are available, routing_availability_map equals availability_map."""
    state.connect('http://host', 'tok', ['FANZA', 'HEYZO'])
    assert state.routing_availability_map() == state.availability_map()
    assert state.routing_availability_map() == {
        'metatube:FANZA': True,
        'metatube:HEYZO': True,
    }


def test_routing_map_within_cooldown_stays_false(state, monkeypatch):
    """Provider failed within cooldown TTL stays False in routing_availability_map."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')

    # Query at t=200 (100s elapsed < 300s TTL)
    monkeypatch.setattr('core.metatube.state._now', lambda: 200.0)
    res = state.routing_availability_map()
    assert res.get('metatube:FANZA') is False


def test_routing_map_expired_cooldown_becomes_true(state, monkeypatch):
    """Provider failed after cooldown TTL expires becomes True in routing_availability_map."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')

    # Query at t=450 (350s elapsed >= 300s TTL)
    monkeypatch.setattr('core.metatube.state._now', lambda: 450.0)
    res = state.routing_availability_map()
    assert res.get('metatube:FANZA') is True


def test_routing_map_exact_cooldown_boundary_becomes_true(state, monkeypatch):
    """Provider failed exactly at cooldown TTL boundary (now - failed_at == TTL) is considered expired (True)."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')

    # Query at t=400 (exactly 300s elapsed == 300s TTL)
    monkeypatch.setattr('core.metatube.state._now', lambda: 400.0)
    res = state.routing_availability_map()
    assert res.get('metatube:FANZA') is True


def test_routing_map_false_without_timestamp_stays_false(state):
    """Fail-closed: provider with False availability and NO timestamp (e.g. from disconnect) stays False."""
    state.connect('http://host', 'tok', ['FANZA', 'HEYZO'])
    state.disconnect()

    # disconnect clears _failed_at while keeping keys False
    res = state.routing_availability_map()
    assert res == {
        'metatube:FANZA': False,
        'metatube:HEYZO': False,
    }


def test_availability_map_ignores_cooldown(state, monkeypatch):
    """availability_map() does NOT apply optimistic cooldown (stays False even when expired)."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')

    # Query at t=500 (expired for routing)
    monkeypatch.setattr('core.metatube.state._now', lambda: 500.0)
    assert state.routing_availability_map().get('metatube:FANZA') is True
    # UI display map must remain unchanged and not optimistic
    assert state.availability_map().get('metatube:FANZA') is False


def test_status_dict_ignores_cooldown(state, monkeypatch):
    """status_dict() providers list does NOT apply optimistic cooldown."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')

    # Query at t=500 (expired for routing)
    monkeypatch.setattr('core.metatube.state._now', lambda: 500.0)
    d = state.status_dict()
    providers = {p['id']: p['available'] for p in d['providers']}
    assert providers.get('metatube:FANZA') is False


def test_routing_map_pure_read_no_side_effects(state, monkeypatch):
    """routing_availability_map() is a pure read with no side effects (does not pop _failed_at)."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')

    # Query at t=500 twice
    monkeypatch.setattr('core.metatube.state._now', lambda: 500.0)
    res1 = state.routing_availability_map()
    res2 = state.routing_availability_map()

    assert res1 == {'metatube:FANZA': True}
    assert res2 == {'metatube:FANZA': True}
    # Internal state untouched: _failed_at still has the timestamp, _availability still False
    assert state._failed_at.get('metatube:FANZA') == 100.0
    assert state.is_available('metatube:FANZA') is False


def test_routing_map_returns_copy(state):
    """Mutating the dict returned by routing_availability_map() does not affect internal state."""
    state.connect('http://host', 'tok', ['FANZA'])
    m = state.routing_availability_map()
    assert m['metatube:FANZA'] is True
    m['metatube:FANZA'] = False
    assert state.routing_availability_map()['metatube:FANZA'] is True


def test_routing_map_empty_availability_returns_empty(state):
    """Fresh state before connect returns an empty dict."""
    assert state.routing_availability_map() == {}


def test_routing_map_multiple_providers_mixed_states(state, monkeypatch):
    """Test 4-quadrant mixed scenario across multiple providers."""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://host', 'tok', ['P_OK', 'P_COOLING', 'P_EXPIRED'])
    # P_EXPIRED fails at t=100
    state.mark_failed('metatube:P_EXPIRED')

    # P_COOLING fails at t=350
    monkeypatch.setattr('core.metatube.state._now', lambda: 350.0)
    state.mark_failed('metatube:P_COOLING')

    # Current time t=450:
    # - P_OK: available (True) -> True
    # - P_COOLING: failed at 350, elapsed 100 < 300 -> False
    # - P_EXPIRED: failed at 100, elapsed 350 >= 300 -> True
    monkeypatch.setattr('core.metatube.state._now', lambda: 450.0)

    routing = state.routing_availability_map()
    assert routing['metatube:P_OK'] is True
    assert routing['metatube:P_COOLING'] is False
    assert routing['metatube:P_EXPIRED'] is True

    # availability_map strictly reflects persistent status
    avail = state.availability_map()
    assert avail['metatube:P_OK'] is True
    assert avail['metatube:P_COOLING'] is False
    assert avail['metatube:P_EXPIRED'] is False


# ===========================================================================
# TASK-130b-T4: reconnect lifecycle & cooldown retention tests (AC-6)
# ===========================================================================


def test_reconnect_same_provider_no_stale_cooldown(state, monkeypatch):
    """同一台伺服器斷線後重連：舊冷卻時間戳被清空，新連線從完全可用開始且過 TTL 後仍可用。"""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://mt:8080', 'tok', ['FANZA', 'HEYZO'])
    state.mark_failed('metatube:FANZA')
    assert state._failed_at.get('metatube:FANZA') == 100.0

    state.disconnect()
    assert state._failed_at == {}

    monkeypatch.setattr('core.metatube.state._now', lambda: 150.0)
    state.connect('http://mt:8080', 'tok', ['FANZA', 'HEYZO'])

    assert state._failed_at == {}
    assert state.availability_map() == {
        'metatube:FANZA': True,
        'metatube:HEYZO': True,
    }
    assert state.is_available('metatube:FANZA') is True
    assert state.is_available('metatube:HEYZO') is True
    assert state.routing_availability_map() == {
        'metatube:FANZA': True,
        'metatube:HEYZO': True,
    }
    assert state.routing_availability_map()['metatube:FANZA'] is True
    assert state.routing_availability_map()['metatube:HEYZO'] is True

    # 再把時鐘推到 t=500（＞ TTL）再讀一次：仍然兩家都 True。
    #
    # ⚠️ 這一段**不是**在走「冷卻到期 → 樂觀翻 True」那條分支。reconnect 之後
    # connect() 已經把 _availability 全設回 True，routing_availability_map() 的
    # `if avail: continue` 會直接跳過這兩把 key，TTL 條件式根本不會被執行。
    # 它證明的是「重連之後狀態穩定、不會隨時間漂移」——真正把
    # 「本來就可用」與「冷卻剛好到期才被放行」分開的是下面那行
    # `_failed_at == {}`（沒有時間戳 ⇒ 不可能是被樂觀放行的）。
    # （sonnet review P3：原註解對這段的敘述不準確，已改正。）
    monkeypatch.setattr('core.metatube.state._now', lambda: 500.0)
    assert state.routing_availability_map() == {
        'metatube:FANZA': True,
        'metatube:HEYZO': True,
    }
    assert state.routing_availability_map()['metatube:FANZA'] is True
    assert state.routing_availability_map()['metatube:HEYZO'] is True
    assert state._failed_at == {}


def test_reconnect_new_server_drops_old_server_cooldown(state, monkeypatch):
    """換一台伺服器（provider 部分重疊）：舊 server 的冷卻與 provider 不殘留。

    **刻意不先 disconnect()**：設定頁換一個 metatube 位址走的是「直接再 connect 一次」
    這條路（connect() 的 docstring 明講 repeated connect 會整份重建）。中間插一個
    disconnect() 會讓 disconnect 先把冷卻紀錄清掉，connect() 自己那行清空就變成
    永遠不會被觸發的死碼——上面 test_reconnect_same_provider_no_stale_cooldown
    已經負責完整的斷線→重連循環，這一支負責的是「不經過斷線的換機」。
    """
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://server1:8080', 'tok1', ['FANZA', 'HEYZO'])
    state.mark_failed('metatube:FANZA')
    assert state._failed_at.get('metatube:FANZA') == 100.0

    monkeypatch.setattr('core.metatube.state._now', lambda: 120.0)
    state.connect('http://server2:9090', 'tok2', ['FANZA', 'JAVBUS_MT'])

    assert state._failed_at == {}
    assert state.availability_map() == {
        'metatube:FANZA': True,
        'metatube:JAVBUS_MT': True,
    }
    assert 'metatube:HEYZO' not in state.availability_map()
    assert state.is_available('metatube:FANZA') is True
    assert state.is_available('metatube:JAVBUS_MT') is True
    assert state.is_available('metatube:HEYZO') is False

    assert state.routing_availability_map() == {
        'metatube:FANZA': True,
        'metatube:JAVBUS_MT': True,
    }
    assert 'metatube:HEYZO' not in state.routing_availability_map()
    assert state.routing_availability_map()['metatube:FANZA'] is True
    assert state.routing_availability_map()['metatube:JAVBUS_MT'] is True


def test_disconnected_state_never_optimistically_routable(state, monkeypatch):
    """斷線狀態下推進時鐘遠超 TTL，routing_availability_map 仍維持全 False（fail-closed）。"""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://mt:8080', 'tok', ['FANZA', 'HEYZO'])
    state.mark_failed('metatube:FANZA')
    state.disconnect()

    # 時鐘推到 t=100000（遠超 TTL）
    monkeypatch.setattr('core.metatube.state._now', lambda: 100000.0)

    routing = state.routing_availability_map()
    assert routing == {
        'metatube:FANZA': False,
        'metatube:HEYZO': False,
    }
    assert routing['metatube:FANZA'] is False
    assert routing['metatube:HEYZO'] is False

    avail = state.availability_map()
    assert avail == {
        'metatube:FANZA': False,
        'metatube:HEYZO': False,
    }
    assert avail['metatube:FANZA'] is False
    assert avail['metatube:HEYZO'] is False


# ===========================================================================
# TASK-130b-T5: full round-trip & 4-quadrant state matrix tests (AC-2)
# ===========================================================================


def test_refail_within_cooldown_restarts_the_window(state, monkeypatch):
    """冷卻期內再次請求失敗時重新起算冷卻時間，避免持續故障的來源過早重試導致使用者頻繁等待逾時。"""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')

    # 時鐘推到 t=250（距第一次失敗 150 秒，仍在冷卻中）
    monkeypatch.setattr('core.metatube.state._now', lambda: 250.0)
    assert state.routing_availability_map()['metatube:FANZA'] is False

    # 在冷卻期內再次失敗，時間戳重置為 250.0
    state.mark_failed('metatube:FANZA')

    # 時鐘推到 t=450（距第一次失敗 350 秒 > 300，但距第二次失敗 200 秒 < 300）
    # 驗證冷卻窗口已重啟，不會因為第一次失敗到期而提早放行
    monkeypatch.setattr('core.metatube.state._now', lambda: 450.0)
    assert state.routing_availability_map()['metatube:FANZA'] is False

    # 時鐘推到 t=560（距第二次失敗 310 秒 > 300），冷卻到期恢復可路由
    monkeypatch.setattr('core.metatube.state._now', lambda: 560.0)
    assert state.routing_availability_map()['metatube:FANZA'] is True


def test_success_after_expiry_converges_both_maps(state, monkeypatch):
    """來源冷卻到期後樂觀重試成功，立即清空失敗紀錄並讓路由與顯示地圖重新收斂一致，避免設定頁顯示正常但底層殘留過期時間戳。"""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')

    # 時鐘推到 t=500（距失敗 400 秒已過期）
    monkeypatch.setattr('core.metatube.state._now', lambda: 500.0)
    assert state.routing_availability_map()['metatube:FANZA'] is True
    assert state.availability_map()['metatube:FANZA'] is False
    assert state.routing_availability_map() != state.availability_map()

    # 樂觀重試成功，呼叫 mark_available
    state.mark_available('metatube:FANZA')
    assert state._failed_at == {}
    assert state.availability_map()['metatube:FANZA'] is True
    assert state.routing_availability_map()['metatube:FANZA'] is True
    assert state.routing_availability_map() == state.availability_map()

    # 時鐘推到遠大於 TTL 的 t=100000，兩張 map 仍保持逐鍵相等且無殘留失敗紀錄
    monkeypatch.setattr('core.metatube.state._now', lambda: 100000.0)
    assert state.routing_availability_map() == state.availability_map()
    assert state._failed_at == {}


def test_refail_after_expiry_reenters_cooldown(state, monkeypatch):
    """來源冷卻到期後樂觀重試若再度失敗，會重新進入完整冷卻期，避免故障來源被連續重試導致使用者每次搜尋都被迫等待逾時。"""
    monkeypatch.setattr('core.metatube.state._now', lambda: 100.0)
    state.connect('http://host', 'tok', ['FANZA'])
    state.mark_failed('metatube:FANZA')

    # 時鐘推到 t=500（已過期，路由地圖樂觀放行）
    monkeypatch.setattr('core.metatube.state._now', lambda: 500.0)
    assert state.routing_availability_map()['metatube:FANZA'] is True

    # 在 t=500 時樂觀重試失敗，再次觸發 mark_failed
    state.mark_failed('metatube:FANZA')
    assert state._failed_at['metatube:FANZA'] == 500.0
    assert state.routing_availability_map()['metatube:FANZA'] is False

    # 時鐘推到 t=700（距 t=500 僅 200 秒 < 300），仍處於冷卻中
    monkeypatch.setattr('core.metatube.state._now', lambda: 700.0)
    assert state.routing_availability_map()['metatube:FANZA'] is False

    # 時鐘推到 t=801（距 t=500 已 301 秒 > 300），冷卻到期再次放行
    monkeypatch.setattr('core.metatube.state._now', lambda: 801.0)
    assert state.routing_availability_map()['metatube:FANZA'] is True
