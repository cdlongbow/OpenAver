"""175b-T7：DMM 女優只留主名（去結尾全形括號舊名）。合成資料，不連外。"""
import pytest

from core.scrapers.dmm import _actress_main_name


@pytest.mark.parametrize("raw, expected", [
    ("あかね麗（二階堂麗）", "あかね麗"),
    ("（二階堂麗）", "（二階堂麗）"),
])
def test_actress_main_name_table(raw, expected):
    assert _actress_main_name(raw) == expected
