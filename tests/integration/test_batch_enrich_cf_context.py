"""TASK-168d-T2 / CD-168d-4 (a)：/api/batch-enrich 三處 run_in_executor 必須帶著請求的殼身分。

oracle：把使用端綁定（web.routers.scraper.*）換成記錄 `cf_handoff.current_key.get()` 的 fake，
斷言讀到的是 'loopback'（TestClient 預設 loopback 無票據），不是「不是 _UNSET」
（key 為 None 時後者會假綠）。每格只走到自己那一處 executor。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from core import cf_handoff
from core.enricher import EnrichResult


def _sse(text: str) -> list:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def _ok(**kw):
    d = dict(success=True, nfo_written=True, cover_written=True, extrafanart_written=0,
             fields_filled=["title"], source_used="javlibrary", error=None)
    d.update(kw)
    return EnrichResult(**d)


@pytest.fixture(autouse=True)
def _isolated_key():
    tok = cf_handoff.current_key.set(cf_handoff._UNSET)
    yield
    cf_handoff.current_key.reset(tok)


def _readonly_config():
    return {
        "gallery": {"directories": [{"path": "/tmp/ro_src", "readonly": True}], "path_mappings": {}},
        "search": {},
        "scraper": {},
    }


def test_batch_enrich_readonly_item_keeps_shell_key(client, mocker):
    seen: list = []

    def fake_readonly(**kwargs):
        seen.append(cf_handoff.current_key.get())
        return _ok()

    mocker.patch("web.routers.scraper.load_config", return_value=_readonly_config())
    src = MagicMock()
    src.path = "/tmp/ro_src"
    mocker.patch("web.routers.scraper.resolve_owning_output_root",
                 return_value=(src, "/out/ro_src-x", "file:///out/ro_src-x"))
    mocker.patch("web.routers.scraper.enrich_one_readonly", side_effect=fake_readonly)

    r = client.post("/api/batch-enrich", json={
        "items": [{"file_path": "/tmp/ro_src/RO-001.mp4", "number": "RO-001"}],
        "mode": "fill_missing",
        "source": "javlibrary",
    })
    assert r.status_code == 200
    assert [e for e in _sse(r.text) if e["type"] == "result-item"]
    assert seen == ["loopback"]


def test_batch_enrich_refresh_full_prefetch_keeps_shell_key(client, mocker):
    seen: list = []

    def fake_search(*a, **kw):
        seen.append(cf_handoff.current_key.get())
        return {"title": "stub", "source": "javlibrary"}

    mocker.patch("web.routers.scraper.search_jav", side_effect=fake_search)
    mocker.patch("web.routers.scraper.enrich_single", return_value=_ok())

    r = client.post("/api/batch-enrich", json={
        "items": [{"file_path": "/video/ABC-001.mp4", "number": "ABC-001"}],
        "mode": "refresh_full",
        "source": "javlibrary",
    })
    assert r.status_code == 200
    assert seen == ["loopback"]


def test_batch_enrich_enrich_single_keeps_shell_key(client, mocker):
    seen: list = []

    def fake_enrich(**kwargs):
        seen.append(cf_handoff.current_key.get())
        return _ok()

    mocker.patch("web.routers.scraper.search_jav", return_value={"title": "stub"})
    mocker.patch("web.routers.scraper.enrich_single", side_effect=fake_enrich)

    r = client.post("/api/batch-enrich", json={
        "items": [{"file_path": "/video/ABC-002.mp4", "number": "ABC-002"}],
        "mode": "fill_missing",
        "source": "javlibrary",
    })
    assert r.status_code == 200
    assert [e for e in _sse(r.text) if e["type"] == "result-item"][0]["success"] is True
    assert seen == ["loopback"]


def test_batch_enrich_each_item_gets_its_own_context_copy(client, mocker):
    """多片批次：每一圈都新開一份 ctx（同一個 Context 不可被並行進入；連續兩圈不得 RuntimeError）。"""
    seen: list = []

    def fake_enrich(**kwargs):
        seen.append(cf_handoff.current_key.get())
        return _ok()

    mocker.patch("web.routers.scraper.search_jav", return_value={"title": "stub"})
    mocker.patch("web.routers.scraper.enrich_single", side_effect=fake_enrich)
    r = client.post("/api/batch-enrich", json={
        "items": [{"file_path": f"/video/ABC-10{i}.mp4", "number": f"ABC-10{i}"} for i in range(3)],
        "mode": "fill_missing",
        "source": "javlibrary",
    })
    assert r.status_code == 200
    assert seen == ["loopback"] * 3
