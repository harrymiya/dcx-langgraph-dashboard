const READY = new Set(["code-ready", "contract-ready", "release-ready"]);

function parseTime(value, fallback = 0) {
  const parsed = typeof value === "string" ? Date.parse(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
}

function activeTask(task) {
  return ["MVP必须", "MVP后续"].includes(task?.data?.scope) && !/^AUTH-/i.test(task.id ?? "");
}

function dependenciesReady(task, byId) {
  return (Array.isArray(task.deps) ? task.deps : []).every((id) => READY.has(byId.get(id)?.status));
}

function retryIsReady(task, nowMs) {
  return task.status !== "blocked" || parseTime(task.retry_after, Number.POSITIVE_INFINITY) <= nowMs;
}

function eligible(task, byId, nowMs) {
  if (!activeTask(task) || !dependenciesReady(task, byId)) return false;
  if (task.status === "planned") return true;
  if (task.status === "blocked") return retryIsReady(task, nowMs);
  return task.status === "in-progress" && parseTime(task.lease_expires_at, 0) <= nowMs;
}

function readyCounts(tasks, nowMs) {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  let readyCount = 0;
  let blockedCount = 0;
  for (const task of tasks) {
    if (!activeTask(task)) continue;
    if (task.status === "blocked") blockedCount += 1;
    if (eligible(task, byId, nowMs)) readyCount += 1;
  }
  return { readyCount, blockedCount };
}

export function claimNextTask(tasks, { workerId, leaseSeconds, now = new Date() }) {
  if (!Array.isArray(tasks)) throw new Error("任务快照必须为数组");
  if (typeof workerId !== "string" || !workerId.trim()) throw new Error("workerId 不能为空");
  if (!Number.isInteger(leaseSeconds) || leaseSeconds < 60 || leaseSeconds > 86_400) throw new Error("leaseSeconds 必须在 60 到 86400 之间");
  const nowMs = now instanceof Date ? now.getTime() : Date.parse(now);
  if (!Number.isFinite(nowMs)) throw new Error("now 不是有效时间");
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const candidate = tasks.find((task) => eligible(task, byId, nowMs));
  const counts = readyCounts(tasks, nowMs);
  if (!candidate) return { tasks, task: null, ...counts };
  const claimed = {
    ...candidate,
    status: "in-progress",
    status_source: "autonomous-agent",
    owner: workerId.trim(),
    claimed_at: new Date(nowMs).toISOString(),
    lease_expires_at: new Date(nowMs + leaseSeconds * 1000).toISOString(),
    autonomous_attempt: (Number.isInteger(candidate.autonomous_attempt) ? candidate.autonomous_attempt : 0) + 1,
  };
  const updated = tasks.map((task) => task.id === candidate.id ? claimed : task);
  return { tasks: updated, task: claimed, ...readyCounts(updated, nowMs) };
}

export function heartbeatTask(tasks, { taskId, workerId, leaseSeconds, now = new Date() }) {
  const nowMs = now instanceof Date ? now.getTime() : Date.parse(now);
  const task = tasks.find((item) => item.id === taskId);
  if (!task || task.status !== "in-progress" || task.owner !== workerId) throw new Error(`任务 ${taskId} 的租约不属于 ${workerId}`);
  if (!Number.isInteger(leaseSeconds) || leaseSeconds < 60 || leaseSeconds > 86_400) throw new Error("leaseSeconds 必须在 60 到 86400 之间");
  const renewed = { ...task, lease_expires_at: new Date(nowMs + leaseSeconds * 1000).toISOString() };
  return { tasks: tasks.map((item) => item.id === taskId ? renewed : item), task: renewed };
}

export function completeTask(tasks, input) {
  const task = tasks.find((item) => item.id === input.taskId);
  if (!task || task.status !== "in-progress" || task.owner !== input.workerId) throw new Error(`任务 ${input.taskId} 当前租约无效`);
  if (!READY.has(input.status)) throw new Error("完成状态必须为 code-ready、contract-ready 或 release-ready");
  if (typeof input.summary !== "string" || !input.summary.trim()) throw new Error("任务完成必须包含机器摘要");
  const byId = new Map(tasks.map((item) => [item.id, item]));
  if (!dependenciesReady(task, byId)) throw new Error(`任务 ${task.id} 的依赖尚未完成`);
  if (!Array.isArray(input.checks) || input.checks.length === 0) throw new Error("任务完成必须包含机器检查");
  for (const [index, check] of input.checks.entries()) {
    if (!check || typeof check.command !== "string" || !check.command.trim() || check.exit_code !== 0 || typeof check.result !== "string") {
      throw new Error(`任务检查 ${index} 未通过或字段不完整`);
    }
  }
  if (typeof input.report !== "string" || !input.report.trim()) throw new Error("缺少任务报告路径");
  const verifiedAt = new Date().toISOString();
  const evidence = Array.isArray(task.evidence) ? task.evidence : [];
  const completed = {
    ...task,
    status: input.status,
    status_source: "autonomous-agent",
    verified_at: verifiedAt,
    last_report: input.report,
    last_checks: input.checks,
    autonomous_result: {
      worker_id: input.workerId,
      summary: input.summary,
      report: input.report,
      changed_files: input.changedFiles ?? [],
      limitations: input.limitations ?? [],
      verified_at: verifiedAt,
    },
    evidence: [...evidence, {
      source: "autonomous-agent",
      status: input.status,
      report: input.report,
      checks: input.checks,
      verified_at: verifiedAt,
    }],
  };
  delete completed.lease_expires_at;
  return { tasks: tasks.map((item) => item.id === task.id ? completed : item), task: completed };
}

export function blockTask(tasks, input) {
  const task = tasks.find((item) => item.id === input.taskId);
  if (!task || task.status !== "in-progress" || task.owner !== input.workerId) throw new Error(`任务 ${input.taskId} 当前租约无效`);
  if (typeof input.error !== "string" || !input.error.trim()) throw new Error("阻塞任务必须记录错误信息");
  if (typeof input.report !== "string" || !input.report.trim()) throw new Error("阻塞任务必须记录复现报告路径");
  const now = input.now instanceof Date ? input.now : new Date(input.now ?? Date.now());
  const retryAfterSeconds = Number.isInteger(input.retryAfterSeconds) ? Math.max(60, Math.min(input.retryAfterSeconds, 86_400)) : 3600;
  const blocked = {
    ...task,
    status: "blocked",
    status_source: "autonomous-agent",
    retry_after: new Date(now.getTime() + retryAfterSeconds * 1000).toISOString(),
    last_error: input.error,
    last_report: input.report,
    last_checks: input.checks ?? [],
    autonomous_failure: { worker_id: input.workerId, error: input.error, report: input.report, failed_at: now.toISOString() },
  };
  delete blocked.lease_expires_at;
  return { tasks: tasks.map((item) => item.id === task.id ? blocked : item), task: blocked };
}

export function releaseTask(tasks, { taskId, workerId }) {
  const task = tasks.find((item) => item.id === taskId);
  if (!task || task.status !== "in-progress" || task.owner !== workerId) return { tasks, task: task ?? null };
  const released = { ...task, status: "planned", status_source: "autonomous-agent", last_release_at: new Date().toISOString() };
  delete released.owner;
  delete released.claimed_at;
  delete released.lease_expires_at;
  return { tasks: tasks.map((item) => item.id === taskId ? released : item), task: released };
}
