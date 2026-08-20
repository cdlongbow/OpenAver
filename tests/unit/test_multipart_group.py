"""test_multipart_group.py — core/multipart_group.py 純邏輯測試（TASK-122-T2）。

涵蓋 plan-122.md §1.2 / TASK-122-T2.md 的 AC-1/2/3/15/16 + resolve_group_for_path
找不到回 None。不需要 DB：group_rows() 是純函式，用簡單 dataclass stub 或直接
Video ORM 建構子造資料即可。
"""
import pytest

from core.database import Video
from core.path_utils import to_file_uri, uri_to_local_fs_path
from core.multipart_group import (
    normalize_stem_key,
    group_key,
    part_number,
    part_token,
    VideoGroup,
    group_rows,
    resolve_group_for_path,
)


def _v(fs_path: str) -> Video:
    """建一個只帶 path 的 Video stub（group_rows 只需要 fs_path_of 能取路徑）。"""
    return Video(path=to_file_uri(fs_path))


def _fs_path_of(v: Video) -> str:
    return uri_to_local_fs_path(v.path, {})


def _uri_of(v: Video) -> str:
    return v.path


# ── AC-1：同資料夾同主幹合併 ────────────────────────────────────────────

class TestAC1SameFolderSameStemMerge:
    def test_two_parts_same_folder_merge_into_one_group(self):
        rows = [
            _v("/media/ABC-123-cd1.mp4"),
            _v("/media/ABC-123-cd2.mp4"),
        ]
        groups = group_rows(rows, _fs_path_of)
        assert len(groups) == 1
        g = groups[0]
        assert len(g.members) == 2
        assert g.part_tokens == ["cd1", "cd2"]
        # members 依 part_number 升冪排序，故 members[0] 是 part-1
        assert _fs_path_of(g.members[0]).endswith("cd1.mp4")
        assert _fs_path_of(g.members[1]).endswith("cd2.mp4")


# ── AC-2：token 不在尾端仍合併 ──────────────────────────────────────────

class TestAC2TokenNotAtEndStillMerges:
    def test_token_followed_by_bracket_suffix_still_merges(self):
        rows = [
            _v("/media/... vol．07 part1[HD].mp4"),
            _v("/media/... vol．07 part2[HD].mp4"),
        ]
        groups = group_rows(rows, _fs_path_of)
        assert len(groups) == 1
        g = groups[0]
        assert len(g.members) == 2
        assert g.part_tokens == ["part1", "part2"]


# ── AC-3：不同資料夾不合併 ──────────────────────────────────────────────

class TestAC3DifferentFolderNoMerge:
    def test_same_stem_different_folder_stays_separate(self):
        rows = [
            _v("/media/dirA/ABC-123-cd1.mp4"),
            _v("/media/dirB/ABC-123-cd2.mp4"),
        ]
        groups = group_rows(rows, _fs_path_of)
        assert len(groups) == 2
        for g in groups:
            assert len(g.members) == 1
            assert g.part_tokens == []


# ── AC-15：owner 真實樣本 PPX-008（見 TASK-122-T2.md 現況分析 §6）─────────

class TestAC15OwnerRealSamplePPX008:
    def test_ppx008_part1_part2_different_space_count_still_merge(self):
        # 兩者番號後空格數不同（'[PPX-008] 8時間' vs '[PPX-008]8時間'），
        # normalize_stem_key 的去空白+lower 要吃掉這個差異。
        rows = [
            _v(
                "/mnt/c/AVtest/涼森れむ - [プレステージ][PPX-008] "
                "8時間 BEST PRESTIGE PREMIUM EXCLUSIVE vol．07 part2[HD].mp4"
            ),
            _v(
                "/mnt/c/AVtest/涼森れむ - [プレステージ][PPX-008]"
                "8時間 BEST PRESTIGE PREMIUM EXCLUSIVE vol．07 part1[HD].mp4"
            ),
        ]
        groups = group_rows(rows, _fs_path_of)
        assert len(groups) == 1
        g = groups[0]
        assert len(g.members) == 2
        assert g.part_tokens == ["part1", "part2"]
        assert _fs_path_of(g.members[0]).endswith("part1[HD].mp4")
        assert _fs_path_of(g.members[1]).endswith("part2[HD].mp4")


