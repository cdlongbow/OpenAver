"""
test_insights_snapshot.py — GET /api/insights/snapshot 整合測試（TASK-156a-T1）

覆蓋 CD-156-1／1.1／1.1.1／2／2.1：母體篩選、別名合併、收藏女優 first-wins、
欄位白名單、ETag／304 與四種反向 ETag。
"""

import pytest
from core.database import (
    init_db,
    VideoRepository,
    Video,
    Actress,
    ActressRepository,
    AliasRepository,
    TagAliasRepository,
)
from core.path_utils import to_file_uri
from core.database.version_tracker import get_showcase_revision


# ============ Fixtures ============

@pytest.fixture
def insights_setup(tmp_path):
    """
    小型 fixture DB，涵蓋 DoD 要求的全部種子：
    - duration=239 的片
    - fixture A：舊名收藏／新名 primary
    - fixture B：同組兩位收藏、aliases=["B子","A子"]（與字母序相反）
    - 多段分集片（-cd1/-cd2）
    - 一筆不在 configured dir 範圍內的片
    - 一位 birth 缺值的收藏女優（應被排除）
    """
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    # --- paths ---
    longform_uri = to_file_uri(str(video_dir / "LONG-239.mp4"), {})
    fixture_a_uri = to_file_uri(str(video_dir / "FIXTURE-A.mp4"), {})
    fixture_b_uri = to_file_uri(str(video_dir / "FIXTURE-B.mp4"), {})
    part1_uri = to_file_uri(str(video_dir / "MULTI-001-cd1.mp4"), {})
    part2_uri = to_file_uri(str(video_dir / "MULTI-001-cd2.mp4"), {})
    outside_uri = to_file_uri(str(outside_dir / "OUTSIDE-001.mp4"), {})

    db_path = tmp_path / "insights_test.db"
    init_db(db_path)

    # --- videos ---
    video_repo = VideoRepository(db_path)
    video_repo.upsert_batch([
        Video(
            path=longform_uri,
            number="LONG-239",
            title="Long Form",
            actresses=["路人甲"],
            maker="Test Maker",
            release_date="2020-06-15",
            tags=["單體作品"],
            duration=239,
            size_bytes=100,
            mtime=1700000000.0,
        ),
        Video(
            path=fixture_a_uri,
            number="FIX-A",
            title="Fixture A",
            actresses=["新名"],  # primary；收藏列是舊名
            maker="Maker A",
            director="Dir A",
            series="Series A",
            release_date="2021-03-10",
            tags=["舊標", "高畫質"],  # 舊標 → 新標 via tag alias
            duration=120,
            size_bytes=200,
            mtime=1700000001.0,
        ),
        Video(
            path=fixture_b_uri,
            number="FIX-B",
            title="Fixture B",
            actresses=["B子"],  # 別名組成員；canonical → 組主
            maker="Maker B",
            release_date="2022-01-01",
            tags=[],
            duration=90,
            size_bytes=300,
            mtime=1700000002.0,
        ),
        Video(
            path=part1_uri,
            number="MULTI-001",
            title="Multipart",
            actresses=["分集女優"],
            maker="Maker M",
            release_date="2019-08-01",
            tags=[],
            duration=100,
            size_bytes=400,
            mtime=1700000003.0,
        ),
        Video(
            path=part2_uri,
            number="MULTI-001",
            title="Multipart Part 2",
            actresses=["分集女優"],
            maker="Maker M",
            release_date="2019-08-01",
            tags=[],
            duration=100,
            size_bytes=500,
            mtime=1700000004.0,
        ),
        Video(
            path=outside_uri,
            number="OUT-001",
            title="Outside Configured Dir",
            actresses=["局外人"],
            maker="Outside Maker",
            release_date="2018-01-01",
            tags=[],
            duration=60,
            size_bytes=50,
            mtime=1700000005.0,
        ),
    ])

    # --- favorite actresses ---
    actress_repo = ActressRepository(db_path)
    actress_repo.save(Actress(name="舊名", birth="1988-05-20"))  # fixture A
    actress_repo.save(Actress(name="A子", birth="1990-01-01"))   # fixture B winner
    actress_repo.save(Actress(name="B子", birth="1995-06-01"))   # fixture B loser
    actress_repo.save(Actress(name="無生日", birth=None))         # must be excluded
    actress_repo.save(Actress(name="空生日", birth=""))           # must be excluded

    # --- aliases ---
    # fixture A：primary=新名，aliases=[舊名]
    AliasRepository(db_path).add("新名", aliases=["舊名"])
    # fixture B：primary=組主，aliases 順序刻意與字母序相反
    AliasRepository(db_path).add("組主", aliases=["B子", "A子"])
    TagAliasRepository(db_path).add("新標", aliases=["舊標"])

    config = {
        "gallery": {
            "directories": [str(video_dir)],
            "path_mappings": {},
            "min_size_mb": 0,
            "thumbnail_width": 400,
        },
        "scraper": {"video_extensions": [".mp4"], "image_extensions": [".jpg"]},
        "database": {"path": ":memory:"},
        "translate": {"provider": "ollama", "ollama_model": "llama3"},
    }

    return {
        "db_path": db_path,
        "config": config,
        "video_dir": video_dir,
        "outside_dir": outside_dir,
        "longform_uri": longform_uri,
        "fixture_a_uri": fixture_a_uri,
        "fixture_b_uri": fixture_b_uri,
        "part1_uri": part1_uri,
        "part2_uri": part2_uri,
        "outside_uri": outside_uri,
    }


