"""core/path_translate 單元測試（168a-T1b，CD-168a-1 oracle a–h）。期望值全為手寫字面。"""
import dataclasses
import subprocess
import sys

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

    def test_boundary_reverse_direction(self):
        pmap = _pmap(("/volume1/av", "D:" + "\\" + "AV"))
        assert _is_uncovered(to_server("D:" + "\\" + "AVX" + "\\" + "x", pmap))


class TestCase:
    def test_windows_prefix_matches_case_insensitively(self):
        """(c1) Windows 風格前綴不分大小寫，剩餘大小寫保留。"""
        pmap = _pmap(("/volume1/av", "D:" + "\\" + "AV"))
        r = to_server("d:" + "\\" + "av" + "\\" + "X.MP4", pmap)
        assert r == Mapped("/volume1/av/X.MP4", 0)

    def test_unix_prefix_is_case_sensitive(self):
        """(c2) Unix 風格前綴大小寫敏感。"""
        pmap = _pmap(("/volume1/AV", UNC_AV))
        assert _is_uncovered(to_local("/volume1/av/x", pmap))


class TestSeparator:
    def test_dest_windows_uses_backslash(self):
        """(d) 目的為 UNC -> 全反斜線。"""
        pmap = _pmap(("/volume1/av", UNC_AV))
        assert to_local("/volume1/av/a/b.mkv", pmap).path == r"\\nas\av\a\b.mkv"

    def test_dest_unix_uses_slash(self):
        """(d) 目的為 /Volumes/av -> 全正斜線。"""
        pmap = _pmap(("/volume1/av", "/Volumes/av"))
        assert to_local("/volume1/av/a/b.mkv", pmap).path == "/Volumes/av/a/b.mkv"


class TestReverse:
    def test_reverse_unmatched_local_path_is_uncovered(self):
        """(f) 本機路徑不在任何規則下 -> Uncovered。"""
        pmap = _pmap(("/volume1/av", UNC_AV))
        assert _is_uncovered(to_server("D:" + "\\" + "Downloads" + "\\" + "x", pmap))

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

    def test_input_equal_to_prefix(self):
        """(h) 輸入恰等於前綴 -> 目的前綴；輸入尾分隔符不影響。"""
        pmap = _pmap(("/volume1/av/", UNC_AV + "\\"))
        assert to_local("/volume1/av", pmap) == Mapped(UNC_AV, 0)
        assert to_local("/volume1/av/x/", pmap) == Mapped(UNC_AV + "\\x", 0)

    def test_unix_root_prefix(self):
        """(h) Unix 根前綴 / 以 / 連接。"""
        pmap = _pmap(("/", "D:" + "\\" + "root"))
        assert to_local("/a/b", pmap).path == "D:" + "\\" + "root" + "\\" + "a" + "\\" + "b"
        pmap2 = _pmap(("/volume1", "/"))
        assert to_local("/volume1/a", pmap2).path == "/a"
        assert to_local("/volume1", pmap2).path == "/"

    def test_drive_root_prefix(self):
        """(h) 磁碟機根 D:\\ 保留根分隔符。"""
        pmap = _pmap(("/volume1/av", "D:" + "\\"))
        assert to_local("/volume1/av/x.mp4", pmap).path == "D:" + "\\" + "x.mp4"
        assert to_local("/volume1/av", pmap).path == "D:" + "\\"

    def test_non_string_or_empty_input_uncovered(self):
        pmap = _pmap(("/volume1/av", UNC_AV))
        assert _is_uncovered(to_local("", pmap))
        assert _is_uncovered(to_local(None, pmap))


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
            ("/media/a/B.mkv", ("/media", "/Volumes/m")),
            ("/volume1/av/z", ("/volume1/av", "D:" + "\\" + "AV")),
        ],
    )
    def test_round_trip(self, x, rule):
        """I1：to_server(to_local(x).path) == x（x 為字面）。"""
        pmap = _pmap(rule)
        local = to_local(x, pmap)
        assert isinstance(local, Mapped)
        assert to_server(local.path, pmap) == Mapped(x, 0)


class TestTypes:
    def test_uncovered_not_str_and_frozen(self):
        u = Uncovered()
        assert not isinstance(u, str)
        with pytest.raises(dataclasses.FrozenInstanceError):
            u.x = 1

class TestFromRules:
    def test_incomplete_rules_skipped_with_warning(self, caplog):
        rules = [
            {"server": "/a"},
            {"local": "/b"},
            {"server": "", "local": "/c"},
            {"server": 1, "local": "/d"},
            "junk",
            {"server": "/volume1/av", "local": UNC_AV},
        ]
        with caplog.at_level("WARNING"):
            pmap = PathMap.from_rules(rules)
        assert pmap.rules == (("/volume1/av", UNC_AV),)
        assert any(rec.levelname == "WARNING" for rec in caplog.records)
        assert to_local("/volume1/av/x", pmap) == Mapped(r"\\nas\av\x", 0)


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


def test_strip_wrapping_quotes_unpaired_untouched():
    assert strip_wrapping_quotes('"' + r'D:\a') == '"' + r'D:\a'
    assert strip_wrapping_quotes(r'D:\a' + '"') == r'D:\a' + '"'
    assert strip_wrapping_quotes('"') == '"'


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


class TestPurity:
    def test_import_does_not_pull_database_or_webview(self):
        code = (
            "import sys, core.path_translate; "
            "assert 'core.database' not in sys.modules; "
            "assert 'webview' not in sys.modules"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
