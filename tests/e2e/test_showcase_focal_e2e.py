"""
E2E 測試：焦點手動編輯（99a-T6）— 4 條精簡回歸網
需要：真實瀏覽器（Chromium）+ 真實 e2e server（tests/e2e/conftest.py::ensure_e2e_server）
      + 真實 owner library（至少一支有封面的影片）

存在理由（見 TASK-99a-T6.md）：99a-T4 落地時 948 條 static_guard + 5209 條 pytest 全綠，
但功能整組不可用 —— 「hit-test 結果」「渲染是否到達目標」兩件事，字串/AST 守衛結構上
量不到，只有真瀏覽器 e2e 量得到。本檔案只鎖 4 條斷言（owner 拍板精簡版），對應
TASK-99a-T5.md 修的兩個 P1 bug：
  1. hit-test：✓/✗ 座標真的命中按鈕本身（非 .lb-mask-overlay 疊層攔截）。
  2. detect-first：.lb-mask-window 在偵測期間不渲染、resolve 後第一幀即終值（無二次跳動）。
  3. ✓ 確實呼叫 confirmMask()，觸發正確 payload 的 POST /api/showcase/video/focal，
     且前端把回應正確套用到 client state（crop_mode 變 manual）。
  4. ✗ 什麼都不存（無 /video/focal request，crop_mode 不變）。

無封面影片 / app 不可達 / 找不到合適候選 → pytest.skip()（不 FAIL，e2e 對缺環境用戶不可假紅）。

**斷言 3 設計（Codex 第二輪 review P1 修復）**：`tests/e2e/conftest.py::ensure_e2e_server`
可能重用 port 8001 上一個既有 server——那個 server 的 `get_db_path()` 不保證與本測試
進程的 `get_db_path()` 是同一個檔案（`get_db_path()` 是純 `__file__`-derived 路徑函式，
不吃任何 env var / config key，見 `core/database/connection.py`；沒有非侵入式的方式能讓
e2e fixture 指揮一個「已經在跑、我們不擁有」的 server 改用別的 DB）。舊版設計用「寫入前
比對 crop_mode/auto_focal 是否巧合相同」做前置篩選、寫入後再用 sentinel-write 補證明，
但這只是**事後量測**，不是結構性保證——若兩個不相關 DB 剛好在同一 path 有相同既有值
（例如複製過的 library），✓ 點擊仍會先打穿被重用 server 背後的**真實 DB**，測試才在那之後
偵測到不一致，木已成舟。

本版改用 Playwright request interception（`page.route`）在瀏覽器網路層攔截
`POST /api/showcase/video/focal`：斷言 payload（`path` + canonical `"x.xxxx,y.xxxx"` 4dp
格式、y 固定 0.5000）完全正確後，直接用 mocked 200 response `route.fulfill()`——請求**從不
離開瀏覽器**，不可能觸及任何 DB（無論是本地 get_db_path() 還是被重用 server 背後的
任一檔案）。這在結構上排除了整個「port 8001 服務不明 DB」的風險類別，不需要 DB 身分
比對、快照、還原機制。

**為什麼這樣測仍然有牙齒（不是 gutted）**：persistence 本身已由整合層驗證
（`tests/integration/test_showcase_focal_endpoints.py::TestManualFocalEndpoint` 證明
`/video/focal` 原子寫入 auto_focal + crop_mode='manual'、out-of-scope → 403 且 DB 不變等
server-side 行為）。e2e 這層獨一無二、integration 測試無法涵蓋的是**瀏覽器端的接線**——
99a-T5 修的兩個 P1（z-index 疊層攔截 ✓/✗ 點擊、detect-first 二次跳動）都是「事件有沒有
真的從 DOM 走到 confirmMask() 並打出正確 payload」這一類，跟 payload 送達後 DB 有沒有
正確更新是正交的兩件事。攔截並嚴格斷言 payload + 前端套用回應後的 client-side crop_mode
變化，完整覆蓋了 e2e 這層該獨有覆蓋的東西，重複測 persistence 只會多花一份「打穿 owner
真實 library」的風險，不會多驗到任何 integration 測不到的邏輯。
"""
import json
import re