def _get_snapshot(client, mocker, setup, if_none_match=None):
    mocker.patch("web.routers.insights.get_db_path", return_value=setup["db_path"])
    mocker.patch("web.routers.insights.load_config", return_value=setup["config"])
    headers = {"If-None-Match": if_none_match} if if_none_match else {}
    return client.get("/api/insights/snapshot", headers=headers)


# ============ Population / multipart / alias ============

class TestInsightsSnapshotPopulation:
    """母體篩選、分集合併、別名 canonicalization。"""

    def test_multipart_counts_match_showcase_logical_and_physical(
        self, client, insights_setup, mocker
    ):
        """分集片只序列化一筆；logicalTitles 與 showcase total 一致。"""
        snap = _get_snapshot(client, mocker, insights_setup)
        assert snap.status_code == 200
        body = snap.json()

        mocker.patch(
            "web.routers.showcase.get_db_path", return_value=insights_setup["db_path"]
        )
        mocker.patch(
            "web.routers.showcase.load_config", return_value=insights_setup["config"]
        )
        showcase = client.get("/api/showcase/videos")
        assert showcase.status_code == 200
        showcase_total = showcase.json()["total"]

        # configured dir 內：longform + A + B + part1 + part2 = 5 physical；
        # multipart 合併後 logical = 4；outside 不計。
        assert body["physicalRows"] == 5
        assert body["logicalTitles"] == 4
        assert body["logicalTitles"] == showcase_total
        assert len(body["records"]) == body["logicalTitles"]

    def test_population_excludes_video_outside_configured_dir(
        self, client, insights_setup, mocker
    ):
        """path 不在 configured_dir_uris → 不進 records／logicalTitles／physicalRows。"""
        snap = _get_snapshot(client, mocker, insights_setup)
        assert snap.status_code == 200
        body = snap.json()

        # outside 片的 maker 不該出現；局外人也不該進 actresses
        makers = {r.get("maker") for r in body["records"]}
        assert "Outside Maker" not in makers
        all_actresses = {
            name for r in body["records"] for name in (r.get("actresses") or [])
        }
        assert "局外人" not in all_actresses
        assert body["physicalRows"] == 5
        assert body["logicalTitles"] == 4

    def test_actresses_use_canonical_primary_names(
        self, client, insights_setup, mocker
    ):
        """別名合併後 records[].actresses[] 用 primary 名字。"""
        snap = _get_snapshot(client, mocker, insights_setup)
        body = snap.json()

        # fixture A 片 actresses 存「新名」（已是 primary）
        # fixture B 片 actresses 存「B子」→ canonical「組主」
        all_actresses = [
            name for r in body["records"] for name in (r.get("actresses") or [])
        ]
        assert "新名" in all_actresses
        assert "組主" in all_actresses
        assert "B子" not in all_actresses
        assert "舊名" not in all_actresses

        # tag alias：舊標 → 新標
        fixture_a = next(
            r for r in body["records"]
            if r.get("maker") == "Maker A"
        )
        assert "新標" in fixture_a["tags"]
        assert "舊標" not in fixture_a["tags"]


# ============ actressFavorites (CD-156-1.1 / 1.1.1) ============

