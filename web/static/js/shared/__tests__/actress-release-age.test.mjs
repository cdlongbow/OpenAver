// TASK-149b-T1: actress-release-age.js 純函式年齡計算與別名解析契約
// 零 import 依賴模組，不需要 importmap resolve hook / window stub。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const mod = await import('../actress-release-age.js');
const {
    LONG_FORM_MIN_DURATION_MINUTES,
    computeAgeAtDate,
    computeActressAgeForVideo,
    resolveFavoriteActressAge,
    computeActorAgesMap,
} = mod;

// ── 常數匯出 ─────────────────────────────────────────────────────────────

test('LONG_FORM_MIN_DURATION_MINUTES 常數匯出為 239', () => {
    assert.strictEqual(LONG_FORM_MIN_DURATION_MINUTES, 239);
});

// ── 邊界條件 1 ──────────────────────────────────────────────────────────

test('computeAgeAtDate 生日已過/未過各一組', () => {
    // port 自 tests/unit/test_scraper_actress_orchestrator.py::TestComputeAgeUnit
    // birth 1998-03-31:
    // dateISO='2026-01-01' -> 27 (未過)
    // dateISO='2026-04-01' -> 28 (已過)
    assert.strictEqual(computeAgeAtDate('1998-03-31', '2026-01-01'), 27);
    assert.strictEqual(computeAgeAtDate('1998-03-31', '2026-04-01'), 28);
    // 邊界：剛好生日當天（已過）與前一天（未過）
    assert.strictEqual(computeAgeAtDate('1998-03-31', '2026-03-31'), 28);
    assert.strictEqual(computeAgeAtDate('1998-03-31', '2026-03-30'), 27);
});

// ── 邊界條件 2 [mutation A 偵測] ─────────────────────────────────────────

test('AC-1 反例閘：不比月日的錯算法（發行年-出生年）與 +1 兩種都必須與正確答案不同', () => {
    const birth = '1998-03-31';
    const release = '2026-01-01';
    const actual = computeAgeAtDate(birth, release);

    // 正確實足年齡應為 27
    assert.strictEqual(actual, 27);

    // 錯算法 1：不比月日（發行年 - 出生年）= 2026 - 1998 = 28
    const wrongYearDiff = 2026 - 1998;
    assert.notStrictEqual(actual, wrongYearDiff);

    // 錯算法 2：虛歲/加一（發行年 - 出生年 + 1）= 29
    const wrongPlusOne = (2026 - 1998) + 1;
    assert.notStrictEqual(actual, wrongPlusOne);
});

// ── 邊界條件 3 ──────────────────────────────────────────────────────────

test('三種不顯示：生日缺失／發行日缺失／發行日只有年份"2015"皆回 null 且不等於退化只減年份', () => {
    // 1. 生日缺失
    assert.strictEqual(computeAgeAtDate(null, '2026-01-01'), null);
    assert.strictEqual(computeAgeAtDate(undefined, '2026-01-01'), null);
    assert.strictEqual(computeAgeAtDate('', '2026-01-01'), null);
    assert.strictEqual(computeAgeAtDate('invalid-date', '2026-01-01'), null);

    // 2. 發行日缺失
    assert.strictEqual(computeAgeAtDate('1998-03-31', null), null);
    assert.strictEqual(computeAgeAtDate('1998-03-31', undefined), null);
    assert.strictEqual(computeAgeAtDate('1998-03-31', ''), null);
    assert.strictEqual(computeAgeAtDate('1998-03-31', 'invalid-date'), null);

    // 3. 發行日只有年份 "2015"
    assert.strictEqual(computeAgeAtDate('1998-03-31', '2015'), null);
    assert.notStrictEqual(computeAgeAtDate('1998-03-31', '2015'), 2015 - 1998); // 退化「只減年份」會得到 17
});

// ── 邊界條件 6 [mutation C 偵測]（2026-09-17 主 session 追加，來源：review P2）─────

test('日曆不合法但格式對的日期必須回 null，閏日必須算得出', () => {
    // 真實庫實測 XC-1379／KA-2216 的 release_date 是 0000-00-00：regex 過得了，日曆上不存在
    assert.strictEqual(computeAgeAtDate('1998-03-31', '0000-00-00'), null);
    // 反方向：生日是 0000-00-00 也要擋
    assert.strictEqual(computeAgeAtDate('0000-00-00', '2020-01-01'), null);
    // 月份超界（13 月）
    assert.strictEqual(computeAgeAtDate('1998-03-31', '2015-13-01'), null);
    // 2 月沒有 30 號
    assert.strictEqual(computeAgeAtDate('1998-03-31', '2015-02-30'), null);
    // 正向斷言：閏年 2/29 是合法日期，不得被日曆檢查一併擋掉
    assert.strictEqual(computeAgeAtDate('1998-03-31', '2016-02-29'), 17);
    // Codex 149b review P3：0000-01-01 月/日皆合法、只有年份是 0——不對齊 Python
    // datetime.strptime（MINYEAR=1）就會放過，顯示出離奇的年齡。生日／發行日兩個位置各驗一次。
    assert.strictEqual(computeAgeAtDate('0000-01-01', '2020-01-01'), null);
    assert.strictEqual(computeAgeAtDate('1998-03-31', '0000-01-01'), null);
    // 0000 依現有 isLeapYear() 公式（0 % 400 === 0）會被判成閏年，2/29 若只驗月份/日期
    // 天數表會放過——同一顆年份下限守衛必須連這個閏日組合也擋下。
    assert.strictEqual(computeAgeAtDate('0000-02-29', '2020-01-01'), null);
    assert.strictEqual(computeAgeAtDate('1998-03-31', '0000-02-29'), null);
});

