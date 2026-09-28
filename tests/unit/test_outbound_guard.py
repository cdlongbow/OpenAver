"""外連防線：純函式判斷 ＋ fixture 的 inline／teardown 兩層轉紅驗收。

- `Test純函式判斷` 兩個 class：直接呼叫 `tests/_outbound_guard.py` 的
  `evaluate_connect`／`evaluate_getaddrinfo`，不需要 pytest 以外的任何東西。
- `pytester` 子 session 幾支：驗證裝在 `tests/conftest.py` 的
  `_outbound_connection_guard` autouse fixture 真的會讓「連到非本機主機」的測試
  轉紅——inline 拋出（主執行緒）、teardown 保險層（背景 `threading.Thread` 裡的
  違規，主執行緒完全不知情）、UDP／AF_UNIX 回歸鎖、smoke marker 不受影響。形狀
  照抄 `tests/unit/test_repo_write_guard_subsession.py`（`_install_live_conftest`：
  讀「活的」root conftest 逐字複製進子 session，兩邊永遠同步，不重寫第二份
  可能漂移的實作）。`pytest_plugins = ["pytester"]` 已在 root `tests/conftest.py`
  註冊，這裡不需要重複宣告。
"""
from __future__ import annotations

import os
import socket
import textwrap
from pathlib import Path

import pytest

import _outbound_guard as _og

OPENAVER_ROOT = str(Path(__file__).resolve().parent.parent.parent)
TESTS_DIR = str(Path(__file__).resolve().parent.parent)
_PYTHONPATH_FOR_SUBSESSION = os.pathsep.join([OPENAVER_ROOT, TESTS_DIR])

# 非本機、非 loopback 的 TCP 目的地——用 RFC 5737 TEST-NET-1 文件保留位址
# （192.0.2.0/24），不是任何真實可連線的主機；防線必須在 connect() 真正送出
# SYN 之前就攔下，所以這個位址連不連得通完全不影響斷言。
_NON_LOOPBACK_ADDR = ("192.0.2.1", 80)


def _install_live_conftest(pytester) -> None:
    """讀「活的」root conftest 逐字複製進子 session（同
    `test_repo_write_guard_subsession.py` 的既有形狀，不重寫第二份）。"""
    live_conftest = Path(OPENAVER_ROOT, "tests", "conftest.py").read_text(encoding="utf-8")
    pytester.makeconftest(live_conftest)


