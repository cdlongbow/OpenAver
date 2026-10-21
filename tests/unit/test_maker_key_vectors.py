"""maker_key_of（Python）與前端 makerKey()（JS）共用向量（175a-T6，BE-TEST-14）。

預期值由 node 實跑 makerKey() 產出；同一份檔由 node --test 另讀一次
（web/static/js/shared/__tests__/maker-merge.test.mjs）。
"""
import json
from pathlib import Path

import pytest

from core.maker_names import maker_key_of

_VECTOR_FILE = Path(__file__).resolve().parent.parent / "data" / "maker_key_vectors.json"
_VECTORS = json.loads(_VECTOR_FILE.read_text(encoding="utf-8"))["vectors"]


@pytest.mark.parametrize("vec", _VECTORS, ids=[repr(v["input"]) for v in _VECTORS])
def test_maker_key_matches_frontend_vectors(vec):
    assert maker_key_of(vec["input"]) == vec["key"]


def test_maker_key_of_none_is_empty():
    assert maker_key_of(None) == ""


def test_vector_file_covers_required_shapes():
    inputs = [v["input"] for v in _VECTORS]
    for needle in ("﻿", "\x1c", "\x85", "ß", "ẞ", "İ"):
        assert any(needle in i for i in inputs), needle
    assert any(i != i.strip() for i in inputs)
