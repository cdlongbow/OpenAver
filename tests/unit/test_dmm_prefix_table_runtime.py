"""TASK-134a-T2 — runtime flatten / cache / merge for _load_prefix_hints."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import core.scrapers.dmm as dmm_module
from core.scrapers.dmm import DMMScraper, _flatten_shipped_table
from core.scrapers.models import ScraperConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_TABLE_PATH = PROJECT_ROOT / "dmm_prefix_table.json"


@pytest.fixture(autouse=True)
def _reset_prefix_hint_caches(monkeypatch):
    """BE-TEST-18：每個測試重置三個 module-level 快取，避免互相污染。"""
    monkeypatch.setattr(dmm_module, "_shipped_table_cache", None)
    monkeypatch.setattr(dmm_module, "_local_hints_cache", None)
    monkeypatch.setattr(dmm_module, "_local_hints_cache_mtime", None)


def _scraper() -> DMMScraper:
    return DMMScraper(ScraperConfig(proxy_url=""))


# ── DoD 1 碰撞 ───────────────────────────────────────────────────────────────


def test_flatten_duplicate_prefix_raises_with_prefix_and_makers():
    """DoD 1：兩家片商同一前綴 → ValueError，訊息含前綴與兩家片商名。"""
    raw = {
        "makers": {
            "MakerA": {"abc": {"dmm_prefix": "1", "sample": "ABC-001"}},
            "MakerB": {"abc": {"dmm_prefix": "2", "sample": "ABC-002"}},
        }
    }
    with pytest.raises(ValueError) as exc_info:
        _flatten_shipped_table(raw)
    msg = str(exc_info.value)
    assert "abc" in msg
    assert "MakerA" in msg
    assert "MakerB" in msg


# ── DoD 2 正常 ───────────────────────────────────────────────────────────────


def test_real_shipped_table_flattens_to_160():
    """DoD 2：真實出貨表展平不拋例外、長度 160。"""
    raw = json.loads(REAL_TABLE_PATH.read_text(encoding="utf-8"))
    flat = _flatten_shipped_table(raw)
    assert len(flat) == 160


# ── DoD 3 快取失效 ───────────────────────────────────────────────────────────


def test_local_hints_cache_respects_mtime(tmp_path, monkeypatch):
    """DoD 3：暖機後本機檔 mtime 未變不重讀；mtime 變才重讀一次。出貨表永不重讀。"""
    shipped_path = tmp_path / "dmm_prefix_table.json"
    prefix_path = tmp_path / "dmm_prefix_hints.json"
    shipped_path.write_text(
        json.dumps(
            {
                "makers": {
                    "X": {"aaa": {"dmm_prefix": "1", "sample": "AAA-001"}},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    prefix_path.write_text(
        json.dumps({"bbb": "9"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(dmm_module, "SHIPPED_TABLE_FILE", shipped_path)
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", prefix_path)

    scraper = _scraper()
    scraper._load_prefix_hints()  # 暖機

    prefix_reads = {"n": 0}
    shipped_reads = {"n": 0}
    real_read_text = Path.read_text

    def tracked_read_text(self, *args, **kwargs):
        if self == prefix_path:
            prefix_reads["n"] += 1
        elif self == shipped_path:
            shipped_reads["n"] += 1
        return real_read_text(self, *args, **kwargs)

    with patch.object(Path, "read_text", tracked_read_text):
        # 改內容但還原 mtime → 不得重讀本機檔
        old_mtime = os.stat(prefix_path).st_mtime
        prefix_path.write_text(
            json.dumps({"bbb": "8"}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.utime(prefix_path, (old_mtime, old_mtime))
        prefix_reads["n"] = 0
        shipped_reads["n"] = 0
        scraper._load_prefix_hints()
        assert prefix_reads["n"] == 0
        assert shipped_reads["n"] == 0

        # 改內容並推進 mtime → 本機檔重讀恰好一次；出貨表仍 0
        prefix_path.write_text(
            json.dumps({"bbb": "7"}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.utime(prefix_path, (old_mtime + 10, old_mtime + 10))
        prefix_reads["n"] = 0
        shipped_reads["n"] = 0
        result = scraper._load_prefix_hints()
        assert prefix_reads["n"] == 1
        assert shipped_reads["n"] == 0
        assert result["bbb"] == "7"


# ── DoD 4 純合併 ─────────────────────────────────────────────────────────────


def test_merge_local_overrides_shipped_values_are_str_no_http(
    tmp_path, monkeypatch
):
    """DoD 4：本機優先；僅出貨表有的前綴取出貨表值；value 皆字串；零 HTTP。"""
    shipped_path = tmp_path / "dmm_prefix_table.json"
    prefix_path = tmp_path / "dmm_prefix_hints.json"
    shipped_path.write_text(
        json.dumps(
            {
                "makers": {
                    "MakerX": {
                        "shared": {
                            "dmm_prefix": "shipped_val",
                            "sample": "SHARED-001",
                        },
                        "only_shipped": {
                            "dmm_prefix": "h_99",
                            "sample": "ONLY-001",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    prefix_path.write_text(
        json.dumps(
            {"shared": "local_val", "_meta": "must_skip"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dmm_module, "SHIPPED_TABLE_FILE", shipped_path)
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", prefix_path)

    scraper = _scraper()
    with (
        patch.object(scraper._session, "post") as mock_post,
        patch.object(scraper._session, "get") as mock_get,
    ):
        merged = scraper._load_prefix_hints()
        assert mock_post.call_count == 0
        assert mock_get.call_count == 0

    assert merged["shared"] == "local_val"
    assert merged["only_shipped"] == "h_99"
    assert "_meta" not in merged
    assert all(isinstance(v, str) for v in merged.values())
    assert not any(isinstance(v, dict) for v in merged.values())


# ── DoD 5 缺席降級 ───────────────────────────────────────────────────────────


def test_missing_shipped_table_degrades_to_local_only(
    tmp_path, monkeypatch, caplog
):
    """DoD 5：出貨表檔案不存在 → 不拋例外、只回本機值、有 WARNING。"""
    prefix_path = tmp_path / "dmm_prefix_hints.json"
    prefix_path.write_text(
        json.dumps({"zzz": "1"}, ensure_ascii=False),
        encoding="utf-8",
    )
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(dmm_module, "SHIPPED_TABLE_FILE", missing)
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", prefix_path)

    scraper = _scraper()
    with caplog.at_level(logging.WARNING, logger=dmm_module.logger.name):
        merged = scraper._load_prefix_hints()

    assert merged == {"zzz": "1"}
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_bad_json_shipped_table_degrades(tmp_path, monkeypatch, caplog):
    """DoD 5：出貨表 JSON 壞掉 → 不拋例外、有 WARNING。"""
    shipped_path = tmp_path / "dmm_prefix_table.json"
    prefix_path = tmp_path / "dmm_prefix_hints.json"
    shipped_path.write_text("{not-json", encoding="utf-8")
    prefix_path.write_text(
        json.dumps({"aaa": "2"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(dmm_module, "SHIPPED_TABLE_FILE", shipped_path)
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", prefix_path)

    scraper = _scraper()
    with caplog.at_level(logging.WARNING, logger=dmm_module.logger.name):
        merged = scraper._load_prefix_hints()

    assert merged == {"aaa": "2"}
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_missing_makers_key_degrades(tmp_path, monkeypatch, caplog):
    """DoD 5：出貨表缺 makers 鍵 → 不拋例外、有 WARNING。"""
    shipped_path = tmp_path / "dmm_prefix_table.json"
    prefix_path = tmp_path / "dmm_prefix_hints.json"
    shipped_path.write_text(
        json.dumps({"_meta": {"count": 0}}, ensure_ascii=False),
        encoding="utf-8",
    )
    prefix_path.write_text(
        json.dumps({"bbb": "3"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(dmm_module, "SHIPPED_TABLE_FILE", shipped_path)
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", prefix_path)

    scraper = _scraper()
    with caplog.at_level(logging.WARNING, logger=dmm_module.logger.name):
        merged = scraper._load_prefix_hints()

    assert merged == {"bbb": "3"}
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# ── DoD 5 補強：JSON 語法合法但「形狀」壞掉（review P1）─────────────────────
#
# 為什麼補這幾支：`except (json.JSONDecodeError, OSError)` 只擋語法錯與 IO 錯。
# 語法合法、欄位型別錯的表會讓 `_flatten_shipped_table` 噴 AttributeError/TypeError，
# 而 `search()` 步驟 2 呼叫 `_convert_with_hints` **沒有包 try/except**——例外會直接
# 穿透，使用者每搜一個番號 DMM 整支罷工（不是「查不到那部片」）。
# D1 明文說出貨表是加分項不是必要條件，所以這一整類都必須降級成空表。


@pytest.mark.parametrize(
    "bad_makers",
    [
        None,                              # {"makers": null}
        ["not", "a", "dict"],              # makers 是 list
        {"X": ["not", "dict"]},            # 片商底下不是 dict
        {"X": {"aaa": "not-a-mapping"}},   # entry 不是 mapping
    ],
    ids=["makers-null", "makers-list", "maker-value-list", "entry-not-mapping"],
)
def test_structurally_broken_shipped_table_degrades(
    tmp_path, monkeypatch, caplog, bad_makers
):
    """DoD 5／review P1：語法合法但形狀壞掉 → 降級成空表，不得穿透例外。"""
    shipped_path = tmp_path / "dmm_prefix_table.json"
    prefix_path = tmp_path / "dmm_prefix_hints.json"
    shipped_path.write_text(
        json.dumps({"_meta": {}, "makers": bad_makers}, ensure_ascii=False),
        encoding="utf-8",
    )
    prefix_path.write_text(
        json.dumps({"ccc": "4"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(dmm_module, "SHIPPED_TABLE_FILE", shipped_path)
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", prefix_path)

    scraper = _scraper()
    with caplog.at_level(logging.WARNING, logger=dmm_module.logger.name):
        merged = scraper._load_prefix_hints()

    assert merged == {"ccc": "4"}
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_structurally_broken_table_does_not_break_search_step2(
    tmp_path, monkeypatch
):
    """review P1 的 sink：壞掉的出貨表不得讓 search() 步驟 2 噴例外。

    這支才是「使用者會看到什麼」那一層——上面幾支只證明 _load_prefix_hints 不拋，
    這支證明整條搜尋路徑仍然只是「查不到」。
    """
    shipped_path = tmp_path / "dmm_prefix_table.json"
    shipped_path.write_text(
        json.dumps({"makers": None}, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(dmm_module, "SHIPPED_TABLE_FILE", shipped_path)
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", tmp_path / "absent.json")
    monkeypatch.setattr(dmm_module, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(dmm_module, "rate_limit", lambda *a, **kw: None)

    scraper = _scraper()
    monkeypatch.setattr(scraper, "_fetch_by_id", lambda cid: None)
    monkeypatch.setattr(scraper, "_search_content_id", lambda number: None)

    assert scraper.search("SONE-205") is None


def test_local_hints_not_a_dict_is_ignored(tmp_path, monkeypatch, caplog):
    """本機檔是使用者手可及的：內容不是物件時整份忽略，不得讓搜尋掛掉。"""
    prefix_path = tmp_path / "dmm_prefix_hints.json"
    prefix_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    monkeypatch.setattr(dmm_module, "SHIPPED_TABLE_FILE", REAL_TABLE_PATH)
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", prefix_path)

    scraper = _scraper()
    with caplog.at_level(logging.WARNING, logger=dmm_module.logger.name):
        merged = scraper._load_prefix_hints()

    assert merged["id"] == "h_113"          # 出貨表仍然生效
    assert any(r.levelno == logging.WARNING for r in caplog.records)
