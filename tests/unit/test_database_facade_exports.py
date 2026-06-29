"""Regression guard: core.database facade must export all public names.

If someone accidentally removes an entry from core/database/__init__.py
(once the module is split into a package in 87a-T2), this test catches it
immediately. Each name is asserted independently so the failure message
identifies exactly which export went missing.

This guard is intentionally added BEFORE the split (87a-T1): it passes on the
current single-file core/database.py and turns RED the moment the split-out
facade omits any re-export.
"""
import pytest

import core.database as db

# spec-87 §A public surface — all 13 names the facade must re-export.
# Includes the underscore-prefixed _migrate_old_aliases because
# tests/unit/test_alias_repository.py:81 imports it directly.
EXPECTED_NAMES = [
    # connection.py
    "get_db_path",
    "get_connection",
    "init_db",
    "_migrate_old_aliases",
    # migrate.py
    "migrate_json_to_sqlite",
    # video.py
    "Video",
    "VideoRepository",
    # alias.py
    "AliasRecord",
    "AliasRepository",
    # tag_alias.py
    "TagAliasRecord",
    "TagAliasRepository",
    # actress.py
    "Actress",
    "ActressRepository",
]


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_facade_exports_public_name(name):
    assert hasattr(db, name), (
        f"core.database is missing '{name}' — "
        f"check core/database/__init__.py __all__ and its import list"
    )
