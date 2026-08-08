"""
Unit tests for web/lan_listener.py — LanListenerManager lifecycle.

Strategy: mock uvicorn.Server and threading.Thread so no real server starts.
          _find_free_port_lan tested with real sockets (fast + deterministic).
"""

import socket
import threading
import unittest
from unittest.mock import MagicMock, patch, call


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
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_start_returns_lan_port(self, MockServer, MockThread):
        """start() returns an int port; is_running is True afterwards."""
        mock_server = _make_mock_server(started=True)
        MockServer.return_value = mock_server

        mock_thread = MagicMock()
        MockThread.return_value = mock_thread

        mgr, _ = _make_wired_manager()
        port = mgr.start()

        self.assertIsInstance(port, int)
        self.assertTrue(mgr.is_running)

    # ------------------------------------------------------------------
    # 2. test_start_not_wired_raises
    # ------------------------------------------------------------------
    def test_start_not_wired_raises(self):
        """start() without prior wire() must raise RuntimeError."""
        from web.lan_listener import LanListenerManager
        mgr = LanListenerManager()
        with self.assertRaises(RuntimeError):
            mgr.start()

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
    def test_stop_when_not_running_noop(self):
        """stop() when not running is a no-op (no exception)."""
        from web.lan_listener import LanListenerManager
        mgr = LanListenerManager()
        mgr.stop()  # must not raise

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
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_start_timeout_raises(self, MockServer, MockThread):
        """If server.started never becomes True, start() raises RuntimeError quickly."""
        # server.started stays False — simulates startup hang
        mock_server = _make_mock_server(started=False, should_exit=False)
        MockServer.return_value = mock_server

        mock_thread = MagicMock()
        MockThread.return_value = mock_thread

        mgr, _ = _make_wired_manager()

        # Pass a very short timeout so the test doesn't actually sleep 5s
        with self.assertRaises(RuntimeError):
            mgr.start(_startup_timeout=0.01)

    # ------------------------------------------------------------------
    # 7. test_lan_port_excluded_from_local
    # ------------------------------------------------------------------
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_lan_port_excluded_from_local(self, MockServer, MockThread):
        """The allocated lan_port must differ from local_port (exclude set enforces this)."""
        mock_server = _make_mock_server(started=True)
        MockServer.return_value = mock_server

        mock_thread = MagicMock()
        MockThread.return_value = mock_thread

        mgr, _ = _make_wired_manager()  # local_port = 49152
        port = mgr.start()

        self.assertNotEqual(port, 49152)

    # ------------------------------------------------------------------
    # 8. test_config_lifespan_off
    # ------------------------------------------------------------------
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    @patch("web.lan_listener.uvicorn.Config")
    def test_config_lifespan_off(self, MockConfig, MockServer, MockThread):
        """The uvicorn.Config passed to Server must have lifespan='off'."""
        mock_config = MagicMock()
        mock_config.lifespan = "off"
        MockConfig.return_value = mock_config

        mock_server = _make_mock_server(started=True)
        MockServer.return_value = mock_server

        mock_thread = MagicMock()
        MockThread.return_value = mock_thread

        mgr, mock_app = _make_wired_manager()
        mgr.start()

        # Verify Config was constructed with lifespan="off"
        MockConfig.assert_called_once()
        kwargs = MockConfig.call_args[1]
        self.assertEqual(kwargs.get("lifespan"), "off")

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
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_stop_join_timeout_sets_force_exit(self, MockServer, MockThread):
        """If thread.join() doesn't terminate the thread, force_exit must be set True."""
        mock_server = _make_mock_server(started=True)
        MockServer.return_value = mock_server

        mock_thread = MagicMock()
        # is_alive returns True even after join — simulates a stuck thread
        mock_thread.is_alive.return_value = True
        MockThread.return_value = mock_thread

        mgr, _ = _make_wired_manager()
        mgr.start()
        mgr.stop()

        self.assertTrue(mock_server.force_exit)


# ---------------------------------------------------------------------------
# is_public_exposure classification (114a-T7)
# ---------------------------------------------------------------------------

