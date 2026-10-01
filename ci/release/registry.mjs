// DEV-03 registry 校验：制品完整 + 版本对应 + 测试部署失败恢复。坏输入一律 fail-closed。
const SHA40 = /^[0-9a-f]{40}$/;
const ENVS = ['dev', 'test'];
const FORBIDDEN = ['prod', 'production', 'distribution', 'release-sign', '59.46.179.'];
const SECRET_RE = /sk-|pk-|token["']?\s*:\s*["'][A-Za-z0-9]{8,}/;

export function validateArtifact(a) {
  const errors = [];
  if (!a || typeof a !== 'object') return { ok: false, errors: ['artifact must be an object'] };
  if (typeof a.name !== 'string' || a.name.length === 0) errors.push('name missing');
  if (!ENVS.includes(a.env)) errors.push('env must be dev/test, got: ' + a.env);
  if (typeof a.sourceSHA !== 'string' || !SHA40.test(a.sourceSHA)) errors.push('sourceSHA must be 40-hex');
  if (typeof a.schemaVersion !== 'string' || a.schemaVersion.length === 0) errors.push('schemaVersion missing');
  if (typeof a.configVersion !== 'string' || a.configVersion.length === 0) errors.push('configVersion missing');
  if (typeof a.matrixKey !== 'string' || !a.matrixKey.includes(a.sourceSHA)) errors.push('matrixKey must correspond to sourceSHA');
  if (!a.signature || a.signature.scheme !== 'test-sha256') errors.push('signature must be test-only test-sha256');
  const blob = JSON.stringify(a);
  for (const h of FORBIDDEN) if (blob.includes(h)) { errors.push('forbidden token: ' + h); break; }
  if (SECRET_RE.test(blob)) errors.push('secret material inside registry entry');
  return { ok: errors.length === 0, errors };
}

export function preflight(job) {
  // migration 先 preflight/backup；只做契约检查，不连真实库。
  const errors = [];
  if (!job || typeof job !== 'object') return { ok: false, errors: ['job must be an object'] };
  if (!ENVS.includes(job.env)) errors.push('deploy env must be dev/test');
  if (job.migration === true) {
    if (typeof job.backupRef !== 'string' || job.backupRef.length === 0) errors.push('migration requires backupRef');
  }
  return { ok: errors.length === 0, errors };
}

export function deploy(registry, artifact, opts = {}) {
  // registry: 已登记制品数组（按登记顺序）；返回 { ok, registry, rolledBack }。
  const v = validateArtifact(artifact);
  const pf = preflight({ env: artifact?.env, migration: opts.migration === true, backupRef: opts.backupRef });
  if (!v.ok) return { ok: false, errors: v.errors, registry, rolledBack: null };
  if (!pf.ok) return { ok: false, errors: pf.errors, registry, rolledBack: null };
  const next = [...registry, { ...artifact, status: 'deployed' }];
  if (opts.fail === true) {
    // 部署失败：回退到上一件同 env 制品。
    const prev = [...registry].reverse().find(a => a.env === artifact.env);
    const marked = next.map(a => (a.name === artifact.name ? { ...a, status: 'failed' } : a));
    if (prev) {
      return {
        ok: false, errors: ['deploy failed (synthetic)'], registry: marked, rolledBack: prev.name,
        note: prev.dbRollback ? 'db rollback deferred: DB-06' : 'rolled back to previous staging artifact',
      };
    }
    return { ok: false, errors: ['deploy failed, no previous artifact'], registry: marked, rolledBack: null };
  }
  return { ok: true, registry: next, rolledBack: null };
}
