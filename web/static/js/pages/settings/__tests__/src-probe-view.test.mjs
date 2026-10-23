// TASK-163b-T4b: 狀態點／原因句的檢視純函式與分片方法（fake this 用 mergeState 建，getter 才會活）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
window.t = (k, p) => k + (p ? JSON.stringify(p) : '');

register(
  new URL('../../search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);

const logic = await import('../source-probe-logic.js');
const { REASON_KEY_MAP } = logic;
const { stateSourceProbe } = await import('../state-source-probe.js');
const { mergeState } = await import('@/shared/merge-state.js');

const EXPECTED_ICON = {
  ok: 'bi-check-circle-fill',
  blocked: 'bi-exclamation-triangle-fill',
  unreachable: 'bi-x-octagon-fill',
  skipped: 'bi-dash-circle',
};


function makeFake(results = {}) {
  const form = { proxyUrl: 'http://p:1', proxyScope: 'dmm' };
  const sources = [
    { id: 'dmm', display_name: 'DMM', enabled: true },
    { id: 'javlibrary', display_name: 'JavLibrary', enabled: false, manual_only: true },
  ];
  const fake = mergeState({ form, sources, showToast() {} }, stateSourceProbe());
  fake.srcProbeResults = results;
  return { fake, form, sources };
}

test('srcProbeLine and srcProbeIcon compose the view for one pill', () => {
  const { fake } = makeFake({
    dmm: { state: 'blocked', reason: 'http_status', advice: 'jp_ip' },
    javlibrary: { state: 'skipped', reason: 'windows_verifier' },
  });
  assert.equal(fake.srcProbeLine('nobody'), '');
  assert.equal(fake.srcProbeIcon('nobody'), '');
  const line = fake.srcProbeLine('dmm');
  assert.ok(line.includes('settings.sources.probe_state_blocked'));
  assert.ok(line.includes('settings.sources.probe_reason_http_status'));
  assert.ok(line.includes('settings.sources.probe_advice_jp_ip'));
  const skipLine = fake.srcProbeLine('javlibrary');
  assert.ok(!skipLine.includes('probe_advice'));
  assert.equal(fake.srcProbeIcon('dmm'), 'bi ' + EXPECTED_ICON.blocked);
  assert.notEqual(fake.srcProbeIcon('javlibrary'), 'bi ' + EXPECTED_ICON.unreachable);
  assert.equal(fake.srcProbeIcon('javlibrary'), 'bi ' + EXPECTED_ICON.skipped);
});


