"""nfo_title_format.py — NFO 標題格式代換／驗證／讀回（CD-154b-1／CD-154b-2）。

單一擁有者：format_nfo_title / validate_nfo_title_format / resolve_title_body。
與 core.organizer.format_string 的差集：不 sanitize_filename、不 .strip()、
不支援 {suffix}、空值一律代換成空字串（無 FALLBACKS）。
"""

from __future__ import annotations

import re
from typing import Optional

from core.organizer import _strip_num_prefixes


def format_nfo_title(template: str, data: dict) -> str:
    """依模板代換 NFO 顯示標題；空值一律空字串，不做 sanitize／strip／fallback。"""
    result = template

    result = result.replace('{num}', data.get('number', ''))

    title = data.get('title', '') or ''
    result = result.replace('{title}', title)

    actors = data.get('actors', []) or []
    if actors:
        result = result.replace('{actor}', actors[0])
        result = result.replace('{actors}', ', '.join(actors))
    else:
        result = result.replace('{actor}', '')
        result = result.replace('{actors}', '')

    maker = data.get('maker', '') or ''
    result = result.replace('{maker}', maker)

    date = data.get('date', '') or ''
    result = result.replace('{date}', date)
    result = result.replace('{year}', date[:4] if date else '')
    result = result.replace('{month}', date[5:7] if len(date) >= 7 else '')
    result = result.replace('{day}', date[8:10] if len(date) >= 10 else '')

    return result


def validate_nfo_title_format(template: str) -> Optional[str]:
    """回傳人類可讀錯誤原因；合法格式回傳 None。

    必須恰好各出現一次 `{num}` 與 `{title}`。
    """
    if template.count('{title}') != 1 or template.count('{num}') != 1:
        if template.count('{num}') == 0:
            return '格式必須包含恰好一個 {num}'
        if template.count('{title}') == 0:
            return '格式必須包含恰好一個 {title}'
        if template.count('{num}') != 1:
            return '{num} 只能出現一次'
        return '{title} 只能出現一次'
    return None


def _strip_bracket_num_prefix(raw_title: str, number: str) -> str:
    """只剝開頭（可多層）的 `[番號]` 方括號前綴；不認裸番號。"""
    if not raw_title or not number:
        return raw_title
    _re = re.compile(
        r'^(?:\[' + re.escape(number) + r'\])[\s\-_]*',
        re.IGNORECASE,
    )
    s = raw_title
    while s:
        nxt = _re.sub('', s, count=1)
        if nxt == s:
            break
        s = nxt
    return s


def resolve_title_body(
    raw_title,
    number,
    actors,
    maker,
    date,
    nfo_title_format,
    record=None,
) -> str:
    """spec §3.5 五步驟讀回規則。見 CD-154b-2。"""
    # 步驟 1／2：record 是 (written, body) 或 None
    if record is not None:
        written, body = record
        if raw_title == written:
            return body                      # 步驟 1：記錄有效
        # 步驟 2：<title> 被外部改過 → 以使用者修改為準，落到步驟 3/4/5
    # 步驟 3：符合預設格式 [{num}]{title}——只認方括號前綴
    bracket_stripped = _strip_bracket_num_prefix(raw_title, number)
    if bracket_stripped != raw_title:         # 有剝到方括號前綴才算「符合預設格式」
        return bracket_stripped
    # 步驟 4：符合目前格式（完全吻合才剝）
    data = {'number': number, 'title': '__BODY__', 'actors': actors, 'maker': maker, 'date': date}
    templated = format_nfo_title(nfo_title_format, data)
    prefix, _, suffix = templated.partition('__BODY__')
    if raw_title.startswith(prefix) and raw_title.endswith(suffix) and (prefix or suffix):
        candidate = raw_title[len(prefix):len(raw_title) - len(suffix) if suffix else None]
        if candidate:
            return candidate
    # 步驟 5：都不符合 → 原樣保留，只去掉開頭番號（今天的既有行為，含裸番號）
    return _strip_num_prefixes(raw_title, number)


def resolve_preserved_title_for_write(disk_title, existing, nfo_title_format, record=None) -> Optional[str]:
    """CD-154b-12：保留重刮時是否用「格式反推本體」覆寫 DB title。

    呼叫端負責讀磁碟 NFO 取得 disk_title／record；本函式不做 I/O。
    回傳非 None 的 body 時，effective_title 應優先採用；回傳 None 時走 154a 原樣保留。
    """
    if existing is None or not existing.title:
        return None
    if disk_title != existing.title:
        return None
    body = resolve_title_body(
        disk_title,
        existing.number,
        existing.actresses,
        existing.maker,
        existing.release_date,
        nfo_title_format,
        record,
    )
    stripped = _strip_num_prefixes(existing.title, existing.number)
    if body != stripped:
        return body
    return None
