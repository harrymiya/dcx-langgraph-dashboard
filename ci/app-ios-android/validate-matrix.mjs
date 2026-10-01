// DEV-02 APP 矩阵校验：来源 SHA/工具链可复现 + 目标平台限制。坏输入一律 fail-closed。
export const TOOLCHAINS = {
  ios: { xcode: '15.4', runner: 'macos-14' },
  android: { jdk: '17', gradle: '8.7', agp: '8.5.2', runner: 'ubuntu-24.04' },
};
const SHA40 = /^[0-9a-f]{40}$/;
const PLATFORMS = ['ios', 'android'];
const ENVS = ['dev', 'test'];
const FORBIDDEN = ['prod', 'production', 'release-sign', 'distribution', 'mp-weixin', 'miniapp'];

export function validateEntry(e) {
  const errors = [];
  if (!e || typeof e !== 'object') return { ok: false, errors: ['entry must be an object'] };
  if (!PLATFORMS.includes(e.platform)) errors.push('unknown platform: ' + e.platform);
  if (!ENVS.includes(e.env)) errors.push('unknown env: ' + e.env);
  if (typeof e.sourceSHA !== 'string' || !SHA40.test(e.sourceSHA)) errors.push('sourceSHA must be 40-hex');
  const blob = JSON.stringify(e);
  for (const h of FORBIDDEN) if (blob.includes(h)) { errors.push('forbidden token: ' + h); break; }
  const tc = TOOLCHAINS[e.platform];
  if (tc && e.toolchain) {
    for (const [k, v] of Object.entries(tc)) {
      if (e.toolchain[k] !== undefined && e.toolchain[k] !== v) errors.push(`toolchain ${k} must pin ${v}`);
    }
  }
  return { ok: errors.length === 0, errors };
}

export function matrixKey(e) {
  // 同一 sourceSHA + toolchain + platform + env → 相同矩阵键（幂等）。
  const v = validateEntry(e);
  if (!v.ok) throw new Error('invalid matrix entry: ' + v.errors.join('; '));
  const tc = TOOLCHAINS[e.platform];
  return [e.platform, e.env, e.sourceSHA, JSON.stringify(tc)].join('|');
}
