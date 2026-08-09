"""Unit tests for core/access_auth.py (TASK-114a-T1).

Isolation (card 補充 D): each test gets its own tmp sqlite file via
monkeypatch on `core.access_auth.get_db_path` (patch use-site, not
definition-site — BE-TEST-01), and an autouse fixture resets the
process-global cache/retry state before and after every test.

Private helpers (`_decide_lockout`, `_now`, module counters) are reached
via `access_auth.<name>` attribute access, never `from core.access_auth
import _name` — the latter trips ruff PLC2701 (import-private-name) even
for a module testing its own internals; attribute access on an imported
module object does not.
"""
import ast
import dataclasses
import sqlite3
import threading
from pathlib import Path

import pytest

from core import access_auth
from core.access_auth import (
    AuthSnapshot,
    attempt_pin,
    ensure_schema,
    get_auth_settings,
    load_snapshot,
    revoke_all,
    set_auth,
    snapshot,
    verify_ticket,
)

_ACCESS_AUTH_SOURCE_PATH = Path("core/access_auth.py")


def _dotted_call_name(node: ast.AST) -> str:
    """Reconstruct a dotted call target name (`"time.sleep"`,
    `"asyncio.sleep"`, `"sleep"`, …) from a Call node's `func` — AST node
    types only, so docstring/comment text containing the literal words
    "await" or "asyncio.sleep" (as explanatory prose) can never trip this."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


_FORBIDDEN_SLEEP_CALLS = frozenset({"time.sleep", "asyncio.sleep", "sleep"})


def _scan_forbidden_async_constructs(node: ast.AST) -> list:
    """Walk `node`'s subtree for: `await` expressions, `async def`,
    `import asyncio` / `from asyncio import ...`, and `time.sleep()` /
    `asyncio.sleep()` calls. Node-type based (ast.Await / ast.AsyncFunctionDef
    / ast.Import / ast.Call), never a substring scan — so it cannot be
    fooled by, nor accidentally trip on, prose inside a docstring."""
    violations = []
    for child in ast.walk(node):
        if isinstance(child, ast.Await):
            violations.append("await expression")
        elif isinstance(child, ast.AsyncFunctionDef):
            violations.append(f"async def {child.name}")
        elif isinstance(child, ast.Import):
            for alias in child.names:
                if alias.name.split(".")[0] == "asyncio":
                    violations.append(f"import {alias.name}")
        elif isinstance(child, ast.ImportFrom):
            if child.module and child.module.split(".")[0] == "asyncio":
                violations.append(f"from {child.module} import ...")
        elif isinstance(child, ast.Call):
            dotted = _dotted_call_name(child.func)
            if dotted in _FORBIDDEN_SLEEP_CALLS:
                violations.append(f"call {dotted}(...)")
    return violations


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    db_path = tmp_path / "access.db"
    monkeypatch.setattr(access_auth, "get_db_path", lambda: db_path)
    access_auth.reset_state_for_tests()
    yield
    access_auth.reset_state_for_tests()


# ---------------------------------------------------------------------------
# lifecycle / cache-cold-vs-warm
# ---------------------------------------------------------------------------


def test_ensure_schema_idempotent_twice():
    ensure_schema()
    ensure_schema()  # must not raise


def test_snapshot_none_before_load_snapshot():
    assert snapshot() is None


def test_load_snapshot_defaults_when_no_row():
    ensure_schema()
    snap = load_snapshot()
    assert snap == AuthSnapshot(enabled=False, pin="", valid_tokens=frozenset())


def test_ensure_schema_warms_cache():
    assert snapshot() is None
    ensure_schema()
    assert snapshot() is not None


def test_attempt_pin_does_not_hang_when_cache_cold():
    """Card 補充 A: attempt_pin must not deadlock the first time it runs
    before ensure_schema()/load_snapshot() has ever warmed the cache."""
    ensure_schema()
    set_auth(True, "1234")
    access_auth.reset_state_for_tests()  # wipes in-memory cache only, not the DB

    result = {}

    def call():
        result["token"] = attempt_pin("1234")

    t = threading.Thread(target=call)
    t.start()
    t.join(timeout=2)
    assert not t.is_alive(), "attempt_pin hung on a cold cache"
    assert result.get("token") is not None


# ---------------------------------------------------------------------------
# PIN format validation (set_auth + attempt_pin share the same gate)
# ---------------------------------------------------------------------------

INVALID_PINS = [
    "12 3",     # whitespace
    "१२३४",     # Devanagari digits — .isdigit()/\d would wrongly accept
    "12345",    # too long
    "",         # empty
    "12-3",     # punctuation — `\w` would wrongly accept `_`, this covers the family
    "ab_d",     # underscore specifically (the `\w` trap)
    "あいうえ",   # CJK — .isalnum() would wrongly accept
    "１２３",     # 3 full-width digits: folds to "123", still too short
]

# 4 ASCII alphanumerics, any mix of case — the whole accepted space.
VALID_PINS = ["1234", "abcd", "ABCD", "a1B2", "0000", "zZ99"]

# NFKC folding: what a CJK IME in wide mode emits -> what must be stored
# and matched. Devanagari is deliberately absent — NFKC does not fold it to
# ASCII, so it stays rejected (verified in INVALID_PINS above).
FULLWIDTH_EQUIVALENTS = [
    ("１２３４", "1234"),
    ("ａｂｃｄ", "abcd"),
    ("ＡＢ12", "AB12"),
]

NON_STRING_CANDIDATES = [None, 42, [1, 2, 3, 4], {}]


@pytest.mark.parametrize("bad_pin", INVALID_PINS)
def test_set_auth_rejects_invalid_pin_formats(bad_pin):
    ensure_schema()
    with pytest.raises(ValueError):
        set_auth(True, bad_pin)


def test_set_auth_invalid_pin_does_not_write_or_revoke():
    ensure_schema()
    set_auth(True, "1234")
    token = attempt_pin("1234")
    assert token is not None

    with pytest.raises(ValueError):
        set_auth(True, "12345")

    # DB/cache must be untouched: settings unchanged, ticket still valid
    assert get_auth_settings(reveal=True) == {"enabled": True, "pin": "1234"}
    assert verify_ticket(token) is True


@pytest.mark.parametrize("bad_pin", INVALID_PINS)
def test_attempt_pin_rejects_invalid_pin_formats_no_raise(bad_pin):
    ensure_schema()
    set_auth(True, "1234")
    assert attempt_pin(bad_pin) is None


@pytest.mark.parametrize("good_pin", VALID_PINS)
def test_alphanumeric_pins_round_trip_and_verify(good_pin):
    """T7fix: the accepted space is 4 ASCII alphanumerics, not just digits."""
    ensure_schema()
    set_auth(True, good_pin)
    assert get_auth_settings(reveal=True) == {"enabled": True, "pin": good_pin}
    assert attempt_pin(good_pin) is not None


def test_pin_comparison_is_case_sensitive():
    """`hmac.compare_digest` is exact, and nothing upstream lower-cases.

    This is why both inputs carry `autocapitalize="off"`: a phone keyboard
    that helpfully capitalises the first letter would otherwise turn the
    owner's "abcd" into "Abcd" and lock them out with no error shown.
    """
    ensure_schema()
    set_auth(True, "abcd")
    assert attempt_pin("ABCD") is None
    assert attempt_pin("Abcd") is None
    assert attempt_pin("abcd") is not None


@pytest.mark.parametrize("wide,ascii_form", FULLWIDTH_EQUIVALENTS)
def test_fullwidth_pin_folds_to_ascii_on_write(wide, ascii_form):
    """Set with a wide-mode IME, and the ASCII form is what got stored —
    so the same PIN typed on a phone (IME off) gets in."""
    ensure_schema()
    set_auth(True, wide)
    assert get_auth_settings(reveal=True) == {"enabled": True, "pin": ascii_form}
    assert attempt_pin(ascii_form) is not None


@pytest.mark.parametrize("wide,ascii_form", FULLWIDTH_EQUIVALENTS)
def test_fullwidth_pin_folds_to_ascii_on_verify(wide, ascii_form):
    """The mirror direction: PIN set in ASCII, typed back wide."""
    ensure_schema()
    set_auth(True, ascii_form)
    assert attempt_pin(wide) is not None


def test_fullwidth_folding_does_not_reopen_non_ascii_pins():
    """Folding must not become a backdoor for scripts NFKC leaves alone —
    a Devanagari 'PIN' is still rejected on both paths."""
    ensure_schema()
    set_auth(True, "1234")
    assert attempt_pin("१२३४") is None
    with pytest.raises(ValueError):
        set_auth(True, "१२३४")


@pytest.mark.parametrize("candidate", NON_STRING_CANDIDATES)
def test_attempt_pin_non_string_candidates_no_raise(candidate):
    ensure_schema()
    set_auth(True, "1234")
    assert attempt_pin(candidate) is None


def test_pin_leading_zero_preserved_across_write_and_read():
    """CD-114a-2 type-trap: DB column must be TEXT, not INTEGER — "0042"
    stored in an INTEGER column would come back as 42 (and "42" would then
    wrongly equal "0042"). `load_snapshot()` forces a genuine DB round-trip
    instead of reading back the in-memory value `set_auth` already held."""
    ensure_schema()
    set_auth(True, "0042")
    reloaded = load_snapshot()
    assert reloaded.pin == "0042"
    assert get_auth_settings(reveal=True) == {"enabled": True, "pin": "0042"}
    assert attempt_pin("0042") is not None


def test_set_auth_enabled_false_ignores_pin_content_no_raise():
    ensure_schema()
    set_auth(False, "not-a-pin-at-all")  # must not raise, value is ignored
    assert get_auth_settings(reveal=True)["enabled"] is False


# ---------------------------------------------------------------------------
# attempt_pin: enabled flag, correctness, ticket issuance
# ---------------------------------------------------------------------------


def test_attempt_pin_returns_none_when_disabled():
    ensure_schema()
    set_auth(False, "0000")
    assert attempt_pin("1234") is None
    assert attempt_pin("0000") is None


def test_attempt_pin_disabled_with_no_leftover_tokens():
    """flag 正交組合：enabled=False 之後不應留下有效票（set_auth 已 revoke_all）。"""
    ensure_schema()
    set_auth(True, "1234")
    token = attempt_pin("1234")
    assert token is not None
    set_auth(False, "0000")
    assert verify_ticket(token) is False
    assert attempt_pin("1234") is None


def test_attempt_pin_correct_pin_issues_ticket_that_verifies():
    ensure_schema()
    set_auth(True, "1234")
    token = attempt_pin("1234")
    assert isinstance(token, str) and token
    assert verify_ticket(token) is True


def test_attempt_pin_wrong_pin_returns_none():
    ensure_schema()
    set_auth(True, "1234")
    assert attempt_pin("9999") is None


class _BoomOnTicketInsertConn:
    """Wraps a real sqlite3 connection; raises on the ticket INSERT only,
    delegates everything else (SELECT reads for `_load_locked`, etc.) to
    the real connection unchanged."""

    def __init__(self, inner: sqlite3.Connection):
        self._inner = inner

    def execute(self, sql, params=()):
        if sql.strip().startswith("INSERT INTO access_tickets"):
            raise sqlite3.OperationalError("simulated ticket-insert failure")
        return self._inner.execute(sql, params)

    def commit(self):
        self._inner.commit()

    def close(self):
        self._inner.close()


def test_attempt_pin_db_failure_does_not_clear_retry_state_or_leak_a_ticket(monkeypatch):
    """Independent review ③: the success branch used to zero the retry
    counters *before* the DB INSERT. If that INSERT (or the commit) then
    raised, the counters were already wiped but no ticket exists — a
    silent, free reset of the lockout ladder on every transient DB error.
    The reset must happen only after the write is confirmed committed."""
    ensure_schema()
    set_auth(True, "1234")
    clock = [T0]
    monkeypatch.setattr(access_auth, "_now", lambda: clock[0])
    for _ in range(4):
        assert attempt_pin("0000") is None
    assert access_auth._consecutive_failures == 4

    real_connect = access_auth._connect
    monkeypatch.setattr(access_auth, "_connect", lambda: _BoomOnTicketInsertConn(real_connect()))

    with pytest.raises(sqlite3.OperationalError):
        attempt_pin("1234")  # correct PIN, but the DB write blows up

    assert access_auth._consecutive_failures == 4, "retry counter must not be cleared on DB failure"
    reloaded = load_snapshot()  # still goes through the wrapper; SELECTs are unaffected
    assert reloaded.valid_tokens == frozenset(), "no ticket should have leaked into the DB"


# ---------------------------------------------------------------------------
# verify_ticket: four cells
# ---------------------------------------------------------------------------


def test_verify_ticket_none_token():
    ensure_schema()
    assert verify_ticket(None) is False


def test_verify_ticket_empty_string_token():
    ensure_schema()
    assert verify_ticket("") is False


def test_verify_ticket_unknown_token():
    ensure_schema()
    set_auth(True, "1234")
    assert verify_ticket("not-a-real-token") is False


def test_verify_ticket_valid_token():
    ensure_schema()
    set_auth(True, "1234")
    token = attempt_pin("1234")
    assert verify_ticket(token) is True


def test_verify_ticket_fails_closed_on_cold_cache():
    # No ensure_schema()/load_snapshot() at all — snapshot() is None.
    assert snapshot() is None
    assert verify_ticket("anything") is False


# ---------------------------------------------------------------------------
# R5: revoke_all / set_auth revocation (mirrored write endpoints)
# ---------------------------------------------------------------------------


def test_revoke_all_on_empty_table_does_not_raise():
    ensure_schema()
    revoke_all()  # should not raise


def test_revoke_all_clears_existing_tickets():
    ensure_schema()
    set_auth(True, "1234")
    token = attempt_pin("1234")
    assert verify_ticket(token) is True
    revoke_all()
    assert verify_ticket(token) is False


def test_set_auth_pin_change_revokes_old_tickets():
    ensure_schema()
    set_auth(True, "1111")
    token = attempt_pin("1111")
    assert verify_ticket(token) is True
    set_auth(True, "2222")
    assert verify_ticket(token) is False


def test_set_auth_same_value_still_revokes_no_exceptions():
    """spec: R5「沒有例外」——即使新設定與舊設定完全相同，票仍全滅。"""
    ensure_schema()
    set_auth(True, "1234")
    token = attempt_pin("1234")
    assert verify_ticket(token) is True
    set_auth(True, "1234")
    assert verify_ticket(token) is False


def test_reset_config_equivalent_does_not_touch_auth_is_out_of_scope():
    """CD-114a-9 is T4/router scope, not T1 — but T1's revoke_all() itself
    must accept zero parameters (no conditional revoke surface)."""
    import inspect

    sig = inspect.signature(revoke_all)
    assert list(sig.parameters) == []


def test_set_auth_revocation_reaches_the_db_not_just_the_cache():
    """Independent review ①: every prior revoke test only asked
    `verify_ticket()`, which reads the in-memory cache — and the cache is
    unconditionally rebuilt empty regardless of whether the DB `DELETE`
    actually ran. That leaves the real failure mode unproven: an owner
    changes the PIN to kick a device out, the cache looks clean, but the
    next process restart does a cold `load_snapshot()` straight from the
    DB — and if the row was never deleted, the old ticket comes back to
    life. This test forces exactly that round-trip: wipe the in-memory
    cache with `reset_state_for_tests()`, then `load_snapshot()` (a real
    DB read), and check the old token is genuinely gone from disk."""
    ensure_schema()
    set_auth(True, "1111")
    token = attempt_pin("1111")
    assert token is not None

    set_auth(True, "2222")  # R5 trigger

    access_auth.reset_state_for_tests()  # wipes the cache only, not the DB
    reloaded = load_snapshot()  # forces a genuine DB read
    assert token not in reloaded.valid_tokens


def test_revoke_all_reaches_the_db_not_just_the_cache():
    """Same DB-round-trip proof as above, for `revoke_all()` called
    directly (not via `set_auth`)."""
    ensure_schema()
    set_auth(True, "1111")
    token = attempt_pin("1111")
    assert token is not None

    revoke_all()

    access_auth.reset_state_for_tests()
    reloaded = load_snapshot()
    assert token not in reloaded.valid_tokens


# ---------------------------------------------------------------------------
# Retry-lockout decision core (pure function) — spec §9.1 truth table
# ---------------------------------------------------------------------------

T0 = 1_000_000.0
T1 = 2_000_000.0
T2 = 3_000_000.0
T3 = 4_000_000.0
T4 = 5_000_000.0

LOCKOUT_TRUTH_TABLE = [
    # (consecutive_failures, now, lockout_started_at) -> (allowed, remaining)
    (0, T0, None, True, 0.0),
    (4, T0, None, True, 0.0),
    (5, T0, T0, False, 60.0),
    (5, T0 + 59, T0, False, 1.0),
    (5, T0 + 60, T0, True, 0.0),
    (5, T0 + 61, T0, True, 0.0),
    (6, T0, None, True, 0.0),
    (9, T0, None, True, 0.0),
    (10, T1, T1, False, 240.0),
    (15, T2, T2, False, 960.0),
    (20, T3, T3, False, 3600.0),
    (25, T4, T4, False, 3600.0),
    (30, T4, T4, False, 3600.0),
    (5, T0 + 10, T0, False, 50.0),
]


@pytest.mark.parametrize(
    "consecutive_failures,now,lockout_started_at,expected_allowed,expected_remaining",
    LOCKOUT_TRUTH_TABLE,
)
def test_lockout_decision_truth_table(
    consecutive_failures, now, lockout_started_at, expected_allowed, expected_remaining
):
    allowed, remaining = access_auth._decide_lockout(
        consecutive_failures, now, lockout_started_at
    )
    assert allowed is expected_allowed
    assert remaining == expected_remaining


def test_lockout_decision_is_pure_no_state_mutation():
    before_failures = access_auth._consecutive_failures
    before_lockout = access_auth._lockout_started_at
    access_auth._decide_lockout(5, T0, T0)
    assert access_auth._consecutive_failures == before_failures
    assert access_auth._lockout_started_at == before_lockout


# ---------------------------------------------------------------------------
# attempt_pin <-> decision core wiring: lockout does not accumulate,
# correct PIN still denied while locked, expiry clears start marker only
# ---------------------------------------------------------------------------


def test_lockout_blocks_correct_pin_while_locked(monkeypatch):
    ensure_schema()
    set_auth(True, "1234")
    clock = [T0]
    monkeypatch.setattr(access_auth, "_now", lambda: clock[0])

    for _ in range(5):
        assert attempt_pin("0000") is None
    assert access_auth._consecutive_failures == 5
    assert access_auth._lockout_started_at == T0

    clock[0] = T0 + 10
    assert attempt_pin("1234") is None  # correct PIN, still locked


def test_lockout_does_not_accumulate_while_locked(monkeypatch):
    ensure_schema()
    set_auth(True, "1234")
    clock = [T0]
    monkeypatch.setattr(access_auth, "_now", lambda: clock[0])

    for _ in range(5):
        assert attempt_pin("0000") is None
    assert access_auth._consecutive_failures == 5
    locked_at = access_auth._lockout_started_at
    assert locked_at is not None

    clock[0] = T0 + 5
    for _ in range(4):
        assert attempt_pin("0000") is None
    assert access_auth._consecutive_failures == 5
    assert access_auth._lockout_started_at == locked_at


def test_lockout_expiry_clears_start_marker_but_keeps_failure_count(monkeypatch):
    ensure_schema()
    set_auth(True, "1234")
    clock = [T0]
    monkeypatch.setattr(access_auth, "_now", lambda: clock[0])

    for _ in range(5):
        assert attempt_pin("0000") is None
    assert access_auth._consecutive_failures == 5

    clock[0] = T0 + 60  # exactly at expiry boundary
    assert attempt_pin("0000") is None  # wrong again, but now unlocked
    # consecutive_failures kept climbing from 5 (not reset to 0 on unlock)
    assert access_auth._consecutive_failures == 6
    assert access_auth._lockout_started_at is None


# ---------------------------------------------------------------------------
# Opus 補充 E': set_auth clears retry-lockout state on a successful write
# ---------------------------------------------------------------------------


def test_set_auth_success_clears_lockout_and_unlocks_immediately(monkeypatch):
    """User story: a family member gets locked out after 5 wrong guesses,
    asks the owner for help. The owner is loopback-only (R4) — this is not
    an attacker-reachable bypass. Without this, she'd have to wait out the
    escalation ladder (up to an hour) even after the owner fixes the PIN."""
    ensure_schema()
    set_auth(True, "1234")
    clock = [T0]
    monkeypatch.setattr(access_auth, "_now", lambda: clock[0])
    for _ in range(5):
        assert attempt_pin("0000") is None
    assert access_auth._consecutive_failures == 5
    assert access_auth._lockout_started_at is not None

    set_auth(True, "9999")  # owner resets the PIN while she's still locked

    assert access_auth._consecutive_failures == 0
    assert access_auth._lockout_started_at is None
    assert attempt_pin("9999") is not None  # she's in immediately, no waiting


def test_set_auth_invalid_pin_leaves_lockout_state_untouched(monkeypatch):
    """The `raise ValueError` path writes nothing — it must not clear
    retry state either (a no-op write shouldn't have a side effect)."""
    ensure_schema()
    set_auth(True, "1234")
    clock = [T0]
    monkeypatch.setattr(access_auth, "_now", lambda: clock[0])
    for _ in range(5):
        assert attempt_pin("0000") is None
    locked_at = access_auth._lockout_started_at
    assert locked_at is not None

    with pytest.raises(ValueError):
        set_auth(True, "12345")  # malformed — no write happens

    assert access_auth._consecutive_failures == 5
    assert access_auth._lockout_started_at == locked_at


# ---------------------------------------------------------------------------
# Concurrency: AC6 barrier (exact count, not "at least 1")
# ---------------------------------------------------------------------------


def test_barrier_concurrent_wrong_pin_exact_failure_count():
    """N == lockout threshold: every one of the N concurrently *launched*
    wrong attempts must be individually counted (proves no lost-update on
    the shared counter under real thread scheduling on this machine), and
    by construction the account ends up locked immediately after.

    NARROWER CLAIM THAN THE NAME MIGHT SUGGEST: this does NOT by itself
    prove mutual exclusion of the critical section — the in-memory
    read-modify-write here is short enough that even a lock-free version
    passes this test on a fast/idle machine (confirmed empirically during
    T1 mutation self-verification: removing `_lock` from `attempt_pin`
    left this test green; only widening the race window with an
    artificial `sleep` between read and write made it go red). The
    deterministic, sleep-free proof of mutual exclusion is
    `test_attempt_pin_critical_section_is_mutually_exclusive` below —
    that is the actual AC6/CD-114a-13 anti-bypass evidence.
    """
    ensure_schema()
    set_auth(True, "1234")
    n = 5
    barrier = threading.Barrier(n)

    def worker():
        barrier.wait()
        attempt_pin("0000")

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert access_auth._consecutive_failures == n, (
        f"Expected exactly {n} counted failures, got {access_auth._consecutive_failures}"
    )
    assert attempt_pin("1234") is None  # still locked despite correct PIN


def test_attempt_pin_critical_section_is_mutually_exclusive(monkeypatch):
    """Deterministic (sleep-free) proof that `attempt_pin`'s critical
    section is mutually exclusive — this is the actual CD-114a-13/AC6
    anti-bypass evidence (`test_barrier_concurrent_wrong_pin_exact_failure_count`
    above only proves "each launched attempt gets counted", not exclusion).

    Oracle: `_now()` is the existing seam called *inside* the lock, before
    the retry-count read-modify-write. Patch it to `barrier.wait(timeout=…)`
    first, then return a fixed value:

    - **Lock present** → only one thread can be inside the critical section
      at a time → the other N-1 threads never reach `_now()` while the
      first one is waiting → the barrier can never gather all N parties →
      it times out and raises `BrokenBarrierError` (surfacing through
      `attempt_pin`, caught by the worker). Asserting "at least one break
      happened" proves the threads never overlapped inside the section.
    - **Lock removed/swapped** → all N threads reach `_now()` at roughly
      the same time → the barrier completes normally for everyone → zero
      breaks → the assertion goes red.
    """
    ensure_schema()
    set_auth(True, "1234")
    n = 4
    barrier = threading.Barrier(n)

    def gated_now():
        barrier.wait(timeout=0.5)
        return T0

    monkeypatch.setattr(access_auth, "_now", gated_now)

    broke = []
    broke_lock = threading.Lock()

    def worker():
        try:
            attempt_pin("0000")
        except threading.BrokenBarrierError:
            with broke_lock:
                broke.append(True)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert broke, (
        "expected the gated barrier to break (threads serialized by the lock "
        "should never rendezvous inside the critical section); zero breaks "
        "means the critical section is NOT mutually exclusive"
    )


def test_auth_snapshot_is_a_frozen_dataclass():
    """Structural proof behind the "no torn read" claim: `AuthSnapshot`
    must be frozen, so the only way to "update" it is to build a whole new
    instance and swap the module-level pointer — never mutate one field at
    a time on a shared object. Remove `frozen=True` and this goes red on
    both assertions (the class param flips, and field assignment stops
    raising)."""
    assert AuthSnapshot.__dataclass_params__.frozen is True
    snap = AuthSnapshot(enabled=True, pin="1234", valid_tokens=frozenset())
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.enabled = False


def test_barrier_concurrent_reads_only_ever_see_one_of_two_legal_states():
    """Falsifiable (not vacuous) proof of no torn/hybrid reads: every
    snapshot a reader observes while a write races them must equal *either*
    the exact pre-write state *or* the exact post-write state — nothing
    in between (e.g. the new `valid_tokens` paired with an otherwise-stale
    object). `snap is None or isinstance(snap, AuthSnapshot)` (the old
    version of this test) can never fail in this module, since `_snapshot`
    is only ever assigned `None` or a fully-built instance — it proved
    nothing. This one actually enumerates the two legal states and rejects
    anything else."""
    ensure_schema()
    set_auth(True, "1234")
    before = snapshot()
    assert before is not None

    n = 8
    barrier = threading.Barrier(n + 1)
    observed = []
    lock = threading.Lock()
    writer_done = threading.Event()

    def reader():
        barrier.wait()
        # Spin until the writer signals completion — NOT a fixed iteration
        # count. A fixed small count (the original version of this test
        # used 20) can finish and exit *before* the writer even reaches its
        # real DB I/O (connect/insert/commit), leaving the entire window
        # where a bug could manifest completely unobserved. Spinning on an
        # Event instead guarantees full overlap with the writer's whole
        # critical section regardless of how long the DB round-trip takes.
        while not writer_done.is_set():
            snap = snapshot()
            with lock:
                observed.append(snap)
        with lock:
            observed.append(snapshot())  # one final read after completion

    def writer():
        barrier.wait()
        attempt_pin("1234")
        writer_done.set()

    threads = [threading.Thread(target=reader) for _ in range(n)]
    threads.append(threading.Thread(target=writer))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    after = snapshot()
    legal_states = {before, after}
    for snap in observed:
        assert snap in legal_states, f"observed a torn/hybrid snapshot: {snap}"


# ---------------------------------------------------------------------------
# CD-114a-13-inv: ticket issuance and auth-settings writes share one lock
#
# (A racy barrier-based version of this used to live here: N verify threads
# racing 1 set_auth thread, asserting no issued token survives. It was
# deterministically unsound — if set_auth happened to run first, every
# verify would return None, `issued_tokens` would be empty, and the `for`
# loop would vacuously pass with zero assertions executed (and it would
# have stayed green even with the lock removed). Replaced with two
# oracle-driven tests that lock the invariant itself: "attempt_pin and
# set_auth block on the exact same lock object.")
# ---------------------------------------------------------------------------


def test_attempt_pin_blocks_while_lock_held_by_another_writer():
    """If `set_auth`'s critical section holds `access_auth._lock`, a
    concurrent `attempt_pin` call must not be able to proceed. Deterministic:
    swap `_lock` for a fresh, unrelated `threading.Lock()` in `attempt_pin`
    and this goes red immediately (the worker thread finishes instead of
    staying blocked)."""
    ensure_schema()
    set_auth(True, "1234")

    access_auth._lock.acquire()
    result = {}
    try:
        def worker():
            result["token"] = attempt_pin("1234")

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=0.5)
        assert t.is_alive(), "attempt_pin was NOT blocked by the externally held lock"
    finally:
        access_auth._lock.release()

    t.join(timeout=5)
    assert not t.is_alive(), "attempt_pin never finished after the lock was released"
    assert result.get("token") is not None


