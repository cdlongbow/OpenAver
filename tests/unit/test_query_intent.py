"""classify_query / _detect_mode 接線測試（175a-T6，CD-175a-2）。"""
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import core.maker_mapping as mm
import core.maker_names as mn
from core.maker_names import known_makers
from core.query_intent import Intent, classify_query
from core.scrapers.utils import is_uncensored_route, resolve_route_target
from web.routers.search import _detect_mode

ROOT = Path(__file__).resolve().parent.parent.parent
LIB_MAKER = "片庫專有片商"


@pytest.fixture
def known():
    """真實對照表 + 注入的片庫片商名（不碰 DB）。"""
    mn._static_keys.cache_clear()
    with patch("core.maker_names.library_maker_names", return_value={LIB_MAKER}):
        yield known_makers()
    mn._static_keys.cache_clear()


# ---------- CD-175a-2 oracle ----------

@pytest.mark.parametrize("q", ["SOD", "S1", "MOODYZ", "Attackers", "アタッカーズ", "本中", LIB_MAKER, "DANDY", "ＤＡＮＤＹ"])
def test_maker_names_resolve_to_maker(known, q):
    assert classify_query(q, known, resolve_makers=True).mode == "maker"


@pytest.mark.parametrize("q,mode", [
    ("MIDV", "prefix"), ("SSIS", "prefix"), ("MIDV-01", "partial"), ("SONE-205", "exact"),
    ("三上悠亜", "actress"), ("温泉", "actress"),
])
def test_non_maker_modes(known, q, mode):
    assert classify_query(q, known, resolve_makers=True).mode == mode


def test_maker_intent_carries_key(known):
    assert classify_query("ＳＯＤ ", known, resolve_makers=True) == Intent("maker", "sod")
    assert classify_query("MIDV", known, resolve_makers=True) == Intent("prefix", "")


@pytest.mark.parametrize("q,expected", [("DOC", "prefix"), ("doc", "prefix"), ("ＤＯＣ", "actress")])
def test_doc_is_prefix_not_maker(q, expected):
    # DOC 同時是 Prestige 的名字（片庫/別名）又是別家的番號前綴 → 不判片商；
    # 之後落到的 mode 與今天相同（全形 ＤＯＣ 今天就不是 prefix 形狀 → actress）
    k = frozenset({"doc", "prestige"})
    got = classify_query(q, k, resolve_makers=True).mode
    assert got != "maker"
    assert got == expected == old_detect_mode(q)


def test_doc_rule_does_not_hit_same_maker_prefix():
    k = frozenset({"dandy"})
    assert classify_query("DANDY", k, resolve_makers=True).mode == "maker"


@pytest.mark.parametrize("q,expected", [("S1", "maker"), ("SOD", "maker")])
def test_maker_beats_partial_and_prefix(known, q, expected):
    assert classify_query(q, known, resolve_makers=True).mode == expected


@pytest.mark.parametrize("q,expected", [("SOD", "prefix"), ("S1", "partial"), ("DANDY", "prefix")])
def test_resolve_makers_false_keeps_todays_mode(known, q, expected):
    assert classify_query(q, known, resolve_makers=False).mode == expected


@pytest.mark.parametrize("q", ["", "   ", "﻿", "　"])
def test_blank_query_is_never_maker(q):
    assert classify_query(q, frozenset({""}), resolve_makers=True).mode != "maker"
    mn._static_keys.cache_clear()
    with patch("core.maker_names.library_maker_names", return_value={"", " ", "\ufeff"}):
        assert "" not in known_makers()


# ---------- _detect_mode 接線 ----------

def test_detect_mode_default_never_reads_library():
    with patch("core.maker_names.library_maker_names") as lib:
        assert _detect_mode("SOD") == "prefix"
        assert _detect_mode("三上悠亜") == "actress"
    assert lib.call_count == 0


def test_detect_mode_default_keeps_todays_mode():
    with patch("core.maker_names.library_maker_names", return_value={LIB_MAKER}):
        assert _detect_mode("SOD") == "prefix"
        assert _detect_mode("S1") == "partial"
        assert _detect_mode(LIB_MAKER) == "actress"


def test_detect_mode_resolve_makers_true_reads_library():
    mn._static_keys.cache_clear()
    with patch("core.maker_names.library_maker_names", return_value={LIB_MAKER}):
        assert _detect_mode("SOD", True) == "maker"
        assert _detect_mode(LIB_MAKER, True) == "maker"


