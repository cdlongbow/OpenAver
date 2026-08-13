"""Scraper 錯誤型別

區分「來源被擋／連不上」（SourceBlocked）與「查無此片」（回傳 None）。
兩者語意不同：前者代表暫時性/網路層問題，後者代表站方確實查無資料
（CD-118b-4）。

BlockedRecord 本檔只定義不使用（plan-118b T4a 才接上聚合層）。
"""
from dataclasses import dataclass
from typing import Optional


class SourceBlocked(RuntimeError):
    """來源被擋／連不上（≠ 查無此片）。"""

    def __init__(
        self,
        source_id: str,
        article_id: str,
        status: Optional[int] = None,
        message: str = "",
    ):
        self.source_id = source_id
        self.article_id = article_id
        self.status = status
        super().__init__(
            message or f"{source_id} blocked for {article_id} (status={status})"
        )


@dataclass(frozen=True, slots=True)
class BlockedRecord:
    """被擋事件的不可變記錄（T4a 聚合層使用）。"""

    source_id: str
    article_id: str
    status: Optional[int]
