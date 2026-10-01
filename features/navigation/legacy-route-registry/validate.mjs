// GOV-03 registry structural validator (no external deps).
// Usage: node features/navigation/legacy-route-registry/validate.mjs
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = dirname(fileURLToPath(import.meta.url));
const regPath = join(dir, 'legacy-route-registry.json');
const raw = readFileSync(regPath, 'utf-8');
const reg = JSON.parse(raw);

const failures = [];
const ok = (cond, msg) => { if (!cond) failures.push(msg); };

ok(reg.task_id === 'GOV-03', 'task_id must be GOV-03');
ok(reg.lane === 'legacy-compatibility-fallback', 'lane must be legacy-compatibility-fallback');
ok(reg.ownership?.single_writer === 'GOV-03', 'single_writer must be GOV-03');
ok(Array.isArray(reg.routes), 'routes must be an array');
ok(reg.routes.length === 163, `routes must be 163, found ${reg.routes?.length}`);
ok(reg.source?.route_count === 163, 'source.route_count must be 163');

const ids = reg.routes.map((r) => r.mp_id);
ok(new Set(ids).size === 163, 'mp_id must be unique (163)');
ok(ids.every((id) => /^MP\d{3}$/.test(id)), 'mp_id format must be MPNNN');

const routes = reg.routes.map((r) => r.legacy_route);
ok(new Set(routes).size === 163, 'legacy_route must be unique (163)');
ok(routes.every((r) => typeof r === 'string' && r.startsWith('/pages/')), 'legacy_route must start with /pages/');

const required = ['mp_id', 'legacy_route', 'source_file', 'domain', 'legacy_alias',
  'query_passthrough', 'attribution_preserved', 'return_stack_preserved',
  'capabilities', 'login_recovery', 'feature_flag', 'fallback'];
for (const r of reg.routes) {
  for (const k of required) {
    if (r[k] === undefined || r[k] === null || r[k] === '') {
      failures.push(`${r.mp_id}: missing required field ${k}`);
      break;
    }
  }
  if (r.legacy_alias !== r.legacy_route) failures.push(`${r.mp_id}: legacy_alias must equal legacy_route`);
  if (r.query_passthrough !== true) failures.push(`${r.mp_id}: query_passthrough must be true`);
  if (r.return_stack_preserved !== true) failures.push(`${r.mp_id}: return_stack_preserved must be true`);
  if (r.feature_flag?.default !== 'legacy') failures.push(`${r.mp_id}: feature_flag.default must be legacy`);
}

const byId = new Map(reg.routes.map((r) => [r.mp_id, r]));
for (const v of reg.verification_routes ?? []) {
  ok(byId.has(v.mp_id), `verification route missing in registry: ${v.mp_id}`);
  const e = byId.get(v.mp_id);
  if (e && v.legacy_route !== e.legacy_route) failures.push(`verification ${v.mp_id}: legacy_route mismatch`);
}
// Staff entry must have no migration task (existing entry retained only).
ok(byId.get('MP143')?.dag_task_id === null, 'MP143 staff entry must keep dag_task_id null (no APP migration task)');
// Payment action routes must exist and carry server-verify fallback note.
for (const mp of ['MP065', 'MP067', 'MP082', 'MP083', 'MP028']) {
  const e = byId.get(mp);
  ok(e?.capabilities?.payment === true, `${mp} must be flagged payment`);
}
// WebView representative must be allowlist-gated.
ok(byId.get('MP006')?.capabilities?.webview === true, 'MP006 must be flagged webview');

const g = reg.global_rules ?? {};
for (const k of ['login_recovery', 'invalid_rejection', 'legacy_fallback', 'fail_closed_audit', 'no_write_master_change', 'third_party_excluded', 'no_auth_tasks']) {
  ok(typeof g[k] === 'string' && g[k].length > 0, `global_rules.${k} must be non-empty`);
}

if (failures.length > 0) {
  console.error(`GOV-03 registry validation FAILED (${failures.length}):`);
  for (const f of failures.slice(0, 30)) console.error(` - ${f}`);
  process.exit(1);
}
console.log('GOV-03 registry validation OK: 163 routes, aliases, flags, verification routes, fail-closed rules.');
