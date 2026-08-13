"""test_batch_enrich_blocked.py — TASK-118-T6 P2-1：批次 enrich pre-fetch 負快取
不得把「被擋」壓成「查無」。

sink：`web/routers/scraper.py:898-919` refresh_full 專用 pre-fetch 若把
`search_jav()` 回 None（含被擋）無條件寫進 `scraper_cache[cache_key] = {}`，
`enrich_single` 收到 `{}` 時 `scraper_data is None` 為 False → 不會自己重搜、
自己的 `blocked_out` 永遠是空的 → `reason` 判成 `not_found`、且
`update_scrape_attempted_at` 照記——那幾片從缺漏清單永久消失。

測試接縫（卡片已驗過可行）：**不 mock `enrich_single`**（既有
`tests/integration/test_batch_enrich_reason.py` 整顆 mock 掉 `enrich_single`，
測不到這個 bug）。改為 patch 兩個 `search_jav` 呼叫點：
- `web.routers.scraper.search_jav`（pre-fetch 那顆 symbol）
- `core.enricher.search_jav`（`enrich_single` 收到 `scraper_data=None` 時，
  自己重搜那一顆——與 pre-fetch 是不同模組各自的 import binding，不patch
  兩處，被擋分支的第二次呼叫會打真網路）
兩處共用同一顆假函式，依 number 分派「blocked / not_found / found」。
另 patch `core.enricher.VideoRepository`，斷言 `update_scrape_attempted_at`
呼叫與否。
"""

import json

import pytest

from core.path_utils import to_file_uri
from core.scrapers.errors import BlockedRecord


def parse_sse(text: str) -> list:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _make_fake_search_jav(behaviors: dict):
    """behaviors: {number: 'blocked' | 'not_found' | 'found'}，未列出的番號預設 not_found。

    簽章對齊 `core.scraper.search_jav`：`(number, source='auto', proxy_url='',
    javbus_lang=None, blocked_out=None)`。回傳同一顆物件，`.calls` 記錄每次
    呼叫的 number，供斷言呼叫次數（P2-1 test #2 的負快取「不重打」）。
    """
    calls = []

    def _fake(number, source="auto", proxy_url="", javbus_lang=None, blocked_out=None):
        calls.append(number)
        behavior = behaviors.get(number, "not_found")
        if behavior == "blocked":
            if blocked_out is not None:
                blocked_out.append(BlockedRecord(source_id="fc2", article_id=number, status=403))
            return None
        if behavior == "found":
            return {
                "number": number,
                "title": "測試標題",
                "source": "javbus",
                "cover": "",
                "actors": [],
                "tags": [],
                "sample_images": [],
            }
        return None

    _fake.calls = calls
    return _fake


@pytest.fixture
def _video_file(tmp_path):
    def _make(name="FC2-PPV-1234567.mp4"):
        f = tmp_path / name
        f.write_bytes(b"x")
        return f
    return _make


class TestBatchEnrichPrefetchBlocked:
    """#1 pre-fetch 被擋 → update_scrape_attempted_at 未被呼叫，reason == 'blocked'。"""

    def test_blocked_prefetch_does_not_record_attempted_and_reason_blocked(
        self, client, mocker, _video_file
    ):
        number = "FC2-PPV-1234567"
        video = _video_file(f"{number}.mp4")
        fake = _make_fake_search_jav({number: "blocked"})
        mocker.patch("web.routers.scraper.search_jav", side_effect=fake)
        mocker.patch("core.enricher.search_jav", side_effect=fake)
        mock_repo_cls = mocker.patch("core.enricher.VideoRepository")
        mock_repo = mock_repo_cls.return_value
        mock_repo.get_by_numbers.return_value = {}

        response = client.post("/api/batch-enrich", json={
            "items": [{"file_path": to_file_uri(str(video)), "number": number}],
            "mode": "refresh_full",
        })

        assert response.status_code == 200
        result_items = [e for e in parse_sse(response.text) if e["type"] == "result-item"]
        assert len(result_items) == 1
        assert result_items[0]["success"] is False
        assert result_items[0]["reason"] == "blocked"
        mock_repo.update_scrape_attempted_at.assert_not_called()
        # pre-fetch 一次 + enrich_single 內部重搜一次（cache 未寫入 → cached_data=None）
        assert fake.calls == [number, number]


