"""
test_javdb_api_mapping.py - JavDB API JSON → Video 映射單元測試（TASK-132b-T2）

本檔不證明站方的欄位名是對的。餵存下來的 JSON 跑欄位斷言，在站方改版時會假綠。
欄位名的偵測器是金絲雀 A（T5）。本檔鎖的只有「我們自己的規則」。


⚠️ **圖片網址一律用 `tp.spfcas.com`（真實的資料介面圖床），不要用 `example.com` 佔位。**
TASK-132b-T4 之後 `fetch_video()` 會驗圖片 host 有沒有登記在 `core/image_host_policy.py`
（CD-132b-7：未登記 → 丟 `ValueError` → `search()` 降級 HTML）。用未登記的佔位網域
會讓本檔每一支都炸在那個閘上，而不是測到映射規則。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import core.scrapers.javdb_api as javdb_api
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.scrapers.models import Actress


def _setup_api_mocks(
    monkeypatch,
    search_return=None,
    detail_return=None,
    search_err=None,
    detail_err=None,
):
    """Monkeypatch javdb_api.api_search 與 javdb_api.api_movie_detail；零網路。"""
    mock_search = MagicMock()
    if search_err is not None:
        mock_search.side_effect = search_err
    else:
        mock_search.return_value = search_return if search_return is not None else []
    monkeypatch.setattr(javdb_api, "api_search", mock_search)

    mock_detail = MagicMock()
    if detail_err is not None:
        mock_detail.side_effect = detail_err
    else:
        mock_detail.return_value = detail_return if detail_return is not None else {}
    monkeypatch.setattr(javdb_api, "api_movie_detail", mock_detail)

    return mock_search, mock_detail


# ============================================================
# AC-1｜gender 過濾（正向 ＋ 反向）
# ============================================================

class TestGenderFilter:
    def test_male_actor_is_excluded(self, monkeypatch):
        """男優 (gender=1) 必須被排除，僅保留女優 (gender=0)。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "測試標題",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "actors": [
                {"id": "a1", "name": "未歩なな", "gender": 0},
                {"id": "a2", "name": "田淵正浩", "gender": 1},
            ],
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.actresses == [Actress(name="未歩なな")]

    def test_non_zero_gender_is_excluded(self, monkeypatch):
        """gender 為 2 / None / 缺 key / 其他值時一律不收進女優清單。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "測試標題",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "actors": [
                {"id": "a1", "name": "女優甲", "gender": 0},
                {"id": "a2", "name": "未知乙", "gender": 2},
                {"id": "a3", "name": "未知丙", "gender": None},
                {"id": "a4", "name": "未知丁"},
                {"id": "a5", "name": "未知戊", "gender": -1},
            ],
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.actresses == [Actress(name="女優甲")]

    def test_actor_with_empty_or_none_name_skipped(self, monkeypatch):
        """actor 名稱為空字串或 None 時跳過，避免 pydantic 拋出 ValidationError。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "測試標題",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "actors": [
                {"id": "a1", "name": "未歩なな", "gender": 0},
                {"id": "a2", "name": "", "gender": 0},
                {"id": "a3", "name": "   ", "gender": 0},
                {"id": "a4", "name": None, "gender": 0},
                {"id": "a5", "gender": 0},
                None,
                "invalid_item",
            ],
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.actresses == [Actress(name="未歩なな")]


# ============================================================
# AC-2｜番號精確比對
# ============================================================