# ---------- BE-GUARD-03 差集 oracle（凍結的舊順序） ----------

def _is_number_format(s):
    from core.scraper import is_number_format
    return is_number_format(s)


def old_detect_mode(q):
    """凍結：改動前 web/routers/search.py::_detect_mode。"""
    from core.scraper import is_number_format, is_partial_number, is_prefix_only
    target = resolve_route_target(q)
    if is_number_format(target):
        return "exact"
    elif is_partial_number(q):
        return "partial"
    elif is_prefix_only(q):
        return "prefix"
    return "actress"


def old_smart_search_mode(query):
    """凍結：改動前 core/scraper.py::smart_search 內聯順序（含兩道前置閘）。"""
    from core.scraper import is_number_format, is_partial_number, is_prefix_only
    query = query.strip()
    if not query or len(query) < 2:
        return "short"
    target = resolve_route_target(query)
    if is_uncensored_route(target):
        return "uncensored"
    if is_number_format(target):
        return "exact"
    elif is_partial_number(query):
        return "partial"
    elif is_prefix_only(query):
        return "prefix"
    return "actress"


ALL_INPUTS = [
    "ABP-1", "SONE-0", "SONE205", "ABP12", "ＳＯＮＥ－２０５", "ＩＰＺＺ", "SONE-205", "IPZZ-03", "MIDV-01",
    "AB", "ABCDEF", "ABCDEFG", "abc", "SONE 205", " SONE-205 ", " IPZZ ", "　", "﻿", "﻿SOD", "[ABC-123]",
    "abc-123.mp4", "sone-205-UC", "SONE-205-UNCEN", "fc2 12", "FC2-123456", "fc2ppv 123456", "HEYZO-1234",
    "123456-789", "123456_789", "a", "", " ", "三上悠亜", "温泉", "SOD", "S1", "DOC", "DANDY", "200GANA-3360",
    "259LUXU-1234", "7IPZ-154", "2024", "VR 8K", "T28-103", "3DSVR-1774", "ABC-1234567",
]


@pytest.mark.parametrize("q", ALL_INPUTS, ids=[repr(q) for q in ALL_INPUTS])
def test_diff_oracle_matches_old_detect_mode(q):
    assert classify_query(q, frozenset()).mode == old_detect_mode(q)
    assert _detect_mode(q) == old_detect_mode(q)


def test_diff_oracle_vs_old_smart_search_only_two_gate_classes():
    diffs = []
    for q in ALL_INPUTS:
        old = old_smart_search_mode(q)
        new = classify_query(q.strip(), frozenset()).mode
        if old != new:
            diffs.append((q, old, new))
    for q, old, _ in diffs:
        assert old in ("short", "uncensored"), (q, old)
        if old == "short":
            assert len(q.strip()) < 2
        else:
            assert is_uncensored_route(resolve_route_target(q.strip()))
    # 不是空比對：兩類閘都真的有被觸發
    assert {o for _, o, _ in diffs} == {"short", "uncensored"}


# ---------- known_makers 組成 ----------

def test_known_makers_composition(monkeypatch, tmp_path):
    import json
    f = tmp_path / "maker_mapping.json"
    f.write_text(json.dumps({
        "_meta": {}, "search_aliases": {"ＡＬＩＡＳ": "Canon Name"},
        "name_mapping": {"ほげ": "Hoge"}, "prefix_mapping": {"HOG": "Hoge", "BLK": "  "},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mm, "MAKER_MAPPING_FILE", f)
    monkeypatch.setattr(mm, "_cache", None)
    mn._static_keys.cache_clear()
    try:
        with patch("core.maker_names.library_maker_names", return_value={"Lib Maker", " "}):
            ks = known_makers()
        assert ks == frozenset({"ほげ", "hoge", "alias", "canon name", "lib maker"})
    finally:
        mn._static_keys.cache_clear()


def test_library_maker_names_failure_returns_empty():
    with patch("core.database.VideoRepository.get_distinct_makers", side_effect=RuntimeError("no db")):
        assert mn.library_maker_names() == set()


# ---------- BE-PY-08 ----------

@pytest.mark.parametrize("mod", ["core.query_intent", "core.maker_names"])
def test_module_import_does_not_pull_database_or_scraper(mod):
    code = (
        f"import sys; sys.path[:0]=[{str(ROOT)!r}]\n"
        f"import {mod}\n"
        "bad=[m for m in ('core.database','core.scraper') if m in sys.modules]\n"
        "assert not bad, bad\n"
    )
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
