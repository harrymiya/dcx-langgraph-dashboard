import { existsSync, readFileSync } from "node:fs";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";

const PROJECT_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/i;

function assertProjectId(value) {
  if (typeof value !== "string" || !PROJECT_ID_PATTERN.test(value)) {
    throw new Error("Invalid project id; use 1-64 letters, numbers, hyphens or underscores");
  }
  return value;
}

function now() {
  return new Date().toISOString();
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

export function projectRuntimeRoot(dashboardRoot, configuredRoot) {
  return resolve(configuredRoot ?? join(dashboardRoot, "backend", ".project-runtime"));
}

export async function createProjectStore({ runtimeRoot, seedTasks, seedProject }) {
  const root = resolve(runtimeRoot);
  const projectsRoot = join(root, "projects");
  const registryPath = join(root, "projects.json");
  await mkdir(projectsRoot, { recursive: true });

  async function readRegistry() {
    try {
      const parsed = JSON.parse(await readFile(registryPath, "utf8"));
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      const initial = [{
        ...clone(seedProject),
        id: assertProjectId(seedProject.id),
        status: "active",
        managedBy: seedProject.managedBy ?? "agent",
        createdAt: seedProject.createdAt ?? now(),
        updatedAt: seedProject.updatedAt ?? now(),
      }];
      await writeRegistry(initial);
      await writeTasks(initial[0].id, seedTasks);
      return initial;
    }
  }

  async function writeRegistry(projects) {
    const temporaryPath = registryPath + ".writing";
    await writeFile(temporaryPath, JSON.stringify(projects, null, 2) + "\n", "utf8");
    await rename(temporaryPath, registryPath);
  }

  function taskPath(projectId) {
    return join(projectsRoot, assertProjectId(projectId), "tasks.json");
  }

  async function writeTasks(projectId, tasks) {
    const path = taskPath(projectId);
    await mkdir(join(projectsRoot, assertProjectId(projectId)), { recursive: true });
    const temporaryPath = path + ".writing";
    await writeFile(temporaryPath, JSON.stringify(tasks, null, 2) + "\n", "utf8");
    await rename(temporaryPath, path);
  }

  async function listProjects() {
    const projects = await readRegistry();
    return Promise.all(projects
      .filter((project) => project && typeof project.id === "string")
      .map(async (project) => ({
        ...project,
        taskCount: (await readTasks(project.id)).length,
      })));
  }

  async function getProject(projectId) {
    const id = assertProjectId(projectId);
    const project = (await readRegistry()).find((item) => item.id === id);
    if (!project) throw new Error("Project not found: " + id);
    return project;
  }

  async function readTasks(projectId) {
    const project = await getProject(projectId);
    const path = taskPath(project.id);
    try {
      return JSON.parse(await readFile(path, "utf8"));
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      await writeTasks(project.id, seedTasks);
      return clone(seedTasks);
    }
  }

  async function createProject(input) {
    const id = assertProjectId(input?.id);
    const projects = await readRegistry();
    if (projects.some((project) => project.id === id)) throw new Error("Project already exists: " + id);
    const sourceId = input?.sourceProjectId ? assertProjectId(input.sourceProjectId) : "default";
    const sourceTasks = await readTasks(sourceId);
    const project = {
      id,
      name: typeof input?.name === "string" && input.name.trim() ? input.name.trim() : id,
      description: typeof input?.description === "string" ? input.description.trim() : "",
      workspace: typeof input?.workspace === "string" ? input.workspace : undefined,
      status: "active",
      managedBy: "agent",
      sourceProjectId: sourceId,
      createdAt: now(),
      updatedAt: now(),
    };
    await writeTasks(id, sourceTasks);
    await writeRegistry([...projects, project]);
    return project;
  }

  function isInTrash(status) {
    // 兼容旧数据：archived 视为回收站内项目，前端统一按 trashed 展示。
    return status === "trashed" || status === "archived";
  }

  async function archiveProject(projectId) {
    return trashProject(projectId);
  }

  // 删除到回收站：只改注册表状态，保留 projects/<id>/tasks.json，支持恢复。
  async function trashProject(projectId) {
    const id = assertProjectId(projectId);
    const projects = await readRegistry();
    const index = projects.findIndex((project) => project.id === id);
    if (index < 0) throw new Error("Project not found: " + id);
    if (id === "default") throw new Error("The default project cannot be moved to trash");
    if (isInTrash(projects[index]?.status)) return projects[index];
    const timestamp = now();
    const next = [...projects];
    next[index] = {
      ...next[index],
      status: "trashed",
      trashedAt: timestamp,
      updatedAt: timestamp,
    };
    await writeRegistry(next);
    return next[index];
  }

  // 从回收站恢复为 active。
  async function restoreProject(projectId) {
    const id = assertProjectId(projectId);
    const projects = await readRegistry();
    const index = projects.findIndex((project) => project.id === id);
    if (index < 0) throw new Error("Project not found: " + id);
    if (!isInTrash(projects[index]?.status)) throw new Error("Project is not in trash: " + id);
    const next = [...projects];
    const restored = { ...next[index], status: "active", updatedAt: now() };
    delete restored.trashedAt;
    next[index] = restored;
    await writeRegistry(next);
    return restored;
  }

  // 彻底删除：仅允许回收站内项目；删除注册表项 + 任务快照目录，不可恢复。
  async function deleteProject(projectId) {
    const id = assertProjectId(projectId);
    if (id === "default") throw new Error("The default project cannot be permanently deleted");
    const projects = await readRegistry();
    const index = projects.findIndex((project) => project.id === id);
    if (index < 0) throw new Error("Project not found: " + id);
    if (!isInTrash(projects[index]?.status)) {
      throw new Error("Please move the project to trash before permanently deleting: " + id);
    }
    const next = projects.filter((project) => project.id !== id);
    await writeRegistry(next);
    // 任务快照目录删除失败不阻断注册表删除（注册表已先落盘）。
    try {
      await rm(join(projectsRoot, id), { recursive: true, force: true });
    } catch {
      // Ignore cleanup errors; registry is the source of truth.
    }
    return { id, deleted: true };
  }

  // 清空回收站：删除所有 trashed/archived 项目（default 永不删除），返回删除数量。
  async function emptyTrash() {
    const projects = await readRegistry();
    const trashed = projects.filter((project) => project && isInTrash(project.status) && project.id !== "default");
    const keep = projects.filter((project) => !trashed.some((item) => item.id === project.id));
    await writeRegistry(keep);
    for (const project of trashed) {
      try {
        await rm(join(projectsRoot, assertProjectId(project.id)), { recursive: true, force: true });
      } catch {
        // Ignore per-project cleanup errors.
      }
    }
    return { deleted: trashed.map((project) => project.id) };
  }

  async function updateProject(projectId, input) {
    const id = assertProjectId(projectId);
    const projects = await readRegistry();
    const index = projects.findIndex((project) => project.id === id);
    if (index < 0) throw new Error("Project not found: " + id);
    const current = projects[index];
    const nextProject = {
      ...current,
      ...(typeof input?.name === "string" && input.name.trim() ? { name: input.name.trim() } : {}),
      ...(typeof input?.description === "string" ? { description: input.description.trim() } : {}),
      ...(typeof input?.workspace === "string" ? { workspace: input.workspace } : {}),
      updatedAt: now(),
    };
    const next = [...projects];
    next[index] = nextProject;
    await writeRegistry(next);
    return nextProject;
  }

  async function updateProjectTasks(projectId, updater) {
    const tasks = await readTasks(projectId);
    const nextTasks = await updater(clone(tasks));
    await writeTasks(projectId, nextTasks);
    return nextTasks;
  }

  async function reconcileTaskDefinitions(projectId) {
    const current = await readTasks(projectId);
    const currentById = new Map(current.map((task) => [task.id, task]));
    const runtimeFields = ["status", "status_source", "evidence", "owner", "claimed_at", "lease_expires_at", "autonomous_attempt", "retry_after", "last_error", "last_report", "last_checks", "autonomous_result", "autonomous_failure", "verified_at", "commit", "commits"];
    const next = seedTasks.map((definition) => {
      const saved = currentById.get(definition.id);
      if (!saved) return clone(definition);
      const task = clone(definition);
      for (const field of runtimeFields) {
        if (Object.prototype.hasOwnProperty.call(saved, field)) task[field] = saved[field];
      }
      const savedData = saved.data && typeof saved.data === "object" ? saved.data : {};
      const definitionData = definition.data && typeof definition.data === "object" ? definition.data : {};
      task.data = { ...savedData, ...definitionData };
      if (Object.prototype.hasOwnProperty.call(savedData, "automated_result")) {
        task.data.automated_result = savedData.automated_result;
      }
      return task;
    });
    const knownIds = new Set(seedTasks.map((task) => task.id));
    for (const saved of current) {
      if (knownIds.has(saved.id)) continue;
      const archived = clone(saved);
      archived.data = { ...(archived.data ?? {}), scope: "MVP后续", mvp_scope_reason: "不在当前权威 DAG 快照；保留旧 ID 与状态，不参与当前任务领取。" };
      next.push(archived);
    }
    await writeTasks(projectId, next);
  }

  let initialProjects = await readRegistry();
  let registryChanged = false;
  initialProjects = initialProjects.map((project) => {
    if (project.id !== "default") return project;
    const nextProject = {
      ...project,
      name: seedProject.name,
      description: seedProject.description,
      workspace: seedProject.workspace,
      updatedAt: now(),
    };
    if (JSON.stringify(nextProject) !== JSON.stringify(project)) registryChanged = true;
    return nextProject;
  });
  if (registryChanged) await writeRegistry(initialProjects);
  for (const project of initialProjects) await reconcileTaskDefinitions(project.id);

  return {
    root,
    listProjects,
    getProject,
    readTasks,
    writeTasks,
    createProject,
    updateProject,
    archiveProject,
    trashProject,
    restoreProject,
    deleteProject,
    emptyTrash,
    updateProjectTasks,
    taskPath,
  };
}

export function readProjectSync(runtimeRoot, projectId) {
  const id = assertProjectId(projectId);
  const registryPath = join(resolve(runtimeRoot), "projects.json");
  const registry = JSON.parse(readFileSync(registryPath, "utf8"));
  const project = registry.find((item) => item.id === id);
  if (!project) throw new Error("Project not found: " + id);
  return project;
}

export { assertProjectId };
