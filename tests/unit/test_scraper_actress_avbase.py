"""avbase 女優來源（TASK-174-T2）。

輸入全是測試檔內嵌的合成 dict／字串；不連網、不收站方存檔。
站方 JSON 形狀對不對不在這裡驗（歸活站金絲雀）。

會呼叫真 `scrape_avbase` 的測試類別標 `real_avbase`（跳過全域替身），並把
`curl_cffi.requests.Session` 換成替身；其餘純函式測試不需要 marker。
"""
import json
import sys
import types
from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import core.scrapers.actress.avbase as avbase_mod
from core.scrapers.actress.avbase import (
    _normalize_basic_info,
)

NAME = "テスト花子"


class _LeakedRealRequest(BaseException):
    """忘了配置替身的測試真的走到 Session.get → 大聲紅（BaseException 不會被 `except Exception` 吞成 None）。"""


@pytest.fixture(autouse=True)
def _curl_session_tripwire():
    """安全網：外連防線不攔 curl_cffi，忘了配置的測試不准真的打 avbase。"""
    sess = MagicMock()
    sess.__enter__.return_value = sess
    sess.get.side_effect = _LeakedRealRequest("test reached a real curl_cffi request")
    with patch("curl_cffi.requests.Session", return_value=sess), \
            patch.object(avbase_mod, "proxy_kwargs", return_value={}), \
            patch("core.scrapers.javdb._resolve_proxies", return_value=None), \
            patch("core.scrapers.javdb._cainfo_override_bytes", return_value=None):
        yield


def _page(talent) -> str:
    data = {"props": {"pageProps": {"talent": talent}}}
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + "</script>"


def _talent(basic_info=None, names=(NAME,), primary=None) -> dict:
    t = {"actors": [{"name": n} for n in names], "meta": {"basic_info": basic_info or {}}}
    if primary is not None:
        t["primary"] = primary
    return t


def _fake_session(*, get=None, status=200, text=""):
    sess = MagicMock()
    sess.__enter__.return_value = sess
    if get is not None:
        sess.get.side_effect = get
    else:
        sess.get.return_value = SimpleNamespace(status_code=status, text=text)
    return sess


# ── 純函式：欄位正規化（CD-174-4）────────────────────────────────────────────

class TestNormalizeBasicInfo:
    @pytest.mark.parametrize("raw,expected", [
        ("162", "162cm"),
        (162, "162cm"),
        ("158.5", "158cm"),
        (158.5, "158cm"),
        ("162cm", "162cm"),
    ])
    def test_height_valid(self, raw, expected):
        assert _normalize_basic_info({"height": raw}) == {"height": expected}

    @pytest.mark.parametrize("raw", ["", "0", None, "abc", "  ", 0, [], {}])
    def test_height_invalid_key_absent(self, raw):
        assert _normalize_basic_info({"height": raw}) == {}

    @pytest.mark.parametrize("raw,expected", [
        ("1999-11-30", "1999-11-30"),
        (" 1999-11-30 ", "1999-11-30"),
    ])
    def test_birthday_kept(self, raw, expected):
        assert _normalize_basic_info({"birthday": raw}) == {"birth": expected}

    @pytest.mark.parametrize("raw", ["1999", "1999-11", "0000-00-00", "1999-13-40", "", None, 1999])
    def test_birthday_incomplete_dropped(self, raw):
        assert _normalize_basic_info({"birthday": raw}) == {}

    @pytest.mark.parametrize("raw,present", [
        ("F", True), ("AA", True), ("f", False), ("1", False), ("", False),
        ("FFF", False), (None, False), (5, False),
    ])
    def test_cup(self, raw, present):
        out = _normalize_basic_info({"cup": raw})
        assert out == ({"cup": raw} if present else {})

    def test_unused_keys_ignored_and_non_dict_safe(self):
        assert _normalize_basic_info({"blood_type": "A", "sns": ["x"], "profile": "p"}) == {}
        assert _normalize_basic_info(None) == {}
        assert _normalize_basic_info("garbage") == {}


def test_numeric_fields_truncate_decimals_and_survive_safe_int():
    """小數捨去、只吐 ^\\d+cm$；收藏路徑的 _safe_int 讀回等於原整數（防「86.5→865」同型事故）。"""
    from web.routers.actress import _safe_int  # lazy：只有這支需要

    out = _normalize_basic_info({
        "height": "158.5", "bust": 86.5, "waist": "58.9", "hip": "88",
    })
    expected = {"height": 158, "bust": 86, "waist": 58, "hip": 88}
    assert set(out) == set(expected)
    for key, want in expected.items():
        assert out[key] == f"{want}cm"
        assert _safe_int(out[key]) == want


# ── 連線函式：失敗一律 None、不丟例外（真函式 + 替身 Session）──────────────

