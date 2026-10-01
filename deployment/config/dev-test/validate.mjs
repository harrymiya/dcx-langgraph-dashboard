// DEV-01 配置校验：fail-closed。坏配置/生产地址/文件内 secret 一律拒绝。
const PROD_HINTS = ['prod', 'production', '59.46.179.'];
export function validateConfig(cfg) {
  const errors = [];
  if (!cfg || typeof cfg !== 'object') return { ok: false, errors: ['config must be an object'] };
  for (const k of ['appBackend', 'wishBackend', 'db', 'commerce']) {
    const v = cfg[k] ?? '';
    if (typeof v !== 'string' || v.length === 0) { errors.push(k + ' missing'); continue; }
    if (PROD_HINTS.some(h => v.includes(h))) errors.push(k + ' points at production');
  }
  const blob = JSON.stringify(cfg);
  if (/sk-|pk-|token["']?\s*:\s*["'][A-Za-z0-9]{8,}/.test(blob)) errors.push('secret material inside config file');
  return { ok: errors.length === 0, errors };
}
export function readiness(deps) {
  // 合成 readiness：依赖名非空即就绪，未知依赖标记 sandbox。
  return Object.fromEntries(Object.entries(deps).map(([k, v]) => [k, v ? 'ready' : 'sandbox']));
}