class TestIsPublicExposure(unittest.TestCase):
    """Three-cell matrix + edge cases for is_public_exposure()."""

    def test_is_public_exposure_private_ip(self):
        from web.lan_listener import is_public_exposure
        self.assertFalse(is_public_exposure("192.168.1.50"))

    def test_is_public_exposure_public_ipv4(self):
        from web.lan_listener import is_public_exposure
        self.assertTrue(is_public_exposure("8.8.8.8"))

    def test_is_public_exposure_public_ipv6(self):
        from web.lan_listener import is_public_exposure
        self.assertTrue(is_public_exposure("2001:4860:4860::8888"))

    def test_is_public_exposure_none(self):
        """None arg → consult get_lan_ip(); when that returns None, stay silent."""
        from web.lan_listener import is_public_exposure
        with patch("web.lan_listener.get_lan_ip", return_value=None):
            self.assertFalse(is_public_exposure(None))

    def test_is_public_exposure_empty_string(self):
        from web.lan_listener import is_public_exposure
        self.assertFalse(is_public_exposure(""))

    def test_is_public_exposure_malformed(self):
        from web.lan_listener import is_public_exposure
        self.assertFalse(is_public_exposure("not-an-ip"))


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

    @patch("web.routers.notifications.emit_notification")
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_start_no_warning_when_private(self, MockServer, MockThread, mock_emit):
        self._start_with_ip(MockServer, MockThread, "192.168.1.50", mock_emit)
        mock_emit.assert_not_called()

    @patch("web.routers.notifications.emit_notification")
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_start_no_warning_when_lan_ip_none(self, MockServer, MockThread, mock_emit):
        """Address unavailable → stay silent (must fail if detection were fail-open)."""
        self._start_with_ip(MockServer, MockThread, None, mock_emit)
        mock_emit.assert_not_called()

    @patch("web.routers.notifications.emit_notification")
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_start_idempotent_no_duplicate_warning(self, MockServer, MockThread, mock_emit):
        mock_server = _make_mock_server(started=True)
        MockServer.return_value = mock_server
        mock_thread = MagicMock()
        MockThread.return_value = mock_thread
        mgr, _ = _make_wired_manager()
        with patch("web.lan_listener.get_lan_ip", return_value="8.8.8.8"):
            mgr.start()
            mgr.start()  # second call hits idempotent early-return
        mock_emit.assert_called_once_with("warn", "settings.server_info.public_exposure")

    @patch("web.routers.notifications.emit_notification")
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_start_notification_failure_does_not_break_start(
        self, MockServer, MockThread, mock_emit
    ):
        mock_emit.side_effect = RuntimeError("boom")
        mock_server = _make_mock_server(started=True)
        MockServer.return_value = mock_server
        mock_thread = MagicMock()
        MockThread.return_value = mock_thread
        mgr, _ = _make_wired_manager()
        with patch("web.lan_listener.get_lan_ip", return_value="8.8.8.8"):
            port = mgr.start()
        self.assertIsInstance(port, int)
        self.assertTrue(mgr.is_running)

    @patch("web.routers.notifications.emit_notification")
    @patch("web.lan_listener.threading.Thread")
    @patch("web.lan_listener.uvicorn.Server")
    def test_start_matches_standalone_autostart_call_pattern(
        self, MockServer, MockThread, mock_emit
    ):
        """Path 2 regression lock: standalone auto-start calls the same start().

        Mirrors windows/standalone.py wire → conditional start() so a future
        move of detection out of start() into only the toggle path would fail here.
        """
        mock_server = _make_mock_server(started=True)
        MockServer.return_value = mock_server
        mock_thread = MagicMock()
        MockThread.return_value = mock_thread

        from web.lan_listener import LanListenerManager
        lan_listener = LanListenerManager()
        mock_app = MagicMock()
        # standalone.py: lan_listener.wire(app, local_port=port) then start()
        lan_listener.wire(mock_app, local_port=49152)
        with patch("web.lan_listener.get_lan_ip", return_value="8.8.8.8"):
            _lp = lan_listener.start()
        self.assertIsInstance(_lp, int)
        mock_emit.assert_called_once_with("warn", "settings.server_info.public_exposure")


# ---------------------------------------------------------------------------
# _find_free_port_lan tests (real sockets — fast/deterministic)
# ---------------------------------------------------------------------------

class TestFindFreePortLan(unittest.TestCase):

    def test_returns_available_port(self):
        """_find_free_port_lan should return a usable port >= start_port."""
        from web.lan_listener import _find_free_port_lan
        import logging
        port = _find_free_port_lan(start_port=49200, exclude=set(), logger=logging.getLogger("test"))
        self.assertGreaterEqual(port, 49200)

    def test_excludes_specified_ports(self):
        """_find_free_port_lan must skip ports in the exclude set."""
        from web.lan_listener import _find_free_port_lan
        import logging
        # Exclude 49200 through 49209; function should skip past them
        excluded = set(range(49200, 49210))
        port = _find_free_port_lan(start_port=49200, exclude=excluded, logger=logging.getLogger("test"))
        self.assertNotIn(port, excluded)
        self.assertGreaterEqual(port, 49210)

    def test_raises_when_exhausted(self):
        """_find_free_port_lan raises RuntimeError when max_attempts reached."""
        from web.lan_listener import _find_free_port_lan
        import logging
        # Hold a port open on a high address to force failure
        # Use max_attempts=1 and exclude that single port to exhaust immediately
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", 0))
        held_port = s.getsockname()[1]
        try:
            with self.assertRaises(RuntimeError):
                # max_attempts=1 and start_port is already in exclude → exhausts immediately
                _find_free_port_lan(
                    start_port=held_port,
                    exclude={held_port},
                    logger=logging.getLogger("test"),
                    max_attempts=1,
                )
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
