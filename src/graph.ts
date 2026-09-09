import type { DagStatus, DagTask } from "./types";

export const WORKFLOW_STATUSES = [
  "release-ready",
  "contract-ready",
  "code-ready",
  "in-progress",
  "blocked",
  "planned",
  "unknown",
] as const satisfies readonly Exclude<DagStatus, "control">[];

export type WorkflowStatus = (typeof WORKFLOW_STATUSES)[number];
export type TaskFilter = "all" | WorkflowStatus;

export const STATUS_META: Record<
  DagStatus,
  { label: string; shortLabel: string; color: string; tone: string }
> = {
  planned: { label: "计划中", shortLabel: "计划", color: "#94a3b8", tone: "neutral" },
  "in-progress": { label: "进行中", shortLabel: "进行", color: "#f59e0b", tone: "warning" },
  blocked: { label: "阻塞", shortLabel: "阻塞", color: "#f87171", tone: "danger" },
  "code-ready": { label: "代码就绪", shortLabel: "代码", color: "#60a5fa", tone: "info" },
  "contract-ready": { label: "合同就绪", shortLabel: "合同", color: "#a78bfa", tone: "violet" },
  "release-ready": { label: "可发布", shortLabel: "发布", color: "#34d399", tone: "success" },
  unknown: { label: "待同步", shortLabel: "待同步", color: "#64748b", tone: "neutral" },
  control: { label: "控制节点", shortLabel: "控制", color: "#38bdf8", tone: "control" },
};

export function isReadyStatus(status: DagStatus): boolean {
  return status === "code-ready" || status === "contract-ready" || status === "release-ready";
}

export function groupForNode(id: string): string {
  if (id === "__start__" || id === "__end__") return "控制流";
  return id.split("-")[0] || "其他";
}

export function taskMatchesFilter(
  task: DagTask,
  query: string,
  filter: TaskFilter,
): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  const queryMatch =
    normalizedQuery.length === 0 ||
    [task.id, task.label, task.group, task.type, JSON.stringify(task.data)]
      .join(" ")
      .toLowerCase()
      .includes(normalizedQuery);
  const statusMatch =
    filter === "all" ||
    task.status === filter;
  return queryMatch && statusMatch;
}

export function relatedTaskIds(selectedId: string | null, tasks: DagTask[]): Set<string> {
  if (!selectedId) return new Set();
  const related = new Set([selectedId]);
  const selected = tasks.find((task) => task.id === selectedId);
  selected?.deps.forEach((dependency) => related.add(dependency));
  tasks.forEach((task) => {
    if (task.deps.includes(selectedId)) related.add(task.id);
  });
  return related;
}
