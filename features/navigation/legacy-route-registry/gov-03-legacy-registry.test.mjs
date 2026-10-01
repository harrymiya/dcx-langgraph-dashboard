// GOV-03 task-specific acceptance tests (node:test, no external deps).
// Covers: home, appointment/order, payment, share, WebView, staff entry —
// param roundtrip, unauthenticated recovery, invalid-link rejection, legacy fallback.
// Usage: node --test features/navigation/legacy-route-registry/gov-03-legacy-registry.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = dirname(fileURLToPath(import.meta.url));
const reg = JSON.parse(readFileSync(join(dir, 'legacy-route-registry.json'), 'utf-8'));
const byId = new Map(reg.routes.map((r) => [r.mp_id, r]));

// ---- Minimal rule engine mirroring registry global_rules (test double) ----
const ALLOWLIST_HOSTS = new Set(['app.native', 'mapp.local', 'live.allowlisted.example']);
const FORBIDDEN_LINK_KEYS = ['token', 'id_token', 'access_token', 'health_data', 'healthData', 'payment_credential', 'password'];
const VALID_SCENES = new Set(['home-scene-1', 'goods-share-1', 'live-allow-1']);

function buildLink(legacyRoute, params = {}) {
  for (const k of Object.keys(params)) {
    if (FORBIDDEN_LINK_KEYS.includes(k)) throw new Error(`forbidden key in link: ${k}`);
  }
  const qs = new URLSearchParams(params).toString();
  return qs ? `${legacyRoute}?${qs}` : legacyRoute;
}

function parseLink(link) {
  const [route, qs = ''] = link.split('?');
  return { route, query: Object.fromEntries(new URLSearchParams(qs)) };
}

function resolveLink(link, ctx = {}) {
  // ctx: { loggedIn, staffSession, origin, sceneExpired }
  const { route, query } = parseLink(link);
  const entry = reg.routes.find((r) => r.legacy_route === route || r.legacy_alias === route);
  if (!entry) return { ok: false, code: 'UNKNOWN_ROUTE', fallback: 'app-native-home' };
  if (ctx.origin && !ALLOWLIST_HOSTS.has(ctx.origin)) {
    return { ok: false, code: 'ORIGIN_NOT_ALLOWLISTED', fallback: 'app-native-page' };
  }
  for (const k of Object.keys(query)) {
    if (FORBIDDEN_LINK_KEYS.includes(k)) {
      return { ok: false, code: 'SENSITIVE_KEY_IN_LINK', fallback: 'app-native-page' };
    }
  }
  if (query.scene && (VALID_SCENES.has(query.scene) === false || ctx.sceneExpired)) {
    return { ok: false, code: 'EXPIRED_SCENE', fallback: 'app-native-page' };
  }
  if (entry.capabilities.webview) {
    const host = query.host || ctx.origin || '';
    if (!ALLOWLIST_HOSTS.has(host)) {
      return { ok: false, code: 'WEBVIEW_HOST_NOT_ALLOWLISTED', fallback: 'app-native-page' };
    }
    if (query.token || query.raw_token) {
      return { ok: false, code: 'RAW_TOKEN_INJECTION', fallback: 'app-native-page' };
    }
  }
  if (entry.capabilities.staff_workbench && !ctx.staffSession) {
    return { ok: false, code: 'STAFF_SESSION_REQUIRED', fallback: 'app-native-page' };
  }
  if (entry.requires_login && !ctx.loggedIn && !ctx.staffSession) {
    return { ok: false, code: 'LOGIN_REQUIRED_STORE_PENDING', pending: link, fallback: 'app-login' };
  }
  return { ok: true, code: 'RESOLVED', mp_id: entry.mp_id, query, fallback: null };
}

function recoverPending(pending, session) {
  // session: { loggedIn, revoked, expired, replayed } — fail closed on any bad state.
  if (!pending) return { ok: false, code: 'NO_PENDING', fallback: 'app-native-page' };
  if (!session?.loggedIn || session.revoked || session.expired || session.replayed) {
    return { ok: false, code: 'RECOVERY_FAIL_CLOSED', fallback: 'app-login' };
  }
  return { ...resolveLink(pending, { loggedIn: true, staffSession: session.staffSession }), recovered: true };
}

function fallbackFor(mpId, flagOn) {
  const entry = byId.get(mpId);
  if (!flagOn) return { target: entry.legacy_alias, via: 'legacy-alias' };
  const migrated = entry.dag_task_id !== null;
  if (migrated) return { target: entry.migration_target, via: 'app-center-route' };
  return { target: entry.legacy_alias, via: 'audited-short-term-adapter-or-safe-external-link' };
}

// ---- Registry integrity ----
test('registry holds 163 unique routes with alias identity', () => {
  assert.equal(reg.routes.length, 163);
  assert.equal(new Set(reg.routes.map((r) => r.mp_id)).size, 163);
  assert.equal(new Set(reg.routes.map((r) => r.legacy_route)).size, 163);
  for (const r of reg.routes) assert.equal(r.legacy_alias, r.legacy_route);
});

test('verification representatives exist with expected identities', () => {
  assert.equal(byId.get('MP002')?.legacy_route, '/pages/index/index');
  assert.equal(byId.get('MP062')?.legacy_route, '/pages/goods/order_list/index');
  assert.equal(byId.get('MP065')?.legacy_route, '/pages/goods/order_payment/index');
  assert.equal(byId.get('MP052')?.legacy_route, '/pages/goods/goods_details/index');
  assert.equal(byId.get('MP006')?.legacy_route, '/pages/webview/webview');
  assert.equal(byId.get('MP143')?.legacy_route, '/pages/admin/order/index');
  assert.equal(byId.get('MP143')?.dag_task_id, null);
});

