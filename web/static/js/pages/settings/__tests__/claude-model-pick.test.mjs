// TASK-170-T5: pickClaudeModel 規則六格（CD-170-8）

import { test } from 'node:test';
import assert from 'node:assert/strict';

const { pickClaudeModel } = await import('../claude-model-pick.js');

const MODELS = ['claude-sonnet-5-5', 'claude-haiku-5-6', 'claude-haiku-5-5'];
const DEFAULT = 'claude-haiku-5-5';
const LATEST = 'claude-haiku-5-6';


test('replaces_hardcoded_default_with_latest_haiku', () => {
  // 假綠陷阱：預設仍在清單內、latestHaiku 是另一個 id
  assert.equal(
    pickClaudeModel(DEFAULT, MODELS, LATEST, DEFAULT),
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


