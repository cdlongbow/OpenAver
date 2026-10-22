"""
test_javdb_api_transport.py - javdb App API 傳輸層單元測試（TASK-132b-T1）

AC-1：sign() 決定性 ＋ golden vector ＋ 無 ts 用當下時間
AC-2：正常路徑 api_search 回 movies，且只打主網域一次
AC-3：查無回 [] 不 raise
AC-4：例外映射（blocked / unreachable / 非 JSON / success:0）＋ ConnectTimeout MRO
AC-5：requests.get kwargs 不含 proxies（反向鎖）
AC-6：鏡像 fallback（連線失敗換鏡像／兩邊都失敗／兩邊 403 → Blocked）
AC-7：來源零留痕（原始碼 grep）
AC-8：零網路（requests.get 一律 monkeypatch）
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import requests



# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ok_envelope(data):
    return {"success": 1, "action": None, "message": None, "data": data}


def _make_resp(status_code: int = 200, payload=None, *, bad_json: bool = False):
    resp = MagicMock()
    resp.status_code = status_code
    if bad_json:
        resp.json.side_effect = ValueError("No JSON object could be decoded")
    else:
        resp.json.return_value = payload
    return resp


def _patch_get(monkeypatch, side_effect=None, return_value=None):
    """Monkeypatch javdb_api.requests.get；AC-8：測試零網路。"""
    import core.scrapers.javdb_api as javdb_api

    mock_get = MagicMock()
    if side_effect is not None:
        mock_get.side_effect = side_effect
    else:
        mock_get.return_value = return_value
    monkeypatch.setattr(javdb_api.requests, "get", mock_get)
    return mock_get


# ============================================================
# AC-1｜簽名決定性
# ============================================================

class TestSign:
    def test_sign_golden_vector_1700000000(self):
        from core.scrapers.javdb_api import sign

        assert sign(1700000000) == "1700000000.lpw6vgqzsp.dacaffcd8b4e1b35c2752f065e906f3a"


    def test_sign_uses_current_time_when_ts_none(self, monkeypatch):
        import core.scrapers.javdb_api as javdb_api

        monkeypatch.setattr(javdb_api.time, "time", lambda: 1700000000)
        assert javdb_api.sign(None) == javdb_api.sign(1700000000)


# ============================================================
# AC-4｜例外映射，且落點唯一
# ============================================================


# ============================================================
# AC-5｜代理不變式（反向鎖）
# ============================================================

class TestProxyInvariant:
    def test_requests_get_kwargs_have_no_proxies(self, monkeypatch):
        # 傳了 proxies 就等於把使用者的系統代理靜默關掉，那是 F1 修過的同一個 bug
        from core.scrapers.javdb_api import api_get

        payload = _ok_envelope({"movies": []})
        mock_get = _patch_get(monkeypatch, return_value=_make_resp(200, payload))

        api_get("/api/v2/search")

        assert mock_get.call_count >= 1
        _, kwargs = mock_get.call_args
        assert "proxies" not in kwargs


# ============================================================
# AC-6｜鏡像 fallback
# ============================================================

class TestMirrorFallback:
    def test_mirror_is_tried_when_primary_connection_fails(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        payload = _ok_envelope({"movies": [{"id": "Y"}]})
        ok = _make_resp(200, payload)

        def side_effect(url, **kwargs):
            if "jdforrepam.com" in url:
                raise requests.exceptions.ConnectionError("primary down")
            return ok

        mock_get = _patch_get(monkeypatch, side_effect=side_effect)

        data = api_get("/api/v2/search", {"q": "SONE-205", "page": "1"})
        assert data == {"movies": [{"id": "Y"}]}
        assert mock_get.call_count == 2
        urls = [call.args[0] for call in mock_get.call_args_list]
        assert "jdforrepam.com" in urls[0]
        assert "javdb.com" in urls[1]


# ============================================================
# AC-7｜來源零留痕
# ============================================================

class TestNoProvenance:
    def test_source_code_has_no_provenance_traces(self):
        src = Path("core/scrapers/javdb_api.py").read_text(encoding="utf-8")
        forbidden = [
            r"apk",
            r"逆向",
            r"反編譯",
            r"decompil",
            r"reverse",
            r"github\.com",
            r"javdb-cli",
            r"jdb_official",
        ]
        for pattern in forbidden:
            assert re.search(pattern, src, re.IGNORECASE) is None, (
                f"forbidden provenance pattern found: {pattern!r}"
            )

    def test_version_literals_appear_only_as_request_parameters(self):
        """版本號**只准**待在 `_PUBLIC_PARAMS` 裡，不准出現在註解／docstring／別的地方。

        為什麼這條長這樣（pre-merge branch review 抓到前一版是死的）：
        前一版禁的是一個**寫死的版本字面**，而檔案裡的版本不是那一個 ⇒ 規則恆綠、
        什麼都沒守到。而「一律禁版本號」也做不到——那兩個值是**請求必帶的參數**，
        拿掉功能就壞了。

        所以真正可執行的不變式是**位置**而不是**存在**：值可以在請求參數裡，
        但不准被複述進任何散文（那才是「怎麼取得的」會外洩的地方）。
        參數值改版時本測試自動跟著走，不需要同步維護一份字面清單。
        """
        import ast

        path = Path("core/scrapers/javdb_api.py")
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        params_node = None
        for node in tree.body:
            targets = getattr(node, "targets", [])
            if targets and getattr(targets[0], "id", None) == "_PUBLIC_PARAMS":
                params_node = node
                break
        assert params_node is not None, "找不到 _PUBLIC_PARAMS —— 本守衛的錨點沒了"

        # 只守「夠獨特」的版本值（≥4 字元）。`system_version` 那種兩位數字面
        # （`"13"`）在任何檔案裡都會撞到一堆無關的東西，守它只會製造假紅。
        versions = {
            v for k, v in ast.literal_eval(params_node.value).items()
            if "version" in k and isinstance(v, str) and len(v) >= 4
        }
        assert versions, "_PUBLIC_PARAMS 裡沒有 version 欄位 —— 錨點漂了，本守衛已失效"

        rest = src.replace(ast.get_source_segment(src, params_node) or "", "")
        for v in versions:
            assert v not in rest, (
                f"版本字面 {v!r} 出現在 _PUBLIC_PARAMS 之外（註解／docstring／其他程式碼）"
                " —— CD-132b-11：不得複述取得來源的任何線索"
            )


# ============================================================
# AC-8｜零網路（結構守衛：本檔不得出現未 mock 的真實請求意圖）
# ============================================================


# ============================================================
# AC-6 補強｜每次嘗試都重新簽名（review P2）
# ============================================================


# ============================================================
# 175b-T2｜api_search_typed / api_list_tags
# ============================================================


class TestTypedSearchAndListTags:
    def test_search_typed_sends_type_param(self, monkeypatch):
        from core.scrapers.javdb_api import api_search_typed

        payload = _ok_envelope({"actors": [{"id": "Av2e"}]})
        mock_get = _patch_get(monkeypatch, return_value=_make_resp(200, payload))

        assert api_search_typed("actor", "三上悠亞") == [{"id": "Av2e"}]
        params = mock_get.call_args.kwargs["params"]
        assert params["type"] == "actor"
        assert params["q"] == "三上悠亞"
        assert params["page"] == "1"
        assert mock_get.call_count == 1


    def test_list_tags_filter_by_goes_in_params(self, monkeypatch):
        from core.scrapers.javdb_api import api_list_tags

        payload = _ok_envelope({"movies": [{"id": "M1"}], "current_page": 2})
        mock_get = _patch_get(monkeypatch, return_value=_make_resp(200, payload))

        assert api_list_tags("0:a:Av2e", 2) == [{"id": "M1"}]
        call = mock_get.call_args
        assert call.kwargs["params"]["filter_by"] == "0:a:Av2e"
        assert call.kwargs["params"]["page"] == "2"
        assert call.kwargs["params"]["limit"] == "50"
        assert "0:a:Av2e" not in call.args[0]  # 不拼進路徑
        assert call.args[0].endswith("/api/v1/movies/tags")


# ============================================================
# 175b-T4a｜api_search_page（無 type 的分頁關鍵字搜尋）
# ============================================================

class TestSearchPage:
    def test_sends_page_and_limit_without_type(self, monkeypatch):
        from core.scrapers.javdb_api import api_search_page

        mock_get = _patch_get(monkeypatch, return_value=_make_resp(200, _ok_envelope({"movies": [{"id": "M1"}]})))
        assert api_search_page("人妻", 3, limit=20) == [{"id": "M1"}]
        params = mock_get.call_args.kwargs["params"]
        assert params["q"] == "人妻" and params["page"] == "3" and params["limit"] == "20"
        assert "type" not in params
        assert mock_get.call_args.args[0].endswith("/api/v2/search")


