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
    folder_uri_prefix,
    VideoGroup,
    group_rows,
    resolve_group_for_path,
    resolve_group,
    resolve_groups_bulk,
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


# ── CD-122-13：段號重複的誤併反例（Codex PR review P0）─────────────────

class TestCD122_13DuplicatePartNumberGuard:
    """同一段號出現兩次 → 那是「同一片的兩種版本」，不是「一片的兩段」。

    使用者流程：同一部片留了 `.mkv` 原檔 ＋ 轉出的 `.mp4` 相容版，兩個都沿用
    同一組分集命名放在同資料夾 → 若誤併，另一個版本會從瀏覽頁消失、播放頁把同一段
    連播兩次，而刪除那張卡會一次移除兩列 DB（手動封面裁切座標只存在 DB、不進 NFO，
    重掃救不回來，使用者得重新框一次）。
    """

    def test_same_part_number_different_container_stay_two_singles(self):
        """ABC-123-cd1.mp4 ＋ ABC-123-cd1.mkv → 兩個單檔組（剝 token 後 stem 相同、
        兩者都帶 token，唯一擋得住的就是段號重複這條）。"""
        rows = [
            _v("/media/ABC-123-cd1.mp4"),
            _v("/media/ABC-123-cd1.mkv"),
        ]
        groups = group_rows(rows, _fs_path_of)
        assert len(groups) == 2
        for g in groups:
            assert len(g.members) == 1
            assert g.part_tokens == []

    def test_same_number_different_token_prefix_stay_two_singles(self):
        """ABC-123-cd1.mp4 ＋ ABC-123-pt1.mkv → 前綴不同但都是第 1 段，同樣是衝突。
        （比對用 part number 而非 token 字面，才擋得住這一種。）"""
        rows = [
            _v("/media/ABC-123-cd1.mp4"),
            _v("/media/ABC-123-pt1.mkv"),
        ]
        groups = group_rows(rows, _fs_path_of)
        assert len(groups) == 2
        for g in groups:
            assert g.part_tokens == []

    def test_unique_part_numbers_still_merge(self):
        """正向對照：段號唯一時照常合併（確認上面那條沒有誤傷正常分集）。"""
        rows = [
            _v("/media/ABC-123-cd1.mp4"),
            _v("/media/ABC-123-cd2.mp4"),
            _v("/media/ABC-123-cd3.mp4"),
        ]
        groups = group_rows(rows, _fs_path_of)
        assert len(groups) == 1
        assert groups[0].part_tokens == ["cd1", "cd2", "cd3"]


# ── grok Stage 1 P3：片庫放在磁碟機根目錄時的資料夾前綴 ─────────────────

class TestDriveRootFolderUriPrefix:
    """`folder_uri_prefix()` 保證正好一個結尾斜線。

    使用者流程：片庫直接放在 `D:\\` 根目錄（專用媒體碟的常見擺法），裡面有
    `ABC-123-cd1.mp4` ＋ `ABC-123-cd2.mp4`。前綴若長成 `file:///D://`，
    `get_by_folder_uri_prefix()` 的 `LIKE prefix%` 一列都對不上 → 三個操作入口
    （單筆 refresh／刪除／播放接續）反解不到組，但瀏覽頁**仍然合併成一張卡**
    （列表走的是 `group_rows` 比對 FS dirname，不是這條）。結果是按「從收藏移除」
    只刪掉第 1 段，重整後那張卡又冒出來。
    """

    def test_drive_root_prefix_has_single_trailing_slash(self):
        # `ntpath.dirname('D:\\ABC-123-cd1.mp4')` == `'D:\\'`（真 Windows Python 3.13 實測）。
        # CI 跑 Linux、posixpath 產不出這個字面，所以直接餵 Windows dirname 的結果——
        # `to_file_uri()` 的 drive-letter 分支不看 CURRENT_ENV，兩邊行為相同。
        assert folder_uri_prefix("D:\\") == "file:///D:/"
        assert folder_uri_prefix("D:/") == "file:///D:/"

    def test_drive_root_prefix_actually_matches_rows_in_that_root(self):
        """真正的後果面：前綴要能對上根目錄裡那些列（LIKE prefix% 的前半段）。"""
        prefix = folder_uri_prefix("D:\\")
        assert to_file_uri("D:/ABC-123-cd1.mp4").startswith(prefix)
        assert to_file_uri("D:/ABC-123-cd2.mp4").startswith(prefix)

    def test_normal_subfolder_prefix_unchanged(self):
        """正向對照：一般子資料夾的前綴逐字不變（沒有誤傷既有路徑）。"""
        assert folder_uri_prefix("C:/AVtest") == "file:///C:/AVtest/"
        assert folder_uri_prefix("C:\\AVtest") == "file:///C:/AVtest/"


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


