/**
 * state-lightbox-mask.js — Showcase ESM（149a-T4a）
 *
 * 焦點裁切遮罩：force-detect 幾何計算與星空等待/收斂動畫（GhostFly timeline）的
 * kill 生命週期。這是遮罩功能的「動畫＋幾何」半——session 生命週期與拖曳/✓/✗互動
 * 留在核心（state-lightbox.js），由 T4b 之後併入本檔。從 state-lightbox.js 拆出，
 * 逐字搬移，見 plan-149a.md CD-149a-1。
 */

import { computeMaskWinGeometry, computeMaskSettleGeometry } from '@/shared/mask-geometry.js';

export function stateLightboxMask() {
    return {
        // 98b-T6：亮窗幾何 reactive data（openMask/drag 同步 imperative 算，非量測-in-binding）。
        // 99a-T5：型別恆為 object（非 string）——headless self-verify 實測抓到：Alpine `:style`
        // 綁 STRING 值時走 `el.setAttribute('style', ...)` 整串覆寫（Alpine 內部 `Xn()`），會把
        // `x-show` 剛設的 inline `display:none` 一併洗掉；`x-show` 本身又會快取「上次算出的布林值」，
        // 布林值沒變就不重跑 show/hide（Alpine 內部 x-show 的 `f===l` 短路），兩者疊加＝窗子在
        // `_maskDetecting` 為真期間仍卡在 `display:block`（baseline flash 不會消失，一路卡到
        // detect resolve）。物件值改走 `el.style.setProperty(key, val)` 逐屬性設值（Alpine 內部
        // `Yn()`），不觸碰 `display`，與 x-show 互不干擾。永遠回傳/賦值 object，不可再退回 string。
        _maskWinStyle: {},
        _maskResizeHandler: null,       // 98b-T6：開遮罩時綁 window resize 重算，teardown/reset 時解


        // 101b-T2（CD-4a/CD-5）：收斂補間進行中旗標——只在 _maskDetecting 翻 false 之後才可能為
        // true（結構上不與 _maskDetecting 重疊，見 _maskStartSettle 步驟④⑤順序）。x-show 驅動
        // .lb-mask-wait-burst/.lb-mask-spinner 延壽 + .lb-mask-window--settling class（CD-5，
        // 停用 CSS transition，防與 GSAP 逐 tick 寫 Alpine :style 雙重 easing）。
        _maskSettling: false,


        _maskWaitTl: null,              // 99a-T5：星空等待動畫 handle（{tl,burst,stars}），detect
                                         // 期間播放；openMask 啟動，finally/_resetMask/_maskTeardown
                                         // 三處對稱停止（_maskStopWaitAnim helper，idempotent）。
                                         // 101b-T2：正常（收斂）路徑改由 _maskStartSettle 交棒
                                         // （handoffFocalDetectWait，不置 null），fallback 分支
                                         // 仍走 _maskStopWaitAnim 全停清空（CD-4b）。
        _maskSettleTl: null,            // 101b-T2：收斂 GSAP timeline handle（id:'focalSettle'），
                                         // _maskStopSettleAnim（拖曳接管/中斷路徑）與 onComplete/
                                         // onInterrupt（正常結束）對稱清空，見 _maskClearSettleProps。


        // 100b-T1（CD-4/§B-1b）：video/actress 兩分支識別資訊統一出口。_maskKind 已由 openMask()
        // 起手凍結（G4，不在此重判）。actress 分支目前結構性不可達（T1 DoD ③：女優分支無 focal
        // icon，openMask 永不在 currentLightboxActress 有值時觸發），此處仍完整定義兩分支欄位
        // 供 T2 銜接（§B-1b 表）。detectEndpoint/focalEndpoint 各自完整字面 URL（Opus 裁決 C：
        // 不可拼接 base，否則 static_guard_lint.mjs:147 的 detect-focal 規則因字面字串消失而
        // 靜默 RED）。imgEl 對 actress 分支须 null-safe（G3：$refs.pickerCoverImg 在 x-if 內）。
        _maskTarget() {
            if (this._maskKind === 'actress') {
                return {
                    obj: this.currentLightboxActress,
                    imgEl: this.$refs && this.$refs.pickerCoverImg,   // G3：x-if 內，null-safe
                    loaded: this._actressPhotoLoaded,   // T2 才宣告；未宣告的 this.xxx property access 回 undefined，非 ReferenceError
                    identity: this.currentLightboxActress?.name,
                    ratio: '--actress-crop-ratio',
                    detectEndpoint: `/api/actresses/${encodeURIComponent(this.currentLightboxActress?.name || '')}/detect-focal`,
                    focalEndpoint: `/api/actresses/${encodeURIComponent(this.currentLightboxActress?.name || '')}/focal`,
                    focalBody: (focal) => ({ focal }),   // v3：無 token，只此一欄
                    handles409: false,   // spec §3.5：女優無背景 writer、無 409
                };
            }
            return {
                obj: this.currentLightboxVideo,
                imgEl: this.$refs.lightboxCoverFull,
                loaded: this._lbFullLoaded,
                identity: this.currentLightboxVideo?.path,
                ratio: '--poster-crop-ratio',
                detectEndpoint: '/api/showcase/video/detect-focal',
                focalEndpoint: '/api/showcase/video/save-focal',
                focalBody: (focal) => ({
                    path: this.currentLightboxVideo?.path,
                    focal,
                    expected_cover_path: this._maskExpectedCoverPath,
                }),
                handles409: true,   // 封面已變更時的 compare-and-store 409
            };
        },


        // 99a-T5：星空等待動畫對稱停止 helper——openMask finally（正常結束，session-gated）、
        // _resetMask（中斷：換片/關燈箱/ESC）、_maskTeardown（防禦性再保險）三處對稱呼叫。
        // idempotent：this._maskWaitTl 已 null 時安全 no-op（GhostFly.stopFocalDetectWait 內部
        // 亦對 null handle 安全 no-op，belt-and-suspenders）。
        _maskStopWaitAnim() {
            if (this._maskWaitTl && window.GhostFly && window.GhostFly.stopFocalDetectWait) {
                window.GhostFly.stopFocalDetectWait(this._maskWaitTl);
            }
            this._maskWaitTl = null;
        },

        // 101b-T2（CD-4a/CD-4b/CD-4c/CD-5/CD-7/CD-8/CD-9/CD-11a，§A-3a 權威步驟表）：由 openMask
        // finally 呼叫（已 session-gated），取代舊有的「_maskDetecting=false + _maskStopWaitAnim()」
        // 硬切。決定「偵測完成 → 星空淡出 → 亮窗收斂到終值」是否以單一 GSAP timeline overlap 播放，
        // 或退化成今天的瞬現路徑（g0 為 null / PRM / 動畫層不可用）。
        //
        // hasFace：CD-8——找到臉才掛第 4 條 proxy tween（收斂），無臉/偵測失敗仍走同一條 timeline
        // （星空/spinner 淡出＋窗淡入），只是窗停在起手基準不收斂。
        _maskStartSettle(hasFace) {
            // ① 取樣一次（比照 _maskDragStart 首次取樣，刻意不逐 tick 量測）。coverEl 是
            // openMask 內 `if (!isPRM)` block 的區域變數，離開該 block 即不可見，此處需自己重取。
            const el = this._maskTarget().imgEl;
            const coverEl = el?.closest('.lightbox-cover');
            let W, H, r;
            if (el && el.naturalWidth) {
                const rect = el.getBoundingClientRect();
                W = rect.width;
                H = rect.height;
                r = parseFloat(getComputedStyle(el).getPropertyValue(
                    this._maskKind === 'actress' ? '--actress-crop-ratio' : '--poster-crop-ratio'
                ));
            }

            // ② gate（CD-11a fail-closed 幾何 + CD-4c 動畫層可用性，同一個 fallback 分支）。
            const g0 = computeMaskSettleGeometry(W, H, r, this._maskFocalX, 0);
            const isPRM = !!(window.OpenAver && window.OpenAver.prefersReducedMotion);
            // 🔴 Codex PR review P2 修正：canAnimate 必須連 gate `this._maskWaitTl`——
            // wait handle 是 :1386 handoffFocalDetectWait(this._maskWaitTl) 交棒的前提，
            // 缺它（burst/star DOM 不在場，即使 gsap 存在）_maskWaitTl 恆為 null，
            // handoffFocalDetectWait(null) 回 null，解構 `{ stars, burst }` 會拋
            // TypeError，此時 _maskSettling 已設 true 卻無 cleanup，卡死 spinner/遮罩。
            // gate 掉後走既有 fallback 分支（瞬現、_maskStopWaitAnim 對 null 安全 no-op），
            // 不是 belt-and-suspenders 式 null-safe 解構——單一決策點，結構上不可能再拿到 null。
            const canAnimate = !isPRM
                && typeof gsap !== 'undefined'
                && window.GhostFly && typeof window.GhostFly.handoffFocalDetectWait === 'function'
                && this._maskWaitTl;
            if (!g0 || !canAnimate) {
                // 既有 :1043 原路——不得用已知無效的 W/H/r 重算終值（那組值已知不合法，
                // computeMaskSettleGeometry 才會回 null）；合法 fallback 恆存在（openMask
                // pre-flight 已擋掉不合法幾何，_maskWinStyle 此刻必為合法值）。
                this._maskWinStyle = this._computeMaskWinStyle() || this._maskWinStyle;
                this._maskStopWaitAnim();   // CD-4b：不呼叫 → repeat:-1 loop 整條洩漏
                this._maskDetecting = false;
                return;
            }

            // ③ 全幅，同步寫在 x-show 翻真之前（CD-4a 核心不變式）——但這只是 hasFace（收斂）
            // 路徑的起點約定：no-face 沒有步驟⑥掛收斂 tween，寫「全幅」給它既非「起點」也非
            // spec §4.2 要求的「終點」（基準）。101b-T5：hasFace 分支一字不動（g0），!hasFace
            // 直接落基準幾何（與既有 PRM fallback 分支 :1380 呼叫同一個 _computeMaskWinStyle()）
            // ——CD-8「找到／沒找到的差別＝收斂 vs 不收斂，只此一項」的直接編碼。
            this._maskWinStyle = hasFace ? g0 : (this._computeMaskWinStyle() || this._maskWinStyle);
            // ④ 必須晚於 ② 的 gate（CD-4c：早於它＝動畫層不可用時永久卡 true）。
            this._maskSettling = true;
            // ⑤ x-show 此刻才放行；首次 paint 讀到步驟③寫入的值——hasFace＝全幅（g0，收斂起點）、
            //    no-face＝基準（右裁/置中，直接落定不收斂，spec §4.2）。
            this._maskDetecting = false;

            // ⑥ 交棒星空（CD-4b，不 clearProps）+ 建立單一 timeline（overlap 由 timeline 保證）。
            const { stars, burst } = window.GhostFly.handoffFocalDetectWait(this._maskWaitTl);
            const win = coverEl?.querySelector('.lb-mask-window');
            const spinner = coverEl?.querySelector('.lb-mask-spinner');
            const cleanup = () => this._maskClearSettleProps();
            // 101b-T2 / Codex PR#110 P2-2：GSAP 編排移入 GhostFly（shared/，不被 pages 守衛掃描，
            // 已是 focal 動畫家族的家）。tween 結構／ease／duration 一字不動，此處只注入
            // onConverge（每 tick 寫收斂中間幾何）與 onDone（收尾）兩個副作用。
            const tl = window.GhostFly.buildFocalSettleTimeline({
                stars, spinner, win, hasFace,
                onConverge: (t) => { this._maskWinStyle = computeMaskSettleGeometry(W, H, r, this._maskFocalX, t) || this._maskWinStyle; },
                onDone: cleanup,
            });
            this._maskSettleTl = tl;
        },

        // 101b-T2（§A-5）：收斂 tween 對稱停止 helper，逐字比照 _maskStopWaitAnim 的形狀
        // （idempotent、單一 helper、多處對稱呼叫）。呼叫點：_maskDragStart（CD-10 拖曳接管）、
        // _maskTeardown／_resetMask（中斷路徑再保險）。openMask finally 刻意不呼叫——那是
        // timeline 的起跑點，kill 等於自殺。
        _maskStopSettleAnim() {
            if (this._maskSettleTl && typeof this._maskSettleTl.kill === 'function') this._maskSettleTl.kill();
            // 顯式呼叫，不依賴 kill() 觸發 onInterrupt（ghost-fly.js 既有註解：GSAP 3 .kill()
            // 不保證 fire onInterrupt）。_maskClearSettleProps 本身冪等，onInterrupt 若仍另外
            // 觸發一次亦安全。
            this._maskClearSettleProps();
        },

        // 101b-T2（CD-9a）：settle timeline 的 onComplete/onInterrupt 共用收尾（比照
        // ghost-fly.js clearLanding「一個 closure、兩路徑共用」先例）。單一清理真理，供
        // _maskStopSettleAnim 與 timeline 自身收尾兩處呼叫，必須冪等（clearProps 對已無 inline
        // style 的元素是 no-op；clearFocalDetectWait 對 null handle 亦 no-op）。
        _maskClearSettleProps() {
            if (window.GhostFly && window.GhostFly.clearFocalDetectWait) {
                window.GhostFly.clearFocalDetectWait(this._maskWaitTl);   // 星空 clearProps 延到此刻
            }
            const el = this._maskTarget().imgEl;
            const coverEl = el?.closest('.lightbox-cover');
            if (coverEl && window.GhostFly?.clearFocalSettleProps) {
                // 101b-T2 (CD-9a) / Codex PR#110 P2-2：clearProps 移入 GhostFly（DOM lookup 仍在此）。
                const win = coverEl.querySelector('.lb-mask-window');
                const spinner = coverEl.querySelector('.lb-mask-spinner');
                window.GhostFly.clearFocalSettleProps({ win, spinner });
            }
            this._maskWaitTl = null;
            this._maskSettleTl = null;
            this._maskSettling = false;   // burst/spinner 此刻才被 x-show 收掉（兩者已 opacity 0）
        },

        // 亮窗幾何：讀 CSS var --poster-crop-ratio（非硬編）+ _maskFocalX 解焦點 x（component state，
        // 非 video.auto_focal——編輯態顯示真實落點，不套 focalObjectPosition 的 deadzone）。
        // 回傳 inline style OBJECT（width/height + transform translateX）供 template :style 綁定
        // （99a-T5：不可回傳 string，見 _maskWinStyle 宣告處註解——string 值會被 Alpine `:style`
        // 整串覆寫 style attribute，洗掉 x-show 設的 display:none）。失敗（rect=0 / ratio 讀不到）
        // 回傳 null，呼叫端（openMask）以 `if (!s)` 判斷；resize handler 呼叫端已知 null 會 fallback
        // 保留前值（見 openMask 內 _maskResizeHandler 定義）。
        // 亮窗以外由 CSS box-shadow spotlight 壓暗；transform 變化時 CSS transition 左右滑動（拖曳中停用，見 showcase.css）。
        // 98b-T6：純 compute（原 _maskWindowStyle 邏輯不變），由 openMask/drag/resize imperative 呼叫。
        // 100b-T2a（§B-3）：el 改走 _maskTarget().imgEl（G3 null-safe，dispatch 兩分支）；
        // 窗幾何建構（winW/winH）委派 computeMaskWinGeometry（shared/mask-geometry.js，
        // 可測試性 + G1 收斂單一 writer 來源，見該檔開頭說明）——ratio 讀取仍留在本函式體內
        // （裁決3，見下）。
        _computeMaskWinStyle() {
            const el = this._maskTarget().imgEl;
            // C17/#10：圖 render 前 rect=0 → 不畫（naturalWidth 未就緒）
            if (!el || !el.naturalWidth) return null;
            const rect = el.getBoundingClientRect();
            const W = rect.width;
            const H = rect.height;
            if (!W || !H) return null;
            // 100b-T2a（裁決3）：兩個字面 CSS var 名保留在本函式體內、不委派 _maskTarget().ratio——
            // static_guard_lint.mjs 有 4 條 scope-anchor 規則錨定本函式本體（getComputedStyle
            // required／--poster-crop-ratio required／兩條硬編比例常數 forbidden）。改成
            // getComputedStyle(el).getPropertyValue(this._maskTarget().ratio) 會讓
            // --poster-crop-ratio 字面字串離開此函式 scope，required 規則靜默 RED（T5-② 才是
            // 調整這 4 條 scope rule 的正式責任 task，T2 不搶做）。三元式是刻意重複，不可「清理」
            // 成委派寫法。
            const r = parseFloat(getComputedStyle(el).getPropertyValue(
                this._maskKind === 'actress' ? '--actress-crop-ratio' : '--poster-crop-ratio'
            ));
            if (!Number.isFinite(r) || r <= 0) return null;
            return computeMaskWinGeometry(W, H, r, this._maskFocalX);
        },
    };
}