class TestNumberMatching:
    def test_exact_number_matching_from_search_results(self, monkeypatch):
        """搜尋結果多筆時，應精確比對並選中相符番號之項目，並調用其 id 查詢詳情。"""
        search_payload = [
            {"id": "id-hone205", "number": "HONE-205"},
            {"id": "id-sone005", "number": "SONE-005"},
            {"id": "id-sone205", "number": "SONE-205"},
        ]
        detail_payload = {
            "id": "id-sone205",
            "number": "SONE-205",
            "title": "精確命中",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
        }
        _, mock_detail = _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.title == "精確命中"
        mock_detail.assert_called_once_with("id-sone205")

    def test_near_miss_number_is_not_accepted(self, monkeypatch):
        """搜尋結果皆為近似番號但無精確相符時，應回傳 None，且不得調用詳情 API。"""
        search_payload = [
            {"id": "id-hone205", "number": "HONE-205"},
            {"id": "id-sone005", "number": "SONE-005"},
        ]
        detail_payload = {
            "id": "id-hone205",
            "number": "HONE-205",
            "title": "近似番號影片",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
        }
        _, mock_detail = _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is None
        mock_detail.assert_not_called()

    @pytest.mark.parametrize(
        ("query_number", "matched_number"),
        [
            ("sone-205", "SONE-205"),
            ("SONE205", "SONE-205"),
            ("sone205", "SONE-205"),
            (" SONE-205 ", "sone-205"),
            ("sone-205", "SONE205"),
        ],
    )
    def test_case_and_hyphen_normalization(self, monkeypatch, query_number, matched_number):
        """大小寫與連字號差異視為相符。"""
        search_payload = [{"id": "id-target", "number": matched_number}]
        detail_payload = {
            "id": "id-target",
            "number": matched_number,
            "title": "相符標題",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
        }
        _, mock_detail = _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video(query_number)

        assert video is not None
        assert video.number == query_number
        mock_detail.assert_called_once_with("id-target")

    def test_search_matches_only_first_5_results(self, monkeypatch):
        """比對僅掃前 5 筆搜尋結果；第 6 筆即使相符也不收。"""
        search_payload = [
            {"id": "id-1", "number": "OTHER-001"},
            {"id": "id-2", "number": "OTHER-002"},
            {"id": "id-3", "number": "OTHER-003"},
            {"id": "id-4", "number": "OTHER-004"},
            {"id": "id-5", "number": "OTHER-005"},
            {"id": "id-6", "number": "SONE-205"},
        ]
        _, mock_detail = _setup_api_mocks(monkeypatch, search_payload, {})

        video = javdb_api.fetch_video("SONE-205")

        assert video is None
        mock_detail.assert_not_called()

    def test_search_match_without_id_returns_none(self, monkeypatch):
        """精確相符之項目若無 id 欄位或為空字串，應回傳 None 且不調用詳情。"""
        search_payload = [{"id": "", "number": "SONE-205"}]
        _, mock_detail = _setup_api_mocks(monkeypatch, search_payload, {})

        video = javdb_api.fetch_video("SONE-205")

        assert video is None
        mock_detail.assert_not_called()


# ============================================================
# AC-3｜劇照全收
# ============================================================

class TestSampleImages:
    def test_sample_images_all_collected_in_order(self, monkeypatch):
        """preview_images 12 筆應全部收錄至 sample_images，且維持原順序。"""
        images = [f"https://tp.spfcas.com/sample_{i:02d}.jpg" for i in range(12)]
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "劇照測試",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "preview_images": [
                {"thumb_url": f"https://tp.spfcas.com/thumb_{i:02d}.jpg", "large_url": u}
                for i, u in enumerate(images)
            ],
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert len(video.sample_images) == 12
        assert video.sample_images == images

    def test_sample_images_first_item_retained_lock(self, monkeypatch):
        """反向鎖：首張劇照不得被丟棄（斷言第 0 筆等於 preview_images[0].large_url）。"""
        first_large = "https://tp.spfcas.com/sample_00_l_0.jpg"
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "首圖測試",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "preview_images": [
                {"large_url": first_large},
                {"large_url": "https://tp.spfcas.com/sample_01.jpg"},
            ],
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert len(video.sample_images) == 2
        assert video.sample_images[0] == first_large

    def test_sample_images_missing_large_url_skipped(self, monkeypatch):
        """preview_images 中缺 large_url、large_url 為 None 或空字串之項目應跳過。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "缺圖測試",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "preview_images": [
                {"large_url": "https://tp.spfcas.com/img1.jpg"},
                {"large_url": ""},
                {"large_url": None},
                {"thumb_url": "https://tp.spfcas.com/thumb_only.jpg"},
                None,
                "invalid",
                {"large_url": "https://tp.spfcas.com/img2.jpg"},
            ],
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.sample_images == [
            "https://tp.spfcas.com/img1.jpg",
            "https://tp.spfcas.com/img2.jpg",
        ]


# ============================================================
# AC-4｜平行欄位留空
# ============================================================

class TestParallelPreviewFields:
    def test_parallel_preview_fields_stay_empty(self, monkeypatch):
        """BE-DATA-07：preview_cover_url 與 preview_sample_images 必須留空。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "平行欄位測試",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "preview_images": [
                {"large_url": f"https://tp.spfcas.com/img_{i}.jpg"} for i in range(12)
            ],
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert len(video.sample_images) == 12
        assert video.preview_cover_url == ""
        assert video.preview_sample_images == []


