import test from 'node:test';
import assert from 'node:assert/strict';
import { validateEntry, matrixKey } from './validate-matrix.mjs';

const SHA = 'a'.repeat(40);
const good = (o = {}) => ({ platform: 'ios', env: 'dev', sourceSHA: SHA, toolchain: { xcode: '15.4', runner: 'macos-14' }, ...o });

test('good ios entry passes', () => { assert.equal(validateEntry(good()).ok, true); });
test('good android entry passes', () => {
  const r = validateEntry({ platform: 'android', env: 'test', sourceSHA: 'b'.repeat(40), toolchain: { jdk: '17', gradle: '8.7', agp: '8.5.2', runner: 'ubuntu-24.04' } });
  assert.equal(r.ok, true);
});
test('bad SHA fail-closed', () => { assert.equal(validateEntry(good({ sourceSHA: 'abc' })).ok, false); });
test('unknown platform rejected', () => { assert.equal(validateEntry(good({ platform: 'harmony' })).ok, false); });
test('production signing rejected', () => { assert.equal(validateEntry(good({ profile: 'distribution-prod' })).ok, false); });
test('miniapp side rejected from app matrix', () => { assert.equal(validateEntry(good({ platform: 'ios', extra: 'mp-weixin' })).ok, false); });
test('matrix key reproducible (idempotent)', () => {
  assert.equal(matrixKey(good()), matrixKey(good()));
  assert.notEqual(matrixKey(good()), matrixKey(good({ env: 'test' })));
});
test('no prod host in matrix doc', async () => {
  const { readFileSync } = await import('node:fs');
  const m = readFileSync(new URL('./build-matrix.md', import.meta.url), 'utf8');
  assert.ok(m.includes('mermaid') === false); // doc-first contract, no diagram claim
  assert.ok(!m.includes('59.46.179.'));
});
