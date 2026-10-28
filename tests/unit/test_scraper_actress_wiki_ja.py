import pytest
from core.scrapers.actress.wiki_ja import _commons_thumb_to_raw, _split_alias_text


@pytest.mark.parametrize("raw_url,expected", [
    # 舊形狀（upload host，scheme-relative）—— 驗收 2
    # 新形狀（thumb host，帶 query string）—— 驗收 1
    (
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/85/Foo.jpg/250px-Foo.jpg?utm_source=ja.wikipedia.org",
        "https://upload.wikimedia.org/wikipedia/commons/8/85/Foo.jpg",
    ),
    # 新形狀（thumb host，scheme-relative，無 query）—— 驗收 1 的另一種輸入形狀
])
def test_commons_thumb_to_raw_matches(raw_url, expected):
    assert _commons_thumb_to_raw(raw_url) == expected




@pytest.mark.parametrize("text,expected", [
    # 多名字 + 殘留註腳 → 乾淨 list
    ("花沢 ひまり、川口 彩夏[ 要出典 ]", ["花沢 ひまり", "川口 彩夏"]),
    # 合法單名（含半形空白）不被誤切
    ("花沢 ひまり", ["花沢 ひまり"]),
])
def test_split_alias_text(text, expected):
    assert _split_alias_text(text) == expected
