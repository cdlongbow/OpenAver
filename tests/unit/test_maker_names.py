"""175b-T8c：maker_spellings（候選拼法：輸入、正名、該正名底下全部別名，不設上限）。"""

from unittest.mock import patch

from core.maker_names import maker_spellings

NAME_MAP = {"SOD": "SOD Create", "ソフトオンデマンド": "SOD Create", "Ｓ１": "S1 NO.1 STYLE"}
ALIASES = {"SODクリエイト": "SOD Create", "ＳＯＤ ＣＲＥＡＴＥ": "SOD Create", "extra": "SOD Create"}


def _patched():
    return (
        patch("core.maker_names.load_name_mapping", return_value=NAME_MAP),
        patch("core.maker_names.load_search_aliases", return_value=ALIASES),
    )


def test_spellings_start_with_input_then_canon_then_all_aliases_no_cap():
    a, b = _patched()
    with a, b:
        out = maker_spellings("SOD")
    assert out[0] == "SOD"
    assert out[1] == "SOD Create"
    assert set(out) >= {"ソフトオンデマンド", "SODクリエイト", "extra"}
    assert len(out) >= 5  # 不設 4 個上限


