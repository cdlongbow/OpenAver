"""core/path_translate 單元測試（168a-T1b，CD-168a-1 oracle a–h）。期望值全為手寫字面。"""

import pytest

from core.path_translate import Mapped, PathMap, Uncovered, strip_wrapping_quotes, to_local, to_server
from core.path_utils import file_uri_to_server_path

UNC_AV = r"\\nas\av"


def _pmap(*pairs):
    return PathMap.from_rules([{"server": s, "local": l} for s, l in pairs])


def _is_uncovered(r):
    return isinstance(r, Uncovered) and not isinstance(r, str)


class TestLongestPrefix:
    def test_longest_prefix_wins(self):
        """(a) 較長前綴勝出，即使短規則排在表中較前面。"""
        pmap = _pmap(("/volume1/av", UNC_AV), ("/volume1/av/jav", r"\\nas\jav"))
        r = to_local("/volume1/av/jav/x.mp4", pmap)
        assert r == Mapped(r"\\nas\jav\x.mp4", 1)

class TestBoundary:
    def test_prefix_boundary_is_enforced(self):
        """(b) /volume1/avx 不是 /volume1/av 的子路徑。"""
        pmap = _pmap(("/volume1/av", UNC_AV))
        assert _is_uncovered(to_local("/volume1/avx/x.mp4", pmap))


class TestSeparator:
    def test_dest_windows_uses_backslash(self):
        """(d) 目的為 UNC -> 全反斜線。"""
        pmap = _pmap(("/volume1/av", UNC_AV))
        assert to_local("/volume1/av/a/b.mkv", pmap).path == r"\\nas\av\a\b.mkv"


class TestReverse:

    def test_reverse_unc_case_insensitive(self):
        """(f) \\\\NAS\\AV 命中。"""
        pmap = _pmap(("/volume1/av", UNC_AV))
        r = to_server(r"\\NAS\AV\a\b.mkv", pmap)
        assert r == Mapped("/volume1/av/a/b.mkv", 0)


class TestEmptyAndEdges:
    def test_empty_map_is_uncovered(self):
        """(g) 空表一律 Uncovered，不回原字串。"""
        pmap = PathMap.from_rules([])
        assert _is_uncovered(to_local("/volume1/av/x", pmap))
        assert _is_uncovered(to_server("D:" + "\\" + "x", pmap))


class TestUriMerge:
    def test_four_slash_uri_to_local(self):
        """(e) file:////volume1/av/x.mp4 經 T1a 還原後可被 to_local 命中。"""
        server_path = file_uri_to_server_path("file:////volume1/av/x.mp4")
        pmap = _pmap(("/volume1/av", UNC_AV))
        assert to_local(server_path, pmap) == Mapped(r"\\nas\av\x.mp4", 0)


class TestRoundTrip:
    @pytest.mark.parametrize(
        "x,rule",
        [
            ("/volume1/av/jav/x.mp4", ("/volume1/av", UNC_AV)),
        ],
    )
    def test_round_trip(self, x, rule):
        """I1：to_server(to_local(x).path) == x（x 為字面）。"""
        pmap = _pmap(rule)
        local = to_local(x, pmap)
        assert isinstance(local, Mapped)
        assert to_server(local.path, pmap) == Mapped(x, 0)


# 與 connect-rows-logic.test.mjs 的 STRIP_TABLE 同表（輸入 → 輸出逐字相同）
STRIP_TABLE = [
    ('"' + r'\\nas\av' + '"', r'\\nas\av'),
    ('  "' + r'D:\av' + '"  ', r'D:\av'),
    ('  ' + r'D:\av' + '  ', r'D:\av'),
    ('"' + r'D:\av', '"' + r'D:\av'),
    (r'D:\av' + '"', r'D:\av' + '"'),
    ('"', '"'),
    ('"' + r'D:\a' + '"v"', r'D:\a' + '"v'),
    ('""', ''),
    ('" ' + r'D:\av' + ' "', r'D:\av'),
]


def test_strip_wrapping_quotes_table():
    for raw, want in STRIP_TABLE:
        assert strip_wrapping_quotes(raw) == want, raw


def test_from_rules_quoted_local_translates_same_as_bare(caplog):
    quoted = PathMap.from_rules([{"server": "/mnt/av", "local": '"' + UNC_AV + '"'}])
    bare = PathMap.from_rules([{"server": "/mnt/av", "local": UNC_AV}])
    got = to_local("/mnt/av/日本/a.mp4", quoted)
    assert got == to_local("/mnt/av/日本/a.mp4", bare)
    assert got == Mapped(r"\\nas\av\日本\a.mp4", 0)
    back = to_server(r"\\nas\av\日本\a.mp4", quoted)
    assert back == to_server(r"\\nas\av\日本\a.mp4", bare)
    assert back == Mapped("/mnt/av/日本/a.mp4", 0)
    with caplog.at_level("WARNING"):
        empty = PathMap.from_rules([{"server": "/mnt/av", "local": '""'}])
    assert empty.rules == ()
    assert any(rec.levelname == "WARNING" for rec in caplog.records)