class TestBatchEnrichPrefetchNegativeCacheStillWorks:
    """#2 pre-fetch 真的查無（not_found）→ 負快取仍生效：同番號第二片不重打
    search_jav，且 attempted 照記（不得因修 P2-1 把負快取整個廢掉）。"""

    def test_not_found_prefetch_negative_cache_dedupes_second_item(
        self, client, mocker, _video_file
    ):
        number = "XXX-999"
        video1 = _video_file("XXX-999-a.mp4")
        video2 = _video_file("XXX-999-b.mp4")
        fake = _make_fake_search_jav({})  # 全部 not_found
        mocker.patch("web.routers.scraper.search_jav", side_effect=fake)
        # enrich_single 收到 cached_data={}（非 None）→ 不會再呼叫 core.enricher.search_jav；
        # 仍要 patch 掉、且不允許被呼叫，才能證明「不重打」不是巧合。
        mock_inner = mocker.patch("core.enricher.search_jav")
        mock_repo_cls = mocker.patch("core.enricher.VideoRepository")
        mock_repo = mock_repo_cls.return_value
        mock_repo.get_by_numbers.return_value = {}

        response = client.post("/api/batch-enrich", json={
            "items": [
                {"file_path": to_file_uri(str(video1)), "number": number},
                {"file_path": to_file_uri(str(video2)), "number": number},
            ],
            "mode": "refresh_full",
        })

        assert response.status_code == 200
        result_items = [e for e in parse_sse(response.text) if e["type"] == "result-item"]
        assert len(result_items) == 2
        for item in result_items:
            assert item["success"] is False
            assert item["reason"] == "not_found"
        # 負快取仍生效：pre-fetch 的 search_jav 只被打一次（第二片直接吃 cache）
        assert fake.calls == [number]
        mock_inner.assert_not_called()
        # attempted 照記：兩片都真的查無，各自記一次
        assert mock_repo.update_scrape_attempted_at.call_count == 2


class TestBatchEnrichMixedBlockedAndNormalDoesNotAbort:
    """#3 一片被擋、另一片正常（未被擋）→ 整批不中止。"""

    def test_one_blocked_one_not_found_both_complete(
        self, client, mocker, _video_file
    ):
        blocked_number = "FC2-PPV-2222222"
        normal_number = "XXX-111"
        video1 = _video_file(f"{blocked_number}.mp4")
        video2 = _video_file(f"{normal_number}.mp4")
        fake = _make_fake_search_jav({blocked_number: "blocked"})
        mocker.patch("web.routers.scraper.search_jav", side_effect=fake)
        mocker.patch("core.enricher.search_jav", side_effect=fake)
        mock_repo_cls = mocker.patch("core.enricher.VideoRepository")
        mock_repo = mock_repo_cls.return_value
        mock_repo.get_by_numbers.return_value = {}

        response = client.post("/api/batch-enrich", json={
            "items": [
                {"file_path": to_file_uri(str(video1)), "number": blocked_number},
                {"file_path": to_file_uri(str(video2)), "number": normal_number},
            ],
            "mode": "refresh_full",
        })

        assert response.status_code == 200
        events = parse_sse(response.text)
        result_items = [e for e in events if e["type"] == "result-item"]
        done_events = [e for e in events if e["type"] == "done"]
        assert len(result_items) == 2
        assert len(done_events) == 1
        assert done_events[0]["summary"]["total"] == 2

        by_number = {item["number"]: item for item in result_items}
        assert by_number[blocked_number]["reason"] == "blocked"
        assert by_number[normal_number]["reason"] == "not_found"
