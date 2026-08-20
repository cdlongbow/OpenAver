"""test_showcase_grouping.py — GET /api/showcase/videos / /api/showcase/video 的
分組序列化行為（TASK-122-T2）。

AC-4（單檔片逐位元組不變，機械驗證）：讀回 `tests/fixtures/showcase/multipart_t2_baseline.json`
—— 這份 fixture 是**動手改 core/multipart_group.py／showcase.py 之前**、用現行未改動的
`_serialize_video()` 對一個「全部單檔片」合成 DB 跑 `GET /api/showcase/videos` 產生的
（見 TASK-122-T2 directive 步驟 1，硬性禁止用 git 指令回復工作區取得改動前輸出）。
本檔用**完全相同的合成 DB 資料**（逐欄位對照 fixture 生成腳本）重打一次同一支端點，
逐筆逐鍵比對：除新增的 `part_tokens` 鍵外，其餘 22 個既有 key 值必須完全相等。

AC-18：`_serialize_group()` 輸出的 `path` 必為 `group.members[0]`（part-1）的 path。
"""
import json
from pathlib import Path

import pytest

from core.database import Video
from core.path_utils import to_file_uri
from core.multipart_group import VideoGroup
from web.routers.showcase import _serialize_group


FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "showcase" / "multipart_t2_baseline.json"

# 與 AC-4 baseline 產生腳本逐欄位相同的合成資料——4 筆全單檔片，涵蓋有封面／無封面／
# 有 sample_images／無 duration 等既有欄位邊界組合。**不得改動這份資料**，否則 AC-4
# 逐鍵比對會失去意義（比的就是「同輸入、改動前後輸出相同」）。
def _baseline_videos() -> list[Video]:
    return [
        Video(
            path=to_file_uri("/home/user/media/SONE-205.mp4"),
            number="SONE-205",
            title="Test Video 1",
            original_title="テストビデオ1",
            actresses=["坂道みる", "深田えいみ"],
            maker="S1 NO.1 STYLE",
            director="Some Director",
            series="Some Series",
            label="SONE",
            release_date="2024-01-15",
            tags=["単体作品", "ハイビジョン", "独占配信"],
            user_tags=["★5"],
            duration=120,
            size_bytes=3145728000,
            cover_path=to_file_uri("/home/user/media/SONE-205/poster.jpg"),
            sample_images=[to_file_uri("/home/user/media/SONE-205/s1.jpg")],
            mtime=1705276800.0,
            auto_focal="0.5,0.5",
            crop_mode="auto",
        ),
        Video(
            path=to_file_uri("/home/user/media/ABW-001.mp4"),
            number="ABW-001",
            title="Test Video 2 - No Cover No Duration",
            original_title="",
            actresses=["新ありな"],
            maker="Prestige",
            release_date="2024-02-01",
            tags=["スレンダー"],
            duration=None,
            size_bytes=2147483648,
            cover_path="",
            mtime=1706745600.0,
        ),
        Video(
            path=to_file_uri("/home/user/media/FC2-001.mp4"),
            number="FC2-PPV-001",
            title="Test Video 3 - Zero size None fields",
            original_title="",
            actresses=[],
            maker="",
            release_date="",
            tags=[],
            duration=None,
            size_bytes=0,
            cover_path="",
            mtime=0.0,
        ),
        Video(
            path=to_file_uri("/home/user/media/sub/MIRD-151.mp4"),
            number="MIRD-151",
            title="Test Video 4 - subfolder with sample images",
            original_title="",
            actresses=["女優D"],
            maker="MakerD",
            release_date="2023-05-05",
            tags=["tagD"],
            duration=90,
            size_bytes=1000000,
            cover_path=to_file_uri("/home/user/media/sub/MIRD-151/poster.jpg"),
            sample_images=[
                to_file_uri("/home/user/media/sub/MIRD-151/s1.jpg"),
                to_file_uri("/home/user/media/sub/MIRD-151/s2.jpg"),
            ],
            mtime=1683273600.0,
        ),
    ]


@pytest.fixture
def baseline_showcase_config():
    return {
        "gallery": {
            "directories": ["/home/user/media"],
            "path_mappings": {},
            "min_size_mb": 0,
            "thumbnail_width": 400,
        },
        "scraper": {"video_extensions": [".mp4"], "image_extensions": [".jpg"]},
        "database": {"path": ":memory:"},
        "translate": {"provider": "ollama", "ollama_model": "llama3"},
        "thumbnail_cache_enabled": False,
    }


@pytest.fixture
def baseline_client(make_client, temp_db, baseline_showcase_config, make_populated_db):
    make_populated_db(_baseline_videos())
    return make_client(
        ["core.database.connection.get_db_path", "web.routers.showcase.get_db_path", "web.routers.showcase.load_config"],
        mock_db_path=temp_db,
        config_override=baseline_showcase_config,
    )


