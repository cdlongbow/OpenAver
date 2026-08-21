// TASK-123-T4 review N3（reduced-motion 守衛）：playPickFill() 在 shouldSkip() 為真時
// 必須走 gsap.set() 降級（Alpine :style 已把 --pick-fill 寫成終值），不得走 gsap.fromTo()
// 補間路徑，且不得放灌滿火花（火花只在 fromTo 的 onComplete 裡點燃，fromTo 不被呼叫 ⟹
// 結構上不可能點火花，見下方 assertNoTimelineCreated 的說明）。
//
// review 用 mutation 證實：把 playPickFill() 裡 `if (shouldSkip()) {...return null;}` 整段
// 拿掉，911 支既有測試沒有任何一支轉紅——這支就是補那個洞。
//
// animations.js 是純 IIFE（`window.ShowcaseAnimations = ...`），零 import/export，
// plain `node --test` 可直接 `import()`，不需要 pick-star-lightbox.test.mjs 那套
// importmap resolve hook（那是給 state-lightbox.js 用的，本檔不碰它）。
//
// shouldSkip() 讀的是 `window.OpenAver?.prefersReducedMotion`（animations.js:31）——這是
// 模組外部可控的全域旗標，不是模組私有閉包成員，屬於合法的外部接縫。

import { test } from 'node:test';
import assert from 'node:assert/strict';

// animations.js 頂層碰 document.addEventListener（DOMContentLoaded 註冊 Flip/CustomEase）
// 與 typeof gsap —— 給最小 stub，比照既有 showcase 測試先 stub window/document。
globalThis.window = globalThis;
globalThis.document = {
    addEventListener() {},
    querySelectorAll() {
        return { length: 0 };
    },
};

/** 建一支記錄呼叫次數的 gsap mock。killPickSpark 用 killTweensOf，playPickFill 本體用
 *  killTweensOf / set / fromTo；playPickSpark（灌滿火花）用 timeline().fromTo().to()。
 *  timeline 呼叫次數 = 0 就是「沒有任何一顆火花 dot 被建立」的直接證據（不是靠推論）。
 */
function makeGsapMock() {
    const calls = { killTweensOf: [], set: [], fromTo: [], to: [], timeline: [] };
    const gsap = {
        killTweensOf(...args) { calls.killTweensOf.push(args); },
        set(...args) { calls.set.push(args); },
        fromTo(...args) {
            calls.fromTo.push(args);
            return {};
        },
        to(...args) {
            calls.to.push(args);
            return {};
        },
        timeline(...args) {
            calls.timeline.push(args);
            const tl = {
                fromTo() { return tl; },
                to() { return tl; },
            };
            return tl;
        },
    };
    return { gsap, calls };
}

const { gsap, calls } = makeGsapMock();
globalThis.gsap = gsap;

// animations.js 沒有 ESM export（純 side-effect：`window.ShowcaseAnimations = ...`），
// import 只為觸發那個賦值，實際物件從 window 上取。
await import('../animations.js');
const ShowcaseAnimations = globalThis.window.ShowcaseAnimations;

function makeFillEl() {
    // playPickFill 對 fillEl 只用 .closest()（找 .pick-star 容器做 scale 動畫）。
    // 回傳 null 讓 pickStarEl 分支跳過，不影響本測試驗的行為。
    return { closest() { return null; } };
}

test('playPickFill: reduced-motion(shouldSkip=true) 時走 gsap.set 降級，不走 fromTo，不放火花', () => {
    calls.killTweensOf.length = 0;
    calls.set.length = 0;
    calls.fromTo.length = 0;
    calls.timeline.length = 0;

    globalThis.window.OpenAver = { prefersReducedMotion: true };

    const fillEl = makeFillEl();
    const result = ShowcaseAnimations.playPickFill(fillEl, null, false, true);

    assert.equal(result, null, 'shouldSkip 分支必須 return null（無 tween 物件）');

    // 降級路徑：gsap.set(fillEl, {'--pick-fill': '0%'})（isPicked=true → toPct='0%'）
    const setCall = calls.set.find((args) => args[0] === fillEl);
    assert.ok(setCall, 'gsap.set 必須被呼叫在 fillEl 上（降級直接寫終值）');
    assert.deepEqual(setCall[1], { '--pick-fill': '0%' });

    // 不得走補間路徑
    assert.equal(calls.fromTo.length, 0, 'shouldSkip=true 時 gsap.fromTo 不應被呼叫');

    // 不得放火花：playPickSpark 的動態 dot 全靠 gsap.timeline() 建立，
    // 0 次 timeline 呼叫＝結構上不可能有任何一顆火花 dot 被點燃
    // （fromTo 都沒被呼叫，onComplete 永遠不存在，playPickSpark 沒有入口可以被觸發）。
    assert.equal(calls.timeline.length, 0, 'shouldSkip=true 時不應建立任何火花 timeline');
});

test('playPickFill: 正常動態（shouldSkip=false）時走 gsap.fromTo 補間，不走降級 set', () => {
    calls.killTweensOf.length = 0;
    calls.set.length = 0;
    calls.fromTo.length = 0;
    calls.timeline.length = 0;

    globalThis.window.OpenAver = { prefersReducedMotion: false };

    const fillEl = makeFillEl();
    const result = ShowcaseAnimations.playPickFill(fillEl, null, false, true);

    assert.notEqual(result, null, '正常路徑必須回傳 gsap.fromTo 的 tween 物件');
    assert.equal(calls.fromTo.length, 1, 'shouldSkip=false 時必須呼叫一次 gsap.fromTo');

    // 降級用的 set(fillEl, {'--pick-fill': toPct}) 不應出現（正常路徑改用 fromTo 起訖值）
    const degradedSetCall = calls.set.find(
        (args) => args[0] === fillEl && args[1] && Object.prototype.hasOwnProperty.call(args[1], '--pick-fill'),
    );
    assert.equal(degradedSetCall, undefined, 'shouldSkip=false 時不應出現降級用的 --pick-fill set');
});
