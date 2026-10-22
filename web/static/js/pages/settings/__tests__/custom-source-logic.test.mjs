// TASK-165-T8: 自訂來源前端純邏輯（狀態→點／文案、失敗句只講第一條）。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const {
  customStatusToProbeState, customStatusIcon, customStatusKey,
  mismatchVerbKey, formatVerifiedAt, pickFirstMismatch, describeCustomLine,
} = await import('../custom-source-logic.js');
const { PROBE_ICON_MAP } = await import('../source-probe-logic.js');

const P = 'settings.sources.';

const TWO_CASES = () => ({
  total: 2,
  failed: 2,
  cases: [
    {
      index: 1, number: 'AAA-001', passed: false,
      mismatches: [
        { key: 'title_contains', expected: 'XA', actual: 'YA', url: 'http://a/1' },
        { key: 'tags_max', expected: 3, actual: 5, url: 'http://a/2' },
      ],
    },
    {
      index: 2, number: 'BBB-002', passed: false,
      mismatches: [
        { key: 'status', expected: 'ok', actual: 'not_found', url: 'http://b/1' },
        { key: 'title', expected: 'PC', actual: 'QC', url: 'http://b/2' },
      ],
    },
  ],
});

const recorder = () => {
  const calls = [];
  const t = (k, p) => { calls.push([k, p]); return k; };
  return { calls, t };
};

test('customStatusToProbeState maps the five statuses', () => {
  assert.strictEqual(customStatusToProbeState('passed'), 'ok');
  assert.strictEqual(customStatusToProbeState('failed'), 'blocked');
  assert.strictEqual(customStatusToProbeState('load_failed'), 'unreachable');
  assert.strictEqual(customStatusToProbeState('unverified'), 'skipped');
  assert.strictEqual(customStatusToProbeState('verifying'), null);
  assert.strictEqual(customStatusToProbeState('bogus'), null);
});


test('describeCustomLine failed names the first mismatch and appends the remaining count', () => {
  const { calls, t } = recorder();
  const when = new Date(2026, 9, 10, 14, 32).getTime() / 1000;
  const out = describeCustomLine({ status: 'failed', verified_at: when, last_result: TWO_CASES() }, t);
  const keys = calls.map((c) => c[0]);
  assert.equal(keys[0], P + 'custom_verb_contains');
  assert.ok(keys.includes(P + 'custom_line_failed'));
  const line = calls.find((c) => c[0] === P + 'custom_line_failed')[1];
  assert.equal(line.n, 1);
  assert.equal(line.number, 'AAA-001');
  assert.equal(line.key, 'title_contains');
  assert.equal(line.expected, 'XA');
  assert.equal(line.actual, 'YA');
  assert.equal(line.time, '10/10 14:32');
  assert.equal(line.verb, P + 'custom_verb_contains');
  const more = calls.filter((c) => c[0] === P + 'custom_line_more');
  assert.equal(more.length, 1);
  assert.equal(more[0][1].count, 3);
  assert.equal(out, P + 'custom_line_failed' + P + 'custom_line_more');
});


