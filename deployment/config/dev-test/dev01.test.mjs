import test from 'node:test';
import assert from 'node:assert/strict';
import { validateConfig, readiness } from './validate.mjs';
const good = () => ({ appBackend: 'mapp-sandbox', wishBackend: 'wish-mock', db: 'wish-synthetic', commerce: 'mer-mock' });
test('good synthetic config passes', () => { assert.equal(validateConfig(good()).ok, true); });
test('missing field fail-closed', () => { const r = validateConfig({}); assert.equal(r.ok, false); });
test('production address rejected', () => {
  const c = good(); c.db = 'wish-production';
  const r = validateConfig(c); assert.equal(r.ok, false);
});
test('secret inside file rejected', () => {
  const c = good(); c.commerce = 'token: "sk-abcdef123456"';
  const r = validateConfig(c); assert.equal(r.ok, false);
});
test('readiness marks unknown as sandbox', () => {
  const r = readiness({ mapp: 'x', wish: '' }); assert.equal(r.mapp, 'ready'); assert.equal(r.wish, 'sandbox');
});
test('no real endpoint in matrix', async () => {
  const { readFileSync } = await import('node:fs');
  const m = readFileSync(new URL('./env-matrix.md', import.meta.url), 'utf8');
  assert.ok(!m.includes('59.46.179.'));
});
