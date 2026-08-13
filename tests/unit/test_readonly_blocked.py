"""test_readonly_blocked.py — TASK-118-T6 P2-1b：唯讀單片 enrich（掃描面板
「補完缺漏」/放大鏡）的被擋訊號要走到 sink，不得被壓成「查無此片」。

sink：`core/readonly_producer.py` 的 `enrich_one_readonly`——`resolve_ingest_plan`
回 `meta=None` 時（找不到可用番號資料），改前無條件呼叫 `_readonly_stub_not_found`
記 `scrape_attempted_at`，即使原因是「來源被擋」而非「真的查無」。與
`core/enricher.py` 非唯讀路徑（`tests/unit/test_enricher_blocked.py`）同一個 sink
形狀：那幾片會從缺漏清單永久消失，且**不需要** AI agent、不需要 `refresh_full`——
scanner 面板的真實點擊（`mode='fill_missing'`）就會走到這條唯讀分支。

測試接縫：patch `core.readonly_producer.resolve_ingest_plan`（與既有
`tests/unit/test_readonly_producer.py::TestEnrichOneReadonlyEntryPoint` 同一個
mock 邊界），side_effect 讀 `blocked_out` kwarg 並依需要塞入一筆 `BlockedRecord`、
回 `(None, ('none',))`。另 patch `core.readonly_producer._readonly_stub_not_found`
（module-level 直接呼叫，patch 該 module 屬性即可攔截同 module 內的呼叫）斷言
呼叫與否。
"""

from unittest.mock import MagicMock, patch

from core.scrapers.errors import BlockedRecord


def _base_kwargs(repo_factory, **overrides):
    kwargs = dict(
        repo_factory=repo_factory,
        ro_source=MagicMock(name="ro_src"),
        output_root="/out",
        output_uri="file:///out",
        canonical="file:///src/videos/FC2-PPV-1234567.mp4",
        file_path="file:///src/videos/FC2-PPV-1234567.mp4",
        number="FC2-PPV-1234567",
        scraper_cfg={},
        path_mappings={},
        action="ingest",
        proxy_url="",
        scraper_data=None,
        scrape_source=None,
        javbus_lang=None,
        write_cover=True,
        overwrite_existing=False,
    )
    kwargs.update(overrides)
    return kwargs


def _fill_blocked_resolve_ingest_plan(*records):
    """假 `resolve_ingest_plan`：把呼叫端傳入的 `blocked_out` list 填入 `records`，
    回 `(None, ('none',))`（找不到可用 meta，觸發 not-found 分流）。"""

    def _fn(*args, **kwargs):
        blocked_out = kwargs.get("blocked_out")
        if blocked_out is not None:
            blocked_out.extend(records)
        return None, ("none",)

    return _fn


class TestEnrichOneReadonlyBlockedSink:
    """#9 唯讀單片：來源被擋 → `_readonly_stub_not_found` 未被呼叫、reason == 'blocked'。"""

    def test_blocked_does_not_call_stub_and_reason_is_blocked(self):
        from core.readonly_producer import enrich_one_readonly

        repo_factory = MagicMock()
        record = BlockedRecord(source_id="fc2", article_id="FC2-PPV-1234567", status=403)

        with (
            patch(
                "core.readonly_producer.resolve_ingest_plan",
                side_effect=_fill_blocked_resolve_ingest_plan(record),
            ) as mock_plan,
            patch("core.readonly_producer._readonly_stub_not_found") as mock_stub,
        ):
            result = enrich_one_readonly(**_base_kwargs(repo_factory))

        mock_plan.assert_called_once()
        mock_stub.assert_not_called()
        repo_factory.assert_not_called()
        assert result.success is False
        assert result.reason == "blocked"
        assert result.error == "找不到可用的番號資料"


class TestEnrichOneReadonlyNotFoundZeroRegression:
    """#10 唯讀單片：真的查無 → 既有行為逐字不變（stub 呼叫 ＋ attempted 照記、
    reason == 'not_found'）。"""

    def test_not_found_still_stubs_and_reason_not_found(self):
        from core.readonly_producer import enrich_one_readonly

        repo = MagicMock()
        repo_factory = MagicMock(return_value=repo)

        with (
            patch(
                "core.readonly_producer.resolve_ingest_plan",
                side_effect=_fill_blocked_resolve_ingest_plan(),  # 空 → 不塞 blocked_out
            ) as mock_plan,
            patch("core.readonly_producer._readonly_stub_not_found") as mock_stub,
        ):
            result = enrich_one_readonly(**_base_kwargs(repo_factory))

        mock_plan.assert_called_once()
        mock_stub.assert_called_once_with(repo, "file:///src/videos/FC2-PPV-1234567.mp4", "FC2-PPV-1234567", "/src/videos/FC2-PPV-1234567.mp4")
        assert result.success is False
        assert result.reason == "not_found"
        assert result.error == "找不到可用的番號資料"


# ---------------------------------------------------------------------------
# P2-1b bulk：produce_source（唯讀來源整批產出）的同一個 sink
# ---------------------------------------------------------------------------

class TestProduceSourceBlockedSink:
    """唯讀批次：被擋的片不得記 scrape_attempted_at，但仍走 no_scrape 計數與
    進度事件，且整批不中止（卡片必備測試 #11）。"""

    def _run(self, blocked: bool):
        from core.readonly_producer import produce_source

        source = MagicMock()
        source.readonly = True
        source.output_path = "/output/dest"
        source.path = "/src/videos"
        config = {"gallery": {}, "scraper": {}}

        repo = MagicMock()
        repo.get_attempted_index.return_value = {}
        repo.get_by_path.return_value = None
        repo.is_output_dir_taken.return_value = False
        repo.get_all.return_value = []

        files = [
            {"path": "/src/videos/FC2-PPV-1234567.mp4", "size": 1_000_000, "mtime": 1.0, "nfo_mtime": 0.0},
            {"path": "/src/videos/FC2-PPV-7654321.mp4", "size": 1_000_000, "mtime": 1.0, "nfo_mtime": 0.0},
        ]

        def fake_search_jav(number, source="auto", proxy_url="", javbus_lang=None, blocked_out=None):
            # 被擋：search_jav 內部把 SourceBlocked 就地記進 blocked_out 後回 None
            # （core/scraper.py 的 _record_blocked）；真的查無：只回 None。
            if blocked and blocked_out is not None:
                blocked_out.append(BlockedRecord(source_id="fc2", article_id=number, status=403))
            return None

        events = []
        with patch("core.readonly_producer._list_source_videos", return_value=files), \
             patch("core.readonly_producer.search_jav", side_effect=fake_search_jav), \
             patch("core.readonly_producer._readonly_stub_not_found") as stub:
            result = produce_source(
                source, config, repo,
                on_progress=lambda *a, **k: events.append(a),
            )
        return result, stub, events

    def test_blocked_does_not_record_attempted_and_batch_continues(self):
        result, stub, events = self._run(blocked=True)
        assert stub.call_count == 0, "被擋時不得寫 scrape_attempted_at（否則該片從缺漏清單永久消失）"
        assert result.no_scrape == 2, "被擋仍要計 no_scrape，且兩片都要跑完（整批不中止）"
        assert len(events) == 2

    def test_not_found_still_records_attempted(self):
        result, stub, events = self._run(blocked=False)
        assert stub.call_count == 2, "真的查無時，既有記帳行為逐字不變"
        assert result.no_scrape == 2
        assert len(events) == 2