def _set_subsession_env(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONPATH", _PYTHONPATH_FOR_SUBSESSION)


class TestEvaluateConnect:
    """`evaluate_connect(addr, sock_type)` 的放行判定——不需要真的開 socket。"""

    def test_udp_non_loopback_allowed(self):
        assert _og.evaluate_connect(("8.8.8.8", 80), socket.SOCK_DGRAM) is True

    def test_udp_loopback_allowed(self):
        assert _og.evaluate_connect(("127.0.0.1", 80), socket.SOCK_DGRAM) is True

    def test_tcp_loopback_ipv4_allowed(self):
        assert _og.evaluate_connect(("127.0.0.1", 8000), socket.SOCK_STREAM) is True

    def test_tcp_loopback_ipv4_prefix_allowed(self):
        assert _og.evaluate_connect(("127.5.5.5", 8000), socket.SOCK_STREAM) is True

    def test_tcp_loopback_ipv6_allowed(self):
        assert _og.evaluate_connect(("::1", 8000, 0, 0), socket.SOCK_STREAM) is True

    def test_tcp_localhost_hostname_allowed(self):
        assert _og.evaluate_connect(("localhost", 8000), socket.SOCK_STREAM) is True

    def test_tcp_zero_addr_allowed(self):
        assert _og.evaluate_connect(("0.0.0.0", 8000), socket.SOCK_STREAM) is True

    def test_tcp_non_loopback_rejected(self):
        assert _og.evaluate_connect(_NON_LOOPBACK_ADDR, socket.SOCK_STREAM) is False

    def test_af_unix_path_allowed(self):
        """AF_UNIX（本機路徑字串位址）一律放行——本機 socket，無外連疑慮，擋下
        只增加假紅風險。"""
        assert _og.evaluate_connect("/tmp/fake.sock", socket.SOCK_STREAM) is True

    def test_non_tuple_non_string_addr_allowed(self):
        """非 tuple 的位址（AF_UNIX 一類）一律放行，不限定於字串型別。"""
        assert _og.evaluate_connect(b"/tmp/fake.sock", socket.SOCK_STREAM) is True

    def test_empty_tuple_addr_rejected(self):
        assert _og.evaluate_connect((), socket.SOCK_STREAM) is False


class TestEvaluateGetaddrinfo:
    """`evaluate_getaddrinfo(host)` 的放行判定。"""

    @pytest.mark.parametrize(
        "host",
        [None, "localhost", "127.0.0.1", "::1", "testserver", "0.0.0.0"],
    )
    def test_allowed_hosts(self, host):
        assert _og.evaluate_getaddrinfo(host) is True

    def test_real_hostname_rejected(self):
        assert _og.evaluate_getaddrinfo("example.com") is False

    @pytest.mark.parametrize(
        "host",
        ["LOCALHOST", " localhost ", b"localhost", "::ffff:127.0.0.1", "127.9.9.9", "::1%lo"],
    )
    def test_local_host_variants_allowed(self, host):
        assert _og.evaluate_getaddrinfo(host) is True

    @pytest.mark.parametrize(
        "host",
        [b"example.com", "8.8.8.8", "::ffff:8.8.8.8", "EXAMPLE.COM", "localhost.evil.com"],
    )
    def test_non_local_variants_rejected(self, host):
        assert _og.evaluate_getaddrinfo(host) is False


class TestLocalVariantsConnect:
    """`evaluate_connect` 對本機位址的各種寫法都放行、對外部位址都拒絕（TCP）。"""

    @pytest.mark.parametrize(
        "addr",
        [("LOCALHOST", 80), ("::ffff:127.0.0.1", 80, 0, 0), ("::1%lo", 80, 0, 0), (b"127.0.0.1", 80)],
    )
    def test_local_variants_allowed(self, addr):
        assert _og.evaluate_connect(addr, socket.SOCK_STREAM) is True

    @pytest.mark.parametrize(
        "addr",
        [("::ffff:8.8.8.8", 443, 0, 0), ("93.184.216.34", 443), (b"example.com", 443)],
    )
    def test_non_local_variants_rejected(self, addr):
        assert _og.evaluate_connect(addr, socket.SOCK_STREAM) is False


# ─────────────────────────────────────────────────────────────────────────────
# mutation 標的：evaluate_connect 的 loopback 判斷改成恆放行 ⇒ 這支要紅
# ─────────────────────────────────────────────────────────────────────────────
def test_inline_violation_fails_immediately(pytester, monkeypatch):
    """✅ inline 層：主執行緒直接 `socket.connect()` 到非本機主機，fixture 的
    wrapper 必須在真正呼叫原生 `connect` 之前就拋出，讓該測試 FAILED。

    mutation 標的：把 `tests/_outbound_guard.py::evaluate_connect` 的
    loopback 判斷那行改成恆 `True`——這支注入測試會變成 passed（因為
    `_guarded_connect` 判斷放行、呼叫真的 `original_connect`，對
    192.0.2.1:80 的連線會卡在系統層 timeout 或立刻 ECONNREFUSED，但那是連線
    失敗不是防線失敗，測試不會再出現 `outbound_guard` 字樣），
    `test_probe_inline_tcp_connect_to_non_loopback_fails` 因此不再 FAILED，
    本測試的 `assert_outcomes(failed=1)` 隨之紅。
    """
    _set_subsession_env(monkeypatch)
    _install_live_conftest(pytester)
    pytester.makepyfile(test_probe=textwrap.dedent("""
        import socket

        def test_probe_inline_tcp_connect_to_non_loopback_fails():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("192.0.2.1", 80))
    """))

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(failed=1)
    assert "outbound_guard" in result.stdout.str()
    assert "192.0.2.1" in result.stdout.str()


def test_getaddrinfo_violation_fails_immediately(pytester, monkeypatch):
    """inline 層的另一個攔截點：`socket.getaddrinfo()` 對非放行主機名也要立即拒絕。"""
    _set_subsession_env(monkeypatch)
    _install_live_conftest(pytester)
    pytester.makepyfile(test_probe=textwrap.dedent("""
        import socket

        def test_probe_getaddrinfo_non_allowed_host_fails():
            socket.getaddrinfo("example.com", 80)
    """))

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(failed=1)
    assert "outbound_guard" in result.stdout.str()


def test_udp_connect_still_allowed(pytester, monkeypatch):
    """回歸鎖：UDP 取區網 IP 技巧（`web/lan_listener.py::get_lan_ip()` 的形狀）
    在防線裝上後仍必須放行，不能被誤傷。"""
    _set_subsession_env(monkeypatch)
    _install_live_conftest(pytester)
    pytester.makepyfile(test_probe=textwrap.dedent("""
        import socket

        def test_probe_udp_connect_allowed():
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
            except OSError:
                # 離線（無對外路由）時原生 connect 會 ENETUNREACH——那不是防線擋的。
                # 防線誤擋拋的是 BaseException 子類，不會被這裡接住，子測試照樣紅。
                pass
            finally:
                s.close()
    """))

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=1)


