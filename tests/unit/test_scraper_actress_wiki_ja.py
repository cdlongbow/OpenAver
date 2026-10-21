import pytest
from core.scrapers.actress.wiki_ja import _commons_thumb_to_raw, _parse_wiki_ja_html


@pytest.mark.parametrize("raw_url,expected", [
    # 舊形狀（upload host，scheme-relative）—— 驗收 2
    (
        "//upload.wikimedia.org/wikipedia/commons/thumb/8/85/Foo.jpg/250px-Foo.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/8/85/Foo.jpg",
    ),
    # 新形狀（thumb host，帶 query string）—— 驗收 1
    (
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/85/Foo.jpg/250px-Foo.jpg?utm_source=ja.wikipedia.org",
        "https://upload.wikimedia.org/wikipedia/commons/8/85/Foo.jpg",
    ),
    # 新形狀（thumb host，scheme-relative，無 query）—— 驗收 1 的另一種輸入形狀
    (
        "//thumb.wikimedia.org/wikipedia/commons/thumb/c/c2/Bar.png/120px-Bar.png",
        "https://upload.wikimedia.org/wikipedia/commons/c/c2/Bar.png",
    ),
])
def test_commons_thumb_to_raw_matches(raw_url, expected):
    assert _commons_thumb_to_raw(raw_url) == expected


def test_commons_thumb_to_raw_fail_open_on_unmatched():
    # 驗收 3：不匹配任何已知形狀 → 原樣回傳
    unmatched = "https://example.com/not-a-wikimedia-url.jpg"
    assert _commons_thumb_to_raw(unmatched) == unmatched


# ---------------------------------------------------------------------------
# 身高／三圍小數捨去（174-T1）——只餵合成的維基 infobox 片段
# ---------------------------------------------------------------------------

def _infobox(rows):
    """rows: [(label, value), ...] -> infobox HTML。固定多帶一列生年月日，
    否則沒有任何有意義欄位時 _parse_wiki_ja_html 會回 None。"""
    body = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
    body += "<tr><th>生年月日</th><td>1999年11月30日</td></tr>"
    return f'<table class="infobox">{body}</table>'


def _parse(rows):
    return _parse_wiki_ja_html(_infobox(rows), "テスト")


@pytest.mark.parametrize("value", [
    "158.5 cm / ― kg",
    "158.5cm",
    "5 ft 2.5 in (158.5 cm)",
])
def test_height_decimal_truncated(value):
    result = _parse([("身長 / 体重", value)])
    assert result["height"] == "158cm"


@pytest.mark.parametrize("value", [
    "86.5 - 55 - 86 cm",
    "86.5 - 55.5 - 86.5 cm",
])
def test_threesize_decimal_truncated(value):
    result = _parse([("スリーサイズ", value)])
    assert result["bust"] == "86cm"
    assert result["waist"] == "55cm"
    assert result["hip"] == "86cm"


def test_height_integer_unchanged():
    result = _parse([("身長 / 体重", "157 cm / 45 kg")])
    assert result["height"] == "157cm"


def test_threesize_integer_unchanged():
    result = _parse([("スリーサイズ", "80 - 58 - 83 cm")])
    assert (result["bust"], result["waist"], result["hip"]) == ("80cm", "58cm", "83cm")


def test_threesize_en_dash_integer_still_parsed():
    # U+2013 en dash 分隔：守住分隔符字元類沒被改窄
    result = _parse([("スリーサイズ", "80 \u2013 58 \u2013 83 cm")])
    assert (result["bust"], result["waist"], result["hip"]) == ("80cm", "58cm", "83cm")


def test_threesize_inch_row_before_cm_row_ignored():
    result = _parse([
        ("スリーサイズ", "34 - 22 - 33 in"),
        ("スリーサイズ", "80 - 58 - 83 cm"),
    ])
    assert (result["bust"], result["waist"], result["hip"]) == ("80cm", "58cm", "83cm")


def test_threesize_inch_row_after_cm_row_ignored():
    result = _parse([
        ("スリーサイズ", "80 - 58 - 83 cm"),
        ("スリーサイズ", "31.5 - 22.8 - 32.7 in"),
    ])
    assert (result["bust"], result["waist"], result["hip"]) == ("80cm", "58cm", "83cm")
