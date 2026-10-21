"""tests/unit/test_maker_javbus_map.py — 片商 → JavBus 對應表（TASK-173-T2）。"""
import sqlite3
from contextlib import closing

import pytest

from core.database import maker_javbus_map
from core.database.connection import init_db, get_connection


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "map.db"
    init_db(path)
    return path


def test_missing_key_returns_none(db):
    assert maker_javbus_map.get_mapping("nobody", db_path=db) is None


def test_record_found_roundtrip(db):
    maker_javbus_map.record_found("moodyz", "censored", "7q", "MOODYZ", db_path=db)
    m = maker_javbus_map.get_mapping("moodyz", db_path=db)
    assert m["status"] == "found"
    assert m["kind"] == "censored"
    assert m["studio_id"] == "7q"
    assert m["label"] == "MOODYZ"
    assert m["checked_at"] > 0


def test_record_not_found_roundtrip(db):
    maker_javbus_map.record_not_found("ghost", "Ghost", db_path=db)
    m = maker_javbus_map.get_mapping("ghost", db_path=db)
    assert m["status"] == "not_found"
    assert m["kind"] == ""
    assert m["studio_id"] == ""
    assert m["label"] == "Ghost"


def test_found_then_not_found_keeps_found_and_studio_id(db):
    maker_javbus_map.record_found("K", "censored", "7q", "K", db_path=db)
    maker_javbus_map.record_not_found("K", "K2", db_path=db)
    m = maker_javbus_map.get_mapping("K", db_path=db)
    assert m["status"] == "found"
    assert m["studio_id"] == "7q"
    assert m["kind"] == "censored"


def test_not_found_then_found_becomes_found(db):
    maker_javbus_map.record_not_found("K", "K", db_path=db)
    maker_javbus_map.record_found("K", "uncensored", "3a", "K", db_path=db)
    m = maker_javbus_map.get_mapping("K", db_path=db)
    assert m["status"] == "found"
    assert m["studio_id"] == "3a"
    assert m["kind"] == "uncensored"


def test_list_not_found_keys_excludes_found(db):
    maker_javbus_map.record_found("A", "censored", "1", "A", db_path=db)
    maker_javbus_map.record_not_found("B", "B", db_path=db)
    maker_javbus_map.record_not_found("C", "C", db_path=db)
    assert sorted(maker_javbus_map.list_not_found_keys(db_path=db)) == ["B", "C"]


@pytest.mark.parametrize("kind,sid", [("censored", ""), ("", "7q"), ("", "")])
def test_check_rejects_found_without_studio_id(db, kind, sid):
    with pytest.raises(sqlite3.IntegrityError):
        maker_javbus_map.record_found("K", kind, sid, "K", db_path=db)
    assert maker_javbus_map.get_mapping("K", db_path=db) is None


def test_key_is_opaque_no_normalization(db):
    maker_javbus_map.record_found("Moodyz", "censored", "7q", "x", db_path=db)
    assert maker_javbus_map.get_mapping("moodyz", db_path=db) is None
    assert maker_javbus_map.get_mapping(" Moodyz", db_path=db) is None


def test_init_db_upgrade_old_db_preserves_data_and_idempotent(tmp_path):
    path = tmp_path / "old.db"
    init_db(path)
    with closing(get_connection(path)) as conn:
        conn.execute("DROP TABLE maker_javbus_map")
        conn.execute("INSERT INTO videos (path, number, title) VALUES (?, ?, ?)",
                     ("file:///x/a.mp4", "ABC-123", "T"))
        conn.execute(
            "INSERT INTO organize_failures (key, reason, number, duplicate_target, attempt_count, last_failed_at)"
            " VALUES (?, ?, ?, ?, ?, ?)", ("ABC-123", "not_found", "ABC-123", "", 2, 1234.5))
        conn.commit()

    init_db(path)
    init_db(path)

    with closing(get_connection(path)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "maker_javbus_map" in names
        v = conn.execute("SELECT path, number, title FROM videos").fetchall()
        assert [tuple(r) for r in v] == [("file:///x/a.mp4", "ABC-123", "T")]
        o = conn.execute("SELECT key, reason, number, duplicate_target, attempt_count, last_failed_at"
                         " FROM organize_failures").fetchall()
        assert [tuple(r) for r in o] == [("ABC-123", "not_found", "ABC-123", "", 2, 1234.5)]
    assert maker_javbus_map.list_not_found_keys(db_path=path) == []
