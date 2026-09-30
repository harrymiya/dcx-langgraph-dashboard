import assert from "node:assert/strict";
import { homedir } from "node:os";
import test from "node:test";
import { AGENT_WORKSPACES } from "./agent-workspaces.mjs";
import { resolveTerminalCwd } from "./terminal-plugin.mjs";

const ROOT = "/srv/dashboard";

test("expands workspace presets to their paths", () => {
  assert.equal(resolveTerminalCwd("APP18", AGENT_WORKSPACES, ROOT), AGENT_WORKSPACES.APP18);
  assert.equal(resolveTerminalCwd("APP20", AGENT_WORKSPACES, ROOT), AGENT_WORKSPACES.APP20);
});

test("falls back to the first preset when cwd is missing", () => {
  assert.equal(resolveTerminalCwd(null, AGENT_WORKSPACES, ROOT), AGENT_WORKSPACES.APP18);
  assert.equal(resolveTerminalCwd("   ", AGENT_WORKSPACES, ROOT), AGENT_WORKSPACES.APP18);
});

test("accepts any directory, not only whitelisted ones", () => {
  assert.equal(resolveTerminalCwd("/etc", AGENT_WORKSPACES, ROOT), "/etc");
  assert.equal(resolveTerminalCwd("/mnt/data/code/other/repo", AGENT_WORKSPACES, ROOT), "/mnt/data/code/other/repo");
  assert.equal(resolveTerminalCwd("/a/b/../c", AGENT_WORKSPACES, ROOT), "/a/c");
  assert.equal(resolveTerminalCwd("sub/dir", AGENT_WORKSPACES, ROOT), `${ROOT}/sub/dir`);
  assert.equal(resolveTerminalCwd("../sibling", AGENT_WORKSPACES, ROOT), "/srv/sibling");
  assert.equal(resolveTerminalCwd("~", AGENT_WORKSPACES, ROOT), homedir());
  assert.equal(resolveTerminalCwd("~/code/foo", AGENT_WORKSPACES, ROOT), `${homedir()}/code/foo`);
});
