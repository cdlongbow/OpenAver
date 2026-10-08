// TASK-148b-T5：資訊展開生命週期 — 動畫結束／被打斷後不殘留位移、建動畫失敗與缺 gsap 的降級、
// 系統「減少動態」直接到位。真的 import() animations.js／state-base.js，用假 DOM／假 gsap 驅動。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

globalThis.window = globalThis;
globalThis.document = {
    addEventListener() {},
    querySelectorAll() {
        return { length: 0 };
    },
};

const gsapOrder = [];
const gsapCalls = { killTweensOf: [], set: [], to: [], tick: 0 };
globalThis.gsap = {
    killTweensOf(...args) {
        gsapOrder.push('killTweensOf');
        gsapCalls.killTweensOf.push(args);
    },
    set(...args) {
        gsapOrder.push('set');
        gsapCalls.set.push(args);
    },
    to(...args) {
        gsapOrder.push('to');
        gsapCalls.to.push(args);
        return { __fakeTween: true, vars: args[1] };
    },
    ticker: {
        tick() {
            gsapOrder.push('tick');
            gsapCalls.tick += 1;
        },
    },
    registerPlugin() {},
};

const WALL_MOTION = {
    STAGGER_ORIGIN: 'center',
    ENTRY_STAGGER_AMOUNT: 0.3,
    FILTER_ENTER_STAGGER_AMOUNT: 0.2,
    INFO_EXPAND_DURATION: 0.2,
};

globalThis.OpenAver = {
    prefersReducedMotion: false,
    motion: {
        DURATION: { medium: 0.333 },
        WALL_MOTION,
    },
};

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
const STATIC_JS_ROOT = pathToFileURL(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../') + '/',
).href;
const MOTION_ADAPTER_PATH = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    '../../../components/motion-adapter.js',
);

const loaderCode = `
const IMPORTMAP = ${JSON.stringify(IMPORTMAP)};
const STATIC_JS_ROOT = ${JSON.stringify(STATIC_JS_ROOT)};
export async function resolve(specifier, context, nextResolve) {
    for (const [prefix, rel] of Object.entries(IMPORTMAP)) {
        if (specifier.startsWith(prefix)) {
            return nextResolve(STATIC_JS_ROOT + rel + specifier.slice(prefix.length), context);
        }
    }
    if (specifier.startsWith('@/')) {
        return nextResolve(STATIC_JS_ROOT + specifier.slice(2), context);
    }
    return nextResolve(specifier, context);
}
`;
register(`data:text/javascript,${encodeURIComponent(loaderCode)}`, import.meta.url);

await import('../animations.js');
const ShowcaseAnimations = globalThis.window.ShowcaseAnimations;

const { stateBase } = await import('../state-base.js');

const VIEWPORT_H = 900;

function makeCard(rect, { animating = false } = {}) {
    const removed = [];
    const added = [];
    const classList = {
        _hasAnimating: animating,
        remove(name) {
            removed.push(name);
            if (name === 'gsap-animating') classList._hasAnimating = false;
        },
        add(name) {
            added.push(name);
            if (name === 'gsap-animating') classList._hasAnimating = true;
        },
        contains(name) {
            return name === 'gsap-animating' && classList._hasAnimating;
        },
    };
    const card = {
        getBoundingClientRect() { return card._rect; },
        classList,
        _removed: removed,
        _added: added,
        _rect: rect,
    };
    return card;
}

function makeGrid(cards) {
    const removed = [];
    const added = [];
    const classes = new Set();
    return {
        querySelectorAll() {
            const list = Object.assign(cards.slice(), { length: cards.length });
            list.forEach = Array.prototype.forEach;
            return list;
        },
        classList: {
            add(name) {
                added.push(name);
                classes.add(name);
            },
            remove(name) {
                removed.push(name);
                classes.delete(name);
            },
            contains(name) {
                return classes.has(name);
            },
            toggle(name, force) {
                if (force) {
                    classes.add(name);
                    added.push(name);
                } else {
                    classes.delete(name);
                    removed.push(name);
                }
            },
        },
        _removed: removed,
        _added: added,
        _classes: classes,
    };
}

function resetCalls() {
    gsapCalls.killTweensOf.length = 0;
    gsapCalls.set.length = 0;
    gsapCalls.to.length = 0;
    gsapCalls.tick = 0;
    gsapOrder.length = 0;
    globalThis.window.OpenAver.prefersReducedMotion = false;
    globalThis.window.innerHeight = VIEWPORT_H;
}

function clearPropsCalls(exact) {
    return gsapCalls.set.filter((args) => {
        const cp = args[1] && args[1].clearProps;
        if (!cp) return false;
        if (exact === undefined) return true;
        return cp === exact;
    });
}

function makeToggleInfoCtx() {
    const fakeGrid = makeGrid([]);
    const ctx = Object.assign(
        stateBase.call({ $persist: (obj) => ({ as: () => obj }) }),
        {
            infoVisible: false,
            _persistedShowcase: {},
            _getActiveGrid: () => fakeGrid,
        },
    );
    return { ctx, fakeGrid };
}

