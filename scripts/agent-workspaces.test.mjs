import assert from "node:assert/strict";
import test from "node:test";
import { AGENT_WORKSPACES, resolveAgentWorkspace } from "./agent-workspaces.mjs";

test("exposes only the approved APP18/APP19/APP20 workspaces", () => {
  assert.deepEqual(Object.keys(AGENT_WORKSPACES), ["APP18", "APP19", "APP20"]);
  assert.equal(resolveAgentWorkspace("APP19"), "/mnt/data/code/dcx/dcx-web");
  assert.equal(resolveAgentWorkspace("APP20"), "/mnt/data/code/well-log-platform");
  assert.equal(resolveAgentWorkspace(undefined), AGENT_WORKSPACES.APP18);
});

test("rejects arbitrary paths and unapproved project names", () => {
  assert.equal(resolveAgentWorkspace("/mnt/data/code/other"), undefined);
  assert.equal(resolveAgentWorkspace("APP21"), undefined);
  assert.equal(resolveAgentWorkspace("toString"), undefined);
  assert.equal(resolveAgentWorkspace({}), undefined);
});