def test_set_auth_blocks_while_lock_held_by_another_writer():
    """Mirror of the above for `set_auth`: proves ticket issuance and
    auth-settings writes contend on the identical lock object
    (CD-114a-13-inv), not two separately-scoped locks that happen to look
    similar."""
    ensure_schema()
    set_auth(True, "1234")

    access_auth._lock.acquire()
    try:
        def worker():
            set_auth(True, "5678")

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=0.5)
        assert t.is_alive(), "set_auth was NOT blocked by the externally held lock"
    finally:
        access_auth._lock.release()

    t.join(timeout=5)
    assert not t.is_alive(), "set_auth never finished after the lock was released"
    assert get_auth_settings(reveal=True) == {"enabled": True, "pin": "5678"}


# ---------------------------------------------------------------------------
# get_auth_settings masking
# ---------------------------------------------------------------------------


def test_get_auth_settings_reveal_true_shows_real_pin():
    ensure_schema()
    set_auth(True, "1234")
    assert get_auth_settings(reveal=True) == {"enabled": True, "pin": "1234"}


def test_get_auth_settings_reveal_false_masks_pin():
    ensure_schema()
    set_auth(True, "1234")
    settings = get_auth_settings(reveal=False)
    assert settings["enabled"] is True
    assert settings["pin"] != "1234"
    assert "1234" not in settings["pin"]
    # nit: pin the exact mask literal — T4/T5's display contract, not just
    # "anything that isn't the real value" (e.g. "***" would also satisfy
    # the two assertions above without this one).
    assert settings["pin"] == "••••"