// ── I-148b-1：讀 production motion-adapter.js ────────────────────

test('I-148b-1: INFO_EXPAND_DURATION <= DURATION.medium（讀 production）', () => {
    const src = fs.readFileSync(MOTION_ADAPTER_PATH, 'utf8');
    const medium = Number(src.match(/medium:\s*([\d.]+)/)[1]);
    const infoDur = Number(src.match(/INFO_EXPAND_DURATION:\s*([\d.]+)/)[1]);
    assert.ok(Number.isFinite(medium) && Number.isFinite(infoDur));
    assert.ok(
        infoDur <= medium,
        `production INFO_EXPAND_DURATION (${infoDur}) must be <= DURATION.medium (${medium})`,
    );
});

// ── 1. toggleInfo：第一行就寫 infoVisible ────────────────────────

// ── 2. capture 在 classList.toggle('info-open') 之前 ─────────────

// ── 3. gsap.set 反轉 x/y，不含 scale ─────────────────────────────

// ── 4. gsap.to 不傳 stagger ──────────────────────────────────────

// ── 4b. ticker.tick() 在 gsap.to 之前 ────────────────────────────

// ── 5. onInterrupt：卸 class ＋ clearProps transform ─────────────

test('playInfoExpand：onInterrupt 卸 gsap-animating／flip-guard 且 clearProps transform', () => {
    // 162a：onComplete 併入同一支（同一失敗原因：動畫結束／被打斷後卡片殘留位移或動畫 class）
    for (const hook of ['onInterrupt', 'onComplete']) {
        resetCalls();
        const cards = [
            makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
            makeCard({ top: 200, bottom: 380, left: 0, right: 100, width: 100, height: 180 }),
        ];
        const gridEl = makeGrid(cards);
        const captured = cards.map((c) => ({
            el: c, top: c._rect.top, left: c._rect.left, bottom: c._rect.bottom,
        }));

        const tween = ShowcaseAnimations.playInfoExpand(captured, gridEl);
        assert.ok(tween);
        for (const c of cards) {
            assert.ok(c.classList.contains('gsap-animating'), '建 tween 後每張卡應帶 gsap-animating');
        }
        assert.ok(gridEl.classList.contains('flip-guard'));

        const setBefore = gsapCalls.set.length;
        tween.vars[hook]();

        const clearAfter = gsapCalls.set.slice(setBefore).find(
            (args) => args[1] && args[1].clearProps === 'transform',
        );
        assert.ok(clearAfter, `${hook} 路徑必須新呼叫 clearProps: transform`);
        for (const c of cards) {
            assert.ok(c._removed.includes('gsap-animating'), '每張卡 gsap-animating 必須卸');
            assert.equal(c.classList.contains('gsap-animating'), false);
        }
        assert.ok(gridEl._removed.includes('flip-guard'));
        assert.equal(gridEl.classList.contains('flip-guard'), false);
    }
});

// ── 6. onComplete：同上 ──────────────────────────────────────────

// ── 7. 建 tween 拋錯 → 收乾淨＋狀態機仍翻轉（AC-6）──────────────

test('建 tween 拋錯：class/transform 收乾淨，toggleInfo 狀態機仍翻轉（AC-6）', () => {
    resetCalls();
    const { ctx } = makeToggleInfoCtx();
    const card = makeCard({
        top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180,
    });
    const gridWithCard = makeGrid([card]);
    ctx._getActiveGrid = () => gridWithCard;

    const origTo = globalThis.gsap.to;
    globalThis.gsap.to = (...args) => {
        gsapOrder.push('to');
        throw new Error('tween-build-boom');
    };

    const savedConsoleError = console.error;
    const errors = [];
    console.error = (...args) => { errors.push(args); };

    try {
        assert.doesNotThrow(() => ctx.toggleInfo());
        assert.equal(ctx.infoVisible, true, '動畫失敗不得回滾 infoVisible');
        assert.equal(ctx._persistedShowcase.infoVisible, true, '持久化仍須翻轉');
        assert.ok(
            clearPropsCalls('transform').length >= 1,
            'catch 路徑必須 clearProps transform',
        );
        assert.ok(card._removed.includes('gsap-animating'));
        assert.ok(gridWithCard._removed.includes('flip-guard'));
        assert.equal(card.classList.contains('gsap-animating'), false);
        assert.equal(gridWithCard.classList.contains('flip-guard'), false);
        assert.ok(errors.length >= 1, '應 console.error 記錄動畫失敗');
    } finally {
        globalThis.gsap.to = origTo;
        console.error = savedConsoleError;
    }
});

// ── 8. 缺 gsap 安靜降級 ──────────────────────────────────────────

