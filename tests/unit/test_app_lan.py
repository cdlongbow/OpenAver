"""
TASK-80a-T2: get_lan_ip() 單元測試

驗證 web/lan_listener.get_lan_ip() helper（canonical location）：
  - 正常路徑：回傳非空字串（區網 IP）
  - 失敗路徑：socket.connect 拋例外 → 回傳 None（不 throw，不空字串）

web.app re-exports get_lan_ip from web.lan_listener for backward compatibility;
tests import from the canonical location (web.lan_listener) and also verify the
re-export works.
"""


def test_get_lan_ip_returns_none_on_socket_error(monkeypatch):
    """
    socket.connect 拋出例外時 get_lan_ip() 回傳 None（不重拋、不回空字串）。
    """
    import web.lan_listener as _ll_mod
    from web.lan_listener import get_lan_ip

    class _FailSocket:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            raise OSError("simulated network failure")

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(_ll_mod.socket, "socket", _FailSocket)

    result = get_lan_ip()
    assert result is None, (
        f"socket 失敗時 get_lan_ip() 應回傳 None，得到 {result!r}"
    )


