"""_sse_event 格式契約測試"""

from web.routers.scanner import _sse_event


class TestSseEventFormat:
    """_sse_event() 格式契約測試"""

    def test_ascii_dict(self):
        """純 ASCII dict 應輸出標準 SSE 格式"""
        result = _sse_event({"type": "test", "message": "hello"})
        assert result == 'data: {"type": "test", "message": "hello"}\n\n'


