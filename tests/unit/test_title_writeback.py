"""TASK-172-T1 — core.title_writeback.rewrite_nfo_titles 單元測試。"""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core.title_writeback import (
    NfoNotFoundError,
    NfoParseError,
    rewrite_nfo_titles,
)

DEF = "[{num}]{title}"
NON = "{num} {title} - {actor}"
TITLE_TAGS = {"title", "originaltitle", "sorttitle", "openaver_title_record"}

NFO_FULL = """<?xml version="1.0" encoding="utf-8"?>
<movie>
  <title>[ABC-123]原標題</title>
  <originaltitle>原文</originaltitle>
  <sorttitle>[ABC-123]原標題</sorttitle>
  <plot>簡介 &amp; 內容</plot>
  <rating>7.5</rating>
  <num>ABC-123</num>
  <release>2024-05-06</release>
  <website>http://x/?a=1&amp;b=2</website>
  <poster>ABC-123-poster.jpg</poster>
  <uniqueid type="home" default="true">ABC-123</uniqueid>
  <actor><name>女優A</name></actor>
  <actor><name>女優B</name></actor>
  <genre>g1</genre>
  <genre>g2</genre>
  <openaver_title_record>
    <written>OLD</written>
    <body>OLDBODY</body>
  </openaver_title_record>
</movie>
"""

NFO_MIN = """<?xml version="1.0" encoding="utf-8"?>
<movie>
  <title>[ABC-123]原標題</title>
  <plot>p</plot>
</movie>
"""


def _write(tmp_path: Path, text: str, name="ABC-123.nfo") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _call(p, **over):
    kw = dict(
        number="ABC-123", title_body="譯文", original_title="原文",
        actors=["女優A", "女優B"], maker="片商", date="2024-05-06",
        nfo_title_format=DEF,
    )
    kw.update(over)
    return rewrite_nfo_titles(str(p), **kw)


def _canon(e):
    return (
        e.tag,
        (e.text or "").strip(),
        tuple(sorted(e.attrib.items())),
        tuple(_canon(c) for c in e),
    )


def _text(root, tag):
    e = root.find(tag)
    return None if e is None else (e.text or "")


def test_other_elements_unchanged(tmp_path):
    p = _write(tmp_path, NFO_FULL)
    before = ET.fromstring(NFO_FULL.encode("utf-8"))
    _call(p)
    after = ET.parse(p).getroot()
    b = [_canon(c) for c in before if c.tag not in TITLE_TAGS]
    a = [_canon(c) for c in after if c.tag not in TITLE_TAGS]
    assert b and b == a
    tags = {c.tag for c in after}
    for t in ("plot", "rating", "website", "poster", "uniqueid", "actor", "genre", "num", "release"):
        assert t in tags


def test_rewrite_title_default_format(tmp_path):
    p = _write(tmp_path, NFO_FULL)
    _call(p)
    root = ET.parse(p).getroot()
    assert _text(root, "title") == "[ABC-123]譯文"
    assert _text(root, "originaltitle") == "原文"


def test_originaltitle_written_and_inserted_when_absent(tmp_path):
    p = _write(tmp_path, NFO_MIN)
    assert "<originaltitle" not in NFO_MIN
    _call(p, original_title="日文原題")
    root = ET.parse(p).getroot()
    assert _text(root, "originaltitle") == "日文原題"
    tags = [c.tag for c in root]
    assert tags.index("originaltitle") == tags.index("title") + 1


def test_empty_original_title_writes_empty_element(tmp_path):
    p = _write(tmp_path, NFO_MIN)
    _call(p, original_title="")
    root = ET.parse(p).getroot()
    assert root.find("originaltitle") is not None
    assert (root.find("originaltitle").text or "") == ""


def test_default_format_removes_existing_record(tmp_path):
    p = _write(tmp_path, NFO_FULL)
    _call(p, nfo_title_format=DEF)
    root = ET.parse(p).getroot()
    assert root.findall("openaver_title_record") == []


def test_non_default_format_single_record(tmp_path):
    p = _write(tmp_path, NFO_FULL)
    _call(p, nfo_title_format=NON)
    root = ET.parse(p).getroot()
    recs = root.findall("openaver_title_record")
    assert len(recs) == 1
    assert recs[0].find("written").text == _text(root, "title")
    assert _text(root, "title") == "ABC-123 譯文 - 女優A"
    assert recs[0].find("body").text == "譯文"


