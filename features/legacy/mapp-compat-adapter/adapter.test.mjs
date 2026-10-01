import test from 'node:test';
import assert from 'node:assert/strict';
import { checkRoute, checkAdapterDecl } from './adapter-check.mjs';

test('allowlisted route passes read-only', () => {
  const r = checkRoute('/pages/legacy/home');
  assert.equal(r.ok, true);
  assert.equal(r.backend, 'MAPP server');
});
test('unknown route fail-closed to app-native', () => {
  const r = checkRoute('/pages/shop/checkout');
  assert.equal(r.ok, false);
  assert.equal(r.fallback, 'app-native');
});
test('write op rejected', () => {
  assert.equal(checkAdapterDecl({ route: '/pages/legacy/orders', method: 'POST' }).ok, false);
});
test('build matrix entry rejected', () => {
  assert.equal(checkAdapterDecl({ route: '/pages/legacy/profile', buildMatrix: true }).ok, false);
});
test('good decl passes', () => {
  assert.equal(checkAdapterDecl({ route: '/pages/legacy/profile' }).ok, true);
});
