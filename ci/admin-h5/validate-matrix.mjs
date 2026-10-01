// DEV-02 H5 矩阵校验：来源 SHA/Node 可复现，拒绝 APP 壳关键字与生产指向。
export const TOOLCHAIN = { node: '20.18.0' };
const SHA40 = /^[0-9a-f]{40}$/;
const FORBIDDEN = ['prod', 'production', 'apk', 'ipa', 'xcode', 'gradle', 'mp-weixin', 'miniapp'];

export function validateEntry(e) {
  const errors = [];
  if (!e || typeof e !== 'object') return { ok: false, errors: ['entry must be an object'] };
  if (e.platform !== 'h5') errors.push('unknown platform: ' + e.platform);
  if (!['dev', 'test'].includes(e.env)) errors.push('unknown env: ' + e.env);
  if (typeof e.sourceSHA !== 'string' || !SHA40.test(e.sourceSHA)) errors.push('sourceSHA must be 40-hex');
  if (e.toolchain && e.toolchain.node !== undefined && e.toolchain.node !== TOOLCHAIN.node) {
    errors.push('node must pin ' + TOOLCHAIN.node);
  }
  const blob = JSON.stringify(e);
  for (const h of FORBIDDEN) if (blob.includes(h)) { errors.push('forbidden token: ' + h); break; }
  return { ok: errors.length === 0, errors };
}

export function matrixKey(e) {
  const v = validateEntry(e);
  if (!v.ok) throw new Error('invalid matrix entry: ' + v.errors.join('; '));
  return ['h5', e.env, e.sourceSHA, JSON.stringify(TOOLCHAIN)].join('|');
}
