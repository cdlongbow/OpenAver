"""純判定核心：CI 一般測試禁止連到非本機主機（外連防線）。

零 pytest 相依，形狀照 `tests/_repo_write_guard.py`（G1）：判斷邏輯放這裡，
`tests/conftest.py` 只做 fixture 轉發 ＋ per-test 累積器記錄。

放行規則：
  - `evaluate_connect`：`sock_type` 含 `SOCK_DGRAM` → 放行（UDP 取區網 IP 的技巧，
    `web/lan_listener.py::get_lan_ip()` 用 `connect(("8.8.8.8", 80))` 查本機介面，
    不送封包）；`addr` 非 tuple（AF_UNIX 本機路徑）→ 放行；其餘看 host 是不是本機。
  - `evaluate_getaddrinfo`：host 為 `None` 或本機才放行。
  - 「本機」＝ `localhost`／`testserver`（TestClient 的虛擬 host）／`0.0.0.0`，
    或 `ipaddress` 判定為 loopback 的位址（含 `127.*`、`::1`、`::ffff:127.*`）；
    大小寫、bytes、IPv6 scope id（`%eth0`）先正規化。

涵蓋範圍（已知不攔的）：只攔 Python `socket` 層。`curl_cffi`（libcurl，C 層自己
解析與連線）與 session／module 層 fixture、`pytest_configure` 期間的連線不在此列。
"""
from __future__ import annotations

import ipaddress
import socket

_LOCAL_NAMES = ("localhost", "testserver", "0.0.0.0")


def _is_local_host(host) -> bool:
    if isinstance(host, (bytes, bytearray)):
        host = bytes(host).decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    h = host.strip().lower()
    if h in _LOCAL_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(h.split("%", 1)[0])
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool(mapped is not None and mapped.is_loopback)


def evaluate_connect(addr, sock_type) -> bool:
    """對一次 `socket.socket.connect(addr)` / `.connect_ex(addr)` 做放行判定。

    True＝放行；False＝呼叫端要拋 `OutboundConnectionViolation`。`sock_type` 用
    位元 AND 比對，因為部分平台的 `.type` 會疊加 `SOCK_CLOEXEC`／`SOCK_NONBLOCK`。
    """
    if sock_type is not None and (int(sock_type) & socket.SOCK_DGRAM) == socket.SOCK_DGRAM:
        return True  # UDP：取區網 IP 技巧
    if not isinstance(addr, tuple):
        return True  # AF_UNIX：本機路徑位址，沒有外連
    if not addr:
        return False
    return _is_local_host(addr[0])


def evaluate_getaddrinfo(host) -> bool:
    """對一次 `socket.getaddrinfo(host, ...)` 做放行判定。"""
    return host is None or _is_local_host(host)


class OutboundConnectionViolation(BaseException):
    """外連防線違規。

    🔴 刻意繼承 `BaseException`：產品碼有 `except Exception: return []` 這類吞例外
    的寫法（例如 `core/scrapers/dmm.py::_fetch_tags_from_html`），一般 `Exception`
    會被吞掉、測試繼續假綠。理由同 `tests/_repo_write_guard.py::RepoWriteGuardViolation`。
    """
