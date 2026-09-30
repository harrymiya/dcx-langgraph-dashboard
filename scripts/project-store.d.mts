export interface ProjectRecord {
  id: string;
  name: string;
  description?: string;
  workspace?: string;
  status: "active" | "archived" | "trashed";
  managedBy: "agent";
  sourceProjectId?: string;
  taskCount?: number;
  createdAt?: string;
  updatedAt?: string;
  trashedAt?: string;
}

export interface ProjectStoreOptions {
  runtimeRoot: string;
  seedTasks: unknown[];
  seedProject: Record<string, unknown> & { id: string };
}

export interface ProjectStore {
  root: string;
  listProjects(): Promise<ProjectRecord[]>;
  getProject(projectId: string): Promise<ProjectRecord>;
  readTasks(projectId: string): Promise<unknown[]>;
  writeTasks(projectId: string, tasks: unknown[]): Promise<void>;
  createProject(input: {
    id: string;
    name?: string;
    description?: string;
    workspace?: string;
    sourceProjectId?: string;
  }): Promise<ProjectRecord>;
  updateProject(projectId: string, input: {
    name?: string;
    description?: string;
    workspace?: string;
  }): Promise<ProjectRecord>;
  archiveProject(projectId: string): Promise<ProjectRecord>;
  trashProject(projectId: string): Promise<ProjectRecord>;
  restoreProject(projectId: string): Promise<ProjectRecord>;
  deleteProject(projectId: string): Promise<{ id: string; deleted: boolean }>;
  emptyTrash(): Promise<{ deleted: string[] }>;
  updateProjectTasks(projectId: string, updater: (tasks: unknown[]) => unknown[] | Promise<unknown[]>): Promise<unknown[]>;
  taskPath(projectId: string): string;
}

export function projectRuntimeRoot(dashboardRoot: string, configuredRoot?: string): string;
export function createProjectStore(options: ProjectStoreOptions): Promise<ProjectStore>;
export function readProjectSync(runtimeRoot: string, projectId: string): ProjectRecord;
export function assertProjectId(value: unknown): string;
