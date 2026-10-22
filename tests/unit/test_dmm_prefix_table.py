"""Offline acceptance for dmm_prefix_table.json (TASK-134a-T1 DoD 1-5)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


from core.scrapers.dmm import DMMScraper, _flatten_shipped_table
from core.proxy_policy import ProxySettings
from core.scrapers.models import ScraperConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TABLE_PATH = PROJECT_ROOT / "dmm_prefix_table.json"
FIXTURE_PATH = PROJECT_ROOT / "tests/fixtures/scrapers/dmm_crawl_groups.json"


def _load_table() -> dict:
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


def _load_fixture() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# ── DoD 1 ─────────────────────────────────────────────────────────────────────


class TestDmmPrefixTableTracked:
    def test_dmm_prefix_table_is_git_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "dmm_prefix_table.json"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


# ── DoD 2 ─────────────────────────────────────────────────────────────────────


# ── DoD 3 ─────────────────────────────────────────────────────────────────────


# ── DoD 4 ─────────────────────────────────────────────────────────────────────


# ── DoD 5 ─────────────────────────────────────────────────────────────────────


class TestCrawlFixtureHitRate:
    def test_hit_rate_is_320_0_15(self):
        """Offline derivation over the frozen 335-group fixture using production
        ``DMMScraper._parse_number`` + zfill(5) + f-string assembly.
        Literals 320 / 0 / 15 are fixed (BE-TEST-09 / 承重段 D4)."""
        table = _load_table()
        flat = _flatten_shipped_table(table)
        groups = _load_fixture()
        assert len(groups) == 335

        scraper = DMMScraper(ScraperConfig(proxy_settings=ProxySettings(url="")))
        hit = miss = unparseable = 0
        for entry in groups:
            prefix, num = scraper._parse_number(entry["authNum"])
            if not prefix or not num:
                unparseable += 1
                continue
            dmm_prefix = flat.get(prefix, {}).get("dmm_prefix", "")
            cid = f"{dmm_prefix}{prefix}{num.zfill(5)}"
            if cid in entry["ids"]:
                hit += 1
            else:
                miss += 1

        assert hit == 320
        assert miss == 0
        assert unparseable == 15
