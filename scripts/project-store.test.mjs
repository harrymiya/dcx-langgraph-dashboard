import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createProjectStore } from "./project-store.mjs";

test("projects keep independent task snapshots and archive without deleting data", async () => {
  const root = await mkdtemp(join(tmpdir(), "dcx-project-store-"));
  try {
    const store = await createProjectStore({
      runtimeRoot: root,
      seedTasks: [{ id: "TASK-1", status: "planned" }],
      seedProject: { id: "default", name: "Default", workspace: "/workspace/default" },
    });
    const created = await store.createProject({
      id: "project-alpha",
      name: "Alpha",
      workspace: "/workspace/alpha",
      sourceProjectId: "default",
      managedBy: "agent",
    });

    assert.equal(created.id, "project-alpha");
    const alphaTasks = await store.readTasks("project-alpha");
    alphaTasks[0].status = "in-progress";
    await store.writeTasks("project-alpha", alphaTasks);

    assert.equal((await store.readTasks("default"))[0].status, "planned");
    assert.equal((await store.readTasks("project-alpha"))[0].status, "in-progress");

    await store.archiveProject("project-alpha");
    const archived = (await store.listProjects()).find((project) => project.id === "project-alpha");
    // archive 兼容为移入回收站：archived/trashed 都视为回收站内状态。
    assert.ok(archived?.status === "archived" || archived?.status === "trashed");
    assert.equal((await readFile(join(root, "projects", "project-alpha", "tasks.json"), "utf8")).includes("in-progress"), true);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("trash keeps data, restore reactivates, permanent delete removes data", async () => {
  const root = await mkdtemp(join(tmpdir(), "dcx-project-store-"));
  try {
    const store = await createProjectStore({
      runtimeRoot: root,
      seedTasks: [{ id: "TASK-1", status: "planned" }],
      seedProject: { id: "default", name: "Default", workspace: "/workspace/default" },
    });
    await store.createProject({ id: "project-beta", name: "Beta", sourceProjectId: "default" });

    // 删除到回收站：保留任务快照
    const trashed = await store.trashProject("project-beta");
    assert.equal(trashed.status, "trashed");
    assert.ok(typeof trashed.trashedAt === "string");
    assert.equal((await store.readTasks("project-beta"))[0].status, "planned");

    // 恢复
    const restored = await store.restoreProject("project-beta");
    assert.equal(restored.status, "active");
    assert.equal(restored.trashedAt, undefined);

    // 彻底删除必须先入回收站
    await assert.rejects(() => store.deleteProject("project-beta"), /move.*trash/i);
    await store.trashProject("project-beta");
    const deleted = await store.deleteProject("project-beta");
    assert.equal(deleted.deleted, true);
    assert.equal((await store.listProjects()).some((project) => project.id === "project-beta"), false);

    // default 永不允许入回收站 / 彻底删除
    await assert.rejects(() => store.trashProject("default"), /default/i);
    await assert.rejects(() => store.deleteProject("default"), /default/i);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("emptyTrash removes only trashed projects", async () => {
  const root = await mkdtemp(join(tmpdir(), "dcx-project-store-"));
  try {
    const store = await createProjectStore({
      runtimeRoot: root,
      seedTasks: [{ id: "TASK-1", status: "planned" }],
      seedProject: { id: "default", name: "Default", workspace: "/workspace/default" },
    });
    await store.createProject({ id: "project-gamma", name: "Gamma", sourceProjectId: "default" });
    await store.createProject({ id: "project-delta", name: "Delta", sourceProjectId: "default" });
    await store.trashProject("project-gamma");
    const result = await store.emptyTrash();
    assert.deepEqual(result.deleted.sort(), ["project-gamma"]);
    const ids = (await store.listProjects()).map((project) => project.id).sort();
    assert.deepEqual(ids, ["default", "project-delta"]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("project ids are restricted to safe path segments", async () => {
  const root = await mkdtemp(join(tmpdir(), "dcx-project-store-"));
  try {
    const store = await createProjectStore({
      runtimeRoot: root,
      seedTasks: [],
      seedProject: { id: "default", name: "Default", workspace: "/workspace/default" },
    });
    await assert.rejects(() => store.createProject({ id: "../escape", name: "Escape" }), /invalid project id/i);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
