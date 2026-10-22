"""
tests/unit/test_nfo_read.py

TASK-113a-T2: 六支 `core.nfo_read` 純函式的單元測試，直接對 `ET.Element` 輸入
輸出斷言（不經過任何 consumer 的 shape）。CD-113a-7 的巢狀值邊界（`nfo_text`）
也在這裡釘住三格。

這是新檔案，不修改任何既有測試。
"""

import xml.etree.ElementTree as ET

from core.nfo_read import (
    nfo_actor_names,
    nfo_first_text,
    nfo_merged_tags,
    nfo_runtime_minutes,
    nfo_series_name,
    nfo_text,
    nfo_title_record,
)


def _root(xml: str) -> ET.Element:
    return ET.fromstring(xml)


# ── nfo_text ─────────────────────────────────────────────────────────────

class TestNfoText:

    def test_tag_with_value_returns_stripped(self):
        root = _root("<movie><title>  Hello World  </title></movie>")
        assert nfo_text(root, "title") == "Hello World"


# ── nfo_first_text ───────────────────────────────────────────────────────

class TestNfoFirstText:

    def test_first_blank_second_has_value_returns_second(self):
        root = _root("<movie><num>   </num><id>REAL-001</id></movie>")
        assert nfo_first_text(root, ("num", "id")) == "REAL-001"


# ── nfo_actor_names ──────────────────────────────────────────────────────

class TestNfoActorNames:
    def test_nested_actors_element_any_depth(self):
        root = _root(
            "<movie><actors><actor><name>Actor1</name></actor>"
            "<actor><name>Actor2</name></actor></actors></movie>"
        )
        assert nfo_actor_names(root) == ["Actor1", "Actor2"]

    def test_flat_actor_element_openaver_native_shape(self):
        root = _root(
            "<movie><actor><name>Actor1</name></actor>"
            "<actor><name>Actor2</name></actor></movie>"
        )
        assert nfo_actor_names(root) == ["Actor1", "Actor2"]


# ── nfo_merged_tags ──────────────────────────────────────────────────────

class TestNfoMergedTags:
    def test_genre_first_then_tag_order_preserved(self):
        root = _root(
            "<movie><genre>G1</genre><tag>T1</tag></movie>"
        )
        assert nfo_merged_tags(root) == ["G1", "T1"]


# ── nfo_series_name ──────────────────────────────────────────────────────

class TestNfoSeriesName:
    def test_set_with_name_returns_name(self):
        root = _root("<movie><set><name>X</name></set></movie>")
        assert nfo_series_name(root) == "X"


# ── nfo_runtime_minutes ──────────────────────────────────────────────────

class TestNfoRuntimeMinutes:
    def test_valid_integer_returns_int(self):
        root = _root("<movie><runtime>120</runtime></movie>")
        assert nfo_runtime_minutes(root) == 120


    def test_non_numeric_returns_none(self):
        root = _root("<movie><runtime>abc</runtime></movie>")
        assert nfo_runtime_minutes(root) is None


# ── nfo_title_record ─────────────────────────────────────────────────────

class TestNfoTitleRecord:
    def test_both_present_returns_tuple(self):
        root = _root(
            "<movie><openaver_title_record>"
            "<written>ABC-123-片名-演員</written>"
            "<body>片名</body>"
            "</openaver_title_record></movie>"
        )
        assert nfo_title_record(root) == ("ABC-123-片名-演員", "片名")


