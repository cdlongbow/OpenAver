"""壓縮設定與 ASGI 中介軟體配置斷言。

[等級鎖守衛設計與異動說明]
- 本檔曾有第二層「掃描 web/**/*.py 確認無 compresslevel= 接非常數字面值」的文字守衛，
  已於 Codex PR review 後移除。
- 移除理由：該守衛使用正則表達式掃描原始文字，不排除註解與 docstring；只要有人在 web/
  底下合法寫入包含例如 compresslevel 指定為 9 等字樣的解釋性註解，整套測試就會假紅、擋住合法開發。
- 已知殘留：目前沒有任何自動化守衛阻擋以下兩種硬編碼情境：
  1. 現有的註冊點（web/app.py 的 app.add_middleware(GZipMiddleware, ...)）被直接換成字面值等級——本檔的常數值斷言只看常數本身是否為 1，看不到呼叫端是否真的引用該常數；行為測試亦無法分辨具體等級。
  2. 有人在 web/ 別處新增第二個 GZipMiddleware 註冊並硬編碼壓縮等級。
  以上兩種情形均需仰賴 code review 把關。
- 目前壓縮等級的防護機制：
  1. 本檔 test_gzip_compress_level_constant_value 常數值斷言（鎖死為 1）。
  2. tests/integration/test_response_compression.py 的行為測試（驗證 middleware 已註冊且壓縮行為生效——注意它驗不到「用的是哪個等級」，任何等級都會產生 Content-Encoding）。
  3. web/compression.py 的設計理由註解。
"""
import inspect
from starlette.middleware.gzip import GZipMiddleware
from web.compression import GZIP_COMPRESS_LEVEL

# findings-152.md §Q1-a：/api/showcase/videos 未壓縮實測 16,631,933 bytes。
SHOWCASE_PAYLOAD_BYTES = 16_631_933


def test_gzip_compress_level_constant_value():
    """等級鎖第 1 層：常數值斷言鎖死為 1。

    findings-152.md §Q1-a：DS218 上 level 6 淨賠、level 9 純虧。
    level 1 是唯一在所有機器、所有連線速度組合下都不會輸的設定。
    """
    assert GZIP_COMPRESS_LEVEL == 1, (
        f"GZIP_COMPRESS_LEVEL 必須鎖死為 1，當前為 {GZIP_COMPRESS_LEVEL}。"
        "level 6/9 在低功耗主機上淨賠或純虧，見 findings-152.md §Q1-a"
    )


def test_gzip_thread_offload_threshold_exists_and_below_showcase_payload():
    """spec-152a §2.4：大塊壓縮不得在 event loop 上同步執行。本專案不自己寫執行緒卸載
    邏輯，靠 starlette GZipMiddleware 的 thread_minimum_size 機制（見 plan-152a.md §0.3／
    CD-3）。這條守衛存在的理由：§2.4 的滿足方式是「繼承上游行為」而不是我們自己的程式碼，
    需要一個會在上游行為改變時發聲的東西——上游若把這個參數改名、拿掉，或把預設門檻抬到
    我們的 payload 之上，這裡就會轉紅。失敗代表：大回應（如這裡的 16.6MB JSON）的壓縮會
    退回 event loop 同步執行，DS218 上全站每次全量回應會停頓（findings-152.md §Q1-a
    實測 0.35 秒），這是使用者的損失。

    ⚠️ 已知限制（owner 核可的粗顆粒取捨，2026-09-20，不要升級成執行緒插樁）：這條測試
    只證明「thread_minimum_size 這個參數存在、且它的預設門檻小於我們的 payload」，
    **不證明 starlette 執行期真的把壓縮工作丟去了 worker thread**——那需要在執行期插樁
    觀察壓縮呼叫實際跑在哪條 thread 上，過於侵入，本 plan 刻意不做。這條守衛擋的是
    「上游把這個機制整個拿掉或門檻改壞」，擋不住「參數還在但內部執行路徑被改壞、
    實際上沒有真的丟執行緒」這種更隱蔽的回歸——後者若發生，只能靠 DS218 真機或效能
    回歸測試發現，不是這條測試的責任範圍。"""
    sig = inspect.signature(GZipMiddleware.__init__)
    assert "thread_minimum_size" in sig.parameters, (
        "GZipMiddleware 不再有 thread_minimum_size 參數——大回應壓縮會退回 event loop 同步"
        "執行，DS218 全站停頓，見 findings-152.md §Q1-a、plan-152a.md §2.4"
    )
    threshold = sig.parameters["thread_minimum_size"].default
    assert threshold < SHOWCASE_PAYLOAD_BYTES, (
        f"thread_minimum_size 預設門檻 {threshold} 已經 >= showcase payload "
        f"{SHOWCASE_PAYLOAD_BYTES}，大回應壓縮不會再自動丟 worker thread，"
        "DS218 全站停頓，見 findings-152.md §Q1-a、plan-152a.md §2.4"
    )
