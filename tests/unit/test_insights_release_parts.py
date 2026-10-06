import pytest
from web.routers.insights import _release_parts

TABLE = [
    ("2015", 2015),
    ("2015-03", 2015),
    ("2015-03-09", 2015),
    ("2015-13-01", 2015),
    ("20150301", 2015),
    ("1900", 1900),
    ("2100", 2100),
    ("1899", None),
    ("2200", None),
    ("abcd", None),
    ("", None),
    (None, None),
]


@pytest.mark.parametrize("raw,expected_year", TABLE)
def test_release_parts_year_table(raw, expected_year):
    year, month, _date = _release_parts(raw)
    assert year == expected_year
    if raw == "2015-13-01":
        assert month is None
