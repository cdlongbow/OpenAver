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
  3. ✓ 確實呼叫 confirmMask()，真的寫入 crop_mode='manual'。
  4. ✗ 什麼都不存（無 /video/focal request，crop_mode 不變）。

無封面影片 / app 不可達 / 找不到合適候選 → pytest.skip()（不 FAIL，e2e 對缺環境用戶不可假紅）。
測試對真實 library 的任何寫入（斷言 3）一律 try/finally 還原（VideoRepository.reset_focal_to_auto）。
"""
import re

import pytest
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from core.database import VideoRepository, get_db_path

pytestmark = pytest.mark.e2e


# ── 共用常數 ──────────────────────────────────────────────────────────────────

DETECT_TIMEOUT_MS = 8_000     # 實測 force-detect ~3.0-3.3s，抓生成 buffer（非固定 sleep）
LB_FULL_TIMEOUT_MS = 15_000
MASK_BTN_TIMEOUT_MS = 5_000
MAX_CANDIDATES = 8            # 候選影片探索迴圈上限，避免無上限拖垮執行時間
MIN_FOCAL_DIFF = 0.05         # 判定「偵測值與右裁基準有材料差異」的門檻（focalX 為 0..1 比例）
PROBE_MAX_MS = 6_500          # 單次 rAF 取樣迴圈總時長上限（生成 buffer vs 3.0-3.3s 實測）
PROBE_TAIL_FRAMES = 8         # detect resolve 後再多取幾幀，驗證無二次跳動


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
    斷言 3（✓ 確實存）：真實 click ✓ → POST /api/showcase/video/focal 真的觸發，
                         crop_mode 變 manual。

    先測 ✗（無副作用）、再測 ✓（有副作用，finally 內用 reset_focal_to_auto 還原）——
    這是打在 owner 真實 library 上的測試，全程 try/finally 保底還原。
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

    try:
        # ── 斷言 4：✗ 應該什麼都不存 ──
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

        # ── 斷言 3：✓ 應該真的存 manual ──
        page.locator(".lb-mask-btn").click()
        _wait_detect_resolved(page)
        page.wait_for_selector(".lb-action-btn--success", state="visible", timeout=3_000)

        rects = _get_hit_test_rects(page)
        success = rects["success"]
        assert success, "✓ 按鈕 rect 缺失，遮罩可能未正確開啟"
        cx = success["x"] + success["width"] / 2
        cy = success["y"] + success["height"] / 2

        with page.expect_request(
            lambda r: r.method == "POST" and "/api/showcase/video/focal" in r.url,
            timeout=5_000,
        ) as req_info:
            page.mouse.click(cx, cy)
        assert req_info.value is not None, "✓ 點擊後應觸發 POST /api/showcase/video/focal"

        page.wait_for_timeout(300)  # 等 response 完成 + DB commit

        resp = page.request.get(f"{base_url}/api/showcase/video", params={"path": video_path})
        body = resp.json()
        assert body.get("success"), f"確認影片狀態失敗：{body}"
        assert body["video"]["crop_mode"] == "manual", (
            f"✓ 後 crop_mode 應變 manual，實際：{body['video']['crop_mode']}"
            "（若仍是 auto，代表 ✓ 靜默觸發了 cancelMask，T5 的 P1 bug 復發）"
        )
    finally:
        # 保底還原：不管上面斷言成功與否，一律把真實 library 這筆記錄還原成未手動編輯過。
        repo = VideoRepository(get_db_path())
        repo.reset_focal_to_auto(video_path)
