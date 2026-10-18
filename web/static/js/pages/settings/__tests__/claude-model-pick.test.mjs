// TASK-170-T5: pickClaudeModel 規則六格（CD-170-8）

import { test } from 'node:test';
import assert from 'node:assert/strict';

const { pickClaudeModel } = await import('../claude-model-pick.js');

const MODELS = ['claude-sonnet-5-5', 'claude-haiku-5-6', 'claude-haiku-5-5'];
const DEFAULT = 'claude-haiku-5-5';
const LATEST = 'claude-haiku-5-6';

test('returns_latest_haiku_when_current_empty', () => {
  assert.equal(
    pickClaudeModel('', MODELS, LATEST, DEFAULT),
    LATEST,
  );
});

test('replaces_hardcoded_default_with_latest_haiku', () => {
  // 假綠陷阱：預設仍在清單內、latestHaiku 是另一個 id
  assert.equal(
    pickClaudeModel(DEFAULT, MODELS, LATEST, DEFAULT),
    LATEST,
  );
});

test('replaces_model_not_in_list_with_latest_haiku', () => {
  assert.equal(
    pickClaudeModel('claude-opus-ghost', MODELS, LATEST, DEFAULT),
    LATEST,
  );
});

test('keeps_user_selected_model_still_in_list', () => {
  // 假綠陷阱：latestHaiku ≠ current，否則拿掉保留分支不會紅
  assert.equal(
    pickClaudeModel('claude-sonnet-5-5', MODELS, LATEST, DEFAULT),
    'claude-sonnet-5-5',
  );
});

test('keeps_current_when_models_empty', () => {
  assert.equal(
    pickClaudeModel('claude-sonnet-5-5', [], LATEST, DEFAULT),
    'claude-sonnet-5-5',
  );
});

test('falls_back_to_first_model_when_no_haiku', () => {
  const onlySonnet = ['claude-sonnet-5-5', 'claude-opus-4'];
  assert.equal(
    pickClaudeModel('', onlySonnet, '', DEFAULT),
    'claude-sonnet-5-5',
  );
});