# ---------------------------------------------------------------------------
# DoD: zero asyncio/await/time.sleep anywhere in the module (AST, not
# string-scan — the module docstring/comments mention "await" and
# "asyncio.sleep" as prose explaining the constraint, which must NOT trip
# these assertions).
# ---------------------------------------------------------------------------


def test_module_has_no_asyncio_await_or_time_sleep():
    tree = ast.parse(
        _ACCESS_AUTH_SOURCE_PATH.read_text(encoding="utf-8"),
        filename=str(_ACCESS_AUTH_SOURCE_PATH),
    )
    violations = _scan_forbidden_async_constructs(tree)
    assert not violations, f"forbidden async/asyncio/time.sleep constructs: {violations}"


def test_attempt_pin_body_has_no_asyncio_await_or_time_sleep():
    tree = ast.parse(
        _ACCESS_AUTH_SOURCE_PATH.read_text(encoding="utf-8"),
        filename=str(_ACCESS_AUTH_SOURCE_PATH),
    )
    func_node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "attempt_pin"
    )
    violations = _scan_forbidden_async_constructs(func_node)
    assert not violations, f"forbidden constructs in attempt_pin(): {violations}"


# ---------------------------------------------------------------------------
# No regression: init_db()/core.database untouched
# ---------------------------------------------------------------------------


def test_does_not_modify_init_db_source():
    src = Path("core/database/connection.py").read_text(encoding="utf-8")
    assert "access_auth" not in src
    assert "access_tickets" not in src


def test_module_has_no_web_import():
    src = _ACCESS_AUTH_SOURCE_PATH.read_text(encoding="utf-8")
    assert "import web" not in src
    assert "from web" not in src
