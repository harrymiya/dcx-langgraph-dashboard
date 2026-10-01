import test from 'node:test';
import assert from 'node:assert/strict';
import { validateArtifact, preflight, deploy } from './registry.mjs';

const SHA = 'd'.repeat(40);
const good = (o = {}) => ({
  name: 'wish-app-dev-001', env: 'dev', sourceSHA: SHA,
  schemaVersion: 'canonical-1', configVersion: 'dev-test-1',
  matrixKey: `android|dev|${SHA}|{toolchain}`, signature: { scheme: 'test-sha256' }, ...o,
});

test('complete artifact passes', () => { assert.equal(validateArtifact(good()).ok, true); });
test('missing version fail-closed', () => { assert.equal(validateArtifact(good({ schemaVersion: '' })).ok, false); });
test('matrixKey must correspond to sourceSHA', () => {
  assert.equal(validateArtifact(good({ matrixKey: 'android|dev|' + 'e'.repeat(40) + '|{}' })).ok, false);
});
test('production env rejected', () => { assert.equal(validateArtifact(good({ env: 'production' })).ok, false); });
test('production signature rejected', () => {
  assert.equal(validateArtifact(good({ signature: { scheme: 'distribution' } })).ok, false);
});
test('secret inside entry rejected', () => {
  assert.equal(validateArtifact(good({ note: 'token: "sk-abcdef123456"' })).ok, false);
});
test('migration without backup blocked by preflight', () => {
  assert.equal(preflight({ env: 'dev', migration: true }).ok, false);
  assert.equal(preflight({ env: 'dev', migration: true, backupRef: 'snap-001' }).ok, true);
});
test('failed deploy rolls back to previous staging artifact', () => {
  const r1 = deploy([], good());
  assert.equal(r1.ok, true);
  const r2 = deploy(r1.registry, good({ name: 'wish-app-dev-002' }), { fail: true });
  assert.equal(r2.ok, false);
  assert.equal(r2.rolledBack, 'wish-app-dev-001');
});
test('registry doc has no prod hosts', async () => {
  const { readFileSync } = await import('node:fs');
  const m = readFileSync(new URL('./artifact-registry.md', import.meta.url), 'utf8');
  assert.ok(m.includes('preflight'));
  assert.ok(!m.includes('59.46.179.'));
});