# ── AC-16：CD-122-10 誤併反例（Codex P0）───────────────────────────────

class TestAC16CD122_10FalseMergeGuard:
    def test_no_token_plus_cd2_stay_two_singles(self):
        """ABC-123.mp4（無 token）＋ ABC-123-cd2.mp4 必須回兩個單檔組。"""
        rows = [
            _v("/media/ABC-123.mp4"),
            _v("/media/ABC-123-cd2.mp4"),
        ]
        groups = group_rows(rows, _fs_path_of)
        assert len(groups) == 2
        for g in groups:
            assert len(g.members) == 1
            assert g.part_tokens == []


# ── 舊庫零遷移守衛：分組不看 nfo_mtime ──────────────────────────────────

class TestLegacyNoNfoMigrationStillGroups:
    def test_part2_with_zero_nfo_mtime_still_merges(self):
        """part-2 沒有 NFO（nfo_mtime=0，舊庫典型情境）時，分組只看檔名，照樣合併。"""
        v1 = Video(path=to_file_uri("/media/ABC-123-cd1.mp4"), nfo_mtime=1700000000.0)
        v2 = Video(path=to_file_uri("/media/ABC-123-cd2.mp4"), nfo_mtime=0.0)
        groups = group_rows([v1, v2], _fs_path_of)
        assert len(groups) == 1
        assert len(groups[0].members) == 2
        assert groups[0].part_tokens == ["cd1", "cd2"]


# ── normalize_stem_key / group_key / part_number / part_token 單元 ──────

class TestHelperPrimitives:
    def test_normalize_stem_key_strips_whitespace_and_lowers(self):
        assert normalize_stem_key("ABC-123 CD1") != normalize_stem_key("abc-123cd1")
        # 剝除 token 後才正規化：帶 token 的 stem 剝完應與不帶 token 的裸 stem 一致
        assert normalize_stem_key("ABC-123-cd1") == normalize_stem_key("ABC-123")

    def test_group_key_splits_folder_and_normalized_stem(self):
        folder, key = group_key("/media/dirA/ABC-123-cd1.mp4")
        assert folder == "/media/dirA"
        assert key == normalize_stem_key("ABC-123-cd1")

    def test_part_number_single_file_is_1(self):
        assert part_number("/media/ABC-123.mp4") == 1

    def test_part_number_with_token(self):
        assert part_number("/media/ABC-123-cd2.mp4") == 2

    def test_part_token_none_for_single_file(self):
        assert part_token("/media/ABC-123.mp4") is None

    def test_part_token_returns_lowercase_literal(self):
        assert part_token("/media/ABC-123-CD1.mp4") == "cd1"


# ── resolve_group_for_path ──────────────────────────────────────────────

class TestResolveGroupForPath:
    def test_found_returns_group_containing_target(self):
        v1 = Video(path=to_file_uri("/media/ABC-123-cd1.mp4"))
        v2 = Video(path=to_file_uri("/media/ABC-123-cd2.mp4"))
        candidates = [v1, v2]
        group = resolve_group_for_path(
            target_uri=v2.path,
            candidates=candidates,
            fs_path_of=_fs_path_of,
            uri_of=_uri_of,
        )
        assert group is not None
        assert len(group.members) == 2

    def test_not_found_returns_none_not_raise(self):
        v1 = Video(path=to_file_uri("/media/ABC-123-cd1.mp4"))
        v2 = Video(path=to_file_uri("/media/ABC-123-cd2.mp4"))
        candidates = [v1, v2]
        group = resolve_group_for_path(
            target_uri=to_file_uri("/media/NOT-THERE.mp4"),
            candidates=candidates,
            fs_path_of=_fs_path_of,
            uri_of=_uri_of,
        )
        assert group is None

    def test_empty_candidates_returns_none(self):
        group = resolve_group_for_path(
            target_uri=to_file_uri("/media/ABC-123.mp4"),
            candidates=[],
            fs_path_of=_fs_path_of,
            uri_of=_uri_of,
        )
        assert group is None
