// TASK-148b-T5：原型 B 契約 — capture 整格位置 → play 視口 OR 過濾 → x/y 反轉
// ＋ ticker.tick 對齊時基、kill-before-measure、releaseMotionClasses 清 transform。
//
// 真的 import() animations.js／state-base.js，用假 DOM／假 gsap 驅動——不是源碼字串斷言。

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
const MARGIN = 200;

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

/**
 * 120 張假卡：視窗內／視窗外／0×0 三類。
 * 0–39 視窗內；40–79 視窗外；80–119 0×0。
 */
function build120Cards() {
    const cards = [];
    for (let i = 0; i < 40; i++) {
        const top = 50 + i * 15;
        cards.push(makeCard({
            top, bottom: top + 180, left: 0, right: 100, width: 100, height: 180,
        }, { animating: i < 3 }));
    }
    for (let i = 0; i < 40; i++) {
        const top = i % 2 === 0 ? 5000 + i * 20 : -3000 - i * 20;
        cards.push(makeCard({
            top, bottom: top + 180, left: 0, right: 100, width: 100, height: 180,
        }));
    }
    for (let i = 0; i < 40; i++) {
        cards.push(makeCard({
            top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0,
        }));
    }
    return cards;
}

function nonZeroCards(cards) {
    return cards.filter((c) => !(c._rect.width === 0 && c._rect.height === 0));
}

