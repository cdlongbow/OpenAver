"""自訂來源 T4：五種變換與欄位型別層（純函式、全離線）。"""
import re

import pytest

from core.custom_source import schema
from core.custom_source.extract import extract_fields
from core.custom_source.transforms import apply_transforms
from tests.unit._custom_source_pages import FIXTURE_DIR, PAGES

BASE = "https://site.example/a/b/page.html"


def T(name, arg=True):
    return schema.Transform(name, arg)


def F(name, kind, selector, attr=None, all=False, then=()):
    return schema.Field(name, kind, selector, attr, all, tuple(then))


def run(html, *fields, base=BASE):
    return extract_fields(html, base, tuple(fields))


@pytest.mark.parametrize("values,transforms,expected", [
    (["SONE-205 標題"], [T("regex", r"^(\S+)")], ["SONE-205"]),
    (["a, b ,, c"], [T("split", ",")], ["a", "b", "c"]),
    (["120", "abc", "nan", "inf"], [T("div", 60)], ["2"]),
])
def test_transform_table(values, transforms, expected):
    assert apply_transforms(values, tuple(transforms), BASE) == expected


@pytest.mark.parametrize("raw,expected", [
    ("2024/5/1", "2024-05-01"),
    ("2024年5月1日", "2024-05-01"),
    ("2024-05-01T00:30:00+09:00", "2024-05-01"),
])
def test_date_shapes(raw, expected):
    html = f'<meta name="d" content="{raw}">'
    assert run(html, F("date", "meta", "d"))["date"] == expected


@pytest.mark.parametrize("raw", [
    "2024-02-30",
])
def test_date_unparsable_is_empty(raw):
    html = f'<meta name="d" content="{raw}">'
    assert run(html, F("date", "meta", "d"))["date"] == ""


@pytest.mark.parametrize("raw,expected", [
    ("約 120.5 分", 121),
])
def test_duration(raw, expected):
    html = f'<meta name="m" content="{raw}">'
    assert run(html, F("duration", "meta", "m"))["duration"] == expected


def test_non_http_urls_dropped():
    html = ('<div><a href="javascript:void(0)">1</a><a href="data:image/png;base64,AA">2</a>'
            '<a href="/ok1.jpg">3</a><a href="mailto:a@b.c">4</a><a href="ftp://x.example/f.jpg">6</a><a href="file://host/f.jpg">7</a><a href="https://x.example/ok2.jpg">5</a></div>')
    out = run(html, F("sample_images", "css", "a", attr="href", all=True))
    assert out["sample_images"] == ["https://site.example/ok1.jpg", "https://x.example/ok2.jpg"]


def test_relative_urls_joined_to_final_url():
    html = '<img class="c" src="/img/a.jpg"><i class="p" data-s="//cdn.example/p.jpg">'
    out = run(html, F("cover", "css", "img.c", attr="src"))
    assert out["cover"] == "https://site.example/img/a.jpg"
    out = run(html, F("cover", "css", "i.p", attr="data-s"))
    assert out["cover"] == "https://cdn.example/p.jpg"


@pytest.mark.parametrize("page", ["<html><body></body></html>"])
def test_garbage_page_gives_empty_shape(page):
    fields = (F("title", "css", "h1"), F("date", "meta", "d"), F("duration", "css", ".x"),
              F("tags", "css", ".t", all=True), F("cover", "jsonld", "A.b"))
    assert extract_fields(page, BASE, fields) == {
        "title": "", "date": "", "duration": None, "tags": [], "cover": ""}


@pytest.mark.parametrize("spec_id,page", [
    ("single-og", "single-og"),
    ("two-step", "two-step-detail-a"),
])
def test_fixtures_shapes(spec_id, page):
    spec = schema.load_file(FIXTURE_DIR / f"{spec_id}.yaml")
    html = PAGES[page]
    out = extract_fields(html, f"https://{spec_id}.example/x", spec.fields)
    assert set(out) == {f.name for f in spec.fields}
    assert out["cover"].startswith("http")
    assert out["tags"] and all(isinstance(t, str) and t for t in out["tags"])
    if "date" in out:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", out["date"])
    if spec_id == "single-og":
        assert out["duration"] == 149  # div: 60 對 8967 秒有作用（唯一站方值相等格）
        assert isinstance(out["duration"], int)


