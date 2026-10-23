"""
test_javdb_cainfo.py - javdb CAINFO override 單元測試（TASK-98-T1）

測試策略：
- 全 mock（本 dev 機 Linux + ASCII certifi 路徑，天然走 no-op 分支）
- patch 使用端 binding（core.scrapers.javdb.*），非定義端
- 每測例 autouse fixture 重置 module-level 快取（_cainfo_override=_UNSET, _ca_warned=False）
- 沿用 tests/unit/test_javdb_scraper.py 的 fixture 寫法 + TestJavdbCurlCffiDiagnostics 慣例
"""


import pytest
from unittest.mock import patch, MagicMock

from core.scrapers import javdb


# ============================================================
# Autouse fixture：每測例重置 module-level cache（避免測試間洩漏）
# ============================================================

@pytest.fixture(autouse=True)
def reset_cainfo_cache(monkeypatch):
    monkeypatch.setattr(javdb, "_cainfo_override", javdb._UNSET)
    monkeypatch.setattr(javdb, "_ca_warned", False)


@pytest.fixture
def scraper():
    with patch("core.scrapers.javdb.rate_limit"):
        s = javdb.JavDBScraper()
        yield s


# ============================================================
# 1. non-win platform → None; _get_html 不帶 curl_options
# ============================================================

class TestNonWin:


    def test_get_html_no_curl_options_on_non_win(self, scraper, monkeypatch):
        pytest.importorskip("curl_cffi")
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        monkeypatch.setattr(javdb.sys, "platform", "linux")
        monkeypatch.setattr(javdb.certifi, "where", lambda: "/etc/ssl/certs/ca-certificates.crt")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html></html>"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        result = scraper._get_html("https://javdb.com/v/Ww9zN8")

        assert result == "<html></html>"
        assert "curl_options" not in mock_get.call_args.kwargs


# ============================================================
# 2. win + ASCII certifi path → None (no-op)
# ============================================================


# ============================================================
# 3. win + 非 ASCII + ACP 可編碼 → bytes；_get_html 帶 curl_options
# ============================================================

class TestWinNonAsciiEncodable:
    CJK_PATH = "C:\\Users\\陳大文\\OpenAver\\certifi\\cacert.pem"


    def test_get_html_passes_curl_options(self, scraper, monkeypatch):
        pytest.importorskip("curl_cffi")
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        monkeypatch.setattr(javdb.sys, "platform", "win32")
        monkeypatch.setattr(javdb.certifi, "where", lambda: self.CJK_PATH)
        monkeypatch.setattr(javdb.locale, "getencoding", lambda: "cp950")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html></html>"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        result = scraper._get_html("https://javdb.com/v/Ww9zN8")

        assert result == "<html></html>"
        expected_bytes = self.CJK_PATH.encode("cp950", errors="strict")
        assert mock_get.call_args.kwargs["curl_options"] == {javdb.CurlOpt.CAINFO: expected_bytes}


# ============================================================
# 4. win + 非 ASCII + UnicodeEncodeError → None + warning once
# ============================================================

class TestWinNonAsciiUndecodable:
    CJK_PATH = "C:\\Users\\陳大文\\OpenAver\\certifi\\cacert.pem"


    def test_get_html_omits_curl_options_on_degrade(self, scraper, monkeypatch):
        pytest.importorskip("curl_cffi")
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        monkeypatch.setattr(javdb.sys, "platform", "win32")
        monkeypatch.setattr(javdb.certifi, "where", lambda: self.CJK_PATH)
        monkeypatch.setattr(javdb.locale, "getencoding", lambda: "ascii")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html></html>"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        result = scraper._get_html("https://javdb.com/v/Ww9zN8")

        assert result == "<html></html>"
        assert "curl_options" not in mock_get.call_args.kwargs


# ============================================================
# 5. cache sentinel：算一次 + 降級終值為 None（非 _UNSET）
# ============================================================


# ============================================================
# 6. import guard：CURL_CFFI_AVAILABLE=False → 短路，不觸及 certifi
# ============================================================

