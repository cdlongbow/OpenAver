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
