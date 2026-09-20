"""TASK-152a-T4 機制層：合成 ASGI SSE app ＋ 真實 GZipMiddleware。

證明 text/event-stream 回應在 GZipMiddleware 包裹下：
1. 分塊時序不被壓縮緩衝卡住（收到的 http.response.body 事件數 > 1）。
2. 不會被加上 Content-Encoding: gzip header。
3. 內容完全未被壓縮破壞。
"""

import asyncio
from starlette.middleware.gzip import GZipMiddleware

from web.compression import GZIP_COMPRESS_LEVEL, GZIP_EXCLUDED_CONTENT_TYPES


def test_gzip_middleware_sse_chunking_not_buffered():
    """合成 ASGI SSE app 發送 3 個 chunk，驗證各 chunk 即時轉發且未被 gzip 壓縮。"""
    chunks = [
        b"data: event 1\n\n",
        b"data: event 2\n\n",
        b"data: event 3\n\n",
    ]

    async def sse_app(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/event-stream; charset=utf-8")],
        })
        await send({"type": "http.response.body", "body": chunks[0], "more_body": True})
        await send({"type": "http.response.body", "body": chunks[1], "more_body": True})
        await send({"type": "http.response.body", "body": chunks[2], "more_body": False})

    wrapped_app = GZipMiddleware(
        sse_app,
        compresslevel=GZIP_COMPRESS_LEVEL,
        exclude_content_types=GZIP_EXCLUDED_CONTENT_TYPES,
    )

    recorded_messages = []

    async def recorder_send(message):
        recorded_messages.append(message)

    async def dummy_receive():
        return {"type": "http.disconnect"}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/stream",
        "headers": [(b"accept-encoding", b"gzip")],
    }

    asyncio.run(wrapped_app(scope, dummy_receive, recorder_send))

    # 1. 斷言 response.start
    start_messages = [m for m in recorded_messages if m["type"] == "http.response.start"]
    assert len(start_messages) == 1
    start_headers = {
        k.decode("latin-1").lower(): v.decode("latin-1")
        for k, v in start_messages[0].get("headers", [])
    }
    assert start_headers.get("content-type", "").startswith("text/event-stream")
    assert "content-encoding" not in start_headers

    # 2. 斷言 response.body 分塊數 > 1（未被壓縮緩衝成一個大 blob）
    body_messages = [m for m in recorded_messages if m["type"] == "http.response.body"]
    assert len(body_messages) == 3
    assert len(body_messages) > 1

    # 3. 斷言各 chunk 原始內容與順序
    received_chunks = [m.get("body", b"") for m in body_messages]
    assert received_chunks == chunks
    assert body_messages[0].get("more_body") is True
    assert body_messages[1].get("more_body") is True
    assert body_messages[2].get("more_body") is False
