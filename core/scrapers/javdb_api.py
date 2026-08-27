"""JavDB App 資料介面的傳輸層：簽名、網域備援、逾時、例外映射。"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Optional

import requests

from core.logger import get_logger
from core.scrapers.errors import SourceBlocked, SourceUnreachable

logger = get_logger(__name__)

# JavDB App 資料介面的請求簽名參數。這組值失效時（例如站方輪替簽章），
# API 路徑會整條失敗 → search() 自動降級回 HTML，使用者無感，
# 我們靠金絲雀 A 轉紅知道。
_API_HOSTS = ("https://jdforrepam.com", "https://javdb.com")

_SIGN_PREFIX = (
    "71cf27bb3c0bcdf207b64abecddc970098c7421ee7203b9cdae54478478a199e"
    "7d5a6e1a57691123c1a931c057842fb73ba3b3c83bcd69c17ccf174081e3d8aa"
)
_SIGN_SUFFIX = "lpw6vgqzsp"

_USER_AGENT = "Dart/3.4 (dart:io)"

_SEARCH_PATH = "/api/v2/search"
_DETAIL_PATH = "/api/v4/movies/{movie_id}"

_TIMEOUT = 20

_PUBLIC_PARAMS = {
    "app_channel": "official",
    "app_version": "1.9.28",
    "app_version_number": "10928",
    "platform": "android",
    "system_version": "13",
    "device_model": "Pixel 6",
    "device_name": "Pixel",
}

# 一個 process 共用一個裝置 id；寫死會讓所有安裝撞同一個 id，每次請求都換又像洗裝置。
_DEVICE_UUID = str(uuid.uuid4())


def sign(ts: int | None = None) -> str:
    """回傳 jdsignature；ts 為 None 或 <=0 時用當下 unix 時間。"""
    if ts is None or ts <= 0:
        ts = int(time.time())
    digest = hashlib.md5(f"{ts}{_SIGN_PREFIX}".encode("utf-8")).hexdigest()
    return f"{ts}.{_SIGN_SUFFIX}.{digest}"


def _success_truthy(value: Any) -> bool:
    """寬鬆判斷信封 success 為真（實測常見 int 1；也可能是 true / \"1\"）。"""
    return bool(value) and value not in (0, "0", "false", "False")


def api_get(path: str, params: Optional[dict] = None) -> dict:
    """對 javdb App API 發 GET，回傳信封裡的 data（dict）；失敗一律 raise。"""
    query = dict(_PUBLIC_PARAMS)
    query["device_uuid"] = _DEVICE_UUID
    if params:
        query.update(params)

    last_error: Optional[BaseException] = None

    for host in _API_HOSTS:
        url = host + path
        # 每次嘗試重新簽名：簽名帶時間戳且有效期有限，主網域吃滿逾時後
        # 沿用同一份簽名，鏡像那一趟可能拿到一個已經過期的簽名。
        headers = {
            "jdsignature": sign(),
            "user-agent": _USER_AGENT,
            "accept-language": "zh-TW",
            "connection": "keep-alive",
        }
        try:
            # 絕對不傳 proxies：傳了就等於把使用者的系統代理靜默關掉。
            resp = requests.get(
                url,
                params=query,
                headers=headers,
                timeout=_TIMEOUT,
            )
        except requests.exceptions.RequestException as e:
            last_error = SourceUnreachable(str(e))
            continue

        status = resp.status_code
        if status in (403, 429, 503):
            logger.warning("JavDB API blocked (%s) for %s", status, url)
            last_error = SourceBlocked(f"blocked {status} for {url}")
            continue

        if status != 200:
            logger.warning("JavDB API non-200 for %s: %s", url, status)
            last_error = SourceUnreachable(f"non-200 {status} for {url}")
            continue

        try:
            envelope = resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            last_error = SourceUnreachable(f"non-json for {url}")
            continue

        if not isinstance(envelope, dict) or not _success_truthy(envelope.get("success")):
            action = envelope.get("action") if isinstance(envelope, dict) else None
            logger.warning("JavDB API rejected (%s) for %s", action, url)
            last_error = SourceUnreachable(f"rejected {action} for {url}")
            continue

        data = envelope.get("data")
        if not isinstance(data, dict):
            last_error = SourceUnreachable(f"data not dict for {url}")
            continue

        return data

    if last_error is not None:
        raise last_error
    raise SourceUnreachable("JavDB API unreachable")


def api_search(keyword: str) -> list[dict]:
    """回搜尋結果清單；查無回 []（不是錯誤，不 raise）。"""
    data = api_get(_SEARCH_PATH, {"q": keyword, "page": "1"})
    movies = data.get("movies")
    return movies if isinstance(movies, list) else []


def api_movie_detail(movie_id: str) -> dict:
    """回詳情 movie 物件；形狀不對就 raise SourceUnreachable。"""
    data = api_get(_DETAIL_PATH.format(movie_id=movie_id))
    movie = data.get("movie")
    if not isinstance(movie, dict):
        raise SourceUnreachable(f"movie detail missing for id={movie_id}")
    return movie
