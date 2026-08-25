"""粗顆粒源碼守衛：確保 routing 呼叫點讀取 routing_availability_map 而非 availability_map。"""
import re
from pathlib import Path


# [lint-guard: pytest-justified] Python 源碼語意（哪個呼叫點讀哪一支方法），lint 表達不了
class TestMetatubeRoutingGuard:
    """確保核心路由路徑傳入 get_enabled_source_ids 的 availability_map 一律來自 routing_availability_map()。"""

    def test_scraper_and_router_use_routing_availability_map(self):
        repo_root = Path(__file__).resolve().parent.parent.parent

        # 1. 檢查 core/scraper.py
        scraper_code = (repo_root / "core" / "scraper.py").read_text(encoding="utf-8")
        scraper_lines = scraper_code.splitlines()

        for i, line in enumerate(scraper_lines):
            code_part = line.split("#")[0]
            if "get_enabled_source_ids(" in code_part:
                # 查看當前行及前 3 行的 window
                window = "\n".join(scraper_lines[max(0, i - 3):i + 1])
                assert "routing_availability_map" in window, (
                    f"core/scraper.py line {i + 1} get_enabled_source_ids 呼叫周圍未發現 routing_availability_map:\n{window}"
                )
                assert not re.search(r"(?<!routing_)availability_map\(", window), (
                    f"core/scraper.py line {i + 1} get_enabled_source_ids 呼叫周圍發現了舊的 availability_map():\n{window}"
                )

        # 2. 檢查 web/routers/scraper_sources.py
        router_code = (repo_root / "web" / "routers" / "scraper_sources.py").read_text(encoding="utf-8")
        router_lines = router_code.splitlines()
        for i, line in enumerate(router_lines):
            code_part = line.split("#")[0]
            if "get_enabled_source_ids(" in code_part:
                window = "\n".join(router_lines[max(0, i - 3):i + 1])
                assert "routing_availability_map" in window, (
                    f"web/routers/scraper_sources.py line {i + 1} get_enabled_source_ids 呼叫周圍未發現 routing_availability_map:\n{window}"
                )
                assert not re.search(r"(?<!routing_)availability_map\(", window), (
                    f"web/routers/scraper_sources.py line {i + 1} get_enabled_source_ids 呼叫周圍發現了舊的 availability_map():\n{window}"
                )