// ── 邊界條件 4 [mutation B 偵測] ─────────────────────────────────────────

test('AC-9 邊界：239 分鐘（IPSD-030 形狀）必須不顯示年齡', () => {
    const result = computeActressAgeForVideo({
        birth: '1998-03-31',
        releaseDate: '2026-04-01',
        durationMinutes: 239,
    });
    assert.strictEqual(result, null);
});

// ── computeActressAgeForVideo 補充邊界（DoD ④）───────────────────────────

test('computeActressAgeForVideo 片長邊界（237/238 正常，240/3278/4378 回 null，null/undefined/0 不阻擋）', () => {
    const base = { birth: '1998-03-31', releaseDate: '2026-04-01' };
    assert.strictEqual(computeActressAgeForVideo({ ...base, durationMinutes: 237 }), 28);
    assert.strictEqual(computeActressAgeForVideo({ ...base, durationMinutes: 238 }), 28);
    assert.strictEqual(computeActressAgeForVideo({ ...base, durationMinutes: 240 }), null);
    assert.strictEqual(computeActressAgeForVideo({ ...base, durationMinutes: 3278 }), null);
    assert.strictEqual(computeActressAgeForVideo({ ...base, durationMinutes: 4378 }), null);
    assert.strictEqual(computeActressAgeForVideo({ ...base, durationMinutes: null }), 28);
    assert.strictEqual(computeActressAgeForVideo({ ...base, durationMinutes: undefined }), 28);
    assert.strictEqual(computeActressAgeForVideo({ ...base, durationMinutes: 0 }), 28);
    assert.strictEqual(computeActressAgeForVideo(null), null);
    assert.strictEqual(computeActressAgeForVideo(undefined), null);
});

// ── 過去發行日與今日比對（DoD ⑤ AC-7）─────────────────────────────────────

test('AC-7 過去發行日算出的年齡必須小於等於今日日期算出的年齡', () => {
    const birth = '1998-03-31';
    const today = new Date();
    const todayISO = today.toISOString().slice(0, 10);
    const ageToday = computeAgeAtDate(birth, todayISO);
    assert.ok(typeof ageToday === 'number');

    const pastDates = ['1998-04-01', '2000-01-01', '2010-06-15', '2020-03-30', '2020-03-31', '2020-04-01'];
    for (const past of pastDates) {
        if (past <= todayISO) {
            const agePast = computeAgeAtDate(birth, past);
            assert.ok(agePast !== null && agePast <= ageToday, `past ${past} (${agePast}) should be <= today ${todayISO} (${ageToday})`);
        }
    }
});

// ── 邊界條件 5 ──────────────────────────────────────────────────────────

test('resolveFavoriteActressAge 四組別名小寫 key 比對成功', () => {
    const actresses = [
        { name: '柚木ティナ', birth: '1986-10-29' },
        { name: '安齋らら', birth: '1993-12-03' },
        { name: '坂道みる', birth: '1999-12-05' },
        { name: '河北彩伽', birth: '1999-04-24' },
    ];
    const nameToGroup = {
        'rio（柚木ティナ）': ['柚木ティナ', 'Rio（柚木ティナ）'],
        '柚木ティナ': ['柚木ティナ', 'Rio（柚木ティナ）'],
        'rion(リオン)': ['安齋らら', 'RION(リオン)'],
        '安齋らら': ['安齋らら', 'RION(リオン)'],
        'miru': ['坂道みる', 'miru'],
        '坂道みる': ['坂道みる', 'miru'],
        '河北彩花': ['河北彩伽', '河北彩花'],
        '河北彩伽': ['河北彩伽', '河北彩花'],
    };
    const video = { release_date: '2020-01-15', duration: 120 };

    assert.strictEqual(resolveFavoriteActressAge('Rio（柚木ティナ）', video, actresses, nameToGroup), 33);
    assert.strictEqual(resolveFavoriteActressAge('RION(リオン)', video, actresses, nameToGroup), 26);
    assert.strictEqual(resolveFavoriteActressAge('miru', video, actresses, nameToGroup), 20);
    assert.strictEqual(resolveFavoriteActressAge('河北彩花', video, actresses, nameToGroup), 20);
});

// ── resolveFavoriteActressAge 防禦性回傳 ───────────────────────────────────

