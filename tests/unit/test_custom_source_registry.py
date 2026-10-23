"""自訂來源登錄：逐檔隔離載入、檔案過濾、唯讀目錄語意、scraper_factories。"""

import shutil

import pytest

from core.custom_source import errors
from core.custom_source.registry import find_path, load_all, load_one
from tests.unit._custom_source_pages import FIXTURE_DIR

GOOD = ["single-og", "single-og-min", "two-step", "fuzzy", "text"]
SOG_TEXT = (FIXTURE_DIR / "single-og.yaml").read_text(encoding="utf-8")


def _put_good(directory, names=GOOD):
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy(FIXTURE_DIR / f"{name}.yaml", directory / f"{name}.yaml")


def _bad_files():
    """七份壞檔，各是不同的輸入。"""
    return {
        "bad-syntax.yaml": ("id: [unclosed", "yaml_syntax"),
        "bad-unknown.yaml": (SOG_TEXT.replace("id: single-og", "id: bad-unknown") + "censored: true\n", "unknown_key"),
        "bad-tag.yaml": ("id: !!python/object/apply:os.system [x]\n", "unsafe_tag"),
        "bad-alias.yaml": ("x: &a 1\ny: *a\n", "alias"),
        "bad-large.yaml": (SOG_TEXT.replace("id: single-og", "id: bad-large") + "# " + "a" * 65600 + "\n", "too_large"),
        "bad-binary.yaml": (bytes([0xFF, 0xFE, 0x00, 0x80]), "yaml_syntax"),
        "bad-mismatch.yaml": (SOG_TEXT, "id_filename_mismatch"),
    }


def _put_bad(directory):
    for name, (content, _reason) in _bad_files().items():
        path = directory / name
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def test_isolation_oracle_five_good_seven_bad(tmp_path):
    mixed, only_good = tmp_path / "mixed", tmp_path / "good"
    _put_good(mixed)
    _put_bad(mixed)
    _put_good(only_good)
    got = {s.id: s for s in load_all(mixed)}
    assert len(got) == 12
    for stem, (_c, reason) in _bad_files().items():
        item = got[stem[:-5]]
        assert item.spec is None and item.error.reason == reason
        assert item.error.reason in errors.LOAD_REASONS
    good = [s for s in load_all(mixed) if s.spec is not None]
    assert all(s.error is None for s in good)
    assert [s.spec for s in good] == [s.spec for s in load_all(only_good)]
    assert sorted(s.id for s in good) == sorted(GOOD)


def test_file_filter_keeps_only_plain_lowercase_yaml_files(tmp_path):
    _put_good(tmp_path, ["single-og"])
    shutil.copy(FIXTURE_DIR / "text.yaml", tmp_path / "text.yml")
    for name in ("UP.YAML", ".hidden.yaml", "._mac.yaml", "notes.txt"):
        (tmp_path / name).write_text(SOG_TEXT, encoding="utf-8")
    (tmp_path / "Bad_Name.yaml").write_text(SOG_TEXT, encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "fuzzy.yaml").write_text(SOG_TEXT, encoding="utf-8")
    (tmp_path / "d.yaml").mkdir()
    try:
        (tmp_path / "link.yaml").symlink_to(tmp_path / "single-og.yaml")
    except (OSError, NotImplementedError):
        pytest.skip("symlink not supported")
    got = load_all(tmp_path)
    assert [s.id for s in got] == ["Bad_Name", "single-og", "text"]
    assert got[0].spec is None and got[0].error.reason in errors.LOAD_REASONS
    assert got[2].spec is not None


def test_find_path_rejects_ids_that_are_not_slugs(tmp_path):
    outside = tmp_path / "outside.yaml"
    outside.write_text(SOG_TEXT, encoding="utf-8")
    target = tmp_path / "dir"
    _put_good(target, ["single-og"])
    (target / "Bad_Name.yaml").write_text(SOG_TEXT, encoding="utf-8")
    for bad in ("../outside", "A_b", "Bad_Name", "single-og\n", ""):
        assert find_path(bad, target) is None, bad
        assert load_one(bad, target) is None, bad