def test_af_unix_connect_still_allowed(pytester, monkeypatch):
    """回歸鎖：AF_UNIX（本機路徑）連線在防線裝上後仍必須放行——即使是一個不存在
    的 socket 路徑（連線本身會因為找不到檔案而失敗，但那是連線失敗不是防線攔截，
    不應該看到 `outbound_guard` 字樣）。"""
    _set_subsession_env(monkeypatch)
    _install_live_conftest(pytester)
    pytester.makepyfile(test_probe=textwrap.dedent("""
        import socket

        def test_probe_af_unix_connect_not_intercepted_by_guard():
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.connect("/tmp/__openaver_outbound_guard_test_nonexistent__.sock")
            except OSError as exc:
                assert "outbound_guard" not in str(exc)
            else:
                raise AssertionError("expected connect to raise OSError (no such file)")
    """))

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=1)


# ─────────────────────────────────────────────────────────────────────────────
# mutation 標的：teardown 保險層拿掉 ⇒ 這支要紅
# ─────────────────────────────────────────────────────────────────────────────
def test_background_thread_violation_caught_by_teardown(pytester, monkeypatch):
    """✅ teardown 保險層：違規發生在背景 `threading.Thread`——該執行緒的未捕捉
    例外只會被 Python 預設 `threading.excepthook` 印到 stderr，不會傳回主測試
    執行緒，主執行緒的 `call` 階段完全不知情、正常 `return`。防線必須靠
    teardown 累積器補刀，讓該測試以 ERROR（不是 FAILED）告終。

    mutation 標的：把 conftest 裡 teardown 那段 `if accumulator:` 改成恆假
    （或直接刪掉整個 teardown 補刀區塊）——這支注入測試就不會再被補刀，
    `test_probe_background_thread_violation_unnoticed` 從「1 passed, 1 error」
    變成「1 passed, 0 errors」，本測試的
    `assert_outcomes(passed=1, errors=1)` 因此紅。
    """
    _set_subsession_env(monkeypatch)
    _install_live_conftest(pytester)
    pytester.makepyfile(test_probe=textwrap.dedent("""
        import socket
        import threading

        def test_probe_background_thread_violation_unnoticed():
            def _worker():
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect(("192.0.2.1", 80))

            t = threading.Thread(target=_worker)
            t.start()
            t.join(timeout=5)
            # 主執行緒完全不檢查背景執行緒的結果——模擬「例外在背景執行緒裡
            # 被 Python 預設 excepthook 吞掉、測試本體毫不知情」的情境。
    """))

    result = pytester.runpytest_subprocess("-q")

    # 測試本體 passed（call 階段沒有失敗），但 teardown 保險層要補一刀
    # ⇒ errors=1（teardown 拋出報成 ERROR 不是 FAILED）。
    result.assert_outcomes(passed=1, errors=1)
    assert "teardown 保險" in result.stdout.str()
    assert "192.0.2.1" in result.stdout.str()


def test_smoke_marker_not_patched(pytester, monkeypatch):
    """回歸鎖：`smoke` marker 的測試完全不受防線影響，即使直接跑該檔（不經
    `-m "not smoke"` 排除）也要連得到外站等級的邏輯路徑——這裡不真的連外，
    只驗證 fixture 對掛 `smoke` marker 的測試完全不 patch（真連得到外站已由
    手動驗證涵蓋，不在本支機械測試範圍內）。
    """
    _set_subsession_env(monkeypatch)
    _install_live_conftest(pytester)
    pytester.makeini("[pytest]\nmarkers =\n    smoke: tests that connect to external services\n")
    pytester.makepyfile(test_probe=textwrap.dedent("""
        import socket
        import pytest

        @pytest.mark.smoke
        def test_probe_smoke_marker_connect_not_intercepted():
            # 防線不 patch 時，這裡呼叫到的是原生 connect——對一個沒有人在
            # 監聽的本機高位埠嘗試連線會得到 ConnectionRefusedError（或
            # 平台等價的錯誤），而不是 OutboundConnectionViolation。這足以
            # 證明 wrapper 沒有介入這次呼叫。
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            try:
                s.connect(("192.0.2.1", 1))
            except OSError as exc:
                assert "outbound_guard" not in str(exc)
            else:
                raise AssertionError("expected connect to raise OSError")
    """))

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=1)