// ---- Param roundtrip ----
test('home param roundtrip (guest readable)', () => {
  const link = buildLink('/pages/index/index', { scene: 'home-scene-1', source: 'home-banner', activity_id: 'a1', content_id: 'c1' });
  const res = resolveLink(link, { loggedIn: false, origin: 'app.native' });
  assert.equal(res.ok, true);
  assert.equal(res.query.scene, 'home-scene-1');
  assert.equal(res.query.source, 'home-banner');
});

test('appointment/order param roundtrip + login recovery', () => {
  const link = buildLink('/pages/goods/order_list/index', { order_id: 'o123', source: 'notice', activity_id: 'a9' });
  const unauth = resolveLink(link, { loggedIn: false, origin: 'app.native' });
  assert.equal(unauth.ok, false);
  assert.equal(unauth.code, 'LOGIN_REQUIRED_STORE_PENDING');
  const recovered = recoverPending(unauth.pending, { loggedIn: true });
  assert.equal(recovered.ok, true);
  assert.equal(recovered.query.order_id, 'o123');
});

test('payment param roundtrip, server-verify note, no token in link', () => {
  const link = buildLink('/pages/goods/order_payment/index', { order_id: 'o123', amount: '100' });
  const res = resolveLink(link, { loggedIn: true, origin: 'app.native' });
  assert.equal(res.ok, true);
  assert.equal(res.query.order_id, 'o123');
  assert.throws(() => buildLink('/pages/goods/order_payment/index', { order_id: 'o1', token: 't' }), /forbidden key/);
  const e = byId.get('MP065');
  assert.match(e.auth_backend, /服务端核对/);
});

test('share attribution roundtrip without token/health data', () => {
  const link = buildLink('/pages/goods/goods_details/index', { goods_id: 'g1', scene: 'goods-share-1', source: 'share', activity_id: 'a2', content_id: 'c2' });
  const res = resolveLink(link, { loggedIn: false, origin: 'app.native' });
  assert.equal(res.ok, true);
  assert.equal(res.query.scene, 'goods-share-1');
  assert.throws(() => buildLink('/pages/goods/goods_details/index', { goods_id: 'g1', health_data: 'x' }), /forbidden key/);
});

test('webview allowlist only, no raw token injection', () => {
  const good = buildLink('/pages/webview/webview', { host: 'live.allowlisted.example', scene: 'live-allow-1' });
  assert.equal(resolveLink(good, { loggedIn: false, origin: 'live.allowlisted.example' }).ok, true);
  const badHost = buildLink('/pages/webview/webview', { host: 'evil.example' });
  assert.equal(resolveLink(badHost, { origin: 'evil.example' }).code, 'ORIGIN_NOT_ALLOWLISTED');
  assert.equal(resolveLink(badHost, { origin: 'app.native' }).code, 'WEBVIEW_HOST_NOT_ALLOWLISTED');
});

test('staff entry retains existing entry, requires staff session, no APP migration', () => {
  const link = buildLink('/pages/admin/order/index', { order_id: 's1' });
  const noSession = resolveLink(link, { loggedIn: true, origin: 'app.native' });
  assert.equal(noSession.code, 'STAFF_SESSION_REQUIRED');
  const withSession = resolveLink(link, { loggedIn: true, staffSession: true, origin: 'app.native' });
  assert.equal(withSession.ok, true);
  assert.equal(withSession.query.order_id, 's1');
});

// ---- Invalid-link rejection ----
test('invalid links rejected fail-closed', () => {
  assert.equal(resolveLink('/pages/unknown/route', {}).code, 'UNKNOWN_ROUTE');
  assert.equal(resolveLink('/pages/index/index?scene=home-scene-1', { origin: 'evil.example' }).code, 'ORIGIN_NOT_ALLOWLISTED');
  assert.equal(resolveLink('/pages/index/index?token=abc', {}).code, 'SENSITIVE_KEY_IN_LINK');
  assert.equal(resolveLink('/pages/goods/goods_details/index?goods_id=g1&scene=stale', { sceneExpired: true }).code, 'EXPIRED_SCENE');
  const badRecovery = recoverPending('/pages/goods/order_list/index?order_id=o1', { loggedIn: false });
  assert.equal(badRecovery.code, 'RECOVERY_FAIL_CLOSED');
  const replayed = recoverPending('/pages/goods/order_list/index?order_id=o1', { loggedIn: true, replayed: true });
  assert.equal(replayed.code, 'RECOVERY_FAIL_CLOSED');
});

// ---- Legacy fallback ----
test('flag-off falls back to legacy alias; history-only via audited adapter', () => {
  assert.deepEqual(fallbackFor('MP002', false), { target: '/pages/index/index', via: 'legacy-alias' });
  assert.deepEqual(fallbackFor('MP065', false).via, 'legacy-alias');
  assert.deepEqual(fallbackFor('MP143', true), {
    target: '/pages/admin/order/index',
    via: 'audited-short-term-adapter-or-safe-external-link',
  });
  const migrated = fallbackFor('MP052', true);
  assert.equal(migrated.via, 'app-center-route');
});

// ---- Lane / ownership guards ----
test('lane, ownership and no-write-master-change guards', () => {
  assert.equal(reg.lane, 'legacy-compatibility-fallback');
  assert.equal(reg.ownership.single_writer, 'GOV-03');
  assert.equal(reg.ownership.center_registration.includes('FND-03'), true);
  assert.match(reg.global_rules.no_write_master_change, /write-master/i);
  assert.match(reg.global_rules.third_party_excluded, /third-party/i);
  assert.match(reg.global_rules.login_recovery, /IDN-01/);
});