test('resolveFavoriteActressAge 找不到、缺值、空陣列等邊界安全回傳 null', () => {
    const actresses = [{ name: '安齋らら', birth: '1993-12-03' }];
    const nameToGroup = { 'rion(リオン)': ['安齋らら', 'RION(リオン)'] };
    const video = { release_date: '2020-01-15', duration: 120 };

    // 查無女優
    assert.strictEqual(resolveFavoriteActressAge('未知女優', video, actresses, nameToGroup), null);
    // 女優未給生日
    assert.strictEqual(resolveFavoriteActressAge('rion(リオン)', video, [{ name: '安齋らら', birth: null }], nameToGroup), null);
    // 缺 video
    assert.strictEqual(resolveFavoriteActressAge('rion(リオン)', null, actresses, nameToGroup), null);
    // 缺 actresses
    assert.strictEqual(resolveFavoriteActressAge('rion(リオン)', video, null, nameToGroup), null);
    assert.strictEqual(resolveFavoriteActressAge('rion(リオン)', video, [], nameToGroup), null);
    // 缺 rawActressName
    assert.strictEqual(resolveFavoriteActressAge('', video, actresses, nameToGroup), null);
    assert.strictEqual(resolveFavoriteActressAge(null, video, actresses, nameToGroup), null);
    // 缺 nameToGroup（fallback 至單一名稱查表）
    assert.strictEqual(resolveFavoriteActressAge('安齋らら', video, actresses, null), 26);
    assert.strictEqual(resolveFavoriteActressAge('安齋らら', video, actresses, undefined), 26);
});

// ── computeActorAgesMap 契約測試（TASK-155a-T1 CD-155a-2）──────────────────

test('computeActorAgesMap 契約：多女優混合、別名命中、片長 >= 239 回空 map、片長缺失正常算、falsy 邊界', () => {
    assert.strictEqual(typeof computeActorAgesMap, 'function');

    const actresses = [
        { name: '柚木ティナ', birth: '1986-10-29' },
        { name: '安齋らら', birth: null }, // 收藏但無生日
        { name: '河北彩伽', birth: '1999-04-24' },
    ];
    const nameToGroup = {
        'rio（柚木ティナ）': ['柚木ティナ', 'Rio（柚木ティナ）'],
        '柚木ティナ': ['柚木ティナ', 'Rio（柚木ティナ）'],
        '河北彩花': ['河北彩伽', '河北彩花'],
        '河北彩伽': ['河北彩伽', '河北彩花'],
    };

    // 1. 多女優混合：Rio（柚木ティナ）(命中別名且有生日=33)、安齋らら(收藏但無生日=null不收錄)、未知女優(非收藏=null不收錄)、河北彩花(命中別名且有生日=20)
    const multiVideo = {
        actresses: 'Rio（柚木ティナ）, 安齋らら, 未知女優, 河北彩花',
        release_date: '2020-01-15',
        duration: 120,
    };
    const multiResult = computeActorAgesMap(multiVideo, actresses, nameToGroup);
    assert.deepStrictEqual(multiResult, {
        'Rio（柚木ティナ）': 33,
        '河北彩花': 20,
    });

    // 2. 片長已知且 >= 239 分鐘回傳空 map
    const longVideo = {
        actresses: 'Rio（柚木ティナ）, 河北彩花',
        release_date: '2020-01-15',
        duration: 239,
    };
    assert.deepStrictEqual(computeActorAgesMap(longVideo, actresses, nameToGroup), {});

    const superLongVideo = {
        actresses: 'Rio（柚木ティナ）',
        release_date: '2020-01-15',
        duration: 300,
    };
    assert.deepStrictEqual(computeActorAgesMap(superLongVideo, actresses, nameToGroup), {});

    // 3. 片長不明（duration 為 null 或缺欄位）仍正常算出年齡（spec v1.2，非「短於 239」）
    const nullDurationVideo = {
        actresses: 'Rio（柚木ティナ）',
        release_date: '2020-01-15',
        duration: null,
    };
    assert.deepStrictEqual(computeActorAgesMap(nullDurationVideo, actresses, nameToGroup), {
        'Rio（柚木ティナ）': 33,
    });

    const missingDurationVideo = {
        actresses: 'Rio（柚木ティナ）',
        release_date: '2020-01-15',
    };
    assert.deepStrictEqual(computeActorAgesMap(missingDurationVideo, actresses, nameToGroup), {
        'Rio（柚木ティナ）': 33,
    });

    // 4. video / video.actresses falsy 回傳空 map（不拋錯）
    assert.deepStrictEqual(computeActorAgesMap(null, actresses, nameToGroup), {});
    assert.deepStrictEqual(computeActorAgesMap(undefined, actresses, nameToGroup), {});
    assert.deepStrictEqual(computeActorAgesMap({}, actresses, nameToGroup), {});
    assert.deepStrictEqual(computeActorAgesMap({ actresses: null }, actresses, nameToGroup), {});
    assert.deepStrictEqual(computeActorAgesMap({ actresses: '' }, actresses, nameToGroup), {});
    assert.deepStrictEqual(computeActorAgesMap({ actresses: '   ' }, actresses, nameToGroup), {});
});