class TestResolveGroupsBulk:
    """123-T8b（Stage 2 Opus review P2）：批次解析必須與「逐一呼叫 resolve_group()」
    語意逐位元相同，且同一資料夾只查一次 DB。

    Why 這支測試存在：批次端點原本逐路徑呼叫 resolve_group()，而它每次都對整個資料夾
    重查 ＋ 重跑 group_rows()（實測 owner 真實片庫 47.6 ms/次 ⇒ 500 路徑約 24 秒）。
    改成批次後**唯一能出錯的地方就是語意漂移**，所以這裡鎖的是等價性，不是效能數字。
    """

    class _FakeRepo:
        """只實作 resolve_group()／resolve_groups_bulk() 用到的那一個方法（duck-typed，
        與 core.multipart_group 的 repo 契約一致），並記錄呼叫次數。"""

        def __init__(self, rows):
            self._rows = rows
            self.calls = []

        def get_by_folder_uri_prefix(self, prefix):
            self.calls.append(prefix)
            return [r for r in self._rows if r.path.startswith(prefix)]

    def _library(self):
        return [
            Video(path=to_file_uri("/media/ABC-123-cd1.mp4")),
            Video(path=to_file_uri("/media/ABC-123-cd2.mp4")),
            Video(path=to_file_uri("/media/SOLO-001.mp4")),
            Video(path=to_file_uri("/other/XYZ-9-cd1.mp4")),
            Video(path=to_file_uri("/other/XYZ-9-cd2.mp4")),
        ]

    def test_matches_per_path_resolve_group_exactly(self):
        rows = self._library()
        targets = [r.path for r in rows] + [to_file_uri("/media/NOT-THERE.mp4")]

        one_by_one = {}
        for uri in targets:
            g = resolve_group(self._FakeRepo(rows), uri, {})
            one_by_one[uri] = None if g is None else [m.path for m in g.members]

        bulk_raw = resolve_groups_bulk(self._FakeRepo(rows), targets, {})
        bulk = {k: (None if v is None else [m.path for m in v.members]) for k, v in bulk_raw.items()}

        assert bulk == one_by_one

    def test_same_folder_queried_once_regardless_of_path_count(self):
        rows = self._library()
        repo = self._FakeRepo(rows)
        # 同一資料夾 3 條路徑 + 另一資料夾 2 條
        targets = [
            to_file_uri("/media/ABC-123-cd1.mp4"),
            to_file_uri("/media/ABC-123-cd2.mp4"),
            to_file_uri("/media/SOLO-001.mp4"),
            to_file_uri("/other/XYZ-9-cd1.mp4"),
            to_file_uri("/other/XYZ-9-cd2.mp4"),
        ]
        resolve_groups_bulk(repo, targets, {})
        assert len(repo.calls) == 2, f"每個資料夾只該查一次，實際 {repo.calls}"
        assert len(set(repo.calls)) == 2

    def test_duplicate_input_resolved_once(self):
        rows = self._library()
        repo = self._FakeRepo(rows)
        uri = to_file_uri("/media/ABC-123-cd1.mp4")
        out = resolve_groups_bulk(repo, [uri, uri, uri], {})
        assert len(repo.calls) == 1
        assert list(out.keys()) == [uri]

    def test_not_found_maps_to_none_not_raise(self):
        repo = self._FakeRepo(self._library())
        missing = to_file_uri("/media/NOPE.mp4")
        out = resolve_groups_bulk(repo, [missing], {})
        assert out[missing] is None

    def test_empty_input_no_db_call(self):
        repo = self._FakeRepo(self._library())
        assert resolve_groups_bulk(repo, [], {}) == {}
        assert repo.calls == []
