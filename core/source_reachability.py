"""Source reachability probe + in-process snapshot (feature/142-v2 T1).

Probe means are a closed set of two (CD-2):
  - UNC ``\\\\host\\...`` → TCP connect to port 445 (2s timeout)
  - everything else → ``os.path.exists(root)`` in a worker thread (5s wait)

Public API:
  - ``get_snapshot()`` — pure memory read; safe from sync threadpool endpoints
  - ``schedule_reprobe_if_stale()`` — async-only; schedules background reprobe
  - ``unc_host(native_path)`` — public (T2 display name; ruff PLC2701)
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import socket
import threading
import time

from core.config import iter_gallery_sources, load_config
from core.logger import get_logger
from core.path_utils import uri_to_fs_path

logger = get_logger(__name__)

_SNAPSHOT_TTL_S = 60.0
_TCP_TIMEOUT_S = 2.0
_EXISTS_WAIT_S = 5.0
_RETRY_SLEEP_S = 1.0

_NEG_ERRNOS = {
    errno.EHOSTUNREACH,
    errno.ENETUNREACH,
    errno.ETIMEDOUT,
    errno.ENETDOWN,
}

_lock = threading.Lock()
_snapshot: dict[str, str] = {}
_snapshot_at: float = 0.0
_in_flight: bool = False
_pending_exists: dict[str, asyncio.Future] = {}
_reprobe_task: asyncio.Task | None = None


def get_snapshot() -> dict[str, str]:
    """Pure memory read of the latest probe snapshot. Never schedules IO."""
    with _lock:
        return dict(_snapshot)


async def schedule_reprobe_if_stale() -> None:
    """If snapshot is older than 60s and no probe is in flight, schedule one.

    Must only be called from an async context (has a running event loop).
    Ownership of ``_in_flight`` is taken under the lock before ``create_task``.
    """
    global _in_flight, _reprobe_task

    should_schedule = False
    with _lock:
        now = time.monotonic()
        stale = (now - _snapshot_at) > _SNAPSHOT_TTL_S
        if stale and not _in_flight:
            _in_flight = True
            should_schedule = True

    if not should_schedule:
        return

    coro = _probe_all()
    try:
        _reprobe_task = asyncio.create_task(coro)
    except Exception:
        coro.close()
        with _lock:
            _in_flight = False
        logger.warning(
            "schedule_reprobe_if_stale: create_task failed; released in-flight",
            exc_info=True,
        )


def unc_host(native_path: str) -> str | None:
    """Return ``\\\\host`` for UNC paths; ``None`` otherwise.

    Public (not ``_unc_host``) so T2 can import it without tripping ruff PLC2701.
    """
    if not native_path:
        return None
    if not (native_path.startswith("\\\\") or native_path.startswith("//")):
        return None
    rest = native_path.lstrip("\\/")
    if not rest:
        return None
    # Normalise separators then take the first segment as the host.
    host = rest.replace("\\", "/").split("/", 1)[0]
    if not host:
        return None
    return "\\\\" + host


async def _probe_all() -> None:
    """Probe every gallery source; write a fresh snapshot. Clears ``_in_flight``."""
    global _snapshot, _snapshot_at, _in_flight

    try:
        try:
            config = await asyncio.to_thread(load_config)
            gallery = config.get("gallery", {}) if isinstance(config, dict) else {}
            sources = await asyncio.to_thread(iter_gallery_sources, gallery)
        except Exception:
            logger.warning("_probe_all: failed to load sources", exc_info=True)
            with _lock:
                _snapshot = {}
                _snapshot_at = time.monotonic()
            return

        if not sources:
            with _lock:
                _snapshot = {}
                _snapshot_at = time.monotonic()
            return

        host_memo: dict[str, str] = {}
        new_snapshot: dict[str, str] = {}
        for src in sources:
            native = uri_to_fs_path(src.path)  # uri-no-reverse
            try:
                status = await _probe_one(native, host_memo)
            except Exception:
                logger.warning(
                    "_probe_all: probe failed for %s", native, exc_info=True
                )
                status = "unknown"
            new_snapshot[native] = status

        with _lock:
            _snapshot = new_snapshot
            _snapshot_at = time.monotonic()
    finally:
        with _lock:
            _in_flight = False


async def _probe_one(native_path: str, host_memo: dict[str, str]) -> str:
    try:
        host = unc_host(native_path)
        if host is not None:
            if host in host_memo:
                return host_memo[host]
            status = await _probe_tcp_with_retry(host)
            host_memo[host] = status
            return status
        return await _probe_exists_with_retry(native_path)
    except Exception:
        return "unknown"


async def _probe_tcp_with_retry(host: str) -> str:
    r1 = await _tcp_probe(host)
    if r1 is None:
        return "unknown"
    if r1 is False:
        return "ok"
    # Negative → retry once after 1s.
    await asyncio.sleep(_RETRY_SLEEP_S)
    r2 = await _tcp_probe(host)
    if r2 is None:
        return "unknown"
    if r2 is False:
        return "ok"
    return "unreachable"


async def _tcp_probe(host: str) -> bool | None:
    """Return False=ok, True=negative, None=unknown.

    ``host`` may be ``\\\\name`` from ``unc_host``; connect uses the bare name.
    """
    connect_host = host.lstrip("\\/")
    try:
        sock = await asyncio.to_thread(
            socket.create_connection, (connect_host, 445), _TCP_TIMEOUT_S
        )
        with contextlib.suppress(Exception):
            sock.close()
        return False
    except (TimeoutError, ConnectionRefusedError):
        return True
    except OSError as exc:
        if getattr(exc, "errno", None) in _NEG_ERRNOS:
            return True
        return None
    except Exception:
        return None


async def _probe_exists_with_retry(path: str) -> str:
    r1 = await _exists_probe(path)
    if r1 is None:
        return "unknown"
    if r1 is False:
        return "ok"
    await asyncio.sleep(_RETRY_SLEEP_S)
    r2 = await _exists_probe(path)
    if r2 is None:
        return "unknown"
    if r2 is False:
        return "ok"
    return "unreachable"


async def _exists_probe(path: str) -> bool | None:
    """Return False=exists(ok), True=missing(negative), None=unknown/pending.

    Per-path dedup via ``_pending_exists``: a timed-out ``exists`` keeps its
    future so the same path cannot enqueue a second worker thread.
    """
    with _lock:
        existing = _pending_exists.get(path)
        if existing is not None and not existing.done():
            return None
        if existing is not None and existing.done():
            _pending_exists.pop(path, None)

        future: asyncio.Future = asyncio.ensure_future(
            asyncio.to_thread(os.path.exists, path)
        )
        _pending_exists[path] = future

    def _clear_if_done(fut: asyncio.Future, *, key: str = path) -> None:
        with _lock:
            cur = _pending_exists.get(key)
            if cur is fut:
                _pending_exists.pop(key, None)

    future.add_done_callback(_clear_if_done)

    try:
        try:
            result = await asyncio.wait_for(
                asyncio.shield(future), timeout=_EXISTS_WAIT_S
            )
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        # exists True → affirmative (False); missing → negative (True)
        return False if result else True
    finally:
        with _lock:
            if future.done() and _pending_exists.get(path) is future:
                _pending_exists.pop(path, None)
