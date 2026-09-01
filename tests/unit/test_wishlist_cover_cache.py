"""Unit tests for core.wishlist_cover_cache (feature/140 T3).

隔離策略：patch 使用端 `core.wishlist_cover_cache.get_db_path` → tmp_path，
以及 `core.wishlist_cover_cache.requests`（不是定義端 / 全域 requests）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

import core.wishlist_cover_cache as wcc
from core.scraper import normalize_number


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """導向 tmp_path，避免 G1 守衛擋真實 DB / output 寫入。"""
    path = tmp_path / "openaver.db"
    monkeypatch.setattr(wcc, "get_db_path", lambda: path)
    return path


def _sha1_path(number: str, db_path: Path) -> Path:
    h = hashlib.sha1(normalize_number(number).encode("utf-8")).hexdigest()
    return db_path.parent / "wishlist_cover" / h[:2] / f"{h}.webp"


def _ok_response(content: bytes, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    return resp


# ── DoD-1: cover_file_for 純推導 ─────────────────────────────────
def test_cover_file_for_same_number_forms_share_path(db_path):
    a = wcc.cover_file_for("fc2ppv-1234567")
    b = wcc.cover_file_for("FC2-1234567")
    assert a == b
    assert a == _sha1_path("FC2-1234567", db_path)


def test_cover_file_for_bucket_format(db_path):
    number = "SONE-001"
    h = hashlib.sha1(normalize_number(number).encode("utf-8")).hexdigest()
    p = wcc.cover_file_for(number)
    assert p == db_path.parent / "wishlist_cover" / h[:2] / f"{h}.webp"
    assert p.parent.name == h[:2]
    assert p.stem == h
    assert p.suffix == ".webp"


def test_cover_file_for_creates_nothing_on_disk(db_path):
    p = wcc.cover_file_for("ABC-123")
    assert not p.exists()
    assert not p.parent.exists()
    assert not (db_path.parent / "wishlist_cover").exists()


# ── DoD-2: 下載成功落地（逐位元） ────────────────────────────────
def test_download_and_save_writes_exact_bytes(db_path, monkeypatch):
    payload = b"x" * 1500
    monkeypatch.setattr(
        wcc.requests, "get", lambda *a, **k: _ok_response(payload)
    )
    assert wcc.download_and_save("SONE-001", "https://cdn.example/cover.jpg") is True
    dest = wcc.cover_file_for("SONE-001")
    assert dest.exists()
    assert dest.read_bytes() == payload
    assert list(dest.parent.glob("*.tmp")) == []


# ── DoD-3 / M2: RequestException → False，不拋、不留檔 ───────────
def test_download_and_save_returns_false_on_request_exception(db_path, monkeypatch):
    def _boom(*_a, **_k):
        raise requests.RequestException("timeout")

    monkeypatch.setattr(wcc.requests, "get", _boom)
    assert wcc.download_and_save("SONE-001", "https://cdn.example/cover.jpg") is False
    dest = wcc.cover_file_for("SONE-001")
    assert not dest.exists()
    if dest.parent.exists():
        assert list(dest.parent.iterdir()) == []


# ── DoD-3 / M1: 過小回應 → False ─────────────────────────────────
def test_download_and_save_rejects_undersized_response(db_path, monkeypatch):
    tiny = b"tiny-error-page"  # << 1000
    monkeypatch.setattr(
        wcc.requests, "get", lambda *a, **k: _ok_response(tiny)
    )
    assert wcc.download_and_save("SONE-001", "https://cdn.example/cover.jpg") is False
    dest = wcc.cover_file_for("SONE-001")
    assert not dest.exists()
    if dest.parent.exists():
        assert list(dest.parent.iterdir()) == []


def test_download_and_save_returns_false_on_non_200(db_path, monkeypatch):
    monkeypatch.setattr(
        wcc.requests, "get", lambda *a, **k: _ok_response(b"x" * 1500, status_code=500)
    )
    assert wcc.download_and_save("SONE-001", "https://cdn.example/cover.jpg") is False
    dest = wcc.cover_file_for("SONE-001")
    assert not dest.exists()


# ── DoD-4: fallback 生效 ─────────────────────────────────────────
def test_download_and_save_uses_fallback_when_cover_fails(db_path, monkeypatch):
    cover_bytes = b"C" * 1500
    fallback_bytes = b"F" * 1500
    calls = []

    def fake_get(url, *a, **k):
        calls.append(url)
        if "cover" in url:
            return _ok_response(b"tiny")  # undersized → fail
        return _ok_response(fallback_bytes)

    monkeypatch.setattr(wcc.requests, "get", fake_get)
    assert (
        wcc.download_and_save(
            "SONE-001",
            "https://cdn.example/cover.jpg",
            fallback_url="https://cdn.example/fallback.jpg",
        )
        is True
    )
    dest = wcc.cover_file_for("SONE-001")
    assert dest.read_bytes() == fallback_bytes
    assert dest.read_bytes() != cover_bytes
    assert calls == [
        "https://cdn.example/cover.jpg",
        "https://cdn.example/fallback.jpg",
    ]


def test_download_and_save_empty_cover_url_tries_fallback(db_path, monkeypatch):
    fallback_bytes = b"F" * 1500
    calls = []

    def fake_get(url, *a, **k):
        calls.append(url)
        return _ok_response(fallback_bytes)

    monkeypatch.setattr(wcc.requests, "get", fake_get)
    assert (
        wcc.download_and_save(
            "SONE-001",
            "",
            fallback_url="https://cdn.example/fallback.jpg",
        )
        is True
    )
    assert calls == ["https://cdn.example/fallback.jpg"]
    assert wcc.cover_file_for("SONE-001").read_bytes() == fallback_bytes


def test_download_and_save_both_urls_empty_returns_false(db_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        wcc.requests, "get", lambda *a, **k: calls.append(1) or _ok_response(b"x" * 1500)
    )
    assert wcc.download_and_save("SONE-001", "", fallback_url="") is False
    assert calls == []
    assert not wcc.cover_file_for("SONE-001").exists()


# ── DoD-5: remove ────────────────────────────────────────────────
def test_remove_deletes_existing_file(db_path, monkeypatch):
    payload = b"x" * 1500
    monkeypatch.setattr(
        wcc.requests, "get", lambda *a, **k: _ok_response(payload)
    )
    assert wcc.download_and_save("SONE-001", "https://cdn.example/cover.jpg") is True
    dest = wcc.cover_file_for("SONE-001")
    assert dest.exists()
    assert wcc.remove("SONE-001") is None
    assert not dest.exists()


def test_remove_missing_is_noop(db_path):
    assert wcc.remove("NEVER-EXISTED") is None


# ── 鏡像對稱：download / remove 對不同格式番號走同一路徑 ─────────
def test_download_and_remove_share_path_across_number_forms(db_path, monkeypatch):
    payload = b"y" * 1500
    monkeypatch.setattr(
        wcc.requests, "get", lambda *a, **k: _ok_response(payload)
    )
    assert wcc.download_and_save("fc2ppv-1234567", "https://cdn.example/c.jpg") is True
    written = wcc.cover_file_for("fc2ppv-1234567")
    assert written.exists()
    # remove 用另一種寫法的同一番號
    wcc.remove("FC2-1234567")
    assert not written.exists()
    assert wcc.cover_file_for("FC2-1234567") == written


# ── timeout 必須傳入 requests.get ────────────────────────────────
def test_fetch_passes_timeout(db_path, monkeypatch):
    seen = {}

    def fake_get(url, *a, **k):
        seen.update(k)
        return _ok_response(b"z" * 1500)

    monkeypatch.setattr(wcc.requests, "get", fake_get)
    assert wcc.download_and_save("SONE-001", "https://cdn.example/c.jpg") is True
    assert "timeout" in seen
    assert seen["timeout"] == 30
