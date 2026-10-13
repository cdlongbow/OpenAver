"""請求所屬殼的身分 key（TASK-168d-T2 / CD-168d-4）。"""
from __future__ import annotations

import hashlib

from fastapi import Request


def shell_key(request: Request) -> str | None:
    """① 帶 `sid` cookie 或 Bearer → `t:<sha256(ticket)[:16]>`；② 否則本機 → `loopback`；
    ③ 否則 `ip:<host>`；沒有 client 且無票據 → None。

    只看「有沒有帶」，**不驗票據**（驗證是 access_gate 的事）；key 不入 log。
    """
    from web.app import _bearer_token, _is_loopback_host  # noqa: PLC2701 — 延遲 import 避免循環，同 web/routers/client.py 先例

    ticket = request.cookies.get("sid") or _bearer_token(request)
    if ticket:
        return "t:" + hashlib.sha256(ticket.encode("utf-8")).hexdigest()[:16]
    host = request.client.host if request.client else None
    if not host:
        return None
    if _is_loopback_host(host):
        return "loopback"
    return "ip:" + host
