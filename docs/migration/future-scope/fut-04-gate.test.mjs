import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const doc = readFileSync(new URL('./fut-04-travel-rehab.md', import.meta.url), 'utf8');

test('declares future scope outside MVP', () => {
  assert.ok(doc.includes('out-of-scope-with-reason'));
  assert.ok(doc.includes('不计 MVP DoD'));
});

test('covers hotel and PMS boundary', () => {
  assert.ok(doc.includes('酒店/PMS'));
  assert.ok(doc.includes('独立商务与合规评估'));
});

test('covers professional rehabilitation boundary', () => {
  assert.ok(doc.includes('医疗/专业康复'));
  assert.ok(doc.includes('医疗资质 owner 确认'));
});

test('future capabilities are not MVP entry points', () => {
  assert.ok(doc.includes('后续能力零出现在本期入口'));
  assert.ok(doc.includes('pages/health/'));
});

test('tenant/site isolation remains an MVP acceptance item', () => {
  assert.ok(doc.includes('tenant/site'));
  assert.ok(doc.includes('两站'));
  assert.ok(doc.includes('site-a/site-b'));
});

test('future capability data needs independent consent', () => {
  assert.ok(doc.includes('独立授权'));
  assert.ok(doc.includes('crm_consent_record'));
});

test('default-off rollback is defined', () => {
  assert.ok(doc.includes('默认关闭'));
  assert.ok(doc.includes('另立 change'));
});
