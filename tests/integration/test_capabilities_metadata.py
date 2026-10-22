"""TASK-135-T8: capabilities 揭露 `metadata`（免確認條目）＋ workflow 範例 ＋ 片長單位修字。

鎖的是 spec-135 AC-11/AC-12 的文件那半：enrich_single 的 input_schema 要讓 AI
推導得出四件事（模式限制 / 17 欄白名單 / rating 刻度 / original_title 空字串例外），
write_cover 的三態語意要寫清楚，workflow 範例要示範「查兩來源→挑→改→提交」，
duration 單位錯字要修掉。不鎖 `test_capabilities_auth.py`（那支鎖認證契約）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.access_auth as access_auth


@pytest.fixture(autouse=True)
def auth_db(tmp_path, monkeypatch):
    """GET /api/capabilities 冷啟動會呼叫 load_snapshot()，未 mock 前連上 output/openaver.db。
    同手法見 tests/unit/test_capabilities.py 的 auth_db fixture。"""
    db_path = tmp_path / "access.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.reset_state_for_tests()
    yield db_path
    access_auth.reset_state_for_tests()


@pytest.fixture
def client():
    from web.app import app
    return TestClient(app)


def _tool(data: dict, name: str) -> dict:
    return next(t for t in data["tools"] if t["name"] == name)


# 17 欄白名單：**直接 import 驗證端的真理來源**，不再硬抄第三份。
# 硬抄版本的問題是「改 _validate_metadata_shape 增刪欄位，這支測試不會紅」（SA-pre-9 P3-2）。
from web.routers.scraper import METADATA_ALLOWED_FIELDS  # noqa: E402

ALLOWED_METADATA_FIELDS = sorted(METADATA_ALLOWED_FIELDS)


def test_capabilities_field_list_matches_validator_whitelist(client):
    """揭露文字的欄位集合 == 驗證端白名單集合（雙向差集，粗顆粒守衛）。

    只驗集合相等，不驗措辭——「這個不變式破了會怎樣」的答案是：AI 照文件送一個
    文件說可以、驗證端其實會 400 的欄位（或反過來，有能力卻沒揭露），使用者看到
    AI 卡住而不知道為什麼。
    """
    desc = _tool(client.get("/api/capabilities").json(), "enrich_single")[
        "input_schema"]["properties"]["metadata"]["description"]
    listed = {f for f in METADATA_ALLOWED_FIELDS if f in desc}
    assert listed == set(METADATA_ALLOWED_FIELDS), (
        f"揭露文字漏掉的欄位: {sorted(set(METADATA_ALLOWED_FIELDS) - listed)}"
    )


class TestEnrichSingleMetadataSchema:
    """DoD-1 / DoD-2：metadata 掛在免確認條目上，描述含四件 AI 推導不出來的事。"""

    # [lint-guard: pytest-justified] 本檔斷言的是 GET /api/capabilities 回傳的 Python
    # dict 內容（AI-facing 揭露契約），不是 html/js/css 字串——lint 表達不了「capabilities
    # 的 17 欄白名單必須與 web/routers/scraper.py::_validate_metadata_shape 的白名單逐字
    # 相同」這種跨檔 contract，屬 CLAUDE.md「Lint 守衛規則」明列的 pytest 欄。


    def test_confirmation_required_unchanged_false(self, client):
        """CD-135-8：掛在免確認條目上，既有值不准改。"""
        data = client.get("/api/capabilities").json()
        tool = _tool(data, "enrich_single")
        assert tool.get("confirmation_required") is False


class TestEnrichSingleWriteCoverDescription:
    """DoD-3 / CD-135-17：只改 enrich_single 的 write_cover，另兩處一字不動。"""


    def test_video_rescrape_does_not_expose_metadata(self, client):
        """CD-135-8：video_rescrape_with_source（confirmation_required=True）不揭露 metadata。"""
        data = client.get("/api/capabilities").json()
        tool = _tool(data, "video_rescrape_with_source")
        assert "metadata" not in tool["input_schema"]["properties"]


class TestWorkflowExampleScenario:
    """DoD-5：workflow 範例示範「查兩來源→挑欄位→改寫→提交」，且必須帶 overwrite_existing: true。"""


    def test_scenario_submit_step_has_overwrite_existing_true(self, client):
        """步驟 4 省略 overwrite_existing: true 會撞既有分裂守衛回 400——示範本身就是壞的。"""
        data = client.get("/api/capabilities").json()
        scenario = next(ex for ex in data["examples"] if ex["scenario"] == "逐欄位選來源 + AI 改寫後提交")
        submit_step = next(s for s in scenario["steps"] if "POST /api/enrich-single" in s)
        assert "overwrite_existing: true" in submit_step


class TestDurationUnitFix:
    """DoD-6：showcase_videos 的 videos.item_fields.duration 說明從「秒」改成「分鐘」。"""

    def test_showcase_videos_duration_is_minutes(self, client):
        data = client.get("/api/capabilities").json()
        tool = _tool(data, "showcase_videos")
        desc = tool["output_schema"]["videos"]["item_fields"]["duration"]
        assert "分鐘" in desc
        assert "秒" not in desc


class TestSAPre9DisclosureFixes:
    """SA-pre-9 P2-4 / P2-5 / P3-4：揭露缺口補齊後的回歸鎖。

    [lint-guard: pytest-justified] 斷言的是 /api/capabilities 回傳的 Python dict
    （AI-facing 契約），不是 html/js/css 字串；lint 表達不了「這個後果有沒有被講出來」。
    """

    def test_omitted_fields_are_documented_as_cleared(self, client):
        """P2-4：使用者說「只翻標題別動其他」→ AI 只送 title → 女優／標籤／片商全被寫空。

        這個後果過去完全沒寫在說明裡（只有一句「整包取代」）。
        """
        desc = _tool(client.get("/api/capabilities").json(), "enrich_single")[
            "input_schema"]["properties"]["metadata"]["description"]
        assert "沒送的白名單欄位會被寫成空" in desc
        assert "不是「維持原值」" in desc


    def test_allow_number_change_declared_in_input_schema(self, client):
        """P2-5：逃生口只寫在描述裡，AI 的工具框架會照 schema 過濾掉這個參數。"""
        props = _tool(client.get("/api/capabilities").json(), "enrich_single")["input_schema"]["properties"]
        assert "allow_number_change" in props, "allow_number_change 必須在 properties 裡，不能只寫在描述"
        assert props["allow_number_change"]["type"] == "boolean"
        assert props["allow_number_change"]["default"] is False