import pytest
from playwright.sync_api import Page, Route, Request, TimeoutError as PlaywrightTimeoutError

pytestmark = pytest.mark.e2e


# ── 共用常數 ──────────────────────────────────────────────────────────────────

DETECT_TIMEOUT_MS = 8_000     # 實測 force-detect ~3.0-3.3s，抓生成 buffer（非固定 sleep）
LB_FULL_TIMEOUT_MS = 15_000
MASK_BTN_TIMEOUT_MS = 5_000
MAX_CANDIDATES = 8            # 候選影片探索迴圈上限，避免無上限拖垮執行時間
MIN_FOCAL_DIFF = 0.05         # 判定「偵測值與右裁基準有材料差異」的門檻（focalX 為 0..1 比例）
PROBE_MAX_MS = 6_500          # 單次 rAF 取樣迴圈總時長上限（生成 buffer vs 3.0-3.3s 實測）
PROBE_TAIL_FRAMES = 8         # detect resolve 後再多取幾幀，驗證無二次跳動

# 前端 confirmMask() 送出的 canonical focal 格式契約（state-lightbox.js:935）：
# `${x.toFixed(4)},0.5000`——y 恆 0.5（render 只用 X，spec §3.3）。
# ⚠ 格式（regex）只驗形狀，**不等於** server 契約：`\d` 放行 2.0000~9.9999，但
# core/focal/detector.py::parse_focal 要求 x ∈ [0,1] 閉區間（超出→400、不碰 DB）。
# 故斷言處另加數值範圍檢查（FOCAL_X_RANGE），否則「canonical」會比 server 寬。
FOCAL_PAYLOAD_RE = re.compile(r"^(\d\.\d{4}),0\.5000$")
FOCAL_X_MIN, FOCAL_X_MAX = 0.0, 1.0   # 鏡射 parse_focal 的 [0,1] 閉區間契約


ALPINE_ROOT_SELECTOR = '[x-data="showcase"]'
# 只認影片卡：.av-card-preview 亦匹配隱藏的 .hero-card（女優 hero，x-show 常為 false）
VIDEO_CARD_SELECTOR = ".av-card-preview[data-flip-id]"


# ── 共用 helper：抓 Alpine state / DOM rect / hit-test ─────────────────────────