test('缺 gsap：capture／play／toggleInfo 整條安靜降級、不 throw', () => {
    resetCalls();
    const cards = [
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
    ];
    const gridEl = makeGrid(cards);
    const captured = [{ el: cards[0], top: 100, left: 0, bottom: 280 }];
    const saved = globalThis.gsap;
    delete globalThis.gsap;
    try {
        assert.doesNotThrow(() => {
            assert.equal(ShowcaseAnimations.captureInfoState(gridEl), null);
            assert.equal(ShowcaseAnimations.playInfoExpand(captured, gridEl), null);
        });

        const { ctx } = makeToggleInfoCtx();
        assert.doesNotThrow(() => ctx.toggleInfo());
        assert.equal(ctx.infoVisible, true);
        assert.equal(ctx._persistedShowcase.infoVisible, true);
    } finally {
        globalThis.gsap = saved;
    }
});

// ── 8b. AC-6：缺 _getActiveGrid／grid null ───────────────────────

test('toggleInfo()：缺 _getActiveGrid 與 grid 為 null 時不 throw，狀態機仍翻轉（AC-6）', () => {
    const ctx = Object.assign(
        stateBase.call({ $persist: (obj) => ({ as: () => obj }) }),
        {
            infoVisible: false,
            _persistedShowcase: {},
        },
    );
    delete ctx._getActiveGrid;
    assert.equal(typeof ctx._getActiveGrid, 'undefined');

    assert.doesNotThrow(() => ctx.toggleInfo());
    assert.equal(ctx.infoVisible, true);
    assert.equal(ctx._persistedShowcase.infoVisible, true);

    ctx._getActiveGrid = () => null;
    assert.doesNotThrow(() => ctx.toggleInfo());
    assert.equal(ctx.infoVisible, false);
    assert.equal(ctx._persistedShowcase.infoVisible, false);

    // 162a：!gridEl 動畫入口守衛併入（同一失敗原因：grid 為 null 不得崩）
    resetCalls();
    assert.equal(ShowcaseAnimations.captureInfoState(null), null);
    assert.equal(ShowcaseAnimations.playInfoExpand(null, null), null);
    assert.equal(
        ShowcaseAnimations.playInfoExpand(
            [{ el: makeCard({ top: 1, bottom: 2, left: 0, right: 1, width: 1, height: 1 }), top: 1, left: 0, bottom: 2 }],
            null,
        ),
        null,
    );
    assert.doesNotThrow(() => ShowcaseAnimations.captureInfoState(null));
    assert.doesNotThrow(() => ShowcaseAnimations.playInfoExpand([], null));
});

// ── 9. shouldSkip（PRM）不建動畫 ─────────────────────────────────

test('playInfoExpand：shouldSkip() 成立時不建動畫（gsap.to 零呼叫）', () => {
    resetCalls();
    globalThis.window.OpenAver.prefersReducedMotion = true;
    const card = makeCard({
        top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180,
    });
    const gridEl = makeGrid([card]);
    const captured = [{ el: card, top: 100, left: 0, bottom: 280 }];

    const result = ShowcaseAnimations.playInfoExpand(captured, gridEl);

    assert.equal(result, null);
    assert.equal(gsapCalls.to.length, 0, 'reduced-motion 時 gsap.to 零呼叫');
    assert.equal(gridEl.classList.contains('flip-guard'), false);
});

// ── 10. capture 收整格非 0×0（視口過濾改在 play）────────────────

// ── 10b. play：舊或新位置在窗內才 animate ────────────────────────

// ── I-148b-2：kill-before-measure 順序 ───────────────────────────

// ── !gridEl guard（⑤⑥）──────────────────────────────────────────

// 視口過濾（162a 依 branch review 補回精簡版）：使用者在上千張的大牆按眼睛 →
// 完全離屏的卡不得被動畫（否則整面牆每張都 gsap.set/to → 卡頓）。
test('playInfoExpand：舊或新位置在視口 ±200px 內才 animate，完全離屏的卡不碰', () => {
    resetCalls();
    const rect = (top) => ({ top, bottom: top + 180, left: 0, right: 100, width: 100, height: 180 });
    const a = makeCard(rect(5000));   // 新位置離屏
    const c = makeCard(rect(5100));   // 新位置離屏
    const gridEl = makeGrid([a, c]);
    const captured = [
        { el: a, top: 100, left: 0, bottom: 280 },     // 舊在窗內
        { el: c, top: 5000, left: 0, bottom: 5180 },   // 舊新都在窗外
    ];
    assert.ok(ShowcaseAnimations.playInfoExpand(captured, gridEl));
    const toTargets = gsapCalls.to[0][0];
    const setTargets = gsapCalls.set.map((args) => args[0]).flat();
    assert.ok(toTargets.includes(a) && setTargets.includes(a), '舊在窗內必須 animate');
    assert.ok(!toTargets.includes(c) && !setTargets.includes(c), '舊新都在窗外不得碰');
    assert.ok(!c._added.includes('gsap-animating'), '窗外卡不得加 gsap-animating');
});
