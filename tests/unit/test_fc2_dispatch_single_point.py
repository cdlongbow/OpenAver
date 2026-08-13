"""TASK-118-T5 / AC-1.4：四條使用者流程共用同一個 fc2 dispatch 點，零設定變更即生效。

spec-118 AC-1.4 說的是「搜尋頁／整理／批次補完／唯讀來源」四條流程**不需要任何設定變更**
就換成官方站。它們之所以能一起生效，是因為四條都走 `core/scraper.py` 的**單一 dispatch**
（`source_to_scraper['fc2']`），而不是各自建 scraper。

本檔用兩段證明這條鏈，不跑真機、不連網：

1. **鏈的末端**：`search_jav(source='fc2')` 建出來的是 `FC2OfficialScraper`
   —— 由 `tests/unit/test_pipeline_routing.py::TestFc2Dispatch` 覆蓋（不在此重複，
   也刻意**不為測試在產品碼開一個匯出 dispatch 表的後門**）。
2. **鏈的四個入口**：四個流程模組裡的 `search_jav` / `smart_search` 與 `core.scraper` 的**同一個函式物件**
   （`is` 比較，不是名稱比較）——任何一條若改成自己 import scraper 類別、或改走別的模組，這裡會紅。

為什麼不逐條跑真機：四條流程共用的是同一個 dispatch 點，真機重跑四次驗的是同一行程式碼。
"""
import core.scraper as core_scraper


def test_four_flows_share_the_same_search_entry():
    """四條流程用的是 core.scraper 的同一個函式物件（＝同一個 dispatch）。"""
    import core.enricher as enricher
    import core.readonly_producer as readonly_producer
    import web.routers.scraper as scraper_router
    import web.routers.search as search_router

    # 搜尋頁（REST ＋ SSE）
    assert search_router.smart_search is core_scraper.smart_search
    assert search_router.search_jav is core_scraper.search_jav
    # 整理（/api/scrape-single）
    assert scraper_router.search_jav is core_scraper.search_jav
    # 批次補完 / 單片補完
    assert enricher.search_jav is core_scraper.search_jav
    # 唯讀來源產出
    assert readonly_producer.search_jav is core_scraper.search_jav
