"""請求所屬殼的身分 key（TASK-168d-T2 / CD-168d-4）。"""
from __future__ import annotations

import hashlib

from fastapi import Request

from core.access_auth import snapshot


def shell_key(request: Request) -> str | None:
    """① 帶 `sid` cookie 或 Bearer → `t:<sha256(ticket)[:16]>`；② 否則本機 → `loopback`；
    ③ 否則 `ip:<host>`；沒有 client 且無票據 → None。

    只看「有沒有帶」，**不驗票據**（驗證是 access_gate 的事）；key 不入 log。
    **PIN 關閉時一律忽略 sid／Bearer**（走 ②③）：關 PIN 會撤銷全部票，殼端 client.json 的舊 token
    已失效、頁面 `?oa_token=` 驗票失敗不種 sid → 頁面端是 ②③，殼端若仍走 ① 兩邊 key 永遠對不上。
    PIN 狀態讀 `snapshot()`（零 I/O，async middleware 內可直接呼叫）；冷快取（None）視同
    PIN 開啟＝看票（與 access_gate 冷載前 fail-closed 的方向一致）。
    """
    from web.app import _bearer_token, _is_loopback_host  # noqa: PLC2701 — 延遲 import 避免循環，同 web/routers/client.py 先例

    snap = snapshot()
    pin_off = snap is not None and not snap.enabled
    ticket = None if pin_off else (request.cookies.get("sid") or _bearer_token(request))
    if ticket:
        return "t:" + hashlib.sha256(ticket.encode("utf-8")).hexdigest()[:16]
    host = request.client.host if request.client else None
    if not host:
        return None
    if _is_loopback_host(host):
        return "loopback"
    return "ip:" + host
