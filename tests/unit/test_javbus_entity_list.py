"""test_javbus_entity_list.py — JavBus 卡片組裝特徵向量＋宣告能力（TASK-175c-T4）。

站方 HTML、實體頁、詳情頁、守衛 belongs 不在單元測試裡造假回應：靠活站金絲雀
（tests/smoke/test_javbus_search_canary.py）。這裡只剩輸入是我們自己的 Video 模型、不碰站方回應的案。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import core.scraper as scraper_mod
from core.scrapers.models import Actress, Video
from core.search_providers.javbus import JavBusProvider
from core.search_providers.types import Kind


# ================================================================ build_card 特徵向量
# 期望 dict 是在 core/scraper.py 未改動（HEAD）時由 search_jav 算出、字面貼回的常數；抽出 build_card 前後都必須相等。
# 〔使用者按「補齊」或搜番號 → 若抽出後卡片多／少一個鍵或補錯片商，書籤／NFO／片庫逐欄吃到的資料就悄悄變了〕
def _vec_video_with_maker() -> Video:
    return Video(
        number="SSIS-001", title="Maker Present", actresses=[Actress(name="Alice"), Actress(name="Bob")],
        date="2026-01-02", maker="MakerA", cover_url="https://img.example/c.jpg", tags=["t1", "t2"],
        source="javbus", detail_url="https://www.javbus.com/ja/SSIS-001", director="Dir", duration=120,
        label="Lab", series="Ser", sample_images=["https://img.example/s1.jpg"],
        entity_ids={"actors": ["2xi", "w5a"], "director": ["o7"], "series": ["fg8"], "label": ["9x"]},
    )


def _vec_video_maker_from_prefix() -> Video:
    return Video(number="ABC-123", title="No Maker Known Prefix", date="2026-02-03", source="javbus",
                 detail_url="https://www.javbus.com/ja/ABC-123", entity_ids={"actors": ["zz1"]})


def _vec_video_summary_rating() -> Video:
    return Video(number="SSIS-002", title="With Summary", maker="MakerB", source="javbus",
                 summary="the plot", rating=4.5, votes=12, preview_cover_url="https://img.example/p.jpg")


def _vec_video_unknown_prefix() -> Video:
    return Video(number="ZZZ-999", title="Unknown Prefix", source="javbus")


VECTOR_CASES = [
    (_vec_video_with_maker, "SSIS-001"),
    (_vec_video_maker_from_prefix, "ABC-123"),
    (_vec_video_summary_rating, "SSIS-002"),
    (_vec_video_unknown_prefix, "ZZZ-999"),
]


def _fixed_maker_by_prefix(number):
    return "PrefixMaker" if number.upper().startswith("ABC-") else ""


@pytest.fixture
def card_env(monkeypatch):
    """build_card／search_jav 尾段的外部輸入固定下來：前綴對照表與片商正名表不吃真檔。"""
    monkeypatch.setattr("core.scraper.get_maker_by_prefix", _fixed_maker_by_prefix)
    monkeypatch.setattr("core.maker_mapping.load_name_mapping", lambda: {"MakerA": "MakerA-Normalized"})


def _search_jav_card(make_video, number):
    with patch.object(scraper_mod.JavBusScraper, "search", return_value=make_video()):
        return scraper_mod.search_jav(number, "javbus", javbus_lang="ja")


EXPECTED_VECTORS = {
    # 在 core/scraper.py 未改動時由 search_jav 輸出字面貼回（含 entity_ids 非空的那組：不得多出任何鍵）
    "SSIS-001": {
        'number': 'SSIS-001', 'title': 'Maker Present', 'actors': ['Alice', 'Bob'], 'date': '2026-01-02',
        'maker': 'MakerA-Normalized', 'cover': 'https://img.example/c.jpg', 'preview_cover_url': '',
        'tags': ['t1', 't2'], 'source': 'javbus', 'url': 'https://www.javbus.com/ja/SSIS-001',
        'director': 'Dir', 'duration': 120, 'label': 'Lab', 'series': 'Ser',
        'sample_images': ['https://img.example/s1.jpg'], 'preview_sample_images': [],
        '_source': 'javbus', '_summary': '', '_rating': None,
    },
    "ABC-123": {
        'number': 'ABC-123', 'title': 'No Maker Known Prefix', 'actors': [], 'date': '2026-02-03',
        'maker': 'PrefixMaker', 'cover': '', 'preview_cover_url': '', 'tags': [], 'source': 'javbus',
        'url': 'https://www.javbus.com/ja/ABC-123', 'director': '', 'duration': None, 'label': '', 'series': '',
        'sample_images': [], 'preview_sample_images': [],
        '_source': 'javbus', '_summary': '', '_rating': None,
    },
    "SSIS-002": {
        'number': 'SSIS-002', 'title': 'With Summary', 'actors': [], 'date': '', 'maker': 'MakerB', 'cover': '',
        'preview_cover_url': 'https://img.example/p.jpg', 'tags': [], 'source': 'javbus', 'url': '',
        'director': '', 'duration': None, 'label': '', 'series': '', 'sample_images': [],
        'preview_sample_images': [],
        '_source': 'javbus', '_summary': 'the plot', '_rating': 4.5,
    },
    "ZZZ-999": {
        'number': 'ZZZ-999', 'title': 'Unknown Prefix', 'actors': [], 'date': '', 'maker': '', 'cover': '',
        'preview_cover_url': '', 'tags': [], 'source': 'javbus', 'url': '', 'director': '', 'duration': None,
        'label': '', 'series': '', 'sample_images': [], 'preview_sample_images': [],
        '_source': 'javbus', '_summary': '', '_rating': None,
    },
}


@pytest.mark.parametrize("make_video,number", VECTOR_CASES, ids=[n for _, n in VECTOR_CASES])
def test_search_jav_card_vector_is_bit_for_bit(card_env, make_video, number):
    """特徵測試（改前綠、抽出後仍綠）：整個 dict 逐位元比對，不是鍵子集；涵蓋 to_legacy_dict 不輸出 entity_ids。"""
    assert _search_jav_card(make_video, number) == EXPECTED_VECTORS[number]


def test_build_card_matches_search_jav_vector(card_env):
    """抽出的 build_card 對同一組 Video 產出與 HEAD 的 search_jav 完全相同的 dict（RED：抽出前不存在）。"""
    from core.scraper import build_card

    for make_video, number in VECTOR_CASES:
        assert build_card(make_video(), number) == EXPECTED_VECTORS[number]


def test_capabilities_are_exactly_the_eight_kinds():
    assert JavBusProvider.capabilities == frozenset({
        Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL, Kind.MAKER, Kind.CODE, Kind.PARTIAL, Kind.KEYWORD})
    assert JavBusProvider.supports_discovery is True
    assert JavBusProvider.fallback_streaming is False  # 補完詳情後依日期重排 ⇒ 串流順序≠最終順序（BE-DATA-20）
