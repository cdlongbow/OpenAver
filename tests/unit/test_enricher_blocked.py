"""TASK-118-T4b：enricher 被擋時不記 scrape_attempted_at。"""

from unittest.mock import MagicMock, patch

from core.scrapers.errors import BlockedRecord


def _fc2_record(article_id="FC2-PPV-1234567"):
    return BlockedRecord(source_id="fc2", article_id=article_id, status=403)


def _fill_blocked(result, *records):
    def _fn(*args, **kwargs):
        blocked_out = kwargs.get("blocked_out")
        if blocked_out is not None:
            blocked_out.extend(records)
        return result

    return _fn


def _make_video(number="SONE-205"):
    from core.database import Video

    return Video(
        number=number,
        title="テストタイトル",
        original_title="テストタイトル",
        actresses=["女優A"],
        maker="SOD",
        director="テスト監督",
        series="テストシリーズ",
        label="LABEL",
        tags=["タグ"],
        sample_images=[],
        duration=120,
        cover_path="https://example.com/cover.jpg",
        release_date="2024-01-01",
    )


def _make_scraper_result(number="SONE-205"):
    return {
        "number": number,
        "title": "テストタイトル",
        "actors": ["女優A"],
        "cover": "https://example.com/cover.jpg",
        "date": "2024-01-01",
        "maker": "SOD",
        "director": "テスト監督",
        "series": "テストシリーズ",
        "label": "LABEL",
        "tags": ["タグ"],
        "sample_images": [],
        "duration": 120,
        "url": "https://www.javbus.com/SONE-205",
        "source": "javbus",
    }


# ── 7 enricher sink：blocked 不記 attempted ────────────────────────────────


def test_enricher_blocked_does_not_record_scrape_attempted_at(tmp_path):
    """#7 被擋 → reason==blocked 且 update_scrape_attempted_at 未被呼叫。"""
    video_file = tmp_path / "FC2-PPV-1234567.mp4"
    video_file.write_bytes(b"x")

    with (
        patch("core.enricher.VideoRepository") as mock_repo_cls,
        patch(
            "core.enricher.search_jav",
            side_effect=_fill_blocked(None, _fc2_record()),
        ),
    ):
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        from core.enricher import enrich_single

        result = enrich_single(
            file_path=str(video_file),
            number="FC2-PPV-1234567",
            mode="refresh_full",
        )

    assert result.success is False
    assert result.reason == "blocked"
    assert result.error == "找不到 FC2-PPV-1234567 的資料"
    mock_repo.update_scrape_attempted_at.assert_not_called()


def test_enricher_fill_missing_blocked_does_not_record_scrape_attempted_at(tmp_path):
    """接線點 #6 第二處 search_jav（fill_missing）。"""
    video_file = tmp_path / "FC2-PPV-1234567.mp4"
    video_file.write_bytes(b"x")

    with (
        patch("core.enricher.VideoRepository") as mock_repo_cls,
        patch(
            "core.enricher.search_jav",
            side_effect=_fill_blocked(None, _fc2_record()),
        ),
    ):
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        mock_repo.get_by_numbers.return_value = {}

        from core.enricher import enrich_single

        result = enrich_single(
            file_path=str(video_file),
            number="FC2-PPV-1234567",
            mode="fill_missing",
        )

    assert result.success is False
    assert result.reason == "blocked"
    mock_repo.update_scrape_attempted_at.assert_not_called()


# ── 8 enricher：not_found 仍照記 ──────────────────────────────────────────


def test_enricher_not_found_still_records_scrape_attempted_at(tmp_path):
    """#8 真的查無資料 → reason==not_found 且 update_scrape_attempted_at 有被呼叫。"""
    video_file = tmp_path / "SONE-205.mp4"
    video_file.write_bytes(b"x")

    with (
        patch("core.enricher.VideoRepository") as mock_repo_cls,
        patch("core.enricher.search_jav", return_value=None),
    ):
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        from core.enricher import enrich_single

        result = enrich_single(
            file_path=str(video_file),
            number="SONE-205",
            mode="refresh_full",
        )

    assert result.success is False
    assert result.reason == "not_found"
    assert result.error == "找不到 SONE-205 的資料"
    mock_repo.update_scrape_attempted_at.assert_called_once()


# ── 9 批次：一片被擋不中止整批 ────────────────────────────────────────────


def test_batch_enrich_one_blocked_does_not_abort(tmp_path):
    """#9 一片被擋、另一片 not_found → 整批不中止，逐項 reason 分得出來。"""
    blocked_file = tmp_path / "FC2-PPV-1.mp4"
    blocked_file.write_bytes(b"x")
    missing_file = tmp_path / "SONE-205.mp4"
    missing_file.write_bytes(b"x")

    def _search(number, **kwargs):
        blocked_out = kwargs.get("blocked_out")
        if number.startswith("FC2"):
            if blocked_out is not None:
                blocked_out.append(_fc2_record(article_id=number))
            return None
        return None

    with (
        patch("core.enricher.VideoRepository") as mock_repo_cls,
        patch("core.enricher.search_jav", side_effect=_search),
    ):
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        from core.enricher import enrich_single

        results = []
        for path, number in (
            (str(blocked_file), "FC2-PPV-1"),
            (str(missing_file), "SONE-205"),
        ):
            results.append(
                enrich_single(file_path=path, number=number, mode="refresh_full")
            )

    assert [r.reason for r in results] == ["blocked", "not_found"]
    assert mock_repo.update_scrape_attempted_at.call_count == 1
