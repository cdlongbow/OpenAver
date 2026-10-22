"""test_search_names.py — 搬家等價與 split_paren_name（TASK-175c-T3，plan CD-175c-1／CD-175c-3）。

`fold`、`maker_names` 自 javdb.py 搬到 core.name_match／core.search_providers.names；
下面兩張向量表的期望值是**搬家前**（HEAD）`javdb.fold`／`javdb._maker_names` 對同一組輸入實際算出的輸出，
字面寫死成常數（不是讓新實作自己算自己比）。零活站請求。
"""
import subprocess
import sys
from pathlib import Path

import pytest

from core.name_match import fold, split_paren_name
from core.search_providers.names import maker_names

ROOT = Path(__file__).resolve().parents[2]

FOLD_VECTORS = [  # (輸入, 搬家前 HEAD javdb.fold 的輸出)
    ('ＡＢＣ１２３', 'abc123'),
    ('あかね・麗', 'あかね麗'),
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
    ('AAA', TABLE, ALIASES, ['AAA', 'A1', 'A2', 'A3']),
    ('カリビアンコム', TABLE, ALIASES, ['カリビアンコム', 'Caribbeancom']),
]


@pytest.mark.parametrize("raw, expected", FOLD_VECTORS)
def test_fold_matches_pre_move_output(raw, expected):
    assert fold(raw) == expected


@pytest.mark.parametrize("q, name_mapping, search_aliases, expected", MAKER_VECTORS)
def test_maker_names_matches_pre_move_output(q, name_mapping, search_aliases, expected):
    assert maker_names(q, name_mapping=name_mapping, search_aliases=search_aliases) == expected


# ---------------------------------------------------------------- split_paren_name（卡片 D4）
PAREN_TABLE = [
    ("あかね麗（二階堂麗）", ("あかね麗", "二階堂麗")),
    ("（二階堂麗）", ("（二階堂麗）", None)),
]


@pytest.mark.parametrize("raw, expected", PAREN_TABLE)
def test_split_paren_name_table(raw, expected):
    assert split_paren_name(raw) == expected


def test_name_match_import_pulls_no_scraper_or_database():
    code = (
        "import sys; sys.path[:0]=[%r]; import core.name_match; "
        "bad=[m for m in ('core.scraper','core.database','core.scrapers') if m in sys.modules]; "
        "assert not bad, bad" % str(ROOT)
    )
    proc = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
