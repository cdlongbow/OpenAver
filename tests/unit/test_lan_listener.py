"""
Unit tests for web/lan_listener.py — LanListenerManager lifecycle.

Strategy: mock uvicorn.Server and threading.Thread so no real server starts.
          _find_free_port_lan tested with real sockets (fast + deterministic).
"""

import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_server(started=True, should_exit=False):
    """Return a mock uvicorn.Server-like object."""
    server = MagicMock()
    server.started = started
    server.should_exit = should_exit
    server.force_exit = False
    return server


def _make_wired_manager():
    """Import fresh LanListenerManager and return a wired instance + mock app."""
    from web.lan_listener import LanListenerManager
    mgr = LanListenerManager()
    mock_app = MagicMock()
    mgr.wire(mock_app, local_port=49152)
    return mgr, mock_app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLanListenerManager(unittest.TestCase):

    # ------------------------------------------------------------------
    # 1. test_start_returns_lan_port
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 2. test_start_not_wired_raises
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 3. test_start_idempotent
    # ------------------------------------------------------------------
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_start_idempotent(self, MockServer, MockThread):
        """Calling start() again when already running returns same port (no double-start)."""
        mock_server = _make_mock_server(started=True)
        MockServer.return_value = mock_server

        mock_thread = MagicMock()
        MockThread.return_value = mock_thread

        mgr, _ = _make_wired_manager()
        port1 = mgr.start()
        port2 = mgr.start()

        self.assertEqual(port1, port2)
        # Server constructor called only once
        self.assertEqual(MockServer.call_count, 1)

    # ------------------------------------------------------------------
    # 4. test_stop_when_not_running_noop
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 5. test_stop_sets_should_exit
    # ------------------------------------------------------------------
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_stop_sets_should_exit(self, MockServer, MockThread):
        """stop() sets server.should_exit = True on the started server."""
        mock_server = _make_mock_server(started=True)
        MockServer.return_value = mock_server

        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        MockThread.return_value = mock_thread

        mgr, _ = _make_wired_manager()
        mgr.start()
        mgr.stop()

        self.assertTrue(mock_server.should_exit)

    # ------------------------------------------------------------------
    # 6. test_start_timeout_raises
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 7. test_lan_port_excluded_from_local
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 8. test_config_lifespan_off
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 9. test_config_host_0_0_0_0
    # ------------------------------------------------------------------
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    @patch("web.lan_listener.uvicorn.Config")
    def test_config_host_0_0_0_0(self, MockConfig, MockServer, MockThread):
        """Config must have host='0.0.0.0' and proxy_headers=False."""
        mock_config = MagicMock()
        MockConfig.return_value = mock_config

        mock_server = _make_mock_server(started=True)
        MockServer.return_value = mock_server

        mock_thread = MagicMock()
        MockThread.return_value = mock_thread

        mgr, _ = _make_wired_manager()
        mgr.start()

        kwargs = MockConfig.call_args[1]
        self.assertEqual(kwargs.get("host"), "0.0.0.0")
        self.assertIs(kwargs.get("proxy_headers"), False)

    # ------------------------------------------------------------------
    # 10. test_stop_join_timeout_sets_force_exit
    # ------------------------------------------------------------------


# ---------------------------------------------------------------------------
# is_public_exposure classification (114a-T7)
# ---------------------------------------------------------------------------

class TestIsPublicExposure(unittest.TestCase):
    """Three-cell matrix + edge cases for is_public_exposure()."""


    def test_is_public_exposure_public_ipv4(self):
        from web.lan_listener import is_public_exposure
        self.assertTrue(is_public_exposure("8.8.8.8"))


    # Codex PR#129 round-2 P3：`not is_private` 與 `is_global` 之間夾著一整批
    # 「既不私有、也不可公開路由」的特殊用途網段。舊寫法會把它們全部判成公網暴露
    # ——每一格都是這個函式契約明文要避免的誤報。
    def test_is_public_exposure_cgnat_is_not_public(self):
        """100.64.0.0/10（CGNAT）：is_private 為 False 但不可公開路由。

        最會踩到的一格——筆電接手機熱點或 4G/5G 路由器時本機就可能拿到 100.64.x，
        使用者會看到一則說他暴露在網際網路上的警告，而他並沒有。
        """
        from web.lan_listener import is_public_exposure
        self.assertFalse(is_public_exposure("100.64.0.1"))
        self.assertFalse(is_public_exposure("100.127.255.254"))


# ---------------------------------------------------------------------------
# start() public-exposure notification wiring (114a-T7)
# ---------------------------------------------------------------------------

class TestStartPublicExposureNotify(unittest.TestCase):
    """start() emits warn only on public IP; never on private/None; never breaks start()."""

    def _start_with_ip(self, MockServer, MockThread, lan_ip, mock_emit):
        mock_server = _make_mock_server(started=True)
        MockServer.return_value = mock_server
        mock_thread = MagicMock()
        MockThread.return_value = mock_thread
        mgr, _ = _make_wired_manager()
        with patch("web.lan_listener.get_lan_ip", return_value=lan_ip):
            port = mgr.start()
        return mgr, port

    @patch("web.routers.notifications.emit_notification")
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_start_emits_warning_when_public(self, MockServer, MockThread, mock_emit):
        mgr, port = self._start_with_ip(MockServer, MockThread, "8.8.8.8", mock_emit)
        self.assertIsInstance(port, int)
        mock_emit.assert_called_once_with("warn", "settings.server_info.public_exposure")


# ---------------------------------------------------------------------------
# _find_free_port_lan tests (real sockets — fast/deterministic)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main()