class TestAC4BaselineFixtureComparison:
    """AC-4：單檔片序列化逐位元組不變的機械驗證。"""

    def test_fixture_file_exists_and_pregenerated(self):
        assert FIXTURE_PATH.exists(), (
            "AC-4 baseline fixture 缺失——必須在動手改分組邏輯之前先產生，"
            "見 TASK-122-T2 directive 步驟 1。"
        )

    def test_all_single_file_videos_produce_groups_of_one(self, baseline_client):
        response = baseline_client.get("/api/showcase/videos")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # AC-1「+1 不是 +2」的鏡像：全單檔片 → total 不變（本例本來就是 4 筆單檔）
        assert data["total"] == 4

    def test_every_video_key_except_part_tokens_matches_baseline_exactly(self, baseline_client):
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            baseline = json.load(f)

        response = baseline_client.get("/api/showcase/videos")
        data = response.json()
        actual_videos = data["videos"]
        expected_videos = baseline["videos"]

        assert len(actual_videos) == len(expected_videos)

        # 以 path 對齊（兩邊皆用同一份合成資料，path 具唯一性可當比對鍵）
        actual_by_path = {v["path"]: v for v in actual_videos}
        expected_by_path = {v["path"]: v for v in expected_videos}
        assert set(actual_by_path.keys()) == set(expected_by_path.keys())

        for path, expected_v in expected_by_path.items():
            actual_v = actual_by_path[path]
            # part_tokens 是本 task 新增的鍵，baseline 裡不存在——單獨斷言，不進逐鍵迴圈
            assert "part_tokens" not in expected_v
            assert actual_v.get("part_tokens") == [], (
                f"單檔片 {path} 的 part_tokens 必為 []，實際 {actual_v.get('part_tokens')}"
            )
            for key, expected_value in expected_v.items():
                assert key in actual_v, f"缺少既有 key: {key}（path={path}）"
                assert actual_v[key] == expected_value, (
                    f"key={key} 值不符（path={path}）: "
                    f"expected={expected_value!r} actual={actual_v[key]!r}"
                )
            # 反向確認沒有意外多出的既有 key（part_tokens 除外，前面已單獨斷言過）
            extra_keys = set(actual_v.keys()) - set(expected_v.keys()) - {"part_tokens"}
            assert not extra_keys, f"多出非預期 key: {extra_keys}（path={path}）"


# ── AC-18：合併卡 path 必為 part-1 ───────────────────────────────────────

class TestAC18RepresentativePathIsPart1:
    def test_serialize_group_path_equals_members_first_path(self):
        part1 = Video(
            path=to_file_uri("/media/ABC-123-cd1.mp4"),
            number="ABC-123",
            title="Part 1 title",
            size_bytes=100,
        )
        part2 = Video(
            path=to_file_uri("/media/ABC-123-cd2.mp4"),
            number="ABC-123",
            title="Part 2 title (should not leak into base)",
            size_bytes=200,
        )
        group = VideoGroup(members=[part1, part2], part_tokens=["cd1", "cd2"])

        result = _serialize_group(group, path_mappings={}, enabled=False)

        assert result["path"] == part1.path
        assert result["path"] == group.members[0].path
        # 其餘欄位（含 title）逐字取 part-1，不做欄位級 merge（CD-122-4）
        assert result["title"] == "Part 1 title"
        # size 是覆寫的加總欄位，唯一例外
        assert result["size"] == 300
        assert result["part_tokens"] == ["cd1", "cd2"]

    def test_serialize_group_size_bytes_none_defends_with_or_zero(self):
        """size_bytes 可能是 None（Video.from_row 對 DB NULL 不做防禦）；
        sum(m.size_bytes or 0 ...) 的 or 0 是必要防禦，不是保險。"""
        part1 = Video(path=to_file_uri("/media/X-1-cd1.mp4"), size_bytes=None)
        part2 = Video(path=to_file_uri("/media/X-1-cd2.mp4"), size_bytes=500)
        group = VideoGroup(members=[part1, part2], part_tokens=["cd1", "cd2"])

        result = _serialize_group(group, path_mappings={}, enabled=False)

        assert result["size"] == 500

    def test_single_file_null_size_stays_none_not_zero(self):
        """AC-4 逐位元組不變：單檔片的 size_bytes 為 DB NULL 時，序列化結果必須維持
        `None`，不可被多段加總路徑的 `or 0` 防禦改成 `0`（T2 review P3）。
        目前前端消費點都做 `bytes || 0`，兩者渲染相同；但 AC-4 的契約是字面的，
        且未來若有人改成 `size === null` 嚴格判斷就會踩到。"""
        v = Video(path=to_file_uri("/media/NULLSIZE-001.mp4"), size_bytes=None)
        group = VideoGroup(members=[v], part_tokens=[])

        result = _serialize_group(group, path_mappings={}, enabled=False)

        assert result["size"] is None, "單檔片的 NULL size 不可被改成 0"

    def test_single_file_group_path_equals_itself(self):
        v = Video(path=to_file_uri("/media/SINGLE-001.mp4"), size_bytes=100)
        group = VideoGroup(members=[v], part_tokens=[])

        result = _serialize_group(group, path_mappings={}, enabled=False)

        assert result["path"] == v.path
        assert result["part_tokens"] == []
