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


# ---------------------------------------------------------------------------
# 4. mark_available restores after mark_failed
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 7. repeated connect resets (bulk-true overwrites failed state)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 9. availability_map does not raise during concurrent marks
# ---------------------------------------------------------------------------


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


# ===========================================================================
# FIX 3: generation guard tests
# ===========================================================================


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


# ===========================================================================
# CD-66b-3: probe_snapshot() — atomic (names, gen, base_url, token)
# ===========================================================================


# ===========================================================================
# TASK-113c-T3a: connected_base_url() — atomic (connected + base_url)
# ===========================================================================


def test_connected_base_url_after_disconnect_returns_none(state):
    """After disconnect() → None (connected=False, base_url=None)."""
    state.connect('http://127.0.0.1:8900', 'tok', ['FANZA'])
    state.disconnect()
    assert state.connected_base_url() is None


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


# ---------------------------------------------------------------------------
# TASK-130b-T2: routing_availability_map() optimistic failure cooldown
# ---------------------------------------------------------------------------


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


# ===========================================================================
# TASK-130b-T4: reconnect lifecycle & cooldown retention tests (AC-6)
# ===========================================================================


# ===========================================================================
# TASK-130b-T5: full round-trip & 4-quadrant state matrix tests (AC-2)
# ===========================================================================


def test_refail_within_cooldown_restarts_the_window(state, monkeypatch):
    """冷卻期內再次請求失敗時重新起算冷卻時間，避免持續故障的來源過早重試導致使用者頻繁等待逾時。
    冷卻到期後樂觀重試又失敗，同樣重新進入完整冷卻期。"""
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

    # 冷卻到期後（t=560 已樂觀放行）重試又失敗 → 重新進入完整冷卻期
    state.mark_failed('metatube:FANZA')
    assert state._failed_at['metatube:FANZA'] == 560.0
    assert state.routing_availability_map()['metatube:FANZA'] is False

    # 時鐘推到 t=700（距 t=560 僅 140 秒 < 300），仍處於冷卻中
    monkeypatch.setattr('core.metatube.state._now', lambda: 700.0)
    assert state.routing_availability_map()['metatube:FANZA'] is False

    # 時鐘推到 t=861（距 t=560 已 301 秒 > 300），冷卻到期再次放行
    monkeypatch.setattr('core.metatube.state._now', lambda: 861.0)
    assert state.routing_availability_map()['metatube:FANZA'] is True


