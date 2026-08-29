"""TASK-134a-T4 + TASK-134b-T10 — _search_content_id / 第二試 / 番號驗證."""
import logging
from unittest.mock import MagicMock, patch

import pytest

import core.scrapers.dmm as dmm_module
from core.scrapers.dmm import DMMScraper
from core.scrapers.models import ScraperConfig, Video

LOG_SNIPPET = "搜尋 API 查無結果"


def _make_mock_resp(status_code=200, json_data=None):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    if json_data is not None:
        mock_resp.json = lambda: json_data
    return mock_resp


def _legacy_search_payload(cids: list[str]) -> dict:
    return {
        "data": {
            "legacySearchPPV": {
                "result": {
                    "contents": [{"id": cid} for cid in cids],
                }
            }
        }
    }


@pytest.fixture
def dmm_scraper(monkeypatch):
    import core.scrapers.dmm as dmm_module

    monkeypatch.setattr(dmm_module, "rate_limit", lambda *a, **kw: None)
    return DMMScraper(ScraperConfig(proxy_url="http://test-proxy:8080"))


def test_learn_prefix_and_save_prefix_hint_removed():
    assert hasattr(DMMScraper, "_learn_prefix") is False
    assert hasattr(DMMScraper, "_save_prefix_hint") is False


def test_search_content_id_rejects_gerk116_for_erk_prefix(dmm_scraper):
    """DoD 3 反向鎖：僅有 gerk116 時不得誤配 ERK-116。"""
    resp = _make_mock_resp(
        status_code=200,
        json_data=_legacy_search_payload(["gerk116"]),
    )
    with patch.object(dmm_scraper._session, "post", return_value=resp):
        assert dmm_scraper._search_content_id("ERK-116") is None


def test_search_content_id_accepts_erk00116(dmm_scraper):
    """DoD 4 正向鎖：含 erk00116 時精確命中。"""
    resp = _make_mock_resp(
        status_code=200,
        json_data=_legacy_search_payload(["gerk116", "erk00116"]),
    )
    with patch.object(dmm_scraper._session, "post", return_value=resp):
        assert dmm_scraper._search_content_id("ERK-116") == "erk00116"


# ── TASK-134b-T10 DoD 1–4 ────────────────────────────────────────────────────


def test_search_content_id_query_word_is_pfx_space_num(dmm_scraper):
    """DoD 1：_search_content_id 送出的 queryWord 是 'PFX NUM' 形狀。"""
    resp = _make_mock_resp(
        status_code=200,
        json_data=_legacy_search_payload([]),
    )
    with patch.object(dmm_scraper._session, "post", return_value=resp) as mock_post:
        dmm_scraper._search_content_id("START-525")

    assert mock_post.called
    payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
    assert payload["variables"]["queryWord"] == "START 525"


def test_second_try_called_with_unpadded_cid_when_padded_fails(
    dmm_scraper, monkeypatch
):
    """DoD 2 反向：補零失敗 → 第二試被呼叫，且送出不補零 cid。"""
    convert_calls = []

    def convert(number, zfill=True):
        convert_calls.append({"number": number, "zfill": zfill})
        return "midd00357" if zfill else "midd357"

    fetch_calls = []

    def fetch(cid):
        fetch_calls.append(cid)
        if cid == "midd357":
            return Video(number="MIDD-357", title="t", source="dmm")
        return None

    monkeypatch.setattr(dmm_scraper, "_convert_with_hints", convert)
    monkeypatch.setattr(dmm_scraper, "_fetch_by_id", fetch)
    monkeypatch.setattr(dmm_scraper, "_search_content_id", lambda number: None)

    result = dmm_scraper.search("MIDD-357")

    assert result is not None
    assert result.number == "MIDD-357"
    assert {"number": "MIDD-357", "zfill": False} in convert_calls
    assert fetch_calls == ["midd00357", "midd357"]


def test_second_try_not_called_when_padded_succeeds(dmm_scraper, monkeypatch):
    """DoD 2 正向鎖：補零成功 → 第二試完全不被呼叫。"""
    convert_calls = []

    def convert(number, zfill=True):
        convert_calls.append(zfill)
        return "sone00205"

    monkeypatch.setattr(dmm_scraper, "_convert_with_hints", convert)
    monkeypatch.setattr(
        dmm_scraper,
        "_fetch_by_id",
        lambda cid: Video(number="SONE-205", title="t", source="dmm"),
    )
    step3_called = {"v": False}

    def step3(number):
        step3_called["v"] = True
        return None

    monkeypatch.setattr(dmm_scraper, "_search_content_id", step3)

    result = dmm_scraper.search("SONE-205")

    assert result is not None
    assert convert_calls == [True]
    assert step3_called["v"] is False


