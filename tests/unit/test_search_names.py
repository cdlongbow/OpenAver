"""test_search_names.py — 搬家等價與 split_paren_name（TASK-175c-T3，plan CD-175c-1／CD-175c-3）。

`fold`、`maker_names` 自 javdb.py 搬到 core.name_match／core.search_providers.names；
下面兩張向量表的期望值是**搬家前**（HEAD）`javdb.fold`／`javdb._maker_names` 對同一組輸入實際算出的輸出，
字面寫死成常數（不是讓新實作自己算自己比）。零活站請求。
"""
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core.name_match import fold, split_paren_name
from core.scrapers.dmm import _actress_main_name
from core.search_providers import javdb as jp
from core.search_providers import names as names_mod
from core.search_providers.names import maker_names

ROOT = Path(__file__).resolve().parents[2]

FOLD_VECTORS = [  # (輸入, 搬家前 HEAD javdb.fold 的輸出)
    ('ＡＢＣ１２３', 'abc123'),
    ('ＳＳＩＳ－００１', 'ssis001'),
    ('三上\u3000悠亜', '三上悠亜'),
    ('三上 悠亜', '三上悠亜'),
    (' 三上悠亜 ', '三上悠亜'),
    ('ｱｲｳｴｵ', 'アイウエオ'),
    ('ﾊﾟｼﾞ', 'パジ'),
    ('ｶﾞｷﾞ', 'ガギ'),
    ('あかね・麗', 'あかね麗'),
    ('あかね·麗', 'あかね麗'),
    ('S1-NO.1_STYLE', 's1no.1style'),
    ('ß', 'ss'),
    ('Straße', 'strasse'),
    ('İstanbul', 'i\u0307stanbul'),
    ('ǅ', 'dž'),
    ('Ａｂｃ\u3000Ｄｅｆ', 'abcdef'),
    ('ABC-def_GHI', 'abcdefghi'),
    ('・·-_', ''),
    ('\t\n三上\xa0悠亜\u2003', '三上悠亜'),
    ('ＰＬＡＴＩＮＵＭ ＳＯＡＰ', 'platinumsoap'),
    ('①②③', '123'),
    ('㈱エスワン', '(株)エスワン'),
    ('ﾏﾙｺ', 'マルコ'),
    ('', ''),
    (None, ''),
    (123, ''),
    (b'abc', ''),
    (['x'], ''),
    (0, ''),
]

TABLE = {'エスワン': 'S1',
 'エスワンナンバーワンスタイル': 'S1',
 'S1 NO.1 STYLE': 'S1',
 'エスワン ナンバーワンスタイル': 'S1',
 'ソフト・オン・デマンド': 'SOD Create',
 'SODクリエイト': 'SOD Create',
 'ＳＯＤ\u3000ＣＲＥＡＴＥ': 'SOD Create',
 'ムーディーズ': 'MOODYZ',
 'A1': 'AAA',
 'A2': 'AAA',
 'A3': 'AAA',
 'A4': 'AAA',
 'A5': 'AAA'}
ALIASES = {'カリビアンコム': 'Caribbeancom', 'エスオーディー': 'SOD Create', 'ワンダー': 'WONDER'}

MAKER_VECTORS = [  # (輸入, name_mapping, search_aliases, 搬家前 HEAD javdb._maker_names 的輸出)
    ('S1', TABLE, ALIASES, ['S1', 'エスワン', 'エスワンナンバーワンスタイル', 'S1 NO.1 STYLE']),
    ('s1', TABLE, ALIASES, ['s1', 'エスワン', 'エスワンナンバーワンスタイル', 'S1 NO.1 STYLE']),
    ('Ｓ１', TABLE, ALIASES, ['Ｓ１', 'エスワン', 'エスワンナンバーワンスタイル', 'S1 NO.1 STYLE']),
    (' S1 ', TABLE, ALIASES, [' S1 ', 'エスワン', 'エスワンナンバーワンスタイル', 'S1 NO.1 STYLE']),
    ('S1\u3000', TABLE, ALIASES, ['S1\u3000', 'エスワン', 'エスワンナンバーワンスタイル', 'S1 NO.1 STYLE']),
    ('エスワン', TABLE, ALIASES, ['エスワン', 'S1', 'エスワンナンバーワンスタイル', 'S1 NO.1 STYLE']),
    ('S1 NO.1 STYLE', TABLE, ALIASES, ['S1 NO.1 STYLE', 'S1', 'エスワン', 'エスワンナンバーワンスタイル']),
    ('ムーディーズ', TABLE, ALIASES, ['ムーディーズ', 'MOODYZ']),
    ('MOODYZ', TABLE, ALIASES, ['MOODYZ', 'ムーディーズ']),
    ('moodyz', TABLE, ALIASES, ['moodyz', 'ムーディーズ']),
    ('AAA', TABLE, ALIASES, ['AAA', 'A1', 'A2', 'A3']),
    ('A3', TABLE, ALIASES, ['A3', 'AAA', 'A1', 'A2']),
    ('SOD Create', TABLE, ALIASES, ['SOD Create', 'ソフト・オン・デマンド', 'SODクリエイト', 'エスオーディー']),
    ('ＳＯＤ ＣＲＥＡＴＥ', TABLE, ALIASES, ['ＳＯＤ ＣＲＥＡＴＥ', 'ソフト・オン・デマンド', 'SODクリエイト', 'エスオーディー']),
    ('sod create', TABLE, ALIASES, ['sod create', 'ソフト・オン・デマンド', 'SODクリエイト', 'エスオーディー']),
    ('SODクリエイト', TABLE, ALIASES, ['SODクリエイト', 'SOD Create', 'ソフト・オン・デマンド', 'エスオーディー']),
    ('エスオーディー', TABLE, ALIASES, ['エスオーディー', 'SOD Create', 'ソフト・オン・デマンド', 'SODクリエイト']),
    ('ソフト・オン・デマンド', TABLE, ALIASES, ['ソフト・オン・デマンド', 'SOD Create', 'SODクリエイト', 'エスオーディー']),
    ('カリビアンコム', TABLE, ALIASES, ['カリビアンコム', 'Caribbeancom']),
    ('Caribbeancom', TABLE, ALIASES, ['Caribbeancom', 'カリビアンコム']),
    ('ワンダー', TABLE, ALIASES, ['ワンダー', 'WONDER']),
    ('WONDER', TABLE, ALIASES, ['WONDER', 'ワンダー']),
    ('UnknownMaker', TABLE, ALIASES, ['UnknownMaker']),
    ('未知の片商', TABLE, ALIASES, ['未知の片商']),
    ('', TABLE, ALIASES, []),
    ('   ', TABLE, ALIASES, []),
    ('\u3000', TABLE, ALIASES, []),
    ('S1', TABLE, {}, ['S1', 'エスワン', 'エスワンナンバーワンスタイル', 'S1 NO.1 STYLE']),
    ('カリビアンコム', TABLE, {}, ['カリビアンコム']),
    ('AAA', TABLE, {}, ['AAA', 'A1', 'A2', 'A3']),
    ('S1', {}, ALIASES, ['S1']),
    ('カリビアンコム', {}, ALIASES, ['カリビアンコム', 'Caribbeancom']),
    ('Caribbeancom', {}, ALIASES, ['Caribbeancom', 'カリビアンコム']),
    ('S1', {}, {}, ['S1']),
    ('', {}, {}, []),
]