# ============================================================
# AC-5｜缺欄位不炸也不回 None 字串
# ============================================================

class TestNullFieldsSafety:
    def test_null_metadata_fields_default_to_empty_string(self, monkeypatch):
        """series_name / director_name / publisher_name 為 null 時，對應欄位為空字串而非 'None'。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "空欄位測試",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "series_name": None,
            "director_name": None,
            "publisher_name": None,
            "maker_name": None,
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.series == ""
        assert video.director == ""
        assert video.label == ""
        assert video.maker == ""


# ============================================================
# AC-6｜型別轉換
# ============================================================

class TestTypeCasting:
    @pytest.mark.parametrize(
        ("score_val", "expected_rating"),
        [
            ("4.13", 4.13),
            (4.13, 4.13),
            (5, 5.0),
            (None, None),
            ("", None),
            ("—", None),
            ("N/A", None),
            ("invalid", None),
        ],
    )
    def test_score_rating_parsing(self, monkeypatch, score_val, expected_rating):
        """score 字串轉 float，無法解析或缺漏時為 None。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "評分測試",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "score": score_val,
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.rating == expected_rating

    @pytest.mark.parametrize(
        ("duration_val", "expected_duration"),
        [
            (150, 150),
            ("150", 150),
            (0, None),
            ("0", None),
            (-10, None),
            (None, None),
            ("invalid", None),
        ],
    )
    def test_duration_parsing(self, monkeypatch, duration_val, expected_duration):
        """duration 為 int，0、負數、None 或無法解析時為 None。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "時長測試",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "duration": duration_val,
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.duration == expected_duration

    @pytest.mark.parametrize(
        ("reviews_val", "expected_votes"),
        [
            (42, 42),
            ("42", 42),
            (0, 0),
            (None, None),
            ("invalid", None),
        ],
    )
    def test_reviews_count_votes_parsing(self, monkeypatch, reviews_val, expected_votes):
        """reviews_count 轉 int votes，None 或無法解析時為 None。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "投票數測試",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "reviews_count": reviews_val,
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.votes == expected_votes


# ============================================================
# AC-7｜欄位對齊（B1 契約）
# ============================================================