function inBand(top, bottom, viewportH) {
    return bottom > -MARGIN && top < viewportH + MARGIN;
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

function invertSetCalls() {
    return gsapCalls.set.filter((args) => {
        const vars = args[1] || {};
        return typeof vars.x === 'number' || typeof vars.y === 'number';
    });
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

test('toggleInfo()：第一行就寫 infoVisible（capture stub 內已是新值）', () => {
    const { ctx, fakeGrid } = makeToggleInfoCtx();
    let infoVisibleAtCapture;
    const savedSA = globalThis.window.ShowcaseAnimations;
    globalThis.window.ShowcaseAnimations = {
        captureInfoState(gridEl) {
            infoVisibleAtCapture = ctx.infoVisible;
            assert.equal(gridEl, fakeGrid);
            return null;
        },
        playInfoExpand() {},
    };
    try {
        assert.equal(ctx.infoVisible, false);
        ctx.toggleInfo();
        assert.equal(
            infoVisibleAtCapture,
            true,
            'captureInfoState 呼叫當下 infoVisible 必須已經是新值 true（眼睛回饋不被擋）',
        );
        assert.equal(ctx.infoVisible, true);
        assert.equal(ctx._persistedShowcase.infoVisible, true);
    } finally {
        globalThis.window.ShowcaseAnimations = savedSA;
    }
});

// ── 2. capture 在 classList.toggle('info-open') 之前 ─────────────

test("toggleInfo()：captureInfoState 在 classList.toggle('info-open') 之前", () => {
    const { ctx, fakeGrid } = makeToggleInfoCtx();
    const order = [];
    const origToggle = fakeGrid.classList.toggle.bind(fakeGrid.classList);
    fakeGrid.classList.toggle = (name, force) => {
        order.push({ step: 'toggle', name, force });
        return origToggle(name, force);
    };
    const savedSA = globalThis.window.ShowcaseAnimations;
    globalThis.window.ShowcaseAnimations = {
        captureInfoState(gridEl) {
            assert.equal(
                gridEl.classList.contains('info-open'),
                false,
                'capture 當下尚未套上 info-open（要量舊位置）',
            );
            order.push({ step: 'capture' });
            return null;
        },
        playInfoExpand() {},
    };
    try {
        ctx.toggleInfo();
        assert.equal(order.length, 2);
        assert.equal(order[0].step, 'capture');
        assert.equal(order[1].step, 'toggle');
        assert.equal(order[1].name, 'info-open');
        assert.equal(order[1].force, true);
    } finally {
        globalThis.window.ShowcaseAnimations = savedSA;
    }
});

// ── 3. gsap.set 反轉 x/y，不含 scale ─────────────────────────────

test('playInfoExpand：gsap.set 傳 x/y 反轉差值，完全不含 scaleX/scaleY/scale', () => {
    resetCalls();
    const card = makeCard({
        top: 100, bottom: 280, left: 50, right: 150, width: 100, height: 180,
    });
    const gridEl = makeGrid([card]);
    const captured = [{ el: card, top: 100, left: 50, bottom: 280 }];
    card._rect = {
        top: 220, bottom: 400, left: 80, right: 180, width: 100, height: 180,
    };

    ShowcaseAnimations.playInfoExpand(captured, gridEl);

    const invertCalls = invertSetCalls();
    assert.equal(invertCalls.length, 1, '必須對每張卡做一次反轉 gsap.set');
    const vars = invertCalls[0][1];
    assert.equal(vars.x, 50 - 80, 'x = oldLeft - newLeft');
    assert.equal(vars.y, 100 - 220, 'y = oldTop - newTop');
    assert.equal('scaleX' in vars, false, '不得含 scaleX');
    assert.equal('scaleY' in vars, false, '不得含 scaleY');
    assert.equal('scale' in vars, false, '不得含 scale');
});

// ── 4. gsap.to 不傳 stagger ──────────────────────────────────────

test('playInfoExpand：gsap.to 不傳 stagger', () => {
    resetCalls();
    const card = makeCard({
        top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180,
    });
    const gridEl = makeGrid([card]);
    const captured = [{ el: card, top: 100, left: 0, bottom: 280 }];

    const tween = ShowcaseAnimations.playInfoExpand(captured, gridEl);

    assert.ok(tween && tween.__fakeTween);
    assert.equal(gsapCalls.to.length, 1);
    const vars = gsapCalls.to[0][1];
    assert.equal('stagger' in vars, false, 'gsap.to 不得傳 stagger');
    assert.equal(vars.x, 0);
    assert.equal(vars.y, 0);
    assert.equal(vars.duration, WALL_MOTION.INFO_EXPAND_DURATION);
    assert.equal(vars.ease, 'fluent');
});

// ── 4b. ticker.tick() 在 gsap.to 之前 ────────────────────────────

test('playInfoExpand：gsap.ticker.tick() 發生在 gsap.to() 之前', () => {
    resetCalls();
    const card = makeCard({
        top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180,
    });
    const gridEl = makeGrid([card]);
    const captured = [{ el: card, top: 100, left: 0, bottom: 280 }];

    ShowcaseAnimations.playInfoExpand(captured, gridEl);

    const tickIdx = gsapOrder.indexOf('tick');
    const toIdx = gsapOrder.indexOf('to');
    assert.ok(tickIdx >= 0, '必須呼叫 gsap.ticker.tick()');
    assert.ok(toIdx >= 0, '必須呼叫 gsap.to()');
    assert.ok(tickIdx < toIdx, 'ticker.tick() 必須在 gsap.to() 之前');
});

// ── 5. onInterrupt：卸 class ＋ clearProps transform ─────────────

test('playInfoExpand：onInterrupt 卸 gsap-animating／flip-guard 且 clearProps transform', () => {
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
    tween.vars.onInterrupt();

    assert.ok(
        clearPropsCalls('transform').length >= 1,
        'onInterrupt 必須 clearProps transform',
    );
    const clearAfter = gsapCalls.set.slice(setBefore).find(
        (args) => args[1] && args[1].clearProps === 'transform',
    );
    assert.ok(clearAfter, 'onInterrupt 路徑必須新呼叫 clearProps: transform');
    for (const c of cards) {
        assert.ok(c._removed.includes('gsap-animating'), '每張卡 gsap-animating 必須卸');
        assert.equal(c.classList.contains('gsap-animating'), false);
    }
    assert.ok(gridEl._removed.includes('flip-guard'));
    assert.equal(gridEl.classList.contains('flip-guard'), false);
});

// ── 6. onComplete：同上 ──────────────────────────────────────────

test('playInfoExpand：onComplete 卸 gsap-animating／flip-guard 且 clearProps transform', () => {
    resetCalls();
    const cards = [
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
    ];
    const gridEl = makeGrid(cards);
    const captured = [{ el: cards[0], top: 100, left: 0, bottom: 280 }];

    const tween = ShowcaseAnimations.playInfoExpand(captured, gridEl);
    const setBefore = gsapCalls.set.length;
    tween.vars.onComplete();

    const clearAfter = gsapCalls.set.slice(setBefore).find(
        (args) => args[1] && args[1].clearProps === 'transform',
    );
    assert.ok(clearAfter, 'onComplete 必須 clearProps transform');
    assert.ok(cards[0]._removed.includes('gsap-animating'));
    assert.ok(gridEl._removed.includes('flip-guard'));
});

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

test('captureInfoState：120 張卡收整格非 0×0；fixture 含三類各至少一張', () => {
    resetCalls();
    const cards = build120Cards();
    const gridEl = makeGrid(cards);
    const expected = nonZeroCards(cards);

    assert.equal(cards.length, 120);
    assert.ok(
        cards.some((c) => c._rect.width > 0 && inBand(c._rect.top, c._rect.bottom, VIEWPORT_H)),
        'fixture 必須含視口內卡',
    );
    assert.ok(
        cards.some((c) => c._rect.width > 0 && !inBand(c._rect.top, c._rect.bottom, VIEWPORT_H)),
        'fixture 必須含視口外卡',
    );
    assert.ok(
        cards.some((c) => c._rect.width === 0 && c._rect.height === 0),
        'fixture 必須含 0×0 卡',
    );
    assert.equal(expected.length, 80, '非 0×0 剛好 80 張（含視口外）');

    const result = ShowcaseAnimations.captureInfoState(gridEl);

    assert.ok(Array.isArray(result), '必須回傳陣列');
    assert.equal(result.length, expected.length, 'capture 不得在此階段做視口過濾');
    assert.deepEqual(result.map((r) => r.el), expected);
    for (const item of result) {
        assert.equal(typeof item.top, 'number');
        assert.equal(typeof item.left, 'number');
        assert.equal(typeof item.bottom, 'number');
        assert.ok(item.el);
    }
});

// ── 10b. play：舊或新位置在窗內才 animate ────────────────────────

test('playInfoExpand：舊或新位置落在視口 ±200px 才 animate，其餘不碰', () => {
    resetCalls();
    // A：舊在窗內、新在窗外
    const a = makeCard({
        top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180,
    });
    // B：舊在窗外、新跳進窗內（收合界外卡）
    const b = makeCard({
        top: 1156, bottom: 1336, left: 0, right: 100, width: 100, height: 180,
    });
    // C：舊新都在窗外
    const c = makeCard({
        top: 5000, bottom: 5180, left: 0, right: 100, width: 100, height: 180,
    });
    const gridEl = makeGrid([a, b, c]);
    const captured = [
        { el: a, top: 100, left: 0, bottom: 280 },
        { el: b, top: 1156, left: 0, bottom: 1336 },
        { el: c, top: 5000, left: 0, bottom: 5180 },
    ];
    a._rect = { top: 5000, bottom: 5180, left: 0, right: 100, width: 100, height: 180 };
    b._rect = { top: 705, bottom: 885, left: 0, right: 100, width: 100, height: 180 };
    c._rect = { top: 5100, bottom: 5280, left: 0, right: 100, width: 100, height: 180 };

    const tween = ShowcaseAnimations.playInfoExpand(captured, gridEl);
    assert.ok(tween);

    const invertEls = invertSetCalls().map((args) => args[0]);
    assert.equal(invertEls.length, 2);
    assert.ok(invertEls.includes(a), '舊在窗內必須 animate');
    assert.ok(invertEls.includes(b), '新跳進窗內必須 animate');
    assert.ok(!invertEls.includes(c), '舊新都在窗外不得碰');

    const toTargets = gsapCalls.to[0][0];
    assert.equal(toTargets.length, 2);
    assert.ok(toTargets.includes(a));
    assert.ok(toTargets.includes(b));
    assert.ok(!toTargets.includes(c));
    assert.ok(!c._added.includes('gsap-animating'), '窗外卡不得加 gsap-animating');
});

// ── I-148b-2：kill-before-measure 順序 ───────────────────────────

test('captureInfoState：killTweensOf → remove(gsap-animating) → clearProps(transform,opacity) → 才量測', () => {
    resetCalls();
    const cards = [
        makeCard({
            top: 50, bottom: 230, left: 0, right: 100, width: 100, height: 180,
        }, { animating: true }),
        makeCard({
            top: 80, bottom: 260, left: 0, right: 100, width: 100, height: 180,
        }, { animating: true }),
    ];
    const gridEl = makeGrid(cards);
    const order = [];

    const origKill = globalThis.gsap.killTweensOf;
    const origSet = globalThis.gsap.set;
    globalThis.gsap.killTweensOf = (...args) => {
        order.push({ step: 'killTweensOf', argLen: args[0].length });
        return origKill(...args);
    };
    globalThis.gsap.set = (...args) => {
        order.push({
            step: 'set',
            clearProps: args[1] && args[1].clearProps,
            argLen: args[0] && args[0].length,
        });
        return origSet(...args);
    };
    for (const c of cards) {
        const origRemove = c.classList.remove.bind(c.classList);
        c.classList.remove = (name) => {
            if (name === 'gsap-animating') order.push({ step: 'remove-gsap-animating' });
            return origRemove(name);
        };
        const origRect = c.getBoundingClientRect.bind(c);
        c.getBoundingClientRect = () => {
            order.push({ step: 'measure' });
            return origRect();
        };
    }

    try {
        const result = ShowcaseAnimations.captureInfoState(gridEl);
        assert.ok(result);
        assert.equal(result.length, 2);
    } finally {
        globalThis.gsap.killTweensOf = origKill;
        globalThis.gsap.set = origSet;
    }

    const steps = order.map((o) => o.step);
    const killIdx = steps.indexOf('killTweensOf');
    const removeIdx = steps.indexOf('remove-gsap-animating');
    const clearIdx = steps.findIndex((s, i) => s === 'set' && order[i].clearProps === 'transform,opacity');
    const measureIdx = steps.indexOf('measure');

    assert.ok(killIdx >= 0, '① 必須呼叫 gsap.killTweensOf(cards)');
    assert.equal(order[killIdx].argLen, cards.length, 'killTweensOf 吃完整 cards');
    assert.ok(removeIdx >= 0, '③ 必須 remove(gsap-animating)');
    assert.ok(clearIdx >= 0, '② 必須 clearProps transform,opacity');
    assert.equal(
        order[clearIdx].clearProps,
        'transform,opacity',
        '④ clearProps 必須是 transform,opacity（不是只清 transform）',
    );
    assert.ok(measureIdx >= 0, '必須量測 getBoundingClientRect');
    assert.ok(killIdx < measureIdx, '⑦ kill 必須在量測之前');
    assert.ok(removeIdx < measureIdx, '⑦ remove class 必須在量測之前');
    assert.ok(clearIdx < measureIdx, '⑦ clearProps 必須在量測之前');
    assert.ok(killIdx < removeIdx || removeIdx < clearIdx, '清理步驟必須在量測前完成');
});

// ── !gridEl guard（⑤⑥）──────────────────────────────────────────

test('captureInfoState / playInfoExpand：!gridEl → null 不 throw', () => {
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
