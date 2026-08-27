"""_parse_rating_votes：評分字串 → (rating, votes) 純函式測試。

只餵字串，不餵 HTML、不 import BeautifulSoup。
"""
from core.scrapers.javdb import _parse_rating_votes


def test_rating_and_votes_both_parsed():
    """完整形狀：分數與人數都抽得到。"""
    assert _parse_rating_votes("4.58分, 由48人評價") == (4.58, 48)


def test_rating_only_no_votes():
    """只有分數、沒有人數 → votes 為 None。"""
    assert _parse_rating_votes("4.13分") == (4.13, None)


def test_empty_string():
    """空字串 → (None, None)。"""
    assert _parse_rating_votes("") == (None, None)


def test_votes_only_no_rating():
    """只有人數、沒有分數 → rating 為 None。"""
    assert _parse_rating_votes("由48人評價") == (None, 48)


def test_dash_no_throw():
    """「—」→ (None, None)，不得拋。"""
    assert _parse_rating_votes("—") == (None, None)