def test_second_try_skipped_when_cid_identical(dmm_scraper, monkeypatch):
    """DoD 2 / D3：num 已是 5 位時兩式 cid 相同 → 不發第二次 HTTP。"""
    fetch_calls = []

    def fetch(cid):
        fetch_calls.append(cid)
        return None

    monkeypatch.setattr(dmm_scraper, "_fetch_by_id", fetch)
    monkeypatch.setattr(dmm_scraper, "_search_content_id", lambda number: None)

    # MIDD-00357 → num="00357"；zfill(5) 後仍是 "00357"，兩式 cid 逐字相同
    dmm_scraper.search("MIDD-00357")

    assert fetch_calls == ["midd00357"]


def test_number_mismatch_rejected_on_second_try_and_step3(
    dmm_scraper, monkeypatch, caplog
):
    """DoD 3 反向鎖：第二試／步驟 3 拿到 number 不符的 Video → 不回傳、不印 F5。

    必須含「兩邊都能 _parse_number 但 tuple 不等」的案例，否則 mutation 把
    helper 末行改成 return True 時仍會被「解析不出 → return False」提前擋掉而 SURVIVED。
    """
    # 兩邊都解析得出、但 prefix/num 不同（守住 helper 末行的 tuple 比對）
    wrong_but_parseable = Video(number="MIDD-999", title="wrong", source="dmm")
    # 解析不出／空字串（守住「任一側解不出即不符」）
    unparseable = Video(number="MCSR-191-02", title="wrong", source="dmm")
    empty_number = Video(number="", title="empty", source="dmm")

    # --- 路徑 A：第二試回「可解析但番號不符」Video ---
    def convert_a(number, zfill=True):
        return "midd00357" if zfill else "midd357"

    def fetch_a(cid):
        if cid == "midd357":
            return wrong_but_parseable
        return None

    monkeypatch.setattr(dmm_scraper, "_convert_with_hints", convert_a)
    monkeypatch.setattr(dmm_scraper, "_fetch_by_id", fetch_a)
    monkeypatch.setattr(dmm_scraper, "_search_content_id", lambda number: None)

    with caplog.at_level(logging.DEBUG, logger=dmm_module.logger.name):
        result_a = dmm_scraper.search("MIDD-357")

    assert result_a is None

    caplog.clear()

    # --- 路徑 B：步驟 3 回空 number ---
    monkeypatch.setattr(dmm_scraper, "_convert_with_hints", lambda number, zfill=True: "")
    monkeypatch.setattr(
        dmm_scraper, "_search_content_id", lambda number: "h_1787mcsr19102"
    )
    monkeypatch.setattr(
        dmm_scraper,
        "_fetch_by_id",
        lambda cid: empty_number if cid == "h_1787mcsr19102" else None,
    )

    with caplog.at_level(logging.DEBUG, logger=dmm_module.logger.name):
        result_b = dmm_scraper.search("MCSR-191")

    assert result_b is None
    assert not any(LOG_SNIPPET in r.getMessage() for r in caplog.records)

    caplog.clear()

    # 路徑 B'：步驟 3 回 MCSR-191-02（_parse_number 解不出 → 不符）
    monkeypatch.setattr(
        dmm_scraper,
        "_fetch_by_id",
        lambda cid: unparseable if cid == "h_1787mcsr19102" else None,
    )

    with caplog.at_level(logging.DEBUG, logger=dmm_module.logger.name):
        result_b2 = dmm_scraper.search("MCSR-191")

    assert result_b2 is None
    assert not any(LOG_SNIPPET in r.getMessage() for r in caplog.records)

    caplog.clear()

    # 路徑 B''：步驟 3 回「可解析但番號不符」（與路徑 A 對稱，守住 helper 末行）
    monkeypatch.setattr(
        dmm_scraper, "_search_content_id", lambda number: "midd00999"
    )
    monkeypatch.setattr(
        dmm_scraper,
        "_fetch_by_id",
        lambda cid: wrong_but_parseable if cid == "midd00999" else None,
    )

    with caplog.at_level(logging.DEBUG, logger=dmm_module.logger.name):
        result_b3 = dmm_scraper.search("MIDD-357")

    assert result_b3 is None
    assert not any(LOG_SNIPPET in r.getMessage() for r in caplog.records)