class TestFullDetailMapping:
    def test_full_detail_mapping_15_fields(self, monkeypatch):
        """完整詳情物件正確映射至 Video 的所有 15 個欄位。"""
        search_payload = [{"id": "P9QrXa", "number": "SONE-205"}]
        detail_payload = {
            "id": "P9QrXa",
            "number": "SONE-205",
            "title": "新人AVデビュー 未歩なな",
            "cover_url": "https://tp.spfcas.com/covers/sone205.jpg",
            "release_date": "2023-01-01",
            "maker_name": "S1 NO.1 STYLE",
            "director_name": "監督太郎",
            "series_name": "新人デビューシリーズ",
            "publisher_name": "S1 出版",
            "tags": [{"id": 1, "name": "美少女"}, {"id": 2, "name": "單體作品"}],
            "actors": [
                {"id": "a1", "name": "未歩なな", "gender": 0},
                {"id": "a2", "name": "田淵正浩", "gender": 1},
            ],
            "score": "4.13",
            "reviews_count": 42,
            "duration": 150,
            "preview_images": [
                {"large_url": "https://tp.spfcas.com/samples/01.jpg"},
                {"large_url": "https://tp.spfcas.com/samples/02.jpg"},
            ],
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("sone-205")

        assert video is not None
        assert video.number == "sone-205"  # 呼叫端傳入之 number
        assert video.title == "新人AVデビュー 未歩なな"
        assert video.cover_url == "https://tp.spfcas.com/covers/sone205.jpg"
        assert video.date == "2023-01-01"
        assert video.maker == "S1 NO.1 STYLE"
        assert video.director == "監督太郎"
        assert video.series == "新人デビューシリーズ"
        assert video.label == "S1 出版"
        assert video.tags == ["美少女", "單體作品"]
        assert video.actresses == [Actress(name="未歩なな")]
        assert video.rating == 4.13
        assert video.votes == 42
        assert video.duration == 150
        assert video.sample_images == [
            "https://tp.spfcas.com/samples/01.jpg",
            "https://tp.spfcas.com/samples/02.jpg",
        ]
        assert video.source == "javdb"
        assert video.detail_url == "https://javdb.com/v/P9QrXa"
        assert video.preview_cover_url == ""
        assert video.preview_sample_images == []
        assert video.summary == ""


# ============================================================
# AC-8｜空結果判定
# ============================================================

class TestEmptyResults:
    def test_empty_result_when_both_title_and_cover_empty(self, monkeypatch):
        """title 與 cover_url 皆為空時，視為空結果回傳 None。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "",
            "cover_url": "",
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is None

    def test_valid_when_only_cover_url_empty(self, monkeypatch):
        """僅 cover_url 為空但有 title 時，仍回傳 Video 物件。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "有標題無封面",
            "cover_url": "",
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.title == "有標題無封面"
        assert video.cover_url == ""

    def test_valid_when_only_title_empty(self, monkeypatch):
        """僅 title 為空但有 cover_url 時，仍回傳 Video 物件。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.title == ""
        assert video.cover_url == "https://tp.spfcas.com/cover.jpg"

    def test_empty_search_results_returns_none(self, monkeypatch):
        """搜尋結果為空清單時，直接回傳 None 且不調用詳情。"""
        _, mock_detail = _setup_api_mocks(monkeypatch, [], {})

        video = javdb_api.fetch_video("NOTEXIST-999")

        assert video is None
        mock_detail.assert_not_called()


# ============================================================
# AC-9｜例外不被吞
# ============================================================

class TestExceptionsNotSwallowed:
    def test_search_source_blocked_is_not_swallowed(self, monkeypatch):
        """api_search 拋出 SourceBlocked 時，fetch_video 原樣往上拋。"""
        _setup_api_mocks(monkeypatch, search_err=SourceBlocked("blocked 403"))

        with pytest.raises(SourceBlocked):
            javdb_api.fetch_video("SONE-205")

    def test_search_source_unreachable_is_not_swallowed(self, monkeypatch):
        """api_search 拋出 SourceUnreachable 時，fetch_video 原樣往上拋。"""
        _setup_api_mocks(monkeypatch, search_err=SourceUnreachable("timeout"))

        with pytest.raises(SourceUnreachable):
            javdb_api.fetch_video("SONE-205")

    def test_detail_source_blocked_is_not_swallowed(self, monkeypatch):
        """api_movie_detail 拋出 SourceBlocked 時，fetch_video 原樣往上拋。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        _setup_api_mocks(
            monkeypatch,
            search_return=search_payload,
            detail_err=SourceBlocked("blocked 429"),
        )

        with pytest.raises(SourceBlocked):
            javdb_api.fetch_video("SONE-205")

    def test_detail_source_unreachable_is_not_swallowed(self, monkeypatch):
        """api_movie_detail 拋出 SourceUnreachable 時，fetch_video 原樣往上拋。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        _setup_api_mocks(
            monkeypatch,
            search_return=search_payload,
            detail_err=SourceUnreachable("detail failed"),
        )

        with pytest.raises(SourceUnreachable):
            javdb_api.fetch_video("SONE-205")


# ============================================================
# AC-10｜tags 不轉換（CD-132b-17）
# ============================================================

class TestTagsPreserved:
    def test_tags_preserved_as_is_without_conversion(self, monkeypatch):
        """tags 保持 API 回傳之原樣，不得進行簡繁轉換或對照表替換。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        detail_payload = {
            "id": "m1",
            "number": "SONE-205",
            "title": "標籤測試",
            "cover_url": "https://tp.spfcas.com/cover.jpg",
            "tags": [
                {"id": 1, "name": "美少女电影"},
                {"id": 2, "name": "巨乳"},
                {"id": 3, "name": "単体作品"},
            ],
        }
        _setup_api_mocks(monkeypatch, search_payload, detail_payload)

        video = javdb_api.fetch_video("SONE-205")

        assert video is not None
        assert video.tags == ["美少女电影", "巨乳", "単体作品"]


# ============================================================
# review 第 1 輪的補強（sonnet ＋ grok 雙審，2026-08-28）
# ============================================================

class TestReviewRound1Hardening:
    """三條 P3 的正向鎖 ＋ AC-9 的同一顆例外物件斷言。"""

    def test_title_goes_through_the_same_normalization_as_html_path(self, monkeypatch):
        """標題與 HTML 那條走同一支 strip_number_prefix（javdb.py:210）。

        F4：兩條路的標題處理必須逐字相同。站方哪天在 title 前面加上番號時，
        只有一條清掉 ＝ 使用者從 NFO 的 <title> 看得出來走了哪條路。
        """
        _setup_api_mocks(
            monkeypatch,
            search_return=[{"id": "m1", "number": "SONE-205"}],
            detail_return={
                "id": "m1",
                "title": "SONE-205 優しくてイヤだと言えない部活少女",
                "cover_url": "https://tp.spfcas.com/c.jpg",
            },
        )
        video = javdb_api.fetch_video("SONE-205")
        assert video is not None
        assert video.title == "優しくてイヤだと言えない部活少女"

    def test_whitespace_only_tag_name_does_not_become_an_empty_tag(self, monkeypatch):
        """純空白的 tag name 不得變成一顆空的標籤 pill。

        瀏覽頁的標籤篩選是逐字比對 tags 的內容，塞進一個 '' 會多出一顆點不到、
        也刪不掉的空 pill。
        """
        _setup_api_mocks(
            monkeypatch,
            search_return=[{"id": "m1", "number": "SONE-205"}],
            detail_return={
                "id": "m1",
                "title": "t",
                "cover_url": "https://tp.spfcas.com/c.jpg",
                "tags": [{"name": "巨乳"}, {"name": "   "}, {"name": "\t\n"}, {"name": "苗条"}],
            },
        )
        video = javdb_api.fetch_video("SONE-205")
        assert video is not None
        assert video.tags == ["巨乳", "苗条"]
        assert "" not in video.tags

    @pytest.mark.parametrize("bad_url", [{"a": 1}, ["x"], 123, True])
    def test_non_string_large_url_is_dropped_not_passed_to_pydantic(
        self, monkeypatch, bad_url
    ):
        """large_url 不是字串時要丟掉，不得讓 Video 拋 ValidationError。

        fetch_video 的契約只有兩種結局：回 Video 或回 None。讓 pydantic 的
        ValidationError 逃出去，上層的降級分支（T3）接不到，javdb 會整支噴錯。
        """
        _setup_api_mocks(
            monkeypatch,
            search_return=[{"id": "m1", "number": "SONE-205"}],
            detail_return={
                "id": "m1",
                "title": "t",
                "cover_url": "https://tp.spfcas.com/c.jpg",
                "preview_images": [
                    {"large_url": bad_url},
                    {"large_url": "https://tp.spfcas.com/ok.jpg"},
                ],
            },
        )
        video = javdb_api.fetch_video("SONE-205")
        assert video is not None
        assert video.sample_images == ["https://tp.spfcas.com/ok.jpg"]

    def test_search_exception_propagates_as_the_very_same_object(self, monkeypatch):
        """不只是同一個型別——必須是同一顆例外物件。

        「catch 起來再 raise 一個同型別的新例外」型別斷言照樣綠，但那會把
        原始訊息（哪個 host、哪個狀態碼）洗掉，debug.log 就查不出是哪一種了。
        """
        sentinel = SourceBlocked("blocked 403 for https://jdforrepam.com/api/v2/search")
        _setup_api_mocks(monkeypatch, search_err=sentinel)

        with pytest.raises(SourceBlocked) as exc:
            javdb_api.fetch_video("SONE-205")
        assert exc.value is sentinel

    def test_detail_exception_propagates_as_the_very_same_object(self, monkeypatch):
        sentinel = SourceUnreachable("non-200 500 for https://javdb.com/api/v4/movies/m1")
        _setup_api_mocks(
            monkeypatch,
            search_return=[{"id": "m1", "number": "SONE-205"}],
            detail_err=sentinel,
        )

        with pytest.raises(SourceUnreachable) as exc:
            javdb_api.fetch_video("SONE-205")
        assert exc.value is sentinel
