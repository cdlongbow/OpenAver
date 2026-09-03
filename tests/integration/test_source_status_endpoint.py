"""Integration tests for GET /api/showcase/source-status and lifespan probe.

Covers TASK-142-T2 DoD 1–5:
1. Rapid calls (5 times in 60s window) probe at most once and respond < 50ms.
2. Lifespan context manager yields within 100ms even if probe takes 10s.
3. get_snapshot exception does not affect GET /api/showcase/videos.
4. Returns empty list [] when all sources are ok/unknown/unprobed.
5. Display formatting for UNC (\\\\host) and non-UNC paths.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import core.source_reachability as sr
from web.app import app, lifespan


def _reset_sr_module() -> None:
    with sr._lock:
        sr._snapshot = {}
        sr._snapshot_at = 0.0
        sr._in_flight = False
        sr._pending_exists.clear()
        sr._reprobe_task = None


def test_dod1_five_rapid_calls_probe_at_most_once_and_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """DoD 1: 5 rapid calls in 60s window trigger at most 1 probe, each < 50ms."""
    _reset_sr_module()

    probe_count = 0

    async def mock_probe_all() -> None:
        nonlocal probe_count
        probe_count += 1
        with sr._lock:
            sr._snapshot = {"/test/path": "unreachable"}
            sr._snapshot_at = time.monotonic()
            sr._in_flight = False

    monkeypatch.setattr(sr, "_probe_all", mock_probe_all)

    client = TestClient(app, client=("127.0.0.1", 50000))
    durations = []
    for _ in range(5):
        t0 = time.perf_counter()
        resp = client.get("/api/showcase/source-status")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        durations.append(elapsed_ms)
        assert resp.status_code == 200

    assert probe_count <= 1
    for d in durations:
        assert d < 50, f"Response duration {d:.2f}ms exceeds 50ms"


@pytest.mark.asyncio
async def test_dod2_lifespan_yield_not_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """DoD 2: lifespan to yield takes < 100ms even when probe runs for 10s."""
    _reset_sr_module()

    monkeypatch.setattr("web.app.init_db", lambda *a, **kw: None)
    monkeypatch.setattr("web.app.ensure_schema", lambda *a, **kw: None)
    monkeypatch.setattr("web.app.backfill_readonly_nfo_mtime", lambda *a, **kw: 0)
    monkeypatch.setattr("web.app.startup_reconnect", lambda *a, **kw: None)
    monkeypatch.setattr("web.app._startup_update_check", AsyncMock())

    async def slow_probe_all() -> None:
        await asyncio.sleep(10.0)

    monkeypatch.setattr(sr, "_probe_all", slow_probe_all)

    called = False
    real_schedule = sr.schedule_reprobe_if_stale

    async def tracking_schedule() -> None:
        nonlocal called
        called = True
        await real_schedule()

    monkeypatch.setattr(sr, "schedule_reprobe_if_stale", tracking_schedule)

    t0 = time.perf_counter()
    cm = lifespan(app)
    try:
        await asyncio.wait_for(cm.__aenter__(), timeout=1.0)
        elapsed = time.perf_counter() - t0
        assert called, "lifespan must call schedule_reprobe_if_stale()"
        assert elapsed < 0.1, f"lifespan startup took {elapsed:.3f}s, expected < 0.1s"
    finally:
        with contextlib.suppress(Exception):
            await cm.__aexit__(None, None, None)
        if sr._reprobe_task and not sr._reprobe_task.done():
            sr._reprobe_task.cancel()


def test_dod3_get_snapshot_error_does_not_affect_videos(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """DoD 3: get_snapshot exception does not affect GET /api/showcase/videos."""
    from core.database import init_db

    test_db = tmp_path / "test_showcase.db"
    init_db(test_db)
    monkeypatch.setattr("web.routers.showcase.get_db_path", lambda: test_db)
    monkeypatch.setattr(
        "web.routers.showcase.load_config",
        lambda: {"gallery": {"directories": [], "path_mappings": {}}},
    )

    def failing_snapshot() -> dict[str, str]:
        raise RuntimeError("simulated get_snapshot failure")

    monkeypatch.setattr(sr, "get_snapshot", failing_snapshot)

    client = TestClient(app, client=("127.0.0.1", 50000))
    resp = client.get("/api/showcase/videos")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert "videos" in data


def test_dod4_all_ok_or_unknown_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """DoD 4: all sources ok/unknown/unprobed returns empty list []."""
    monkeypatch.setattr(
        sr,
        "get_snapshot",
        lambda: {
            "//server/share1": "ok",
            "//server/share2": "unknown",
            "/local/media": "ok",
        },
    )
    monkeypatch.setattr(sr, "schedule_reprobe_if_stale", AsyncMock())

    client = TestClient(app, client=("127.0.0.1", 50000))
    resp = client.get("/api/showcase/source-status")
    assert resp.status_code == 200
    assert resp.json() == []

    # Unprobed scenario (empty snapshot)
    monkeypatch.setattr(sr, "get_snapshot", lambda: {})
    resp_empty = client.get("/api/showcase/source-status")
    assert resp_empty.status_code == 200
    assert resp_empty.json() == []


def test_dod5_unreachable_sources_display_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """DoD 5: unreachable UNC formats to \\\\<host>, non-UNC to raw path."""
    mock_snapshot = {
        "\\\\nas-box\\share\\videos": "unreachable",
        "/mnt/storage/media": "unreachable",
        "//other-nas/data": "ok",
    }
    monkeypatch.setattr(sr, "get_snapshot", lambda: mock_snapshot)
    monkeypatch.setattr(sr, "schedule_reprobe_if_stale", AsyncMock())

    client = TestClient(app, client=("127.0.0.1", 50000))
    resp = client.get("/api/showcase/source-status")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2

    unc_item = next(
        (item for item in data if item["path"] == "\\\\nas-box\\share\\videos"),
        None,
    )
    assert unc_item is not None
    assert unc_item["display"] == "\\\\nas-box"
    assert unc_item["status"] == "unreachable"

    local_item = next(
        (item for item in data if item["path"] == "/mnt/storage/media"),
        None,
    )
    assert local_item is not None
    assert local_item["display"] == "/mnt/storage/media"
    assert local_item["status"] == "unreachable"