class TestInsightsActressFavorites:
    """收藏女優別名解析、first-wins、欄位白名單、缺生日排除。"""

    def test_fixture_a_old_name_favorite_maps_to_new_primary_photo_name(
        self, client, insights_setup, mocker
    ):
        """fixture A：actressFavorites['新名'].photoName == '舊名'。"""
        snap = _get_snapshot(client, mocker, insights_setup)
        body = snap.json()
        fav = body["actressFavorites"]["新名"]
        assert fav["photoName"] == "舊名"
        assert fav["birth"] == "1988-05-20"

    def test_fixture_b_favorite_actress_tiebreak_first_wins_by_name_order(
        self, client, insights_setup, mocker
    ):
        """fixture B：字母序較前的 A子 勝出（birth=1990-01-01），不是 aliases 先出現的 B子。"""
        snap = _get_snapshot(client, mocker, insights_setup)
        body = snap.json()
        fav = body["actressFavorites"]["組主"]
        assert fav["birth"] == "1990-01-01"
        assert fav["photoName"] == "A子"

    def test_actress_favorites_value_key_whitelist_exact(
        self, client, insights_setup, mocker
    ):
        """每個 value 的 key 集合逐字等於 {birth, photoName, auto_focal, crop_mode}。"""
        snap = _get_snapshot(client, mocker, insights_setup)
        body = snap.json()
        expected = {"birth", "photoName", "auto_focal", "crop_mode"}
        assert body["actressFavorites"], "應至少有收藏女優進入表"
        for primary, value in body["actressFavorites"].items():
            assert set(value.keys()) == expected, (
                f"actressFavorites[{primary!r}] keys={set(value.keys())} != {expected}"
            )
            # 預設焦點欄位原樣輸出（不是當缺值丟掉）
            assert value["auto_focal"] == ""
            assert value["crop_mode"] == "auto"

    def test_favorite_without_birth_excluded_entirely(
        self, client, insights_setup, mocker
    ):
        """birth 為 None／空字串的收藏女優整筆排除（不是塞 null）。"""
        snap = _get_snapshot(client, mocker, insights_setup)
        body = snap.json()
        favs = body["actressFavorites"]
        assert "無生日" not in favs
        assert "空生日" not in favs
        # 也沒有以她們為 key、value 為 null 的怪形狀
        for key, value in favs.items():
            assert value is not None
            assert value.get("birth")


# ============ ETag / 304 ============

