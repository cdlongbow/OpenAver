"""自訂來源 schema：載入即驗證，要嘛得到不可變 Spec，要嘛得到指出欄位與類別的 LoadError。"""

import pytest

from core.custom_source.errors import LOAD_REASONS, LoadError

from core.custom_source.schema import load_file, load_text, load_uploaded


BASE = """\
id: base
name: Base
fetch: plain
number_pattern: 'ABC-\\d+'
steps:
  - url: "https://base.example/{number_lower}"
fields:
  title: {css: "h1"}
tests:
  - number: ABC-123
    expect: {title: "x", tags_max: 3}
  - number: ABC-999
    status: not_found
"""


NF_CASE = "  - number: ABC-999\n    status: not_found\n"


def sub(base, old, new):
    assert base.count(old) == 1, old
    return base.replace(old, new)


def rows():
    """(格名, 輸入文字, filename_stem, 預期 reason, 預期 field_path)；每格輸入各異。"""
    r = []

    def add(name, text, reason, path, stem=None):
        r.append((name, text, stem or ("two" if text.startswith("id: two") else "base"), reason, path))

    # YAML 層級
    add("alias", sub(BASE, "fields:\n  title: {css: \"h1\"}",
                     "fields:\n  title: &a {css: \"h1\"}\n  cover: *a"), "alias", "")
    add("too_large", BASE + "# " + "a" * 70000 + "\n", "too_large", "")
    # unknown_key
    # id / fetch
    # pattern / template / selector / transform
    add("pattern_too_long", sub(BASE, "'ABC-\\d+'", "'" + "a" * 201 + "'"), "bad_pattern", "number_pattern")
    add("tpl_in_host", sub(BASE, "base.example/{number_lower}", "{number}.example/x"), "bad_template", "steps[0].url")
    add("tpl_ipv4", sub(BASE, "https://base.example/", "http://10.0.0.5/"), "bad_template", "steps[0].url")
    # AC-4 負向
    # CD-165-9：至少一案查無
    # bad_value：結構與值域
    add("negative_only_in_not_found", sub(BASE, ", tags_max: 3", "") + "  - number: ABC-456\n    status: not_found\n    expect: {tags_max: 0}\n",
        "missing_negative_assert", "tests")
    return r


REJECTIONS = rows()


@pytest.mark.parametrize("name,text,stem,reason,path", REJECTIONS, ids=[r[0] for r in REJECTIONS])
def test_rejection_table(name, text, stem, reason, path):
    with pytest.raises(LoadError) as ei:
        load_text(text, stem)
    assert (ei.value.reason, ei.value.field_path) == (reason, path)
    assert reason in LOAD_REASONS


def test_bom_and_crlf_file_loads(tmp_path):
    p = tmp_path / "base.yaml"
    p.write_bytes(b"\xef\xbb\xbf" + BASE.replace("\n", "\r\n").encode("utf-8"))
    assert load_file(p).id == "base"


def test_unsafe_tag_not_executed(tmp_path):
    sentinel = tmp_path / "sentinel"
    text = f'id: !!python/object/apply:os.system ["touch {sentinel}"]\n'
    with pytest.raises(LoadError) as ei:
        load_text(text, "base")
    assert ei.value.reason == "unsafe_tag"
    assert not sentinel.exists()


@pytest.mark.parametrize("text", [
    sub(BASE, NF_CASE, "  - number: ABC-456\n    status: multiple\n    expect: {title: \"y\"}\n"),
], ids=["ok_plus_multiple"])
def test_not_found_case_required(text):
    with pytest.raises(LoadError) as ei:
        load_text(text, "base")
    assert (ei.value.reason, ei.value.field_path) == ("missing_not_found_case", "tests")


@pytest.mark.parametrize("bad_id, reason", [
    ("../x", "bad_id"), ('"a\\n"', "bad_id"),
])
def test_load_uploaded_rejects_untrusted_id(bad_id, reason):
    with pytest.raises(LoadError) as ei:
        load_uploaded(sub(BASE, "id: base", f"id: {bad_id}"))
    assert ei.value.reason == reason


# ---- T15：number_pattern 選填（缺席或 null＝任何非空番號都接受）
NO_PATTERN = sub(BASE, "number_pattern: 'ABC-\\d+'\n", "")


@pytest.mark.parametrize("text", [NO_PATTERN], ids=["absent"])
def test_number_pattern_optional(text):
    assert load_text(text, "base").number_pattern is None


