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
)


def _root(xml: str) -> ET.Element:
    return ET.fromstring(xml)


# ── nfo_text ─────────────────────────────────────────────────────────────

class TestNfoText:
    def test_tag_missing_returns_empty(self):
        root = _root("<movie></movie>")
        assert nfo_text(root, "title") == ""

    def test_tag_with_value_returns_stripped(self):
        root = _root("<movie><title>  Hello World  </title></movie>")
        assert nfo_text(root, "title") == "Hello World"

    def test_whitespace_only_returns_empty(self):
        root = _root("<movie><title>   </title></movie>")
        assert nfo_text(root, "title") == ""

    def test_cd_113a_7_nested_only_child_returns_empty(self):
        """<studio><name>X</name></studio> → '' (Element.text 只讀開始標籤到
        第一個子元素之間的文字，此處為 None)。"""
        root = _root("<movie><studio><name>X</name></studio></movie>")
        assert nfo_text(root, "studio") == ""

    def test_cd_113a_7_leading_text_before_nested_child_is_kept(self):
        """<studio>A<name>X</name>B</studio> → 'A'（只取開始標籤後、第一個
        子元素前的文字，尾隨的 'B' 不算 .text）。"""
        root = _root("<movie><studio>A<name>X</name>B</studio></movie>")
        assert nfo_text(root, "studio") == "A"

    def test_cd_113a_7_flat_tag_unaffected(self):
        """<label>Y</label>（無巢狀子元素）→ 'Y'，作為對照組確認扁平 tag 不受
        CD-113a-7 限制影響。"""
        root = _root("<movie><label>Y</label></movie>")
        assert nfo_text(root, "label") == "Y"


# ── nfo_first_text ───────────────────────────────────────────────────────

class TestNfoFirstText:
    def test_all_tags_missing_returns_empty(self):
        root = _root("<movie></movie>")
        assert nfo_first_text(root, ("num", "id")) == ""

    def test_first_blank_second_has_value_returns_second(self):
        root = _root("<movie><num>   </num><id>REAL-001</id></movie>")
        assert nfo_first_text(root, ("num", "id")) == "REAL-001"

    def test_first_has_value_returns_first_without_checking_rest(self):
        root = _root("<movie><num>ABC-123</num><id>SHOULD-NOT-BE-USED</id></movie>")
        assert nfo_first_text(root, ("num", "id")) == "ABC-123"


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

    def test_none_or_empty_text_node_is_filtered(self):
        root = _root(
            "<movie><actor><name/></actor>"
            "<actor><name></name></actor>"
            "<actor><name>Real</name></actor></movie>"
        )
        assert nfo_actor_names(root) == ["Real"]

    def test_whitespace_only_flat_actor_name_is_filtered(self):
        """TASK-113a-T4 (Codex PR review P1): a flat `<actor><name>   </name>
        </actor>` is whitespace-only, not data, and must not survive as
        `''`."""
        root = _root("<movie><actor><name>   </name></actor></movie>")
        assert nfo_actor_names(root) == []

    def test_whitespace_only_nested_actor_name_is_filtered(self):
        """TASK-113a-T4 (Codex PR review P1): same as the flat case but via
        the any-depth `<actors><actor><name>` shape — this is the exact
        regression Codex flagged (T1a made this silently non-empty)."""
        root = _root(
            "<movie><actors><actor><name>   </name></actor></actors></movie>"
        )
        assert nfo_actor_names(root) == []

    def test_mixed_real_and_whitespace_keeps_only_real(self):
        """TASK-113a-T4: a real name alongside a whitespace-only one keeps
        only the real value (no trailing blank entry)."""
        root = _root(
            "<movie><actor><name>A</name></actor>"
            "<actor><name>   </name></actor></movie>"
        )
        assert nfo_actor_names(root) == ["A"]


# ── nfo_merged_tags ──────────────────────────────────────────────────────

class TestNfoMergedTags:
    def test_genre_first_then_tag_order_preserved(self):
        root = _root(
            "<movie><genre>G1</genre><tag>T1</tag></movie>"
        )
        assert nfo_merged_tags(root) == ["G1", "T1"]

    def test_genre_genre_duplicate_dedup(self):
        root = _root(
            "<movie><genre>G1</genre><genre>G1</genre><genre>G2</genre></movie>"
        )
        assert nfo_merged_tags(root) == ["G1", "G2"]

    def test_genre_tag_cross_loop_duplicate_dedup(self):
        root = _root(
            "<movie><genre>G1</genre><tag>G1</tag><tag>T1</tag></movie>"
        )
        assert nfo_merged_tags(root) == ["G1", "T1"]

    def test_whitespace_only_genre_and_tag_filtered(self):
        """TASK-113a-T4 (Codex PR review P1): whitespace-only `<genre>` and
        `<tag>` values are not data and must not survive as `''`."""
        root = _root("<movie><genre>   </genre><tag>   </tag></movie>")
        assert nfo_merged_tags(root) == []

    def test_mixed_real_and_whitespace_genre_keeps_only_real(self):
        """TASK-113a-T4: a real genre alongside a whitespace-only genre keeps
        only the real value."""
        root = _root(
            "<movie><genre>  G1  </genre><genre>   </genre></movie>"
        )
        assert nfo_merged_tags(root) == ["G1"]


# ── nfo_series_name ──────────────────────────────────────────────────────

class TestNfoSeriesName:
    def test_set_with_name_returns_name(self):
        root = _root("<movie><set><name>X</name></set></movie>")
        assert nfo_series_name(root) == "X"

    def test_path_lookup_skips_set_without_name(self):
        root = _root(
            "<movie><set/><set><name>S2</name></set></movie>"
        )
        assert nfo_series_name(root) == "S2"

    def test_no_set_returns_empty(self):
        root = _root("<movie></movie>")
        assert nfo_series_name(root) == ""


# ── nfo_runtime_minutes ──────────────────────────────────────────────────

class TestNfoRuntimeMinutes:
    def test_valid_integer_returns_int(self):
        root = _root("<movie><runtime>120</runtime></movie>")
        assert nfo_runtime_minutes(root) == 120

    def test_negative_is_accepted(self):
        root = _root("<movie><runtime>-5</runtime></movie>")
        assert nfo_runtime_minutes(root) == -5

    def test_non_numeric_returns_none(self):
        root = _root("<movie><runtime>abc</runtime></movie>")
        assert nfo_runtime_minutes(root) is None

    def test_decimal_returns_none(self):
        root = _root("<movie><runtime>12.5</runtime></movie>")
        assert nfo_runtime_minutes(root) is None

    def test_empty_string_returns_none(self):
        root = _root("<movie><runtime></runtime></movie>")
        assert nfo_runtime_minutes(root) is None

    def test_tag_missing_returns_none(self):
        root = _root("<movie></movie>")
        assert nfo_runtime_minutes(root) is None
