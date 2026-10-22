"""自訂來源：hosts 基底規則（detail_host_allowed）、模板 www 載入、public_url（純函式，全離線）。"""

import dataclasses

import pytest

from core.custom_source import schema
from core.custom_source.schema import detail_host_allowed
from core.custom_source.urls import public_url
from tests.unit._custom_source_pages import FIXTURE_DIR


def _spec_with_base(base):
    spec = schema.load_file(FIXTURE_DIR / "single-og.yaml")
    return dataclasses.replace(spec, hosts=(base,))


@pytest.mark.parametrize("base, url, allowed", [
    ("a.example", "https://video.a.example/x", True),
    ("a.example", "https://nota.example/x", False),
])
def test_host_rule_table(base, url, allowed):
    assert detail_host_allowed(_spec_with_base(base), url) is allowed


@pytest.mark.parametrize("url, expected", [
    ("https://u:p@x.example/a?id=1", "https://x.example/a?id=1"),
    ("https://x.example/a?mail=a@b", "https://x.example/a?mail=a@b"),
])
def test_public_url_table(url, expected):
    assert public_url(url) == expected
