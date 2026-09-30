import assert from "node:assert/strict";
import { homedir } from "node:os";
import test from "node:test";
import { AGENT_WORKSPACES, resolveAgentWorkspace } from "./agent-workspaces.mjs";

test("keeps APP18/APP19/APP20 as convenience presets", () => {
  assert.deepEqual(Object.keys(AGENT_WORKSPACES), ["APP18", "APP19", "APP20"]);
  assert.equal(resolveAgentWorkspace("APP19"), "/mnt/data/code/dcx/dcx-web");
  assert.equal(resolveAgentWorkspace("APP20"), "/mnt/data/code/well-log-platform");
  assert.equal(resolveAgentWorkspace(undefined), AGENT_WORKSPACES.APP18);
  assert.equal(resolveAgentWorkspace(""), AGENT_WORKSPACES.APP18);
});

test("accepts arbitrary directories without a whitelist", () => {
  assert.equal(resolveAgentWorkspace("/mnt/data/code/other"), "/mnt/data/code/other");
  assert.equal(resolveAgentWorkspace("/tmp"), "/tmp");
  assert.equal(resolveAgentWorkspace("APP21"), `${process.cwd()}/APP21`);
  assert.equal(resolveAgentWorkspace("toString"), `${process.cwd()}/toString`);
  assert.equal(resolveAgentWorkspace("/a/b/../c"), "/a/c");
  assert.equal(resolveAgentWorkspace("~"), homedir());
  assert.equal(resolveAgentWorkspace("~/code/foo"), `${homedir()}/code/foo`);
});

test("still rejects non-string input", () => {
  assert.equal(resolveAgentWorkspace({}), undefined);
  assert.equal(resolveAgentWorkspace(42), undefined);
});
