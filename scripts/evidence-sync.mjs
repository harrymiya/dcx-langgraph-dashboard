const READY_STATUSES = new Set(["code-ready", "contract-ready"]);
const STATUS_RANK = new Map([
  ["planned", 0],
  ["in-progress", 1],
  ["blocked", 1],
  ["code-ready", 2],
  ["contract-ready", 3],
  ["release-ready", 4],
]);

function nonEmptyString(value, field) {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${field} 必须是非空字符串`);
  }
  return value.trim();
}

function optionalCommitMap(value) {
  if (value === undefined) return undefined;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("commits 必须是对象");
  }
  const result = {};
  for (const [project, commit] of Object.entries(value)) {
    const projectName = nonEmptyString(project, "commits 项目名");
    result[projectName] = nonEmptyString(commit, `commits.${projectName}`);
  }
  if (!Object.keys(result).length) throw new Error("commits 不能为空");
  return result;
}

function record(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${field} 必须是对象`);
  }
  return value;
}

function manifestEntry(manifest, taskId) {
  const root = record(manifest, "manifest");
  const entries = record(root.tasks, "manifest.tasks");
  return entries[taskId];
}

function latestEvidence(entry) {
  const evidence = Array.isArray(entry?.evidence) ? entry.evidence : [];
  for (let index = evidence.length - 1; index >= 0; index -= 1) {
    if (evidence[index] && typeof evidence[index] === "object" && !Array.isArray(evidence[index])) {
      return evidence[index];
    }
  }
  throw new Error("manifest 中没有可接收的 evidence");
}

function successfulChecks(evidence) {
  if (!Array.isArray(evidence.checks) || evidence.checks.length === 0) {
    throw new Error("evidence 缺少 checks");
  }
  for (const [index, check] of evidence.checks.entries()) {
    if (!check || typeof check !== "object" || Array.isArray(check)) {
      throw new Error(`evidence.checks[${index}] 必须是对象`);
    }
    nonEmptyString(check.command, `evidence.checks[${index}].command`);
    if (!Number.isInteger(check.exit)) {
      throw new Error(`evidence.checks[${index}].exit 必须是整数`);
    }
    if (check.exit !== 0) {
      throw new Error(`evidence.checks[${index}] 退出码为 ${check.exit}，不能同步`);
    }
  }
}

function taskMap(tasks) {
  if (!Array.isArray(tasks)) throw new Error("tasks.json 根节点必须是数组");
  return new Map(tasks.map((task) => [task?.id, task]));
}

function statusRank(status) {
  return STATUS_RANK.get(status) ?? -1;
}

export function reconcileEvidenceSnapshot({ tasks, manifest }) {
  if (!Array.isArray(tasks)) throw new Error("tasks.json 根节点必须是数组");
  const root = record(manifest, "manifest");
  const entries = record(root.tasks, "manifest.tasks");
  const updatedTasks = tasks.map((task) => {
    const entry = entries[task?.id];
    if (!entry || !task || typeof task !== "object") return task;
    const evidence = Array.isArray(entry.evidence) ? entry.evidence.filter((item) => item && typeof item === "object") : [];
    const latest = evidence[evidence.length - 1];
    const manifestStatus = entry.status ?? latest?.status;
    if (!READY_STATUSES.has(manifestStatus) || statusRank(manifestStatus) < statusRank(task.status)) return task;
    if (!latest || !Array.isArray(latest.checks) || latest.checks.some((check) => check?.exit !== 0)) return task;
    const commit = latest.commit ?? entry.commit ?? task.commit;
    const verifiedAt = latest.verified_at ?? entry.verified_at ?? task.verified_at;
    return {
      ...task,
      status: manifestStatus,
      status_source: "evidence-manifest",
      ...(commit ? { commit } : {}),
      ...(verifiedAt ? { verified_at: verifiedAt } : {}),
      evidence,
    };
  });
  return { tasks: updatedTasks, changed: JSON.stringify(updatedTasks) !== JSON.stringify(tasks) };
}

export function buildEvidenceUpdate({ tasks, manifest, payload }) {
  const input = record(payload, "请求体");
  const taskId = nonEmptyString(input.taskId, "taskId");
  const status = nonEmptyString(input.status, "status");
  if (!READY_STATUSES.has(status)) {
    throw new Error("只允许同步 code-ready 或 contract-ready");
  }

  const byId = taskMap(tasks);
  const currentTask = byId.get(taskId);
  if (!currentTask) throw new Error(`任务 ${taskId} 不存在于 dashboard task snapshot`);
  const currentStatus = typeof currentTask.status === "string" ? currentTask.status : "planned";
  if (statusRank(currentStatus) > statusRank(status)) {
    throw new Error(`不能把任务 ${taskId} 从 ${currentStatus} 降级为 ${status}`);
  }

  const dependencies = Array.isArray(currentTask.deps) ? currentTask.deps : [];
  for (const dependency of dependencies) {
    const dependencyTask = byId.get(dependency);
    if (!dependencyTask || !READY_STATUSES.has(dependencyTask.status) && dependencyTask.status !== "release-ready") {
      throw new Error(`任务 ${taskId} 的前置依赖 ${dependency} 尚未达到就绪状态`);
    }
  }

  const entry = manifestEntry(manifest, taskId);
  if (!entry) throw new Error(`manifest 没有任务 ${taskId} 的证据`);
  const evidence = latestEvidence(entry);
  successfulChecks(evidence);

  const commits = optionalCommitMap(evidence.commits ?? entry.commits ?? currentTask.commits);
  const commit = nonEmptyString(
    evidence.commit ?? entry.commit ?? currentTask.commit ?? (commits ? Object.values(commits)[0] : undefined),
    "commit",
  );
  const report = nonEmptyString(evidence.report ?? evidence.path, "evidence.report");
  const verifiedAt = nonEmptyString(
    evidence.verified_at ?? entry.verified_at ?? currentTask.verified_at,
    "verified_at",
  );

  const currentEvidence = Array.isArray(currentTask.evidence) ? currentTask.evidence : [];
  const syncedEvidence = {
    ...evidence,
    report,
    status,
    commit,
    ...(commits ? { commits } : {}),
    verified_at: verifiedAt,
  };
  const alreadySynced = currentEvidence.some(
    (item) =>
      item &&
      typeof item === "object" &&
      item.report === report &&
      item.commit === commit &&
      item.status === status,
  );
  const nextEvidence = alreadySynced ? currentEvidence : [...currentEvidence, syncedEvidence];
  const nextTask = {
    ...currentTask,
    status,
    status_source: "evidence-manifest",
    verified_at: verifiedAt,
    commit,
    ...(commits ? { commits } : {}),
    evidence: nextEvidence,
  };
  const updatedTasks = tasks.map((task) => (task?.id === taskId ? nextTask : task));

  return {
    tasks: updatedTasks,
    taskId,
    status,
    statusSource: "evidence-manifest",
    commit,
    ...(commits ? { commits } : {}),
    report,
    verifiedAt,
    evidenceCount: nextEvidence.length,
    changed: !alreadySynced || currentStatus !== status,
  };
}