@pytest.mark.parametrize("raw, expected", FOLD_VECTORS)
def test_fold_matches_pre_move_output(raw, expected):
    assert fold(raw) == expected


def test_javdb_uses_the_shared_fold_not_a_second_copy():
    # 使用者打女優名 → JavDB 與 JavBus 若各有一份 fold，某天改一邊另一邊就悄悄比對不到同一個人
    assert jp.fold is fold


@pytest.mark.parametrize("q, name_mapping, search_aliases, expected", MAKER_VECTORS)
def test_maker_names_matches_pre_move_output(q, name_mapping, search_aliases, expected):
    assert maker_names(q, name_mapping=name_mapping, search_aliases=search_aliases) == expected


@pytest.mark.parametrize("q, name_mapping, search_aliases, expected", MAKER_VECTORS)
def test_javdb_maker_names_wrapper_still_reads_javdb_load_functions(q, name_mapping, search_aliases, expected):
    # 既有 JavDB 測試 patch 的是 javdb 模組上的 load_*；薄包裝必須仍從那裡取表，合成對照表才打得進來
    with patch.object(jp, "load_name_mapping", lambda: name_mapping), \
         patch.object(jp, "load_search_aliases", lambda: search_aliases):
        assert jp._maker_names(q) == expected


def test_maker_names_loads_tables_itself_when_not_given():
    with patch.object(names_mod, "load_name_mapping", lambda: TABLE), \
         patch.object(names_mod, "load_search_aliases", lambda: ALIASES):
        assert maker_names("カリビアンコム") == ["カリビアンコム", "Caribbeancom"]
        assert maker_names("S1") == ["S1", "エスワン", "エスワンナンバーワンスタイル", "S1 NO.1 STYLE"]


def test_maker_names_explicit_empty_table_is_not_replaced_by_loading():
    # 傳入 {} 是「這張表就是空的」，不是「請自己載入」
    with patch.object(names_mod, "load_name_mapping", lambda: TABLE), \
         patch.object(names_mod, "load_search_aliases", lambda: ALIASES):
        assert maker_names("S1", name_mapping={}, search_aliases={}) == ["S1"]


# ---------------------------------------------------------------- split_paren_name（卡片 D4）
PAREN_TABLE = [
    ("あかね麗（二階堂麗）", ("あかね麗", "二階堂麗")),
    ("あかね麗 （二階堂麗）", ("あかね麗", "二階堂麗")),
    ("A（B、C）", ("A", "B、C")),
    ("三上悠亜", ("三上悠亜", None)),
    ("Name(Old)", ("Name(Old)", None)),
    ("A（B）C", ("A（B）C", None)),
    ("（二階堂麗）", ("（二階堂麗）", None)),
    ("A（B）（C）", ("A（B）", "C")),
    ("", ("", None)),
    (None, (None, None)),
]


@pytest.mark.parametrize("raw, expected", PAREN_TABLE)
def test_split_paren_name_table(raw, expected):
    assert split_paren_name(raw) == expected


@pytest.mark.parametrize("raw, _", PAREN_TABLE)
def test_split_paren_main_equals_dmm_actress_main_name(raw, _):
    # T7 才讓 DMM 改呼叫 split_paren_name；在那之前兩邊必須逐項相等，換手時才不會有行為差
    assert split_paren_name(raw)[0] == _actress_main_name(raw)


def test_name_match_import_pulls_no_scraper_or_database():
    code = (
        "import sys; sys.path[:0]=[%r]; import core.name_match; "
        "bad=[m for m in ('core.scraper','core.database','core.scrapers') if m in sys.modules]; "
        "assert not bad, bad" % str(ROOT)
    )
    proc = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
