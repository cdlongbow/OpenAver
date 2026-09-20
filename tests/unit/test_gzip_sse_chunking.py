"""TASK-152a-T4 機制層：合成 ASGI SSE app ＋ 真實 GZipMiddleware。

證明 text/event-stream 回應在 GZipMiddleware 包裹下：
1. 真正承重的是：text/event-stream 在排除清單裡 ⇒ 不出現 Content-Encoding header，各塊原始內容與順序原樣轉發。
2. 訊息數與 more_body 那兩條斷言目前不承重：starlette 的串流壓縮分支用 Z_SYNC_FLUSH 逐塊沖出，
   就算壓縮真的發生，訊息數與 more_body 也不會變——它們是留著記錄意圖、並在上游哪天改成緩衝式壓縮時才會發聲。
"""

import asyncio
from starlette.middleware.gzip import GZipMiddleware

from web.compression import GZIP_COMPRESS_LEVEL, GZIP_EXCLUDED_CONTENT_TYPES


def test_gzip_middleware_sse_chunking_not_buffered():
    """合成 ASGI SSE app 發送 3 個 chunk，驗證各 chunk 未被 gzip 壓縮且原樣轉發。

    真正承重的是 Content-Encoding 不存在與各塊原始內容比對。
    訊息數與 more_body 斷言目前不承重（因 starlette 串流壓縮分支採 Z_SYNC_FLUSH 逐塊沖出），
    保留以記錄意圖，並在未來上游改用緩衝式壓縮時作為防護。
    """
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
