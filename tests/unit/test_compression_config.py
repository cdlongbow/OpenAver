import inspect
from pathlib import Path
import re
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


def test_gzip_compress_level_no_hardcoded_bypass():
    """等級鎖第 2 層：文字掃描確認 web/ 目錄無硬編碼 compresslevel= 數值繞過。

    擋住複製貼上官方文件範例、將 compresslevel 改寫成非 GZIP_COMPRESS_LEVEL 字面值的行為。
    見 findings-152.md §Q1-a。
    """
    web_dir = Path(__file__).resolve().parent.parent.parent / "web"
    pattern = re.compile(r"compresslevel\s*=\s*([^\s,\)]+)")
    violations = []
    for py_file in web_dir.glob("**/*.py"):
        text = py_file.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            val = m.group(1).strip()
            if val != "GZIP_COMPRESS_LEVEL":
                violations.append(f"{py_file.name}: {m.group(0)}")
    assert not violations, (
        f"發現未透過 GZIP_COMPRESS_LEVEL 常數設定的 compresslevel: {violations}。"
        "不得硬編碼壓縮等級，見 findings-152.md §Q1-a"
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
