import assert from "node:assert/strict";
import test from "node:test";
import { blockTask, claimNextTask, completeTask } from "../../../scripts/autonomous-task-state.mjs";

const now = new Date("2026-10-01T12:00:00.000Z");
const report = "docs/migration/handoff-and-rollback/README.md";
function taskSnapshot() {
  return [
    { id: "BASE", deps: [], status: "planned", evidence: [], data: { scope: "MVP必须" } },
    { id: "NEXT", deps: ["BASE"], status: "planned", evidence: [], data: { scope: "MVP必须" } },
  ];
}

test("simulated competing workers cannot claim the same active task", () => {
  const first = claimNextTask(taskSnapshot(), { workerId: "worker-a", leaseSeconds: 900, now });
  const competing = claimNextTask(first.tasks, { workerId: "worker-b", leaseSeconds: 900, now });
  assert.equal(first.task.id, "BASE");
  assert.equal(competing.task, null);
  assert.equal(competing.readyCount, 0);
});

test("machine checks and completion result persist in the returned snapshot", () => {
  const claimed = claimNextTask(taskSnapshot(), { workerId: "worker-a", leaseSeconds: 900, now });
  const checks = [{ command: "node --test scripts/autonomous-task-state.test.mjs", exit_code: 0, result: "passed", artifact: report }];
  const completed = completeTask(claimed.tasks, {
    taskId: "BASE", workerId: "worker-a", status: "code-ready", summary: "synthetic checks passed",
    report, checks, changedFiles: [report], limitations: ["simulation only; no runtime persistence exercised"],
  });
  const persistedSnapshot = structuredClone(completed.tasks);
  const reread = persistedSnapshot.find((task) => task.id === "BASE");
  assert.equal(reread.status, "code-ready");
  assert.deepEqual(reread.last_checks, checks);
  assert.equal(reread.autonomous_result.summary, "synthetic checks passed");
  assert.equal(reread.evidence.length, 1);
});

test("blocked task releases lease and can resume after retry time", () => {
  const claimed = claimNextTask(taskSnapshot(), { workerId: "worker-a", leaseSeconds: 900, now });
  const blocked = blockTask(claimed.tasks, {
    taskId: "BASE", workerId: "worker-a", error: "synthetic check failed", report,
    checks: [{ command: "synthetic failing check", exit_code: 1, result: "failed" }],
    retryAfterSeconds: 60, now,
  });
  assert.equal(blocked.task.status, "blocked");
  assert.equal(blocked.task.lease_expires_at, undefined);
  assert.equal(claimNextTask(blocked.tasks, { workerId: "worker-b", leaseSeconds: 900, now }).task, null);

  const resumedAt = new Date(now.getTime() + 60_000);
  const resumed = claimNextTask(blocked.tasks, { workerId: "worker-b", leaseSeconds: 900, now: resumedAt });
  assert.equal(resumed.task.id, "BASE");
  assert.equal(resumed.task.autonomous_attempt, 2);
  assert.equal(resumed.task.autonomous_failure.error, "synthetic check failed");
});

test("failed retry remains blocked until its next retry time", () => {
  const first = claimNextTask(taskSnapshot(), { workerId: "worker-a", leaseSeconds: 900, now });
  const blocked = blockTask(first.tasks, {
    taskId: "BASE", workerId: "worker-a", error: "first failure", report, retryAfterSeconds: 60, now,
  });
  const retry = claimNextTask(blocked.tasks, { workerId: "worker-b", leaseSeconds: 900, now: new Date(now.getTime() + 60_000) });
  const failedAgain = blockTask(retry.tasks, {
    taskId: "BASE", workerId: "worker-b", error: "retry failure", report, retryAfterSeconds: 120,
    now: new Date(now.getTime() + 60_000),
  });
  assert.equal(failedAgain.task.status, "blocked");
  assert.equal(failedAgain.task.autonomous_failure.error, "retry failure");
  assert.equal(claimNextTask(failedAgain.tasks, { workerId: "worker-c", leaseSeconds: 900, now: new Date(now.getTime() + 179_000) }).task, null);
  assert.equal(claimNextTask(failedAgain.tasks, { workerId: "worker-c", leaseSeconds: 900, now: new Date(now.getTime() + 180_000) }).task.id, "BASE");
});

test("simulated shared-file claim registry rejects overlapping writers", () => {
  const claims = new Map();
  function acquire(worker, paths) {
    const conflicts = paths.filter((path) => claims.has(path) && claims.get(path) !== worker);
    if (conflicts.length) return { acquired: false, conflicts };
    for (const path of paths) claims.set(path, worker);
    return { acquired: true, conflicts: [] };
  }
  assert.deepEqual(acquire("GOV-04", ["docs/migration/handoff-and-rollback/README.md"]), { acquired: true, conflicts: [] });
  assert.deepEqual(acquire("other", ["docs/migration/handoff-and-rollback/README.md"]), {
    acquired: false, conflicts: ["docs/migration/handoff-and-rollback/README.md"],
  });
  assert.deepEqual(acquire("page-task", ["pages/example/route.fragment.json"]), { acquired: true, conflicts: [] });
});