def test_existing_sorttitle_synced_and_absent_not_created(tmp_path):
    p = _write(tmp_path, NFO_FULL)
    _call(p)
    root = ET.parse(p).getroot()
    assert _text(root, "sorttitle") == _text(root, "title") == "[ABC-123]譯文"
    p2 = _write(tmp_path, NFO_MIN, name="B.nfo")
    assert "<sorttitle" not in NFO_MIN
    _call(p2)
    assert ET.parse(p2).getroot().find("sorttitle") is None


def test_bare_ampersand_nfo_is_rewritable(tmp_path):
    bad = NFO_MIN.replace("<plot>p</plot>", "<plot>A & B</plot>")
    p = _write(tmp_path, bad)
    _call(p)
    root = ET.fromstring(p.read_bytes())
    assert _text(root, "title") == "[ABC-123]譯文"
    assert _text(root, "plot") == "A & B"


def test_control_chars_stripped_output_parseable(tmp_path):
    p = _write(tmp_path, NFO_MIN)
    out = _call(p, title_body="譯\x07文", original_title="原\x07文")
    root = ET.fromstring(out)
    assert "\x07" not in (_text(root, "title") or "")
    assert _text(root, "originaltitle") == "原文"
    assert b"\x07" not in p.read_bytes()
    ET.fromstring(p.read_bytes())


def test_missing_nfo_raises_and_not_created(tmp_path):
    p = tmp_path / "none.nfo"
    with pytest.raises(NfoNotFoundError):
        _call(p)
    assert not p.exists()


def test_unparseable_xml_raises_and_file_unchanged(tmp_path):
    p = tmp_path / "bad.nfo"
    raw = b"<?xml version='1.0'?><movie><title>x</title><plot>"
    p.write_bytes(raw)
    with pytest.raises(NfoParseError):
        _call(p)
    assert p.read_bytes() == raw


def test_exceptions_distinguishable():
    assert not issubclass(NfoNotFoundError, NfoParseError)
    assert not issubclass(NfoParseError, NfoNotFoundError)
    assert not issubclass(NfoNotFoundError, OSError)
    assert not issubclass(NfoParseError, OSError)


def test_write_failure_propagates_oserror_unwrapped(tmp_path, monkeypatch):
    p = _write(tmp_path, NFO_MIN)

    def boom(self, data):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "write_bytes", boom)
    with pytest.raises(PermissionError):
        _call(p)


def test_read_failure_propagates_oserror_unwrapped(tmp_path, monkeypatch):
    p = _write(tmp_path, NFO_MIN)

    def boom(self):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(PermissionError):
        _call(p)


def test_rewrite_strips_num_prefix_from_title(tmp_path):
    for body in ("ABC-123 譯文", "[ABC-123]譯文"):
        p = _write(tmp_path, NFO_MIN)
        _call(p, title_body=body)
        title = _text(ET.parse(p).getroot(), "title")
        assert title == "[ABC-123]譯文"
        assert title.count("ABC-123") == 1


def test_empty_title_body_falls_back_to_original(tmp_path):
    p = _write(tmp_path, NFO_FULL)
    _call(p, title_body="", original_title="日文原題", nfo_title_format=NON)
    root = ET.parse(p).getroot()
    assert _text(root, "title") == "ABC-123 日文原題 - 女優A"
    assert root.find("openaver_title_record").find("body").text == "日文原題"


def test_returns_written_bytes(tmp_path):
    p = _write(tmp_path, NFO_MIN)
    out = _call(p)
    assert isinstance(out, bytes)
    assert out == p.read_bytes()


NFO_NO_NUM = """<?xml version="1.0" encoding="utf-8"?>
<movie>
  <title>舊標題</title>
  <plot>p</plot>
</movie>
"""


def test_missing_num_is_added_so_rescan_strips_prefix(tmp_path):
    from core.gallery_scanner import VideoScanner

    p = _write(tmp_path, NFO_NO_NUM)
    _call(p)
    root = ET.parse(p).getroot()
    assert _text(root, "num") == "ABC-123"
    info = VideoScanner().parse_nfo(str(p))
    assert info.title == "譯文"
    assert "[ABC-123]" not in info.title


def test_existing_id_does_not_gain_num(tmp_path):
    p = _write(tmp_path, NFO_NO_NUM.replace("<plot>", "<id>ABC-123</id>\n  <plot>"))
    _call(p)
    root = ET.parse(p).getroot()
    assert root.find("num") is None
    assert _text(root, "id") == "ABC-123"