@pytest.mark.real_avbase
class TestScrapeAvbaseWithStubbedSession:
    def _run(self, session):
        with patch("curl_cffi.requests.Session", return_value=session):
            return avbase_mod.scrape_avbase(NAME)

    def test_system_proxy_fallback_used_only_without_configured_proxy(self):
        """設定頁沒選中女優連線 → 退回系統代理（curl_cffi 不讀 Windows 註冊表）；
        有設定代理就用設定的，不被系統代理覆蓋。"""
        sys_proxies = {"https": "http://sys:1"}
        cfg_proxies = {"http": "http://cfg:1", "https": "http://cfg:1"}
        ok = _page(_talent({"hobby": "x"}))
        with patch("core.scrapers.javdb._resolve_proxies", return_value=sys_proxies):
            session = _fake_session(text=ok)
            self._run(session)
            assert session.get.call_args.kwargs["proxies"] == sys_proxies

            session = _fake_session(text=ok)
            with patch.object(avbase_mod, "proxy_kwargs", return_value={"proxies": cfg_proxies}):
                self._run(session)
            assert session.get.call_args.kwargs["proxies"] == cfg_proxies

        with patch("core.scrapers.javdb._resolve_proxies", return_value=None):
            session = _fake_session(text=ok)
            self._run(session)
            assert "proxies" not in session.get.call_args.kwargs

    def test_cainfo_override_passed_as_curl_option(self):
        """CAINFO 屬於 Session 建構子；get() 不收 curl_options（傳錯位置 → TypeError → 被吞成 None）。
        沒有覆寫時兩處都不帶。"""
        from curl_cffi import CurlOpt

        ok = _page(_talent({"hobby": "x"}))
        with patch("core.scrapers.javdb._cainfo_override_bytes", return_value=b"x"):
            session = _fake_session(text=ok)
            with patch("curl_cffi.requests.Session", return_value=session) as ctor:
                assert avbase_mod.scrape_avbase(NAME) is not None
            assert ctor.call_args.kwargs["curl_options"] == {CurlOpt.CAINFO: b"x"}
            assert "curl_options" not in session.get.call_args.kwargs
        session = _fake_session(text=ok)  # tripwire 預設回 None
        with patch("curl_cffi.requests.Session", return_value=session) as ctor:
            avbase_mod.scrape_avbase(NAME)
        assert "curl_options" not in ctor.call_args.kwargs
        assert "curl_options" not in session.get.call_args.kwargs

    def test_curl_options_belong_to_real_session_constructor_not_get(self):
        """用真的 curl_cffi 簽名守住參數位置（MagicMock 看不出 get() 收不收該參數）。"""
        import inspect
        from curl_cffi import CurlOpt
        # 從定義模組取真類別：autouse tripwire 已把 `curl_cffi.requests.Session` 換成替身，
        # 經 `curl_cffi.requests` 取會拿到 Mock，驗的就不是真 API。
        from curl_cffi.requests.session import Session as RealSession

        assert inspect.isclass(RealSession)
        assert RealSession.__module__.startswith("curl_cffi")
        assert not isinstance(RealSession, MagicMock)

        assert "curl_options" not in inspect.signature(RealSession.get).parameters
        assert "curl_options" not in inspect.signature(RealSession.request).parameters
        # 真建構（不發請求）：avbase 實際傳的建構參數不得丟例外
        with RealSession(impersonate="chrome", curl_options={CurlOpt.CAINFO: b"x"}):
            pass

    @pytest.mark.parametrize("make_exc", [
        lambda: ImportError("no curl"),
        lambda: PackageNotFoundError("curl_cffi"),
    ], ids=["ImportError", "PackageNotFoundError"])
    def test_curl_cffi_import_failure_returns_none(self, make_exc):
        exc = make_exc()

        class _Broken(types.ModuleType):
            def __getattr__(self, attr):
                raise exc

        with patch.dict(sys.modules, {"curl_cffi": _Broken("curl_cffi")}):
            assert avbase_mod.scrape_avbase(NAME) is None

    @pytest.mark.parametrize("bad", ["", "   ", None])
    def test_blank_name_returns_none_without_request(self, bad):
        session = _fake_session(text=_page(_talent({"hobby": "x"})))
        with patch("curl_cffi.requests.Session", return_value=session) as ctor:
            assert avbase_mod.scrape_avbase(bad) is None
        assert ctor.call_count == 0

    def test_baseexception_is_not_swallowed(self):
        """外連防線違規是 BaseException，必須穿透（不能被 except Exception 吞成 None）。"""
        with pytest.raises(_LeakedRealRequest):
            avbase_mod.scrape_avbase(NAME)  # tripwire fixture 的 Session 一被 get 就丟


# ── 全域替身（tests/conftest.py::_no_real_avbase）──────────────────────────

def test_global_stub_blocks_real_curl_session_for_unmarked_tests():
    """未標 real_avbase：經模組屬性呼叫得到的是全域替身 → None，且完全沒碰 curl_cffi。
    （經 `from … import` 會在 collection 階段綁到真函式，所以必須走模組屬性。）"""
    with patch("curl_cffi.requests.Session") as session_cls:
        assert avbase_mod.scrape_avbase("x") is None
        assert session_cls.call_count == 0