def test_padded_first_try_returns_mismatched_number_without_validation(
    dmm_scraper, monkeypatch
):
    """DoD 4 正向鎖：補零主路徑刻意不加驗證——number 不符的 Video 仍被回傳。"""
    mismatched = Video(number="OTHER-999", title="t", source="dmm")

    monkeypatch.setattr(
        dmm_scraper, "_convert_with_hints", lambda number, zfill=True: "midd00357"
    )
    monkeypatch.setattr(
        dmm_scraper,
        "_fetch_by_id",
        lambda cid: mismatched if cid == "midd00357" else None,
    )
    step3_called = {"v": False}

    def step3(number):
        step3_called["v"] = True
        return None

    monkeypatch.setattr(dmm_scraper, "_search_content_id", step3)

    result = dmm_scraper.search("MIDD-357")

    assert result is mismatched
    assert step3_called["v"] is False


def test_number_matches_tolerates_zero_padding_difference(dmm_scraper):
    """D4 的補零寬容是刻意的契約，不是可以「順手簡化」掉的細節。

    DMM 的 ``makerContentId`` 與使用者輸入的補零位數不保證一致。若比對改成逐字
    相等，回 ``MIDD-00357`` 而使用者打 ``MIDD-357`` 就會被判成別部片 → 步驟 2
    第二試與步驟 3 雙雙視同未命中 → 畫面上是「DMM 沒有這部片」，而它其實找到了。

    2026-08-29：這一行原本沒有任何測試守著（Opus 自選 mutation 打出 SURVIVED），
    本測試就是那道鎖。反向案確保它沒有寬容過頭——番號真的不同仍必須判不符。
    """
    # 正向：只有補零位數不同 → 視為同一片
    assert dmm_scraper._number_matches("MIDD-00357", "MIDD-357") is True
    assert dmm_scraper._number_matches("MIDD-357", "MIDD-00357") is True

    # 反向：數字真的不同 → 仍必須判不符（別把寬容做成無條件放行）
    assert dmm_scraper._number_matches("MIDD-00358", "MIDD-357") is False
    # 反向：前綴不同 → 不符
    assert dmm_scraper._number_matches("KAWD-00357", "MIDD-357") is False
    # 反向：三段番號解析不出來 → 不符（這是擋掉 MCSR-191-02 的那一條）
    assert dmm_scraper._number_matches("MCSR-191-02", "MCSR-191") is False


def test_convert_with_hints_zfill_flag_changes_the_cid(dmm_scraper, monkeypatch):
    """D1 的 zfill 開關本體要有直接的鎖，不能只靠呼叫端與 mock 序列。

    2026-08-29 review（grok P2）：DoD 2 的反向鎖把 ``_convert_with_hints`` 整支
    mock 掉、只鎖「search() 有傳 zfill=False」；而 D3 跳過那支用的是已經 5 位數的
    ``MIDD-00357``（兩式本來就相同）。⇒ 把 ``num.zfill(5) if zfill else num``
    改成永遠補零之後，本檔測試全綠——真正紅的是
    ``tests/unit/test_scraper_dmm_direct.py::test_dmm_graphql_success``，
    而它是靠 mock 序列的格數**間接**接住的（已用 mutation 逐檔確認）。

    間接的保護會被「順手清掉一格用不到的 mock」洗掉，所以這裡補一支直接斷言。

    使用者流程：這行失效 → ``MIDD-357`` 這類「補零 404、不補零才有片」的老片
    第二試組出的 cid 與第一試逐字相同 → 被 D3 的去重條件跳過 → 路徑 (b) 整條死掉
    → 畫面上是「DMM 沒有這部片」，而 ``midd357`` 直拉其實是有的。
    """
    monkeypatch.setattr(dmm_scraper, "_prefix_map", lambda: {})

    assert dmm_scraper._convert_with_hints("MIDD-357") == "midd00357"
    assert dmm_scraper._convert_with_hints("MIDD-357", zfill=True) == "midd00357"
    assert dmm_scraper._convert_with_hints("MIDD-357", zfill=False) == "midd357"

    # 前綴有值時兩式都要帶上它（證明 zfill 只影響補零，不影響前綴組裝）
    monkeypatch.setattr(dmm_scraper, "_prefix_map", lambda: {"nwf": "3"})
    assert dmm_scraper._convert_with_hints("NWF-237") == "3nwf00237"
    assert dmm_scraper._convert_with_hints("NWF-237", zfill=False) == "3nwf237"
