// DEV-02 compat adapter 检查：历史路由 allowlist + 只读 + fail-closed。
export const ALLOWLIST = [
  '/pages/legacy/home',
  '/pages/legacy/profile',
  '/pages/legacy/orders',
];
const WRITE_HINTS = ['POST', 'write', 'ledger', 'payment', 'token-issue'];

export function checkRoute(route) {
  if (typeof route !== 'string' || !ALLOWLIST.includes(route)) {
    return { ok: false, fallback: 'app-native', reason: 'route not in allowlist' };
  }
  return { ok: true, backend: 'MAPP server', mode: 'read-only' };
}

export function checkAdapterDecl(decl) {
  const errors = [];
  if (!decl || typeof decl !== 'object') return { ok: false, errors: ['decl must be an object'] };
  const r = checkRoute(decl.route);
  if (!r.ok) errors.push(r.reason);
  const blob = JSON.stringify(decl);
  for (const h of WRITE_HINTS) if (blob.includes(h)) { errors.push('write op in compat adapter: ' + h); break; }
  if (decl.buildMatrix === true) errors.push('compat adapter must not enter build matrix');
  return { ok: errors.length === 0, errors };
}
