"""In-flight generate registry — lets the settings mode-switch refuse while a
`GET /api/gallery/generate` SSE is still running (feature/90 Finding 2 guard).

Why this exists: `switch_external_manager` purges the offline sources' DB cards.
If a readonly `generate` is streaming at the same time, its background producer
thread keeps `_upsert_db`-ing the same readonly rows *after* the purge deletes
them → the "switch mode = clean" contract breaks. The generate handler registers
a unique token for its lifetime; the switch endpoint refuses while any token is
active.

Thread-safety: `generate()` (async handler / event loop) registers and clears;
`switch_external_manager` (sync def → threadpool) reads. A plain `threading.Lock`
serialises across both. Tokens are the per-request `cancel_event` objects (unique
by identity), so add/discard are idempotent and never collide between requests.

⚠️ Known residual (documented, owner-accepted): the token is cleared in the
disconnect watcher's `finally`, which fires the instant a client disconnect is
detected — the producer thread may process *one more file* before it observes
`should_abort` at the next per-file checkpoint. So a switch fired in that sub-second
window right after a disconnect could still race a single re-insert. This is far
smaller than the original unbounded race and is not perfect serialisation by design.
"""
import threading

_lock = threading.Lock()
_active_tokens: set = set()


def mark_generate_active(token) -> None:
    """Register a generate as in-flight (call at handler start, before producing)."""
    with _lock:
        _active_tokens.add(token)


def mark_generate_done(token) -> None:
    """Clear a generate token (idempotent; call from the watcher `finally` so it
    runs on BOTH normal-completion and client-disconnect paths)."""
    with _lock:
        _active_tokens.discard(token)


def is_generate_in_progress() -> bool:
    """True if any generate SSE is currently registered as in-flight."""
    with _lock:
        return bool(_active_tokens)
