import assert from "node:assert/strict";
import test from "node:test";
import { buildEvidenceUpdate } from "./evidence-sync.mjs";

const evidence = {
  report: ".test-local/reports/WL-13-code-restructure-20260909.md",
  commits: { APP18: "f8ed4f277", APP19: "ee9d6a7", APP20: "04756c9" },
  checks: [{ command: "pnpm test:curve-all-consumers", exit: 0 }],
};

function fixture(overrides = {}) {
  const tasks = [
    { id: "CURVE-ALL-01", status: "code-ready", deps: [] },
    { id: "WL-13", status: "in-progress", deps: ["CURVE-ALL-01"], evidence: [] },
    { id: "WL-14", status: "planned", deps: ["WL-13"] },
    { id: "UNRELATED", status: "planned", deps: [] },
  ];
  return {
    tasks,
    manifest: { tasks: { "WL-13": { verified_at: "2026-09-09T06:00:14Z", commit: "ee9d6a7", evidence: [evidence] } } },
    payload: { taskId: "WL-13", status: "contract-ready", ...overrides },
  };
}

test("accepts successful manifest evidence and preserves project commits", () => {
  const input = fixture();
  input.payload.commit = "client-supplied-fake";
  input.payload.commits = { DASHBOARD: "client-supplied-fake" };
  const result = buildEvidenceUpdate(input);
  const task = result.tasks.find((item) => item.id === "WL-13");
  assert.equal(result.status, "contract-ready");
  assert.equal(result.changed, true);
  assert.deepEqual(result.commits, { APP18: "f8ed4f277", APP19: "ee9d6a7", APP20: "04756c9" });
  assert.equal(task.status_source, "evidence-manifest");
  assert.equal(task.evidence.length, 1);
  assert.equal(task.evidence[0].status, "contract-ready");
  assert.equal(result.tasks.find((item) => item.id === "UNRELATED").status, "planned");
});

test("rejects failed checks and missing dependency readiness", () => {
  const missingCommit = fixture({ commits: undefined });
  missingCommit.manifest.tasks["WL-13"].commit = undefined;
  missingCommit.manifest.tasks["WL-13"].verified_at = undefined;
  missingCommit.manifest.tasks["WL-13"].evidence = [{ ...evidence, commit: undefined }];
  assert.throws(() => buildEvidenceUpdate(missingCommit), /commit|verified_at/);
  const failed = fixture();
  failed.manifest.tasks["WL-13"].evidence = [{ ...evidence, checks: [{ command: "bad", exit: 1 }] }];
  assert.throws(() => buildEvidenceUpdate(failed), /退出码为 1/);
  const blocked = fixture();
  blocked.tasks[0].status = "in-progress";
  assert.throws(() => buildEvidenceUpdate(blocked), /前置依赖/);
});

test("does not duplicate the same accepted evidence", () => {
  const first = buildEvidenceUpdate(fixture());
  const second = buildEvidenceUpdate({ ...fixture(), tasks: first.tasks });
  assert.equal(second.changed, false);
  assert.equal(second.evidenceCount, 1);
});