class TestInsightsSnapshotETag:
    """ETag／304 短路與四種反向 ETag。"""

    def test_route_passes_revision_into_compute_etag(
        self, client, insights_setup, mocker
    ):
        """route 層獨立驗證：`get_insights_snapshot()` 真的把 `get_showcase_revision()`
        的值接進 `compute_etag()`——先把 `compute_db_fingerprint` 凍成常數，才能單獨
        看 revision 有沒有真的被傳進去（真實寫入也會改 -wal stat，指紋會頂替 revision）。
        """
        mocker.patch(
            "web.routers.insights.compute_db_fingerprint",
            return_value="frozen-fingerprint",
        )

        first = _get_snapshot(client, mocker, insights_setup)
        etag = first.headers["etag"]
        revision_before = get_showcase_revision()

        repo = VideoRepository(insights_setup["db_path"])
        repo.set_user_rating(insights_setup["fixture_a_uri"], 5)

        assert get_showcase_revision() != revision_before, (
            "自我把關：這支測試的前提是這筆寫入真的 bump 了 revision，否則後面的 200 斷言"
            "測不出任何東西（假綠）"
        )

        second = _get_snapshot(client, mocker, insights_setup, if_none_match=etag)
        assert second.status_code == 200, (
            "db_fingerprint 被凍結不動，若 route 沒有把 revision 傳進 compute_etag()，"
            "這裡會誤回 304——使用者剛操作完切回片庫分析頁，看到的還是操作前的舊快照"
        )

    def test_second_request_with_same_etag_returns_304(
        self, client, insights_setup, mocker
    ):
        """無寫入時第二次帶舊 ETag 的請求回 304。"""
        first = _get_snapshot(client, mocker, insights_setup)
        assert first.status_code == 200
        etag = first.headers["etag"]

        second = _get_snapshot(client, mocker, insights_setup, if_none_match=etag)
        assert second.status_code == 304
        assert second.headers["etag"] == etag
        assert second.content == b""

    def test_reverse_etag_new_video_returns_200(
        self, client, insights_setup, mocker
    ):
        """反向 ETag：新增一部片 → 舊 ETag 回 200 且 body 與寫入前不同。"""
        first = _get_snapshot(client, mocker, insights_setup)
        etag = first.headers["etag"]
        body_before = first.json()

        new_uri = to_file_uri(str(insights_setup["video_dir"] / "NEW-001.mp4"), {})
        VideoRepository(insights_setup["db_path"]).upsert_batch([
            Video(
                path=new_uri,
                number="NEW-001",
                title="New Video",
                actresses=[],
                release_date="2023-01-01",
                duration=50,
            )
        ])

        second = _get_snapshot(client, mocker, insights_setup, if_none_match=etag)
        assert second.status_code == 200
        assert second.headers["etag"] != etag
        assert second.json() != body_before
        assert second.json()["logicalTitles"] == body_before["logicalTitles"] + 1

    def test_reverse_etag_actress_alias_change_returns_200(
        self, client, insights_setup, mocker
    ):
        """反向 ETag：改一筆 actress_aliases → 舊 ETag 回 200 且 body 不同。"""
        first = _get_snapshot(client, mocker, insights_setup)
        etag = first.headers["etag"]
        body_before = first.json()

        # 把「路人甲」收進新別名組 → longform 片的 actresses[] canonical 會變，body 必不同
        AliasRepository(insights_setup["db_path"]).add(
            "路人甲主名", aliases=["路人甲"]
        )

        second = _get_snapshot(client, mocker, insights_setup, if_none_match=etag)
        assert second.status_code == 200
        assert second.headers["etag"] != etag
        assert second.json() != body_before
        all_actresses = {
            name
            for r in second.json()["records"]
            for name in (r.get("actresses") or [])
        }
        assert "路人甲主名" in all_actresses
        assert "路人甲" not in all_actresses

    def test_reverse_etag_actress_birth_change_returns_200(
        self, client, insights_setup, mocker
    ):
        """反向 ETag：改收藏女優 birth → 舊 ETag 回 200 且 body 與寫入前不同。"""
        first = _get_snapshot(client, mocker, insights_setup)
        etag = first.headers["etag"]
        body_before = first.json()

        ActressRepository(insights_setup["db_path"]).save(
            Actress(name="舊名", birth="1988-12-31")
        )

        second = _get_snapshot(client, mocker, insights_setup, if_none_match=etag)
        assert second.status_code == 200
        assert second.headers["etag"] != etag
        assert second.json()["actressFavorites"]["新名"]["birth"] == "1988-12-31"
        assert second.json() != body_before

    def test_reverse_etag_gallery_config_change_returns_200(
        self, client, insights_setup, mocker
    ):
        """反向 ETag：改 config.gallery 來源資料夾 → 舊 ETag 回 200（純設定投影，無 DB 寫入）。"""
        # outside 片在 first 之前已在 DB，只是不在設定範圍內
        first = _get_snapshot(client, mocker, insights_setup)
        assert first.status_code == 200
        etag = first.headers["etag"]
        body_before = first.json()
        revision_before = get_showcase_revision()

        new_config = dict(insights_setup["config"])
        new_config["gallery"] = dict(new_config["gallery"])
        new_config["gallery"]["directories"] = [
            str(insights_setup["video_dir"]),
            str(insights_setup["outside_dir"]),
        ]
        setup_with_new = {**insights_setup, "config": new_config}

        second = _get_snapshot(client, mocker, setup_with_new, if_none_match=etag)
        assert get_showcase_revision() == revision_before, (
            "兩次請求之間不該有真實 DB 寫入，否則量不到設定投影單獨的效果"
        )
        assert second.status_code == 200
        assert second.headers["etag"] != etag
        assert second.json()["logicalTitles"] == body_before["logicalTitles"] + 1
        makers = {r.get("maker") for r in second.json()["records"]}
        assert "Outside Maker" in makers

    def test_empty_db_returns_shell_without_etag(
        self, client, insights_setup, mocker, tmp_path
    ):
        """空庫（db_path 不存在）→ 空殼 JSON、無 ETag header。"""
        missing = tmp_path / "does_not_exist.db"
        setup = {**insights_setup, "db_path": missing}
        response = _get_snapshot(client, mocker, setup)
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "logicalTitles": 0,
            "physicalRows": 0,
            "years": [],
            "records": [],
            "actressFavorites": {},
        }
        assert "etag" not in response.headers


# ============ Record field shape smoke ============

class TestInsightsRecordShape:
    """records 欄位形狀與 duration=239 fixture 存在性。"""

    def test_record_contains_duration_239_and_core_keys(
        self, client, insights_setup, mocker
    ):
        snap = _get_snapshot(client, mocker, insights_setup)
        body = snap.json()
        durations = [r.get("duration") for r in body["records"]]
        assert 239 in durations

        expected_keys = {
            "year", "month", "date", "duration",
            "actresses", "maker", "director", "series", "tags",
        }
        for record in body["records"]:
            assert set(record.keys()) == expected_keys

        fixture_a = next(r for r in body["records"] if r.get("maker") == "Maker A")
        assert fixture_a["year"] == 2021
        assert fixture_a["month"] == "2021-03"
        assert fixture_a["date"] == "2021-03-10"
        assert fixture_a["duration"] == 120
        assert fixture_a["director"] == "Dir A"
        assert fixture_a["series"] == "Series A"
