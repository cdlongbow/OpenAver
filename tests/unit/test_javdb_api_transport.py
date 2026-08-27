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

import pytest
import requests

from core.scrapers.errors import SourceBlocked, SourceUnreachable


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

    def test_sign_golden_vector_1(self):
        from core.scrapers.javdb_api import sign

        assert sign(1) == "1.lpw6vgqzsp.c8ff493d6b6ab61f4b4618c27f696981"

    def test_sign_uses_current_time_when_ts_none(self, monkeypatch):
        import core.scrapers.javdb_api as javdb_api

        monkeypatch.setattr(javdb_api.time, "time", lambda: 1700000000)
        assert javdb_api.sign(None) == javdb_api.sign(1700000000)

    def test_sign_uses_current_time_when_ts_non_positive(self, monkeypatch):
        import core.scrapers.javdb_api as javdb_api

        monkeypatch.setattr(javdb_api.time, "time", lambda: 1700000000)
        assert javdb_api.sign(0) == javdb_api.sign(1700000000)
        assert javdb_api.sign(-5) == javdb_api.sign(1700000000)


# ============================================================
# AC-2｜正常路徑
# ============================================================

class TestHappyPath:
    def test_api_search_returns_movies_and_calls_once(self, monkeypatch):
        from core.scrapers.javdb_api import api_search

        payload = _ok_envelope({"movies": [{"id": "X"}], "current_page": 1})
        mock_get = _patch_get(monkeypatch, return_value=_make_resp(200, payload))

        result = api_search("SONE-205")

        assert result == [{"id": "X"}]
        assert mock_get.call_count == 1  # 主網域成功時鏡像不該被打


# ============================================================
# AC-3｜查無不是錯誤
# ============================================================

class TestEmptySearch:
    def test_api_search_empty_movies_returns_empty_list(self, monkeypatch):
        from core.scrapers.javdb_api import api_search

        payload = _ok_envelope({"movies": [], "current_page": 1})
        _patch_get(monkeypatch, return_value=_make_resp(200, payload))

        assert api_search("NOTEXIST-999") == []


# ============================================================
# AC-4｜例外映射，且落點唯一
# ============================================================

