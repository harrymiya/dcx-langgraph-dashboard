import test from 'node:test';
import assert from 'node:assert/strict';
import { validateEntry, matrixKey } from './validate-matrix.mjs';

const SHA = 'c'.repeat(40);
const good = (o = {}) => ({ platform: 'h5', env: 'dev', sourceSHA: SHA, toolchain: { node: '20.18.0' }, ...o });

test('good h5 entry passes', () => { assert.equal(validateEntry(good()).ok, true); });
test('test env passes', () => { assert.equal(validateEntry(good({ env: 'test' })).ok, true); });
test('bad SHA fail-closed', () => { assert.equal(validateEntry(good({ sourceSHA: 'zzz' })).ok, false); });
test('app shell keywords rejected', () => { assert.equal(validateEntry(good({ artifact: 'app.apk' })).ok, false); });
test('production pointer rejected', () => { assert.equal(validateEntry(good({ api: 'https://production.internal' })).ok, false); });
test('matrix key reproducible', () => { assert.equal(matrixKey(good()), matrixKey(good())); });
test('no prod host in matrix doc', async () => {
  const { readFileSync } = await import('node:fs');
  const m = readFileSync(new URL('./build-matrix.md', import.meta.url), 'utf8');
  assert.ok(m.includes('H5'));
  assert.ok(!m.includes('59.46.179.'));
});