def _fetch_cover_videos(page: Page, base_url: str) -> list:
    """候選影片探索：以 showcase 第一頁「DOM 上真的存在的卡片」為準，再 join
    /api/showcase/videos 的 metadata（has_cover / crop_mode）。

    刻意不直接用 API 回傳順序挑候選：API 是全庫順序，UI 有排序（預設 date desc）+
    分頁（items_per_page=90），兩者順序不一致——直接拿 API 前幾筆去找卡片會全部
    落在第一頁之外（實測 match 0/8），導致測試靜默 skip（假綠）。
    """
    resp = page.request.get(f"{base_url}/api/showcase/videos")
    if not resp.ok:
        return []
    by_path = {v["path"]: v for v in resp.json().get("videos", [])}

    page.goto(f"{base_url}/showcase")
    try:
        # 只認影片卡（[data-flip-id]）——.av-card-preview 亦匹配隱藏的 .hero-card
        # （女優 hero），若不限定會 wait 在永遠不可見的元素上 timeout（假 skip）。
        page.wait_for_selector(VIDEO_CARD_SELECTOR, state="visible", timeout=LB_FULL_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        return []

    dom_paths = page.eval_on_selector_all(
        VIDEO_CARD_SELECTOR, "els => els.map(e => e.getAttribute('data-flip-id'))"
    )
    out = []
    for p in dom_paths:
        v = by_path.get(p)
        if v and v.get("has_cover"):
            out.append(v)
    return out


def _open_lightbox_for(page: Page, base_url: str, video_path: str) -> bool:
    """導到 showcase、點對應卡片、等 _lbFullLoaded===true + .lb-mask-btn 可見。"""
    page.goto(f"{base_url}/showcase")
    try:
        page.wait_for_selector(VIDEO_CARD_SELECTOR, state="visible", timeout=LB_FULL_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        return False

    card = page.locator(f'.av-card-preview[data-flip-id="{video_path}"]')
    if card.count() == 0:
        return False
    card.first.click()

    try:
        page.wait_for_function(
            """() => {
                const root = document.querySelector('%s');
                const data = window.Alpine && Alpine.$data(root);
                return !!(data && data._lbFullLoaded);
            }""" % ALPINE_ROOT_SELECTOR,
            timeout=LB_FULL_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        return False

    try:
        page.wait_for_selector(".lb-mask-btn", state="visible", timeout=MASK_BTN_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        return False
    return True


def _wait_detect_resolved(page: Page, timeout: int = DETECT_TIMEOUT_MS) -> None:
    """等 _maskDetecting 翻 false（force-detect resolve，成功或失敗皆算）。"""
    page.wait_for_function(
        """() => {
            const root = document.querySelector('%s');
            const data = window.Alpine && Alpine.$data(root);
            return !!(data && data._maskDetecting === false);
        }""" % ALPINE_ROOT_SELECTOR,
        timeout=timeout,
    )


def _cancel_mask_if_open(page: Page) -> None:
    """清理 helper：若遮罩仍開著就呼叫 cancelMask()（不透過真實 click，純粹收尾用）。"""
    page.evaluate(
        """() => {
            const root = document.querySelector('%s');
            const data = window.Alpine && Alpine.$data(root);
            if (data && data._maskVisible && typeof data.cancelMask === 'function') {
                data.cancelMask();
            }
        }"""
        % ALPINE_ROOT_SELECTOR
    )


def _get_hit_test_rects(page: Page) -> dict:
    """讀 overlay / window / ✓ / ✗ 四個元素的 getBoundingClientRect()（viewport 座標）。"""
    return page.evaluate(
        """() => {
            const rect = (el) => {
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return { x: r.left, y: r.top, width: r.width, height: r.height };
            };
            return {
                overlay: rect(document.querySelector('.lb-mask-overlay')),
                win: rect(document.querySelector('.lb-mask-window')),
                success: rect(document.querySelector('.lb-action-btn--success')),
                danger: rect(document.querySelector('.lb-action-btn--danger')),
            };
        }"""
    )


def _elem_from_point(page: Page, x: float, y: float) -> dict:
    """document.elementFromPoint(x, y) 命中結果，經 .closest() 分類。"""
    return page.evaluate(
        """([x, y]) => {
            const el = document.elementFromPoint(x, y);
            if (!el) return { tag: null, isButton: false, inOverlay: false, inWindow: false };
            const btn = el.closest('.lb-action-btn');
            const overlay = el.closest('.lb-mask-overlay');
            const win = el.closest('.lb-mask-window');
            return {
                tag: el.tagName,
                cls: el.className,
                isButton: !!btn,
                btnCls: btn ? btn.className : null,
                inOverlay: !!overlay,
                inWindow: !!win,
            };
        }""",
        [x, y],
    )


def _pick_outside_point(overlay: dict, window_r: dict, margin: float = 10):
    """在 overlay 內、window 外找一個安全座標（用來驗證「點外＝取消」未回歸）。

    動態依當次 rect 找左右兩側的縫隙，不假設 window 固定停在某一側
    （detect resolve 後 window 可能滑到任意位置，含貼齊 overlay 左/右緣的極端值）。
    """
    gap_left = window_r["x"] - overlay["x"]
    gap_right = (overlay["x"] + overlay["width"]) - (window_r["x"] + window_r["width"])
    mid_y = overlay["y"] + overlay["height"] / 2
    if gap_left >= margin:
        return overlay["x"] + margin / 2, mid_y
    if gap_right >= margin:
        return overlay["x"] + overlay["width"] - margin / 2, mid_y
    return None


_TRANSLATE_X_RE = re.compile(r"^matrix\(([^)]+)\)$")


def _parse_translate_x(transform: str):
    """從 computed transform（matrix(...) 或 none）解出 translateX 分量。"""
    if not transform or transform == "none":
        return None
    m = _TRANSLATE_X_RE.match(transform.strip())
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split(",")]
    if len(parts) < 6:
        return None
    try:
        return float(parts[4])
    except ValueError:
        return None


_RENDER_PROBE_JS = """
() => new Promise((resolve) => {
    const root = document.querySelector('%s');
    const data = window.Alpine && Alpine.$data(root);
    if (!data) { resolve({ error: 'no-alpine-data' }); return; }
    const samples = [];
    let seenFalse = false;
    let tailCount = 0;
    const t0 = performance.now();
    function tick() {
        const win = document.querySelector('.lb-mask-window');
        const detecting = !!data._maskDetecting;
        let display = null;
        let transform = null;
        if (win) {
            const cs = getComputedStyle(win);
            display = cs.display;
            transform = cs.transform;
        }
        samples.push({
            t: performance.now() - t0,
            detecting: detecting,
            display: display,
            transform: transform,
            focalX: data._maskFocalX,
        });
        if (!detecting) { seenFalse = true; }
        if (seenFalse) { tailCount += 1; }
        if ((seenFalse && tailCount >= %d) || (performance.now() - t0) > %d) {
            resolve({ samples: samples, finalFocalX: data._maskFocalX });
        } else {
            requestAnimationFrame(tick);
        }
    }
    requestAnimationFrame(tick);
})
""" % (ALPINE_ROOT_SELECTOR, PROBE_TAIL_FRAMES, PROBE_MAX_MS)


def _run_render_probe(page: Page) -> dict:
    """假設 .lb-mask-btn 剛被真實點擊、force-detect 剛啟動——在瀏覽器內以
    requestAnimationFrame 連續取樣直到 detect resolve 後再多取幾幀，整段留在瀏覽器內
    執行（避免 Python↔瀏覽器 IPC 往返污染逐幀時序精度）。
    """
    return page.evaluate(_RENDER_PROBE_JS)


# ── 斷言 1 + 2：hit-test + detect-first 無二次跳動 ────────────────────────────

def test_hit_test_and_detect_first_render(page: Page, base_url: str) -> None:
    """
    斷言 1（hit-test）：✓/✗ 按鈕中心座標的 elementFromPoint 命中按鈕本身；
                         窗外座標仍命中 .lb-mask-overlay（點外＝取消未回歸）。
    斷言 2（detect-first）：.lb-mask-window 在整段 _maskDetecting===true 期間 display:none；
                             resolve 後第一幀 transform 即終值，往後取樣不再跳動。

    動態尋找一支「偵測值與右裁基準有材料差異」的影片（不寫死番號）——若窗子第一幀
    就已經是終值，觀察不出「有沒有二次跳動」，斷言 2 會失去意義。
    """
    videos = _fetch_cover_videos(page, base_url)
    if not videos:
        pytest.skip("找不到任何有封面的影片，跳過焦點編輯 e2e")

    found = None
    for v in videos[:MAX_CANDIDATES]:
        path = v["path"]
        if not _open_lightbox_for(page, base_url, path):
            continue

        page.locator(".lb-mask-btn").click()
        result = _run_render_probe(page)
        samples = result.get("samples") or []
        if result.get("error") or not samples:
            _cancel_mask_if_open(page)
            continue

        detecting_samples = [s for s in samples if s["detecting"]]
        if not detecting_samples:
            _cancel_mask_if_open(page)
            continue

        baseline_focal = detecting_samples[0]["focalX"]
        final_focal = result.get("finalFocalX")
        if baseline_focal is None or final_focal is None:
            _cancel_mask_if_open(page)
            continue

        if abs(final_focal - baseline_focal) >= MIN_FOCAL_DIFF:
            found = {
                "path": path,
                "samples": samples,
                "baseline_focal": baseline_focal,
                "final_focal": final_focal,
            }
            break

        _cancel_mask_if_open(page)

    if found is None:
        pytest.skip(
            f"窮舉 {min(len(videos), MAX_CANDIDATES)} 部候選影片皆找不到偵測值與右裁基準"
            f"有材料差異（>= {MIN_FOCAL_DIFF}）的樣本，跳過 e2e（無法區分「detect-first 正確」"
            f"與「偵測值恰好等於基準、根本沒有東西可跳動」）"
        )

    try:
        samples = found["samples"]

        # --- 斷言 2a：detecting 期間全程 display:none ---
        detecting_rows = [s for s in samples if s["detecting"]]
        for s in detecting_rows:
            assert s["display"] == "none", (
                f".lb-mask-window 應在 _maskDetecting===true 期間 display:none，"
                f"實際樣本：{s}"
            )

        # --- 斷言 2b：第一個「真的畫出來」的幀即終值，往後不再跳動 ---
        # 註：_maskDetecting 翻 false 後的第一幀 display 可能仍是 'none'（Alpine 的 x-show
        # effect 尚未 flush），那一幀還沒畫出任何東西、不構成「使用者看得到的第一幀」——
        # 取樣要篩掉，斷言真正被 paint 出來的幀。
        first_false_idx = next(i for i, s in enumerate(samples) if not s["detecting"])
        post = [s for s in samples[first_false_idx:] if s["display"] and s["display"] != "none"]
        assert len(post) >= 2, (
            f"detect resolve 後「已 paint」的取樣幀數不足（{len(post)}），無法驗證是否有二次滑動"
        )

        first_tx = _parse_translate_x(post[0]["transform"])
        assert first_tx is not None, (
            f"第一個 paint 出來的幀應可從 computed transform 解出 translateX，"
            f"實際：{post[0]}"
        )
        for s in post[1:]:
            tx = _parse_translate_x(s["transform"])
            assert tx is not None, f"取樣幀 transform 應可解析出 translateX：{s}"
            assert abs(tx - first_tx) < 1.0, (
                f"detect resolve 後偵測到二次滑動（第一幀 translateX={first_tx:.2f}px，"
                f"後續幀={tx:.2f}px）—— detect-first 設計要求第一次畫出來就是終值"
                f"（baseline_focal={found['baseline_focal']:.4f}, "
                f"final_focal={found['final_focal']:.4f}）"
            )

        # --- 斷言 1：hit-test ---
        rects = _get_hit_test_rects(page)
        overlay, window_r = rects["overlay"], rects["win"]
        success_btn, danger_btn = rects["success"], rects["danger"]
        assert overlay and window_r and success_btn and danger_btn, (
            f"必要元素 rect 缺失（遮罩可能已提前關閉）：{rects}"
        )

        sx = success_btn["x"] + success_btn["width"] / 2
        sy = success_btn["y"] + success_btn["height"] / 2
        dx = danger_btn["x"] + danger_btn["width"] / 2
        dy = danger_btn["y"] + danger_btn["height"] / 2

        hit_success = _elem_from_point(page, sx, sy)
        assert hit_success["isButton"], (
            f"✓ 按鈕中心 ({sx:.1f}, {sy:.1f}) 的 elementFromPoint 應命中按鈕本身"
            f"（經 .closest('.lb-action-btn')），實際：{hit_success}"
        )

        hit_danger = _elem_from_point(page, dx, dy)
        assert hit_danger["isButton"], (
            f"✗ 按鈕中心 ({dx:.1f}, {dy:.1f}) 的 elementFromPoint 應命中按鈕本身"
            f"（經 .closest('.lb-action-btn')），實際：{hit_danger}"
        )

        outside = _pick_outside_point(overlay, window_r)
        assert outside is not None, (
            f"找不到「遮罩窗外仍在 overlay 內」的安全座標——overlay={overlay}, window={window_r}"
        )
        ox, oy = outside
        hit_outside = _elem_from_point(page, ox, oy)
        assert hit_outside["inOverlay"] and not hit_outside["inWindow"] and not hit_outside["isButton"], (
            f"窗外座標 ({ox:.1f}, {oy:.1f}) 應仍命中 .lb-mask-overlay（點外＝取消不回歸），"
            f"實際：{hit_outside}"
        )
    finally:
        _cancel_mask_if_open(page)


# ── 斷言 3 + 4：✓ 確實存 / ✗ 什麼都不存 ────────────────────────────────────────

def test_confirm_saves_and_cancel_saves_nothing(page: Page, base_url: str) -> None:
    """
    斷言 4（✗ 不存）：真實 click ✗ → 無 /video/focal request，crop_mode 不變。
    斷言 3（✓ 確實存）：真實 click ✓ → POST /api/showcase/video/focal 真的以正確 payload
                         觸發，且前端把回應正確套用到 client state（crop_mode 變 manual）。

    斷言 3 的請求用 `page.route()` 攔截並以 mocked 200 response `fulfill()`——請求
    **從不離開瀏覽器**，結構上不可能寫入任何 DB（見本檔開頭模組 docstring「斷言 3 設計」
    段落：`get_db_path()` 無任何非侵入式 override 機制，`ensure_e2e_server` 重用既有
    server 時無法保證它與本測試進程用同一個 DB 檔案，唯一結構安全的做法是讓寫入請求
    根本不送達任何 server）。persistence 本身已由
    `tests/integration/test_showcase_focal_endpoints.py::TestManualFocalEndpoint` 在
    server 端驗證（原子寫 auto_focal + crop_mode='manual'、out-of-scope→403 且 DB 不變）。
    """
    videos = _fetch_cover_videos(page, base_url)
    candidates = [v for v in videos if v.get("crop_mode") == "auto"]
    if not candidates:
        pytest.skip(
            "找不到 crop_mode='auto' 且有封面的影片，跳過"
            "（避免動到已是 manual/default 的既有資料列）"
        )

    target = None
    for v in candidates[:MAX_CANDIDATES]:
        if _open_lightbox_for(page, base_url, v["path"]):
            target = v
            break
    if target is None:
        pytest.skip("候選影片皆無法開啟 lightbox，跳過")

    video_path = target["path"]

    # ── 斷言 4：✗ 應該什麼都不存（無 DB 寫入，讀真實 server 狀態是安全的，不需 mock） ──
    page.locator(".lb-mask-btn").click()
    _wait_detect_resolved(page)
    page.wait_for_selector(".lb-action-btn--danger", state="visible", timeout=3_000)

    focal_requests = []

    def _record(req):
        if req.method == "POST" and "/api/showcase/video/focal" in req.url:
            focal_requests.append(req.url)

    page.on("request", _record)
    try:
        rects = _get_hit_test_rects(page)
        danger = rects["danger"]
        assert danger, "✗ 按鈕 rect 缺失，遮罩可能未正確開啟"
        dx = danger["x"] + danger["width"] / 2
        dy = danger["y"] + danger["height"] / 2
        page.mouse.click(dx, dy)
        page.wait_for_timeout(800)  # 讓「什麼都沒發生」有機會被觀察到
    finally:
        page.remove_listener("request", _record)

    assert not focal_requests, (
        f"✗ 點擊後不應有 /video/focal request，實際攔到：{focal_requests}"
    )

    resp = page.request.get(f"{base_url}/api/showcase/video", params={"path": video_path})
    body = resp.json()
    assert body.get("success"), f"確認影片狀態失敗：{body}"
    assert body["video"]["crop_mode"] == "auto", (
        f"✗ 後 crop_mode 不應改變，實際：{body['video']['crop_mode']}"
    )

    # ── 斷言 3：✓ 應該真的觸發正確 payload 的 POST，且前端套用回應更新 client state ──
    # route 攔截：payload 驗證後 fulfill 一個 mocked 200，請求從不到達 server/DB。
    captured = {}

    def _handle_focal_route(route: Route) -> None:
        request: Request = route.request
        captured["url"] = request.url
        captured["method"] = request.method
        try:
            captured["payload"] = request.post_data_json
        except Exception:
            captured["payload"] = None
        # mocked response：直接把送來的 focal 回顯為 auto_focal（模擬 server 端
        # format_focal(parse_focal(...)) 對合法 canonical 字串的 idempotent 正規化）。
        mocked_auto_focal = (captured["payload"] or {}).get("focal", "")
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "auto_focal": mocked_auto_focal}),
        )

    page.route("**/api/showcase/video/focal", _handle_focal_route)
    try:
        page.locator(".lb-mask-btn").click()
        _wait_detect_resolved(page)
        page.wait_for_selector(".lb-action-btn--success", state="visible", timeout=3_000)

        rects = _get_hit_test_rects(page)
        success = rects["success"]
        assert success, "✓ 按鈕 rect 缺失，遮罩可能未正確開啟"
        cx = success["x"] + success["width"] / 2
        cy = success["y"] + success["height"] / 2

        # 用 expect_response（非 expect_request）等待——這是刻意選擇，非隨手替換：
        # expect_request 只保證 Chromium 的 'Network.requestWillBeSent' 事件已送達，
        # 不保證我們這支 Python route handler（收到 'Fetch.requestPaused' 後才觸發、
        # 走獨立的 CDP event stream）已經執行完 route.fulfill()——兩者之間有真實 race
        # window（實測 ~500ms，見 99a-T6 P1 第二輪修復除錯記錄）。若之後的斷言在這個
        # race window 內失敗，下面 finally 的 page.unroute() 會把「尚未被我們的
        # handler 處理、還卡在 Fetch domain 的 paused request」直接放行到真實網路——
        # 這正是上一輪修復漏掉的路徑：mocked route 看似攔截成功，實際上在特定時序下
        # 讓請求逃逸打穿真實 server。expect_response 等的是 fulfill() 產生的回應本身，
        # 只有 handler 真正跑完、呼叫過 fulfill() 之後才可能有 response 事件，用它才能
        # 結構性保證「with 區塊結束時 handler 必已執行完」，徹底關掉這個 race。
        with page.expect_response(
            lambda r: r.request.method == "POST" and "/api/showcase/video/focal" in r.url,
            timeout=5_000,
        ) as resp_info:
            page.mouse.click(cx, cy)
        assert resp_info.value is not None, "✓ 點擊後應觸發 POST /api/showcase/video/focal"
        assert resp_info.value.status == 200, (
            f"mocked route 應回 200，實際：{resp_info.value.status}"
            "（非 200 代表 fulfill 未如預期執行，或請求真的打穿到別處）"
        )

        # --- payload 契約斷言（嚴格：防止 browser↔endpoint contract drift 溜過） ---
        assert captured.get("payload") is not None, (
            f"攔截到的 request 應有 JSON body，實際：{captured}"
        )
        payload = captured["payload"]
        assert payload.get("path") == video_path, (
            f"POST payload path 應等於目標影片 path，實際：{payload}"
        )
        focal_value = payload.get("focal", "")
        m = FOCAL_PAYLOAD_RE.match(focal_value)
        assert m is not None, (
            f"POST payload focal 應符合 canonical \"x.xxxx,y.xxxx\" 4dp 格式且 y=0.5000"
            f"（state-lightbox.js confirmMask() 契約），實際：{focal_value!r}"
        )
        # 形狀對還不夠：x 必須落在 server 的 [0,1] 閉區間（parse_focal），否則真實
        # server 會 400、不寫 DB——mocked 200 會讓這種 payload 靜默通過（Codex P3）。
        focal_x = float(m.group(1))
        assert FOCAL_X_MIN <= focal_x <= FOCAL_X_MAX, (
            f"POST payload focal 的 x 應落在 server parse_focal 的 [{FOCAL_X_MIN},{FOCAL_X_MAX}] "
            f"閉區間（超出→真實 server 回 400、不碰 DB），實際：{focal_x}（payload {focal_value!r}）"
        )

        # expect_response 只保證 HTTP response 已送達頁面，不保證 fetch() 的 .then()
        # chain（confirmMask 內 await resp.json() 之後才 mutate targetVideo）已跑完——
        # 用 wait_for_function 輪詢等 client state 真的翻到 manual 或逾時，取代盲猜的
        # 固定 sleep（也讓底下 assert 拿到的 lb_state 不會因為時序差一點點而誤判）。
        try:
            page.wait_for_function(
                """() => {
                    const root = document.querySelector('%s');
                    const data = window.Alpine && Alpine.$data(root);
                    const v = data && data.currentLightboxVideo;
                    return !!(v && v.crop_mode === 'manual');
                }""" % ALPINE_ROOT_SELECTOR,
                timeout=3_000,
            )
        except PlaywrightTimeoutError:
            pass  # 逾時不在此立即 fail——讓下面的 assert 讀到目前實際狀態、給出明確診斷訊息

        # --- 前端套用回應後的 client state 斷言 ---
        lb_state = page.evaluate(
            """() => {
                const root = document.querySelector('%s');
                const data = window.Alpine && Alpine.$data(root);
                const v = data && data.currentLightboxVideo;
                return v ? { crop_mode: v.crop_mode, auto_focal: v.auto_focal, path: v.path } : null;
            }"""
            % ALPINE_ROOT_SELECTOR
        )
        assert lb_state is not None, "✓ 後應仍在 lightbox 內，currentLightboxVideo 不應為 null"
        assert lb_state["path"] == video_path, f"currentLightboxVideo path 不符：{lb_state}"
        assert lb_state["crop_mode"] == "manual", (
            f"✓ 後前端 client state 的 crop_mode 應變 manual，實際：{lb_state}"
            "（若仍是 auto，代表 ✓ 靜默觸發了 cancelMask 或 confirmMask 回應處理回歸，"
            "T5 的 P1 bug 復發）"
        )
        assert lb_state["auto_focal"] == focal_value, (
            f"前端套用 mocked response 後 auto_focal 應等於送出的 focal payload："
            f"期望 {focal_value!r}，實際 {lb_state!r}"
        )
    finally:
        page.unroute("**/api/showcase/video/focal", _handle_focal_route)
        _cancel_mask_if_open(page)

    # ── 結構性保證的收尾驗證：真實 server DB 應完全未被寫入 ──
    # 上面整段 ✓ 流程的 POST 從未離開瀏覽器（page.route 攔截 + fulfill），這裡再對
    # 真實 server 讀一次確認 crop_mode 仍是候選篩選時保證的 'auto'——不是「補救措施」，
    # 是結構論證的複驗（request interception 正確運作的話，這裡必然通過）。
    resp = page.request.get(f"{base_url}/api/showcase/video", params={"path": video_path})
    body = resp.json()
    assert body.get("success"), f"確認影片狀態失敗：{body}"
    assert body["video"]["crop_mode"] == "auto", (
        f"結構性保證複驗失敗：真實 server DB 的 crop_mode 應仍是 'auto'（mocked ✓ 流程"
        f"從未送達 server），實際：{body['video']['crop_mode']}——若不是 'auto'，代表"
        f"page.route() 攔截失效、請求真的打穿了 server，需要立即調查。"
    )