class TestExceptionMapping:
    @pytest.mark.parametrize("status", [403, 429, 503])
    def test_blocked_status_maps_to_source_blocked(self, status, monkeypatch):
        from core.scrapers.javdb_api import api_get

        mock_get = _patch_get(monkeypatch, return_value=_make_resp(status))
        with pytest.raises(SourceBlocked):
            api_get("/api/v2/search")
        assert mock_get.call_count == 2  # 兩個 host 都試過

    def test_403_maps_to_source_blocked(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(monkeypatch, return_value=_make_resp(403))
        with pytest.raises(SourceBlocked):
            api_get("/api/v2/search")

    def test_429_maps_to_source_blocked(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(monkeypatch, return_value=_make_resp(429))
        with pytest.raises(SourceBlocked):
            api_get("/api/v2/search")

    def test_503_maps_to_source_blocked(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(monkeypatch, return_value=_make_resp(503))
        with pytest.raises(SourceBlocked):
            api_get("/api/v2/search")

    @pytest.mark.parametrize("status", [400, 404, 500])
    def test_non_blocked_http_error_maps_to_unreachable(self, status, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(monkeypatch, return_value=_make_resp(status))
        with pytest.raises(SourceUnreachable):
            api_get("/api/v2/search")

    def test_400_maps_to_source_unreachable(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(monkeypatch, return_value=_make_resp(400))
        with pytest.raises(SourceUnreachable):
            api_get("/api/v2/search")

    def test_404_maps_to_source_unreachable(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(monkeypatch, return_value=_make_resp(404))
        with pytest.raises(SourceUnreachable):
            api_get("/api/v2/search")

    def test_500_maps_to_source_unreachable(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(monkeypatch, return_value=_make_resp(500))
        with pytest.raises(SourceUnreachable):
            api_get("/api/v2/search")

    def test_connection_error_maps_to_source_unreachable(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(
            monkeypatch,
            side_effect=requests.exceptions.ConnectionError("refused"),
        )
        with pytest.raises(SourceUnreachable):
            api_get("/api/v2/search")

    def test_timeout_maps_to_source_unreachable(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(
            monkeypatch,
            side_effect=requests.exceptions.Timeout("timed out"),
        )
        with pytest.raises(SourceUnreachable):
            api_get("/api/v2/search")

    def test_connect_timeout_maps_to_source_unreachable(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(
            monkeypatch,
            side_effect=requests.exceptions.ConnectTimeout("connect timed out"),
        )
        with pytest.raises(SourceUnreachable):
            api_get("/api/v2/search")

    def test_ssl_error_maps_to_source_unreachable(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(
            monkeypatch,
            side_effect=requests.exceptions.SSLError("ssl bad"),
        )
        with pytest.raises(SourceUnreachable):
            api_get("/api/v2/search")

    def test_non_json_body_maps_to_source_unreachable(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(monkeypatch, return_value=_make_resp(200, bad_json=True))
        with pytest.raises(SourceUnreachable):
            api_get("/api/v2/search")

    def test_success_0_maps_to_source_unreachable(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        # data 刻意給一個**合法的 dict**：若 success 那道守衛被拿掉，下游
        # 「data 不是 dict」那道就接不住，這支才會真的紅（review P1：原本
        # data=None 讓兩道守衛產生同一個結果，守衛刪掉測試照樣綠）。
        payload = {
            "success": 0,
            "action": "ParameterInvalid",
            "message": "bad",
            "data": {"movies": []},
        }
        _patch_get(monkeypatch, return_value=_make_resp(200, payload))
        with pytest.raises(SourceUnreachable) as exc:
            api_get("/api/v2/search")
        # 訊息要指得出是「被拒絕」而不是別條分支
        assert "ParameterInvalid" in str(exc.value)

    def test_connect_timeout_mro_witness(self):
        # BE-TEST-16：ConnectTimeout 同時是 ConnectionError 與 Timeout 的子類。
        # 本檔只有一條 transport 分支（RequestException），所以不會分岔；
        # 這支在防的是日後有人把它拆成兩條。
        assert issubclass(
            requests.exceptions.ConnectTimeout,
            (requests.exceptions.ConnectionError, requests.exceptions.Timeout),
        )


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

    def test_both_hosts_connection_error_raises_unreachable(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(
            monkeypatch,
            side_effect=requests.exceptions.ConnectionError("all down"),
        )
        with pytest.raises(SourceUnreachable):
            api_get("/api/v2/search")

    def test_both_hosts_403_raises_source_blocked(self, monkeypatch):
        from core.scrapers.javdb_api import api_get

        _patch_get(monkeypatch, return_value=_make_resp(403))
        with pytest.raises(SourceBlocked):
            api_get("/api/v2/search")


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
            r"1\.9\.35",
        ]
        for pattern in forbidden:
            assert re.search(pattern, src, re.IGNORECASE) is None, (
                f"forbidden provenance pattern found: {pattern!r}"
            )


# ============================================================
# AC-8｜零網路（結構守衛：本檔不得出現未 mock 的真實請求意圖）
# ============================================================

class TestZeroNetwork:
    def test_test_file_monkeypatches_requests_get(self):
        """整支測試檔透過 _patch_get 鎖定 requests.get；不得發真實請求。"""
        this_file = Path(__file__).read_text(encoding="utf-8")
        assert "_patch_get" in this_file
        assert 'monkeypatch.setattr(javdb_api.requests, "get"' in this_file


# ============================================================
# AC-6 補強｜每次嘗試都重新簽名（review P2）
# ============================================================

class TestSignaturePerAttempt:
    def test_each_host_attempt_gets_a_fresh_signature(self, monkeypatch):
        """主網域失敗換鏡像時，第二趟必須是新算的簽名，不得沿用第一趟那份。

        Why：簽名帶時間戳且有效期有限（站方會回 ExpiredSignature）。主網域吃滿
        逾時（最長 20 秒）之後才輪到鏡像，沿用舊簽名等於讓備援那條天生就可能過期。
        """
        import core.scrapers.javdb_api as javdb_api

        ticks = iter([1000, 2000])
        monkeypatch.setattr(javdb_api.time, "time", lambda: next(ticks))

        mock_get = _patch_get(
            monkeypatch,
            side_effect=[
                requests.exceptions.ConnectionError("primary down"),
                _make_resp(200, _ok_envelope({"movies": [{"id": "X"}]})),
            ],
        )
        assert javdb_api.api_search("SONE-205") == [{"id": "X"}]

        sigs = [c.kwargs["headers"]["jdsignature"] for c in mock_get.call_args_list]
        assert len(sigs) == 2
        assert sigs[0] != sigs[1], "兩趟共用同一份簽名＝簽名被快取了"
        assert sigs[0].startswith("1000.") and sigs[1].startswith("2000.")


# ============================================================
# api_movie_detail｜詳情端點的形狀契約（review P2：原本零覆蓋）
# ============================================================

class TestMovieDetail:
    def test_returns_movie_dict(self, monkeypatch):
        from core.scrapers.javdb_api import api_movie_detail

        movie = {"id": "P9QrXa", "number": "SONE-205"}
        mock_get = _patch_get(
            monkeypatch, return_value=_make_resp(200, _ok_envelope({"movie": movie}))
        )
        assert api_movie_detail("P9QrXa") == movie
        assert mock_get.call_count == 1
        assert mock_get.call_args.args[0].endswith("/api/v4/movies/P9QrXa")

    @pytest.mark.parametrize("bad_movie", [None, [], "x", 3])
    def test_movie_not_a_dict_raises_unreachable(self, monkeypatch, bad_movie):
        from core.scrapers.javdb_api import api_movie_detail

        _patch_get(
            monkeypatch,
            return_value=_make_resp(200, _ok_envelope({"movie": bad_movie})),
        )
        with pytest.raises(SourceUnreachable):
            api_movie_detail("P9QrXa")

    def test_missing_movie_key_raises_unreachable(self, monkeypatch):
        from core.scrapers.javdb_api import api_movie_detail

        _patch_get(monkeypatch, return_value=_make_resp(200, _ok_envelope({})))
        with pytest.raises(SourceUnreachable):
            api_movie_detail("P9QrXa")
