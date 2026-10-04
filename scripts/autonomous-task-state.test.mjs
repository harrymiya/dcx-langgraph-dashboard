import test from "node:test";
import assert from "node:assert/strict";
import { blockTask, claimNextTask, completeTask, heartbeatTask } from "./autonomous-task-state.mjs";

const now = new Date("2026-09-30T12:00:00.000Z");
function fixture() {
  return [
    { id: "BASE", deps: [], status: "planned", data: { scope: "MVP必须" } },
    { id: "NEXT", deps: ["BASE"], status: "planned", data: { scope: "MVP必须" } },
    { id: "LATER", deps: [], status: "planned", data: { scope: "MVP后续" } },
  ];
}

test("领取 MVP 和后续范围内当前依赖就绪的任务", () => {
  const result = claimNextTask(fixture(), { workerId: "agent-1", leaseSeconds: 900, now });
  assert.equal(result.task.id, "BASE");
  assert.equal(result.task.status, "in-progress");
  assert.equal(result.readyCount, 1);
});

test("租约过期后可回收原进行中任务", () => {
  const tasks = fixture();
  tasks[0] = { ...tasks[0], status: "in-progress", owner: "dead-agent", lease_expires_at: "2026-09-30T11:59:59.000Z" };
  const result = claimNextTask(tasks, { workerId: "agent-2", leaseSeconds: 900, now });
  assert.equal(result.task.id, "BASE");
  assert.equal(result.task.owner, "agent-2");
});

test("任务完成要求租约归属和全通过机器检查", () => {
  const claimed = claimNextTask(fixture(), { workerId: "agent-1", leaseSeconds: 900, now });
  const input = { taskId: "BASE", workerId: "agent-1", status: "code-ready", summary: "done", report: "docs/reports/tasks/BASE.md", checks: [{ command: "node --check", exit_code: 0, result: "ok" }] };
  const result = completeTask(claimed.tasks, input);
  assert.equal(result.task.status, "code-ready");
  assert.equal(result.task.evidence.length, 1);
  assert.throws(() => completeTask(claimed.tasks, { ...input, workerId: "other" }), /租约无效/);
  assert.throws(() => completeTask(claimed.tasks, { ...input, checks: [{ command: "bad", exit_code: 1, result: "failed" }] }), /未通过/);
});

test("失败可回写 blocked 状态，延后重试并释放租约，loop 继续领取其它范围任务", () => {
  const claimed = claimNextTask(fixture(), { workerId: "agent-1", leaseSeconds: 900, now });
  const result = blockTask(claimed.tasks, { taskId: "BASE", workerId: "agent-1", error: "check failed", report: "docs/reports/tasks/BASE.md", retryAfterSeconds: 3600, now });
  assert.equal(result.task.status, "blocked");
  assert.equal(result.task.lease_expires_at, undefined);
  assert.equal(result.task.retry_after, "2026-09-30T13:00:00.000Z");
  assert.equal(claimNextTask(result.tasks, { workerId: "agent-2", leaseSeconds: 900, now }).task.id, "LATER");
});

test("心跳只续租当前 worker 持有的任务", () => {
  const claimed = claimNextTask(fixture(), { workerId: "agent-1", leaseSeconds: 900, now });
  const renewed = heartbeatTask(claimed.tasks, { taskId: "BASE", workerId: "agent-1", leaseSeconds: 900, now: new Date("2026-09-30T12:01:00.000Z") });
  assert.equal(renewed.task.lease_expires_at, "2026-09-30T12:16:00.000Z");
  assert.throws(() => heartbeatTask(claimed.tasks, { taskId: "BASE", workerId: "other", leaseSeconds: 900, now }), /租约不属于/);
});
