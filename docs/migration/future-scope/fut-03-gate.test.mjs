import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const doc = readFileSync(new URL('./fut-03-ai-call-recording.md', import.meta.url), 'utf8');

test('declares out-of-scope for MVP', () => {
  assert.ok(doc.includes('out-of-scope-with-reason'));
  assert.ok(doc.includes('不计 MVP DoD') || doc.includes('不计MVP DoD'));
});
test('MVP UI must not claim delivery', () => { assert.ok(doc.includes('不得声明已交付')); });
test('default off with separate change gate', () => {
  assert.ok(doc.includes('默认关闭'));
  assert.ok(doc.includes('另立 change'));
});
test('owner assigned per sub-item', () => {
  assert.ok(doc.includes('owner'));
  assert.ok(doc.includes('合规'));
});
test('gate covers consent', () => { assert.ok(doc.includes('同意')); });
test('gate covers retention', () => { assert.ok(doc.includes('留存')); });
test('gate covers redaction', () => { assert.ok(doc.includes('脱敏')); });
test('gate covers vendor', () => { assert.ok(doc.includes('供应商')); });
test('gate covers human review', () => { assert.ok(doc.includes('人工复核')); });
