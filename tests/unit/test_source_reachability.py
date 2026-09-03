"""Unit tests for core.source_reachability (TASK-142-T1 DoD ①–⑨)."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import DirectoryConfig


def _reset_module(sr):
    with sr._lock:
        sr._snapshot = {}
        sr._snapshot_at = 0.0
        sr._in_flight = False
        sr._pending_exists.clear()
        sr._reprobe_task = None


@pytest.fixture
def sr():
    import core.source_reachability as mod

    _reset_module(mod)
    yield mod
    # Drain any leftover probe task so it cannot leak into the next test.
    task = mod._reprobe_task
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(Exception):
            asyncio.get_event_loop().run_until_complete(task)
    _reset_module(mod)


def _sources(*paths: str):
    return [DirectoryConfig(path=p) for p in paths]


# ── DoD ① ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_sources_makes_no_probe_calls(sr):
    """① 無來源 → 不建立任何 socket/exists 呼叫，快照為空。"""
    with (
        patch.object(sr, "load_config", return_value={"gallery": {}}),
        patch.object(sr, "iter_gallery_sources", return_value=[]),
        patch.object(sr.socket, "create_connection") as mock_conn,
        patch.object(sr.os.path, "exists") as mock_exists,
    ):
        await sr.schedule_reprobe_if_stale()
        await sr._reprobe_task
        assert mock_conn.call_count == 0
        assert mock_exists.call_count == 0
        assert sr.get_snapshot() == {}


# ── DoD ② ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_same_unc_host_connects_once_and_closes(sr):
    """② 三個同主機 UNC → create_connection 恰 1 次，且 socket.close() 有被呼叫。"""
    sock = MagicMock()
    sources = _sources(
        r"\\nas\share1",
        r"\\nas\share2",
        r"\\nas\videos",
    )
    with (
        patch.object(sr, "load_config", return_value={"gallery": {}}),
        patch.object(sr, "iter_gallery_sources", return_value=sources),
        patch.object(sr.socket, "create_connection", return_value=sock) as mock_conn,
        patch.object(sr.asyncio, "sleep", new_callable=AsyncMock),
    ):
        await sr.schedule_reprobe_if_stale()
        await sr._reprobe_task
        assert mock_conn.call_count == 1
        sock.close.assert_called_once()
        snap = sr.get_snapshot()
        assert len(snap) == 3
        assert all(v == "ok" for v in snap.values())


# ── DoD ③ ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tcp_double_negative_is_unreachable(sr):
    """③ 兩次 TCP 否定（True/True）→ unreachable。"""
    with (
        patch.object(sr, "_tcp_probe", new_callable=AsyncMock, side_effect=[True, True]),
        patch.object(sr.asyncio, "sleep", new_callable=AsyncMock),
    ):
        status = await sr._probe_tcp_with_retry("nas")
    assert status == "unreachable"


@pytest.mark.asyncio
async def test_tcp_negative_then_positive_is_ok(sr):
    """③ 一次否定＋一次肯定（True/False）→ ok。"""
    with (
        patch.object(sr, "_tcp_probe", new_callable=AsyncMock, side_effect=[True, False]),
        patch.object(sr.asyncio, "sleep", new_callable=AsyncMock),
    ):
        status = await sr._probe_tcp_with_retry("nas")
    assert status == "ok"


# ── DoD ④ / ④b ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tcp_probe_none_is_unknown(sr):
    """④ TCP 探測回 None（如 gaierror）→ unknown（不是 ok）。"""

    def boom(*_a, **_k):
        raise socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided")

    with (
        patch.object(sr, "load_config", return_value={"gallery": {}}),
        patch.object(sr, "iter_gallery_sources", return_value=_sources(r"\\nas\share")),
        patch.object(sr.socket, "create_connection", side_effect=boom),
        patch.object(sr.asyncio, "sleep", new_callable=AsyncMock),
    ):
        await sr.schedule_reprobe_if_stale()
        await sr._reprobe_task
    snap = sr.get_snapshot()
    assert len(snap) == 1
    assert next(iter(snap.values())) == "unknown"


@pytest.mark.asyncio
async def test_tcp_negative_then_none_is_unknown(sr):
    """④b 第一次否定、第二次 None → unknown（不是 ok 也不是 unreachable）。"""
    with (
        patch.object(sr, "_tcp_probe", new_callable=AsyncMock, side_effect=[True, None]),
        patch.object(sr.asyncio, "sleep", new_callable=AsyncMock),
    ):
        status = await sr._probe_tcp_with_retry("nas")
    assert status == "unknown"


# ── DoD ⑤ / ⑤b ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_iter_gallery_sources_error_clears_snapshot(sr):
    """⑤ iter_gallery_sources 拋例外 → _in_flight False、快照 == {}（不保留舊快照）。"""
    with sr._lock:
        sr._snapshot = {"/old": "unreachable"}
        sr._snapshot_at = time.monotonic()
        sr._in_flight = True

    with (
        patch.object(sr, "load_config", return_value={"gallery": {}}),
        patch.object(sr, "iter_gallery_sources", side_effect=RuntimeError("bad config")),
    ):
        await sr._probe_all()

    assert sr._in_flight is False
    assert sr.get_snapshot() == {}


@pytest.mark.asyncio
async def test_single_source_probe_error_is_isolated(sr):
    """⑤b 單一來源探測拋例外 → 該來源 unknown，其餘來源不受影響。"""
    paths = ["/mnt/ok", "/mnt/boom"]
    sources = _sources(*paths)

    async def probe_one(native_path, host_memo):
        if native_path == "/mnt/boom":
            raise RuntimeError("probe exploded")
        return "ok"

    with (
        patch.object(sr, "load_config", return_value={"gallery": {}}),
        patch.object(sr, "iter_gallery_sources", return_value=sources),
        patch.object(sr, "_probe_one", side_effect=probe_one),
    ):
        await sr.schedule_reprobe_if_stale()
        await sr._reprobe_task

    snap = sr.get_snapshot()
    assert snap["/mnt/ok"] == "ok"
    assert snap["/mnt/boom"] == "unknown"


# ── DoD ⑥ ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_snapshot_returns_within_100ms_during_probe(sr):
    """⑥ 模擬 5 秒探測進行中時，get_snapshot() 在 100ms 內返回（不變式 I1）。"""

    async def slow_probe():
        try:
            await asyncio.sleep(5)
        finally:
            with sr._lock:
                sr._in_flight = False

    with patch.object(sr, "_probe_all", side_effect=slow_probe):
        await sr.schedule_reprobe_if_stale()
        assert sr._in_flight is True
        t0 = time.perf_counter()
        snap = sr.get_snapshot()
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.1
        assert isinstance(snap, dict)
        # Cancel background task so the test doesn't wait 5s on teardown.
        if sr._reprobe_task is not None:
            sr._reprobe_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await sr._reprobe_task


def test_get_snapshot_never_creates_reprobe_task(sr):
    """⑥ 單獨呼叫 get_snapshot() 永遠不建立 _reprobe_task。"""
    assert sr._reprobe_task is None
    sr.get_snapshot()
    assert sr._reprobe_task is None


# ── DoD ⑦ ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_schedule_reprobe_creates_single_task(sr):
    """⑦ 同一 tick 5 次 schedule_reprobe_if_stale() → 只建立 1 個 _probe_all task。"""

    async def slow_probe():
        try:
            await asyncio.sleep(0.05)
        finally:
            with sr._lock:
                sr._in_flight = False

    real_create = asyncio.create_task
    create_count = {"n": 0}

    def counting_create(coro, *a, **k):
        create_count["n"] += 1
        return real_create(coro, *a, **k)

    with (
        patch.object(sr, "_probe_all", side_effect=slow_probe),
        patch.object(sr.asyncio, "create_task", side_effect=counting_create),
    ):
        await asyncio.gather(*[sr.schedule_reprobe_if_stale() for _ in range(5)])
        assert create_count["n"] == 1
        if sr._reprobe_task is not None:
            await sr._reprobe_task


# ── DoD ⑧ ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_exists_dedup_across_ttl_cycles(sr):
    """⑧ exists 真阻塞去重：第二輪呼叫數仍為 1；放行後第三輪才變 2（不變式 I4）。"""
    block = threading.Event()
    call_count = {"n": 0}

    def blocking_exists(_path):
        call_count["n"] += 1
        block.wait(timeout=30)
        # Return True (exists) so round-3's first probe is affirmative and does
        # not fire the negative-retry second exists() — DoD ⑧ locks call count,
        # not the final status after release.
        return True

    path = "/mnt/dead-nfs"
    sources = _sources(path)

    with (
        patch.object(sr, "load_config", return_value={"gallery": {}}),
        patch.object(sr, "iter_gallery_sources", return_value=sources),
        patch.object(sr.os.path, "exists", side_effect=blocking_exists),
        patch.object(sr.asyncio, "sleep", new_callable=AsyncMock),
    ):
        # Round 1: 5s timeout → unknown; future stays pending.
        await sr.schedule_reprobe_if_stale()
        await sr._reprobe_task
        assert sr.get_snapshot().get(path) == "unknown"
        assert call_count["n"] == 1

        # Round 2: push TTL stale; pending future still unfinished → no new exists.
        with sr._lock:
            sr._snapshot_at = time.monotonic() - (sr._SNAPSHOT_TTL_OK_S + 1.0)
        await sr.schedule_reprobe_if_stale()
        await sr._reprobe_task
        assert call_count["n"] == 1
        assert sr.get_snapshot().get(path) == "unknown"

        # Release the blocked worker and wait until the pending future completes.
        block.set()
        pending = None
        with sr._lock:
            pending = sr._pending_exists.get(path)
        if pending is not None and not pending.done():
            await asyncio.wait_for(asyncio.shield(pending), timeout=2.0)
        # Allow done-callback to clear the pending entry.
        await asyncio.sleep(0)

        # Round 3: after cleanup, a new exists may be submitted.
        with sr._lock:
            sr._snapshot_at = time.monotonic() - (sr._SNAPSHOT_TTL_OK_S + 1.0)
        await sr.schedule_reprobe_if_stale()
        await sr._reprobe_task
        assert call_count["n"] == 2


# ── DoD ⑨ ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_task_failure_recovers_in_flight(sr):
    """⑨ create_task 拋 RuntimeError → 不上拋、_in_flight False；移除 patch 後可再排程。"""

    def boom(_coro, *a, **k):
        raise RuntimeError("loop is closing")

    with patch.object(sr.asyncio, "create_task", side_effect=boom):
        await sr.schedule_reprobe_if_stale()  # must not raise
        assert sr._in_flight is False

    scheduled = {"n": 0}
    real_create = asyncio.create_task

    def counting_create(coro, *a, **k):
        scheduled["n"] += 1
        return real_create(coro, *a, **k)

    async def quick_probe():
        with sr._lock:
            sr._in_flight = False

    with (
        patch.object(sr, "_probe_all", side_effect=quick_probe),
        patch.object(sr.asyncio, "create_task", side_effect=counting_create),
    ):
        await sr.schedule_reprobe_if_stale()
        assert scheduled["n"] == 1
        if sr._reprobe_task is not None:
            await sr._reprobe_task


# ── unc_host smoke（公開 API，供 T2 顯示名）────────────────────────────


def test_unc_host_parses_backslash_and_slash(sr):
    assert sr.unc_host(r"\\nas\share\path") == r"\\nas"
    assert sr.unc_host("//nas/share/path") == r"\\nas"
    assert sr.unc_host("/mnt/data") is None
    assert sr.unc_host(r"D:\Videos") is None


# ── CD-5 TTL 非對稱（owner 2026-09-03 修訂）────────────────────────────


@pytest.mark.asyncio
async def test_all_ok_snapshot_uses_long_ttl(sr):
    """全部 ok/unknown 的快照走 600 秒 TTL：過了 120 秒仍不重探。"""
    with sr._lock:
        sr._snapshot = {"/mnt/a": "ok", "/mnt/b": "unknown"}
        sr._snapshot_at = time.monotonic() - 120.0

    with patch.object(sr.asyncio, "create_task") as mock_create:
        await sr.schedule_reprobe_if_stale()

    assert mock_create.call_count == 0
    assert sr._in_flight is False


@pytest.mark.asyncio
async def test_unreachable_snapshot_uses_short_ttl(sr):
    """有任何 unreachable 的快照走 60 秒 TTL：過了 120 秒就重探（碟插回來要快點消失）。"""
    with sr._lock:
        sr._snapshot = {"/mnt/a": "ok", "/mnt/nas": "unreachable"}
        sr._snapshot_at = time.monotonic() - 120.0

    async def quick_probe():
        with sr._lock:
            sr._in_flight = False

    with patch.object(sr, "_probe_all", side_effect=quick_probe):
        await sr.schedule_reprobe_if_stale()
        assert sr._reprobe_task is not None
        await sr._reprobe_task
