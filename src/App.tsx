import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  CSSProperties,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Copy,
  ExternalLink,
  Info,
  LocateFixed,
  MousePointerClick,
  RefreshCw,
  Search,
  Terminal,
  Moon,
  Workflow,
  X,
  ZoomIn,
  ZoomOut,
  Sun,
} from "lucide-react";
import {
  checkBackend,
  displayApiUrl,
  launchAgent,
  loadGraphDefinition,
  runLangGraph,
  syncTaskEvidence,
} from "./api";
import type { AgentWorkspace, EvidenceReadyStatus } from "./api";
import AgentBoard, { type Agent, type AgentBoardSnapshot } from "./AgentBoard";
import TerminalPanel, { type TerminalPanelHandle } from "./TerminalPanel";
import {
  groupForNode,
  relatedTaskIds,
  STATUS_META,
  taskMatchesFilter,
  WORKFLOW_STATUSES,
} from "./graph";
import type { TaskFilter } from "./graph";
import type {
  Assistant,
  BackendStatus,
  DagStatus,
  DagTask,
  GraphDefinition,
  GraphEdge,
  GraphNode,
  LiveTaskRecord,
  AgentKind,
} from "./types";

type Theme = "dark" | "light";

const CONTROL_NODES = new Set(["__start__", "__end__"]);

const AGENT_META: Record<AgentKind, { label: string; hint: string }> = {
  opencode: { label: "OpenCode", hint: "适合直接在仓库内执行改动" },
  pi: { label: "Pi", hint: "适合快速拆解和推进单个切片" },
  codex: { label: "Codex", hint: "适合带门禁验证完成实现" },
};

const AGENT_WORKSPACE_META: Record<AgentWorkspace, { label: string; path: string }> = {
  APP18: { label: "APP18", path: "/mnt/data/code/dcx-web/dcx-web" },
  APP19: { label: "APP19", path: "/mnt/data/code/dcx/dcx-web" },
  APP20: { label: "APP20", path: "/mnt/data/code/well-log-platform" },
};

function inferAgentWorkspace(task: DagTask): AgentWorkspace {
  if (task.project?.includes("APP19")) return "APP19";
  if (task.project?.includes("APP20")) return "APP20";
  return "APP18";
}

const clampScale = (value: number) => Math.min(1.2, Math.max(0.58, value));

function textValue(value: unknown): string | undefined {
  if (typeof value === "string") return value.trim() || undefined;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const values = value.map(textValue).filter((item): item is string => Boolean(item));
    return values.length ? values.join("；") : undefined;
  }
  if (value && typeof value === "object") {
    const values = Object.entries(value)
      .map(([key, item]) => {
        const itemText = textValue(item);
        return itemText ? key + "：" + itemText : undefined;
      })
      .filter((item): item is string => Boolean(item));
    return values.length ? values.join("；") : undefined;
  }
  return undefined;
}

function firstText(...values: unknown[]): string | undefined {
  for (const value of values) {
    const result = textValue(value);
    if (result) return result;
  }
  return undefined;
}

function recordText(record: Record<string, unknown>, keys: string[]) {
  return firstText(...keys.map((key) => record[key]));
}

function materializeTasks(
  definition: GraphDefinition,
  liveRecords: LiveTaskRecord[] = [],
): DagTask[] {
  const liveById = new Map(liveRecords.map((record) => [record.id, record]));
  const dependencies = new Map<string, string[]>();

  definition.edges.forEach((edge) => {
    const current = dependencies.get(edge.target) ?? [];
    current.push(edge.source);
    dependencies.set(edge.target, current);
  });

  return definition.nodes.map((node: GraphNode) => {
    const isControl = CONTROL_NODES.has(node.id);
    const live = liveById.get(node.id);
    const data = node.data ?? {};
    const dataName = typeof data.name === "string" ? data.name : undefined;
    return {
      id: node.id,
      label: dataName ?? node.id,
      type: node.type ?? "runnable",
      group: groupForNode(node.id),
      isControl,
      deps: dependencies.get(node.id) ?? [],
      status: isControl ? "control" : live?.status ?? "unknown",
      statusSource: isControl ? "graph-definition" : live?.status_source ?? "LangGraph run",
      ingestionStatus: isControl ? "ingested" : live?.ingestion_status ?? "unknown",
      description: firstText(
        live?.description,
        live?.summary,
        recordText(data, ["description", "summary", "detail", "说明"]),
      ),
      goal: firstText(
        live?.goal,
        live?.objective,
        live?.target,
        recordText(data, ["goal", "objective", "target", "目标"]),
      ),
      acceptance: firstText(
        live?.acceptance,
        live?.acceptance_criteria,
        live?.criteria,
        recordText(data, ["acceptance", "acceptance_criteria", "criteria", "done_when", "达成条件"]),
      ),
      implementation: firstText(
        live?.implementation,
        live?.implementation_plan,
        live?.plan,
        recordText(data, ["implementation", "implementation_plan", "plan", "solution", "实施方案"]),
      ),
      section: firstText(live?.section, recordText(data, ["section", "章节"])),
      project: firstText(live?.project, recordText(data, ["project", "项目", "工作项目"])),
      output: firstText(live?.output, recordText(data, ["output", "deliverable", "唯一产出"])),
      scope: firstText(live?.scope, recordText(data, ["scope", "范围", "修改范围"])),
      verify: firstText(live?.verify, recordText(data, ["verify", "verification", "验证", "计划验证"])),
      evidence: live?.evidence,
      commit: live?.commit,
      commits: live?.commits,
      verifiedAt: live?.verified_at,
      data,
    };
  });
}

function statusCounts(tasks: DagTask[]) {
  return tasks
    .filter((task) => !task.isControl)
    .reduce<Record<string, number>>((counts, task) => {
      counts[task.status] = (counts[task.status] ?? 0) + 1;
      return counts;
    }, {});
}

function formatDate(value: string) {
  if (!value) return "尚未同步";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function buildAgentPrompt(
  agent: AgentKind,
  task: DagTask,
  tasks: DagTask[],
  assistant: Assistant | null,
  apiUrl: string,
): string {
  const byId = new Map(tasks.map((item) => [item.id, item]));
  const dependents = tasks
    .filter((item) => item.deps.includes(task.id))
    .map((item) => item.id);
  const dependencyContext = task.deps.length
    ? task.deps
        .map((id) => {
          const dependency = byId.get(id);
          return id + "（" + (dependency ? STATUS_META[dependency.status].label : "未返回") + "）";
        })
        .join("、")
    : "无";
  const dependentContext = dependents.length ? dependents.join("、") : "无";
  const value = (input: string | undefined) => input?.trim() || "未由当前运行记录提供";

  return [
    "你是 " + AGENT_META[agent].label + "，请负责推进前端架构重构计划中的单个 DAG 节点。",
    "",
    "## 目标节点",
    "- ID：" + task.id,
    "- 名称：" + task.label,
    "- 当前状态：" + STATUS_META[task.status].label + "（来源：" + task.statusSource + "）",
    "- 工作项目：" + value(task.project),
    "- 唯一产出：" + value(task.output),
    "- 修改范围：" + value(task.scope),
    "- 计划验证：" + value(task.verify),
    "",
    "## LangGraph 上下文",
    "- graph_id：" + (assistant?.graph_id ?? "refactor_dag"),
    "- assistant_id：" + (assistant?.assistant_id ?? "当前未返回"),
    "- API：" + apiUrl,
    "- 前置依赖：" + dependencyContext,
    "- 后续节点：" + dependentContext,
    "- checkpoint：" + (task.ingestionStatus === "ingested" ? "已进入" : "未确认") + "；这不等同于完成",
    "",
    "## 执行要求",
    "1. 先阅读 /home/musk/code/dcx-web/dcx-web/docs/frontend-architecture-refactor-plan.md 的第 6.2.3 节和第 14 章对应任务行，再检查工作项目当前工作树和已有改动。",
    "2. 只在工作项目和该节点的修改范围内选择最小可交付实现；保留用户已有改动，不触碰无关项目、token、query 或 .env。",
    "3. 先确认前置依赖和当前计划门禁；如果依赖或真实环境证据未满足，不绕过门禁、不伪造状态，明确记录阻塞原因。",
    "4. 完成实现后运行任务声明的最小验证，并记录真实命令、退出码、报告和提交；失败就保持当前状态。",
    "5. 只有获得真实证据后才提升 code-ready/contract-ready；release-ready 还必须完成真实环境、性能、发布与回滚门。",
    "",
    "## 输出格式",
    "说明：完成了什么、修改了哪些文件、验证命令及退出码、剩余门禁/阻塞、建议的下一节点。",
  ].join("\n");
}

function getGroupTitle(group: string) {
  return group === "控制流" ? "控制流" : group;
}

interface LayoutPosition {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface DagLayout {
  groups: string[];
  positions: Map<string, LayoutPosition>;
  width: number;
  height: number;
}

function buildLayout(tasks: DagTask[]): DagLayout {
  const grouped = new Map<string, DagTask[]>();
  tasks.forEach((task) => {
    const list = grouped.get(task.group) ?? [];
    list.push(task);
    grouped.set(task.group, list);
  });

  const groups = Array.from(grouped.keys());
  const laneWidth = 264;
  const nodeWidth = 226;
  const nodeHeight = 78;
  const rowGap = 12;
  const top = 76;
  const positions = new Map<string, LayoutPosition>();
  let maxRows = 1;

  groups.forEach((group, groupIndex) => {
    const items = grouped.get(group) ?? [];
    maxRows = Math.max(maxRows, items.length);
    items.forEach((task, rowIndex) => {
      positions.set(task.id, {
        x: 20 + groupIndex * laneWidth,
        y: top + rowIndex * (nodeHeight + rowGap),
        width: nodeWidth,
        height: nodeHeight,
      });
    });
  });

  return {
    groups,
    positions,
    width: Math.max(1120, groups.length * laneWidth + 20),
    height: Math.max(610, top + maxRows * (nodeHeight + rowGap) + 42),
  };
}

function edgePath(source: LayoutPosition, target: LayoutPosition) {
  const x1 = source.x + source.width;
  const y1 = source.y + source.height / 2;
  const x2 = target.x;
  const y2 = target.y + target.height / 2;
  const bend = Math.max(34, Math.abs(x2 - x1) * 0.42);
  return (
    "M " +
    x1 +
    " " +
    y1 +
    " C " +
    (x1 + bend) +
    " " +
    y1 +
    ", " +
    (x2 - bend) +
    " " +
    y2 +
    ", " +
    x2 +
    " " +
    y2
  );
}

interface StatusPillProps {
  status: DagStatus;
  compact?: boolean;
}

function StatusPill({ status, compact = false }: StatusPillProps) {
  const meta = STATUS_META[status];
  return (
    <span
      className={"status-pill status-" + meta.tone + (compact ? " compact" : "")}
      style={{ "--status-color": meta.color } as CSSProperties}
    >
      <span className="status-dot" />
      {compact ? meta.shortLabel : meta.label}
    </span>
  );
}

interface DetailValueProps {
  value: string;
}

function DetailValue({ value }: DetailValueProps) {
  return <strong title={value}>{value}</strong>;
}

interface StatusProgressProps {
  tasks: DagTask[];
  counts: Record<string, number>;
}

function StatusProgress({ tasks, counts }: StatusProgressProps) {
  const total = tasks.filter((task) => !task.isControl).length;
  const releaseReady = counts["release-ready"] ?? 0;
  const releasePercent = total ? Math.round((releaseReady / total) * 100) : 0;
  const progressLabel = WORKFLOW_STATUSES.filter((status) => (counts[status] ?? 0) > 0)
    .map((status) => STATUS_META[status].label + " " + (counts[status] ?? 0))
    .join("，");

  return (
    <section className="status-overview" aria-labelledby="status-overview-title">
      <div className="status-overview-header">
        <div>
          <span className="status-overview-kicker">WORKFLOW PROGRESS</span>
          <h2 id="status-overview-title">任务状态总览</h2>
        </div>
        <div className="status-overview-summary">
          <strong>{releaseReady}/{total}</strong>
          <span>可发布 · {releasePercent}%</span>
        </div>
      </div>

      <div className="status-progress-track" role="img" aria-label={progressLabel || "暂无业务节点状态"}>
        {WORKFLOW_STATUSES.map((status) => {
          const count = counts[status] ?? 0;
          if (!count || !total) return null;
          return (
            <span
              className="status-progress-segment"
              key={status}
              style={{
                width: (count / total) * 100 + "%",
                backgroundColor: STATUS_META[status].color,
              }}
              title={STATUS_META[status].label + "：" + count + "（" + Math.round((count / total) * 100) + "%）"}
            />
          );
        })}
      </div>

      <div className="status-progress-legend">
        {WORKFLOW_STATUSES.map((status) => {
          const count = counts[status] ?? 0;
          const percent = total ? Math.round((count / total) * 100) : 0;
          return (
            <span className="status-progress-item" key={status}>
              <i
                style={{
                  backgroundColor: STATUS_META[status].color,
                  color: STATUS_META[status].color,
                }}
              />
              <span>{STATUS_META[status].label}</span>
              <em>{percent}%</em>
            </span>
          );
        })}
      </div>
    </section>
  );
}

interface TaskBrief {
  description: string;
  goal: string;
  acceptance: string;
  implementation: string;
}

function getTaskBrief(task: DagTask): TaskBrief {
  return {
    description:
      task.description ??
      "该节点负责「" + task.label + "」，接口未返回更详细的节点说明。",
    goal:
      task.goal ??
      (task.output ? "交付：" + task.output : "完成「" + task.label + "」对应的工作目标。"),
    acceptance:
      task.acceptance ??
      (task.verify ? "验证：" + task.verify : "接口未返回明确的达成条件，请结合状态和验证记录确认。"),
    implementation:
      task.implementation ??
      (task.scope ? "按以下修改范围实施：" + task.scope : "接口未返回实施方案，请先检查前置依赖和修改范围。"),
  };
}

interface DagCanvasProps {
  tasks: DagTask[];
  edges: GraphEdge[];
  selectedId: string | null;
  matchedIds: Set<string>;
  onSelect: (id: string | null) => void;
  onZoom: (nextScale: number) => void;
  scale: number;
}

function DagCanvas({
  tasks,
  edges,
  selectedId,
  matchedIds,
  onSelect,
  onZoom,
  scale,
}: DagCanvasProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef({ active: false, moved: false, startX: 0, startY: 0, scrollLeft: 0, scrollTop: 0 });
  const suppressClickRef = useRef(false);
  const layout = useMemo(() => buildLayout(tasks), [tasks]);
  const related = useMemo(() => relatedTaskIds(selectedId, tasks), [selectedId, tasks]);
  const stageStyle = {
    width: layout.width * scale,
    height: layout.height * scale,
  };
  const worldStyle = {
    width: layout.width,
    height: layout.height,
    transform: "scale(" + scale + ")",
  };

  useEffect(() => {
    if (!selectedId) return;
    const position = layout.positions.get(selectedId);
    const viewport = viewportRef.current;
    if (!position || !viewport) return;

    // 选中节点后把它移到视口中央，筛选结果位于画布较远处时也能直接看到。
    const frame = window.requestAnimationFrame(() => {
      const nodeCenterX = (position.x + position.width / 2) * scale;
      const nodeCenterY = (position.y + position.height / 2) * scale;
      viewport.scrollTo({
        left: nodeCenterX - viewport.clientWidth / 2,
        top: nodeCenterY - viewport.clientHeight / 2,
        behavior: "smooth",
      });
    });

    return () => window.cancelAnimationFrame(frame);
  }, [layout, scale, selectedId]);

  const handleWheel = useCallback((event: globalThis.WheelEvent) => {
    if (!event.ctrlKey) return;
    // Chrome/Firefox 会把 Ctrl+滚轮解释为页面缩放；用 passive:false 的
    // 原生捕获监听同时阻止默认动作和冒泡，确保只改变 DAG 画布的 scale。
    event.preventDefault();
    event.stopPropagation();

    const viewport = viewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const pointerOffsetX = event.clientX - rect.left;
    const pointerOffsetY = event.clientY - rect.top;
    const canvasPointX = pointerOffsetX + viewport.scrollLeft;
    const canvasPointY = pointerOffsetY + viewport.scrollTop;
    const nextScale = clampScale(scale + (event.deltaY > 0 ? -0.08 : 0.08));
    if (nextScale === scale) return;

    onZoom(nextScale);
    requestAnimationFrame(() => {
      const ratio = nextScale / scale;
      viewport.scrollLeft = canvasPointX * ratio - pointerOffsetX;
      viewport.scrollTop = canvasPointY * ratio - pointerOffsetY;
    });
  }, [onZoom, scale]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    // 节点按钮需要保留原生 click 链路；如果在节点上捕获 pointer，后续
    // click 会被重定向到 viewport，导致选中状态被空白画布逻辑清掉。
    const target = event.target;
    if (target instanceof Element && target.closest(".dag-node")) return;
    const viewport = viewportRef.current;
    if (!viewport) return;
    dragRef.current = {
      active: true,
      moved: false,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    };
    viewport.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const viewport = viewportRef.current;
    const drag = dragRef.current;
    if (!viewport || !drag.active) return;
    const deltaX = event.clientX - drag.startX;
    const deltaY = event.clientY - drag.startY;
    if (Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3) drag.moved = true;
    if (!drag.moved) return;
    viewport.scrollLeft = drag.scrollLeft - deltaX;
    viewport.scrollTop = drag.scrollTop - deltaY;
  };

  const finishPointerDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const viewport = viewportRef.current;
    const drag = dragRef.current;
    if (!drag.active) return;
    if (drag.moved) suppressClickRef.current = true;
    drag.active = false;
    if (viewport?.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
  };

  const handleCanvasClick = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    const target = event.target as HTMLElement;
    if (!target.closest(".dag-node")) onSelect(null);
  };

  const handleNodeClick = (id: string) => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    onSelect(id);
  };

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.addEventListener("wheel", handleWheel, { capture: true, passive: false });
    return () => viewport.removeEventListener("wheel", handleWheel, true);
  }, [handleWheel]);

  return (
    <div
      ref={viewportRef}
      className="canvas-scroll"
      aria-label="LangGraph 动态 DAG"
      onClick={handleCanvasClick}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishPointerDrag}
      onPointerCancel={finishPointerDrag}
      onDragStart={(event) => event.preventDefault()}
      title="按住鼠标左键拖拽画布；按住 Ctrl 滚动鼠标滚轮缩放"
    >
      <div className="canvas-stage" style={stageStyle}>
        <div className="canvas-world" style={worldStyle}>
          <svg
            className="dag-edges"
            viewBox={"0 0 " + layout.width + " " + layout.height}
            aria-hidden="true"
          >
            <defs>
              <marker
                id="edge-arrow"
                markerWidth="7"
                markerHeight="7"
                refX="6"
                refY="3.5"
                orient="auto"
              >
                <path d="M0,0 L7,3.5 L0,7" className="edge-arrow" />
              </marker>
            </defs>
            {edges.map((edge) => {
              const source = layout.positions.get(edge.source);
              const target = layout.positions.get(edge.target);
              if (!source || !target) return null;
              const highlighted =
                Boolean(selectedId) && (edge.source === selectedId || edge.target === selectedId);
              const dimmed = Boolean(selectedId) && !highlighted;
              return (
                <path
                  key={edge.source + ">" + edge.target}
                  className={"dag-edge" + (highlighted ? " highlighted" : "") + (dimmed ? " dimmed" : "")}
                  d={edgePath(source, target)}
                  markerEnd="url(#edge-arrow)"
                />
              );
            })}
          </svg>

          {layout.groups.map((group, groupIndex) => (
            <div
              className="dag-lane"
              key={group}
              style={{ left: groupIndex * 264, width: 264 }}
            >
              <div className="lane-heading">
                <span className="lane-index">{String(groupIndex + 1).padStart(2, "0")}</span>
                <span>{getGroupTitle(group)}</span>
              </div>
              <span className="lane-count">{tasks.filter((task) => task.group === group).length} 节点</span>
            </div>
          ))}

          {tasks.map((task) => {
            const position = layout.positions.get(task.id);
            if (!position) return null;
            const matched = matchedIds.has(task.id);
            const relatedNode = !selectedId || related.has(task.id);
            const statusMeta = STATUS_META[task.status];
            const className =
              "dag-node" +
              (task.isControl ? " control-node" : "") +
              (task.id === selectedId ? " selected" : "") +
              (!matched ? " filtered" : "") +
              (!relatedNode ? " unrelated" : "");
            return (
              <button
                className={className}
                data-task-id={task.id}
                key={task.id}
                type="button"
                onClick={() => handleNodeClick(task.id)}
                style={
                  {
                    left: position.x,
                    top: position.y,
                    width: position.width,
                    height: position.height,
                    "--status-color": statusMeta.color,
                  } as CSSProperties
                }
                title={"查看 " + task.id}
              >
                <span className="node-topline">
                  <span className="node-id">{task.id}</span>
                  <StatusPill status={task.status} />
                </span>
                <span className="node-label">{task.label}</span>
                <span className="node-meta">
                  <span className="node-status-label" title={statusMeta.label}>
                    {statusMeta.label}
                  </span>
                  <span>{task.deps.length ? task.deps.length + " 个前置" : "无前置"}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <Workflow size={22} />
      </div>
      <strong>{message}</strong>
      <span>页面数据完全来自 LangGraph graph API。</span>
    </div>
  );
}

function AgentDagLinks({ agents, taskVersion, bindings }: { agents: Agent[]; taskVersion: string; bindings: Record<string, string> }) {
  const [lines, setLines] = useState<Array<{ id: string; x1: number; y1: number; x2: number; y2: number }>>([]);
  useEffect(() => {
    const update = () => {
      const workspace = document.querySelector<HTMLElement>(".workspace-linked");
      if (!workspace) return;
      const root = workspace.getBoundingClientRect();
      // 画布可视区域（.canvas-scroll 的视口）在 workspace 坐标系下的边界。
      // 目标节点滚出可视区时，虚线终点钳制到该边框，不再跟随节点跑到屏外。
      const viewport = workspace.querySelector<HTMLElement>(".canvas-scroll");
      const viewportRect = viewport?.getBoundingClientRect();
      let hasViewport = false;
      let borderLeft = 0;
      let borderTop = 0;
      let borderRight = 0;
      let borderBottom = 0;
      if (viewportRect && viewportRect.width > 0 && viewportRect.height > 0) {
        borderLeft = viewportRect.left - root.left + 4;
        borderTop = viewportRect.top - root.top + 4;
        borderRight = viewportRect.right - root.left - 8;
        borderBottom = viewportRect.bottom - root.top - 8;
        hasViewport = borderRight > borderLeft && borderBottom > borderTop;
      }
      const next = agents.flatMap((agent) => {
        const name = String(agent.agent ?? "").toLowerCase();
        // Agent Board 的 agent 名称通常包含任务节点 ID；也兼容最后阶段字段。
        const stage = String(agent.last?.stage ?? "").toLowerCase();
        const taskNodes = Array.from(document.querySelectorAll<HTMLElement>("[data-task-id]"));
        const assignedTaskId = bindings[String(agent.agent ?? "")];
        const target = (assignedTaskId && taskNodes.find((node) => node.dataset.taskId === assignedTaskId)) ?? taskNodes.find((node) => {
          const id = String(node.dataset.taskId ?? "").toLowerCase();
          return id && (name.includes(id) || stage === id || name === id);
        });
        // 不使用 CSS.escape，兼容旧版浏览器及包含特殊字符的 Agent 名称。
        const source = Array.from(document.querySelectorAll<HTMLElement>("[data-agent]"))
          .find((node) => node.dataset.agent === String(agent.agent ?? ""));
        if (!target || !source) return [];
        const from = source.getBoundingClientRect();
        const to = target.getBoundingClientRect();
        let x2 = to.left - root.left;
        let y2 = to.top + to.height / 2 - root.top;
        if (hasViewport && (x2 < borderLeft || x2 > borderRight || y2 < borderTop || y2 > borderBottom)) {
          x2 = Math.min(Math.max(x2, borderLeft), borderRight);
          y2 = Math.min(Math.max(y2, borderTop), borderBottom);
        }
        return [{ id: String(agent.agent), x1: from.right - root.left, y1: from.top + from.height / 2 - root.top, x2, y2 }];
      });
      setLines(next);
    };
    update();
    const observer = new ResizeObserver(update);
    const workspace = document.querySelector<HTMLElement>(".workspace-linked");
    if (workspace) observer.observe(workspace);
    const viewport = workspace?.querySelector<HTMLElement>(".canvas-scroll");
    if (viewport) observer.observe(viewport);
    const handleViewportScroll = () => update();
    viewport?.addEventListener("scroll", handleViewportScroll, { passive: true });
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => { observer.disconnect(); viewport?.removeEventListener("scroll", handleViewportScroll); window.removeEventListener("resize", update); window.removeEventListener("scroll", update, true); };
  }, [agents, taskVersion, bindings]);
  return <svg className="agent-dag-links" aria-hidden="true"><defs><marker id="agent-link-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" /></marker></defs>{lines.map((line) => { const bend = Math.max(24, (line.x2 - line.x1) * .35); return <path key={line.id} d={`M ${line.x1} ${line.y1} C ${line.x1 + bend} ${line.y1}, ${line.x2 - bend} ${line.y2}, ${line.x2} ${line.y2}`} />; })}</svg>;
}

export default function App() {
  const [tasks, setTasks] = useState<DagTask[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [backend, setBackend] = useState<BackendStatus>({
    connected: false,
    checkedAt: "",
  });
  const [assistant, setAssistant] = useState<Assistant | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<TaskFilter>("all");
  const [query, setQuery] = useState("");
  const [scale, setScale] = useState(0.82);
  const [isLoading, setIsLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState("");
  const [lastSync, setLastSync] = useState("");
  const [copied, setCopied] = useState(false);
  const [agentByTask, setAgentByTask] = useState<Record<string, AgentKind>>({});
  const [workspaceByTask, setWorkspaceByTask] = useState<Record<string, AgentWorkspace>>({});
  const [agentPrompt, setAgentPrompt] = useState("");
  const [launchingAgent, setLaunchingAgent] = useState<AgentKind | null>(null);
  const [agentLaunchMessage, setAgentLaunchMessage] = useState("");
  const [agentLaunchError, setAgentLaunchError] = useState("");
  const [evidenceStatus, setEvidenceStatus] = useState<EvidenceReadyStatus>("contract-ready");
  const [syncingEvidence, setSyncingEvidence] = useState(false);
  const [evidenceSyncMessage, setEvidenceSyncMessage] = useState("");
  const [evidenceSyncError, setEvidenceSyncError] = useState("");
  const [agentSnapshot, setAgentSnapshot] = useState<AgentBoardSnapshot>([]);
  const [agentTaskByPid, setAgentTaskByPid] = useState<Record<string, string>>({});
  const terminalRef = useRef<TerminalPanelHandle>(null);
  const [pendingAgentTasks, setPendingAgentTasks] = useState<string[]>([]);
  const [agentBindings, setAgentBindings] = useState<Record<string, string>>({});
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return localStorage.getItem("refactor-control-room-theme") === "light" ? "light" : "dark";
    } catch {
      return "dark";
    }
  });

  useEffect(() => {
    document.body.dataset.theme = theme;
    localStorage.setItem("refactor-control-room-theme", theme);
  }, [theme]);

  const refresh = useCallback(async () => {
    setError("");
    setIsRunning(true);
    try {
      const backendStatus = await checkBackend();
      setBackend(backendStatus);
      if (!backendStatus.connected || !backendStatus.assistantId) {
        throw new Error(backendStatus.error ?? "LangGraph 服务不可用");
      }

      const currentAssistant: Assistant = {
        assistant_id: backendStatus.assistantId,
        graph_id: backendStatus.graphId ?? "refactor_dag",
      };
      setAssistant(currentAssistant);

      const definition = await loadGraphDefinition(currentAssistant.assistant_id);
      setEdges(definition.edges);

      let liveRecords: LiveTaskRecord[] = [];
      try {
        liveRecords = await runLangGraph(currentAssistant.assistant_id);
      } catch (runError) {
        setError(
          "图结构已从 LangGraph 加载，但本次运行状态同步失败：" +
            (runError instanceof Error ? runError.message : "未知错误"),
        );
      }

      setTasks(materializeTasks(definition, liveRecords));
      setLastSync(new Date().toISOString());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "LangGraph 加载失败");
    } finally {
      setIsLoading(false);
      setIsRunning(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const businessTasks = useMemo(() => tasks.filter((task) => !task.isControl), [tasks]);
  const counts = useMemo(() => statusCounts(tasks), [tasks]);
  const matchedTasks = useMemo(
    () => tasks.filter((task) => taskMatchesFilter(task, query, filter)),
    [filter, query, tasks],
  );
  const matchedIds = useMemo(() => new Set(matchedTasks.map((task) => task.id)), [matchedTasks]);
  const selectedTask = tasks.find((task) => task.id === selectedId) ?? null;
  const selectedMatchIndex = matchedTasks.findIndex((task) => task.id === selectedId);
  const searchResultPosition = selectedMatchIndex >= 0 ? selectedMatchIndex + 1 : 1;
  const selectedBrief = selectedTask ? getTaskBrief(selectedTask) : null;
  const selectedDependents = selectedTask
    ? tasks.filter((task) => task.deps.includes(selectedTask.id))
    : [];
  const releaseReadyCount = businessTasks.filter((task) => task.status === "release-ready").length;
  const selectedAgent = selectedTask ? agentByTask[selectedTask.id] ?? null : null;
  const selectedWorkspace = selectedTask
    ? workspaceByTask[selectedTask.id] ?? inferAgentWorkspace(selectedTask)
    : "APP18";

  useEffect(() => {
    if (!selectedTask || !selectedAgent) {
      setAgentPrompt("");
      setAgentLaunchMessage("");
      setAgentLaunchError("");
      return;
    }
    setAgentPrompt(buildAgentPrompt(selectedAgent, selectedTask, tasks, assistant, displayApiUrl));
    setAgentLaunchMessage("");
    setAgentLaunchError("");
  }, [selectedAgent, selectedId]);

  const handleQueryChange = (nextQuery: string) => {
    setQuery(nextQuery);
    if (!nextQuery.trim()) return;

    const nextMatches = tasks.filter((task) => taskMatchesFilter(task, nextQuery, filter));
    setSelectedId(nextMatches[0]?.id ?? null);
  };

  const navigateSearchResult = (offset: -1 | 1) => {
    if (matchedTasks.length < 2) return;
    const currentIndex = selectedMatchIndex >= 0 ? selectedMatchIndex : 0;
    const nextIndex = (currentIndex + offset + matchedTasks.length) % matchedTasks.length;
    setSelectedId(matchedTasks[nextIndex].id);
  };

  const handleFilterClick = (nextFilter: TaskFilter) => {
    // “全部”只切换筛选状态；其他类型按钮同时承担结果节点的循环导航。
    if (nextFilter === "all") {
      setFilter(nextFilter);
      return;
    }

    const nextMatches = tasks.filter((task) => taskMatchesFilter(task, query, nextFilter));
    if (!nextMatches.length) {
      setFilter(nextFilter);
      setSelectedId(null);
      return;
    }

    const currentIndex =
      filter === nextFilter ? nextMatches.findIndex((task) => task.id === selectedId) : -1;
    const nextTask = nextMatches[(currentIndex + 1) % nextMatches.length];
    setFilter(nextFilter);
    setSelectedId(nextTask.id);
  };

  const copySelectedId = async () => {
    if (!selectedTask) return;
    await navigator.clipboard?.writeText(selectedTask.id);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1300);
  };

  const selectAgent = (kind: AgentKind) => {
    if (!selectedTask || launchingAgent) return;
    setAgentByTask((current) => ({ ...current, [selectedTask.id]: kind }));
  };

  const selectWorkspace = (workspace: AgentWorkspace) => {
    if (!selectedTask || launchingAgent) return;
    setWorkspaceByTask((current) => ({ ...current, [selectedTask.id]: workspace }));
  };

  const buildInjectedPrompt = () => {
    const task = selectedTask;
    if (!task) return "";
    return [
      agentPrompt.trim(),
      "",
      "[系统注入要求]",
      `本次处理的 DAG 节点 ID 是：${task.id}`,
      `请在你的思维链中原样输出一次节点 ID：${task.id}`,
      "只需要输出一次该节点 ID，后续不要重复输出。",
    ].join("\n");
  };

  // 主链路：属性栏拉起 Agent 时，直接在画布下方命令行开一个新 Tab 并运行，
  // Agent 跑完后 Tab 保留为可交互 shell，可继续敲命令。
  const launchSelectedAgent = () => {
    const task = selectedTask;
    const kind = selectedAgent;
    if (!task || !kind || launchingAgent) return;
    if (!agentPrompt.trim()) {
      setAgentLaunchError("提示词不能为空");
      return;
    }
    setAgentLaunchMessage("");
    setAgentLaunchError("");
    const handler = terminalRef.current;
    if (!handler) {
      setAgentLaunchError("页内终端尚未就绪，请稍后重试（或用外部 Konsole）");
      return;
    }
    handler.openAgentTerminal({
      agent: kind,
      taskId: task.id,
      prompt: buildInjectedPrompt(),
      workspace: selectedWorkspace,
    });
    setAgentLaunchMessage(`${AGENT_META[kind].label} 已在下方命令行新开 Tab（${selectedWorkspace} · ${task.id}），正在启动…`);
    setPendingAgentTasks((current) => (current.includes(task.id) ? current : [...current, task.id]));
  };

  // 兜底链路：保留原来的外部 Konsole 弹窗方式。
  const launchSelectedAgentExternal = async () => {
    const task = selectedTask;
    const kind = selectedAgent;
    if (!task || !kind || launchingAgent) return;
    if (!agentPrompt.trim()) {
      setAgentLaunchError("提示词不能为空");
      return;
    }
    setAgentLaunchMessage("");
    setAgentLaunchError("");
    setLaunchingAgent(kind);
    try {
      const result = await launchAgent({
        agent: kind,
        taskId: task.id,
        prompt: buildInjectedPrompt(),
        workspace: selectedWorkspace,
      });
      setAgentLaunchMessage(result.message ?? `${AGENT_META[kind].label} 已在 ${selectedWorkspace} 启动`);
      if (result.pid && task.id) setAgentTaskByPid((current) => ({ ...current, [String(result.pid)]: task.id }));
      setPendingAgentTasks((current) => current.includes(task.id) ? current : [...current, task.id]);
    } catch (launchError) {
      setAgentLaunchError(
        launchError instanceof Error ? launchError.message : "Agent 启动失败",
      );
    } finally {
      setLaunchingAgent(null);
    }
  };

  const syncSelectedEvidence = async () => {
    const task = selectedTask;
    if (!task || !task.evidence?.length || syncingEvidence) return;
    setEvidenceSyncMessage("");
    setEvidenceSyncError("");
    setSyncingEvidence(true);
    try {
      const result = await syncTaskEvidence({ taskId: task.id, status: evidenceStatus });
      setEvidenceSyncMessage(
        `${result.status} 已同步，证据 ${result.evidenceCount} 条，commit ${result.commit}`,
      );
      await refresh();
    } catch (syncError) {
      setEvidenceSyncError(syncError instanceof Error ? syncError.message : "证据同步失败");
    } finally {
      setSyncingEvidence(false);
    }
  };

  const filterItems: Array<{ id: TaskFilter; label: string; count: number; color?: string }> = [
    { id: "all", label: "全部", count: businessTasks.length },
    ...WORKFLOW_STATUSES.map((status) => ({
      id: status,
      label: STATUS_META[status].label,
      count: counts[status] ?? 0,
      color: STATUS_META[status].color,
    })),
  ];

  if (isLoading && tasks.length === 0) {
    return (
      <main className="app-loading">
        <div className="loading-orbit">
          <Workflow size={28} />
        </div>
        <strong>正在从 LangGraph 加载 DAG</strong>
        <span>读取 graph definition，并同步一次运行状态…</span>
      </main>
    );
  }

  return (
    <main className={"dashboard-shell " + (theme === "light" ? "theme-light" : "")}>
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <Workflow size={19} />
          </div>
          <div>
            <strong>Refactor Control Room</strong>
            <span>重构工作流控制台</span>
          </div>
        </div>
        <div className="topbar-actions">
          <span className={"connection-badge " + (backend.connected ? "online" : "offline")}>
            <span className="connection-dot" />
            {backend.connected ? "LangGraph 已连接" : "LangGraph 未连接"}
          </span>
          <button className="button button-ghost" type="button" onClick={() => void refresh()} disabled={isRunning}>
            <RefreshCw size={15} className={isRunning ? "spin" : ""} />
            {isRunning ? "同步中" : "重新同步"}
          </button>
          <button
            className="theme-toggle"
            type="button"
            onClick={() => setTheme((value) => (value === "dark" ? "light" : "dark"))}
            title={theme === "dark" ? "切换浅色模式" : "切换深色模式"}
          >
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
            <span>{theme === "dark" ? "浅色" : "深色"}</span>
          </button>
          <a
            className="button button-primary"
            href={displayApiUrl + "/docs"}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={15} />
            后端 API
          </a>
        </div>
      </header>

      {error ? (
        <div className="notice notice-warning">
          <AlertCircle size={17} />
          <span>{error}</span>
          <button type="button" onClick={() => setError("")} aria-label="关闭提示">
            <X size={15} />
          </button>
        </div>
      ) : null}

      <StatusProgress tasks={tasks} counts={counts} />

      <section className="workspace workspace-linked">
        <AgentBoard onAgentsChange={(agents) => {
          setAgentSnapshot(agents);
          const pending = pendingAgentTasks.filter((taskId) => !Object.values(agentBindings).includes(taskId));
          const next = { ...agentBindings };
          const unbound = agents.filter((agent) => !next[String(agent.agent ?? "")]);
          pending.forEach((taskId) => {
            const match = unbound.find((agent) => {
              const text = JSON.stringify(agent).toLowerCase();
              return text.includes(taskId.toLowerCase());
            });
            if (match?.agent) next[String(match.agent)] = taskId;
          });
          if (Object.keys(next).length !== Object.keys(agentBindings).length) setAgentBindings(next);
        }} />
        <div className="graph-panel">
          <div className="panel-header">
            <div className="panel-heading">
              <div className="panel-title-row">
                <h2>完整 DAG</h2>
                <span className="api-badge">来自 /graph</span>
              </div>
            </div>
            <div className="graph-toolbar">
              <label className="search-box">
                <Search size={16} />
                <input
                  value={query}
                  onChange={(event) => handleQueryChange(event.target.value)}
                  placeholder="搜索任务 ID、分组或节点类型…"
                  aria-label="搜索任务"
                />
                {query && matchedTasks.length ? (
                  <span className="search-result-count" aria-live="polite">
                    {searchResultPosition}/{matchedTasks.length}
                  </span>
                ) : null}
                {query && matchedTasks.length > 1 ? (
                  <span className="search-result-nav" aria-label="切换搜索结果">
                    <button
                      type="button"
                      onClick={() => navigateSearchResult(-1)}
                      aria-label="聚焦上一个搜索结果"
                      title="上一个搜索结果"
                    >
                      <ChevronUp size={14} />
                    </button>
                    <button
                      type="button"
                      onClick={() => navigateSearchResult(1)}
                      aria-label="聚焦下一个搜索结果"
                      title="下一个搜索结果"
                    >
                      <ChevronDown size={14} />
                    </button>
                  </span>
                ) : null}
                {query ? (
                  <button type="button" onClick={() => setQuery("")} aria-label="清除搜索" className="search-clear">
                    <X size={14} />
                  </button>
                ) : null}
              </label>
              <div className="filter-tabs" role="tablist" aria-label="状态筛选">
                {filterItems.map((item) => (
                  <button
                    className={filter === item.id ? "active" : ""}
                    key={item.id}
                    type="button"
                    onClick={() => handleFilterClick(item.id)}
                    role="tab"
                    aria-selected={filter === item.id}
                    aria-label={
                      item.id === "all"
                        ? "显示全部节点"
                        : "筛选" + item.label + "并聚焦下一个节点"
                    }
                  >
                    {item.color ? (
                      <i
                        className="filter-dot"
                        aria-hidden="true"
                        style={{ backgroundColor: item.color }}
                      />
                    ) : null}
                    {item.label}
                    <span>{item.count}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="graph-tools">
              <button type="button" onClick={() => setScale((value) => clampScale(value - 0.1))} title="缩小">
                <ZoomOut size={16} />
              </button>
              <span className="zoom-value">{Math.round(scale * 100)}%</span>
              <button type="button" onClick={() => setScale((value) => clampScale(value + 0.1))} title="放大">
                <ZoomIn size={16} />
              </button>
              <button type="button" onClick={() => setScale(0.82)} title="重置缩放">
                <LocateFixed size={16} />
              </button>
              <span className="zoom-hint">拖拽移动 · Ctrl + 滚轮</span>
            </div>
          </div>

          {tasks.length ? (
            <DagCanvas
              tasks={tasks}
              edges={edges}
              selectedId={selectedId}
              matchedIds={matchedIds}
              onSelect={setSelectedId}
              onZoom={setScale}
              scale={scale}
            />
          ) : (
            <EmptyState message="LangGraph 没有返回节点" />
          )}
          <TerminalPanel ref={terminalRef} theme={theme} defaultWorkspace={selectedWorkspace} />
        </div>

        <aside className={"details-panel " + (selectedTask ? "has-selection" : "")}>
          {selectedTask ? (
            <>
              <div className="details-header">
                <div>
                  <span className="details-kicker">NODE INSPECTOR</span>
                  <h2 title={selectedTask.id}>{selectedTask.id}</h2>
                </div>
                <button type="button" className="icon-button" onClick={() => setSelectedId(null)} aria-label="关闭详情">
                  <X size={17} />
                </button>
              </div>
              <div className="details-status">
                <StatusPill status={selectedTask.status} />
                <span className="ingestion-state">
                  <span className="status-dot" />
                  {selectedTask.ingestionStatus === "ingested" ? "已进入 checkpoint" : "未同步 checkpoint"}
                </span>
              </div>
              <h3 className="task-name" title={selectedTask.label}>{selectedTask.label}</h3>
              <div className="task-brief" aria-label="节点说明">
                <div className="task-brief-item">
                  <span>节点说明</span>
                  <p>{selectedBrief?.description}</p>
                </div>
                <div className="task-brief-item">
                  <span>目标</span>
                  <p>{selectedBrief?.goal}</p>
                </div>
                <div className="task-brief-item">
                  <span>达成条件</span>
                  <p>{selectedBrief?.acceptance}</p>
                </div>
                <div className="task-brief-item">
                  <span>实施方案</span>
                  <p>{selectedBrief?.implementation}</p>
                </div>
              </div>
              <div className="detail-list">
                <div><span>节点类型</span><DetailValue value={selectedTask.type} /></div>
                <div><span>分组</span><DetailValue value={selectedTask.group} /></div>
                <div><span>工作项目</span><DetailValue value={selectedTask.project ?? "未返回"} /></div>
                <div><span>唯一产出</span><DetailValue value={selectedTask.output ?? "未返回"} /></div>
                <div><span>修改范围</span><DetailValue value={selectedTask.scope ?? "未返回"} /></div>
                <div><span>计划验证</span><DetailValue value={selectedTask.verify ?? "未返回"} /></div>
                <div><span>状态来源</span><DetailValue value={selectedTask.statusSource} /></div>
                <div><span>证据数量</span><DetailValue value={String(selectedTask.evidence?.length ?? 0)} /></div>
                <div><span>提交</span><DetailValue value={selectedTask.commit ?? "未返回"} /></div>
                <div><span>数据来源</span><DetailValue value="LangGraph graph + run API + evidence manifest" /></div>
              </div>

              <div className="evidence-block">
                <div className="section-label">
                  接收并同步证据 <span>{selectedTask.evidence?.length ?? 0}</span>
                </div>
                <p className="evidence-note">
                  只接收 manifest 中 checks 全部 exit=0 的证据；同步会先校验前置依赖，不直接改写普通 graph state。
                </p>
                {selectedTask.commits ? (
                  <div className="commit-list">
                    {Object.entries(selectedTask.commits).map(([project, commit]) => (
                      <span key={project} title={commit}>{project} {commit}</span>
                    ))}
                  </div>
                ) : null}
                <div className="evidence-controls">
                  <label htmlFor="evidence-status">目标状态</label>
                  <select
                    id="evidence-status"
                    value={evidenceStatus}
                    onChange={(event) => setEvidenceStatus(event.target.value as EvidenceReadyStatus)}
                    disabled={syncingEvidence}
                  >
                    <option value="contract-ready">contract-ready</option>
                    <option value="code-ready">code-ready</option>
                  </select>
                  <button
                    className="button button-primary"
                    type="button"
                    onClick={() => void syncSelectedEvidence()}
                    disabled={syncingEvidence || !selectedTask.evidence?.length}
                  >
                    {syncingEvidence ? <RefreshCw size={14} className="spin" /> : <Check size={14} />}
                    {syncingEvidence ? "同步中…" : "接收证据"}
                  </button>
                </div>
                {!selectedTask.evidence?.length ? <p className="muted-copy">当前节点没有可接收的 manifest 证据。</p> : null}
                {evidenceSyncMessage ? <p className="launch-feedback success">{evidenceSyncMessage}</p> : null}
                {evidenceSyncError ? <p className="launch-feedback error">{evidenceSyncError}</p> : null}
              </div>

              <div className="agent-block">
                <div className="section-label">
                  选择处理 Agent / 工作项目 <span>3</span>
                </div>
                <div className="agent-workspace-row">
                  <label htmlFor="agent-workspace-select">白名单项目</label>
                  <select
                    id="agent-workspace-select"
                    value={selectedWorkspace}
                    onChange={(event) => selectWorkspace(event.target.value as AgentWorkspace)}
                    disabled={launchingAgent !== null}
                  >
                    {(Object.keys(AGENT_WORKSPACE_META) as AgentWorkspace[]).map((workspace) => (
                      <option key={workspace} value={workspace}>
                        {AGENT_WORKSPACE_META[workspace].label}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="agent-note workspace-note">
                  仅允许 APP18、APP19、APP20 白名单目录；当前路径：{AGENT_WORKSPACE_META[selectedWorkspace].path}
                </p>
                <div className="agent-options" role="radiogroup" aria-label="选择处理 Agent">
                  {(Object.keys(AGENT_META) as AgentKind[]).map((kind) => (
                    <button
                      className={selectedAgent === kind ? "active" : ""}
                      key={kind}
                      type="button"
                      onClick={() => selectAgent(kind)}
                      disabled={launchingAgent !== null}
                      role="radio"
                      aria-checked={selectedAgent === kind}
                      title={"选择 " + AGENT_META[kind].label + "：" + AGENT_META[kind].hint}
                    >
                      <Terminal size={12} />
                      {AGENT_META[kind].label}
                    </button>
                  ))}
                </div>
                {selectedAgent ? (
                  <div className="agent-prompt-editor">
                    <label htmlFor="agent-prompt-input">提示词（可编辑）</label>
                    <textarea
                      id="agent-prompt-input"
                      value={agentPrompt}
                      onChange={(event) => setAgentPrompt(event.target.value)}
                      rows={10}
                      spellCheck={false}
                    />
                    <button
                      className="button button-primary agent-launch-button"
                      type="button"
                      onClick={() => launchSelectedAgent()}
                      disabled={launchingAgent !== null}
                    >
                      <Terminal size={15} />
                      在下方终端拉起
                    </button>
                    <button
                      className="button button-ghost agent-launch-button"
                      type="button"
                      onClick={() => void launchSelectedAgentExternal()}
                      disabled={launchingAgent !== null}
                      title="兜底：仍用外部 Konsole 窗口启动"
                    >
                      {launchingAgent ? <RefreshCw size={15} className="spin" /> : <Terminal size={15} />}
                      {launchingAgent ? "拉起中…" : "外部 Konsole 拉起"}
                    </button>
                  </div>
                ) : null}
                <p className="agent-note">选择 Agent 后可编辑提示词；「在下方终端拉起」会在画布下方命令行新开一个 Tab 并运行，跑完后可继续交互；「外部 Konsole 拉起」仍用原来的外部窗口方式。</p>
                {agentLaunchMessage ? <p className="launch-feedback success">{agentLaunchMessage}</p> : null}
                {agentLaunchError ? <p className="launch-feedback error">{agentLaunchError}</p> : null}
              </div>

              <div className="relation-block">
                <div className="section-label">前置依赖 <span>{selectedTask.deps.length}</span></div>
                {selectedTask.deps.length ? (
                  <div className="relation-list">
                    {selectedTask.deps.map((dependency) => (
                      <button
                        type="button"
                        key={dependency}
                        title={dependency}
                        onClick={() => setSelectedId(dependency)}
                      >
                        <ChevronRight size={13} />
                        {dependency}
                      </button>
                    ))}
                  </div>
                ) : <p className="muted-copy">这是一个入口节点，没有前置依赖。</p>}
              </div>

              <div className="relation-block">
                <div className="section-label">后续节点 <span>{selectedDependents.length}</span></div>
                {selectedDependents.length ? (
                  <div className="relation-list">
                    {selectedDependents.map((dependent) => (
                      <button
                        type="button"
                        key={dependent.id}
                        title={dependent.id}
                        onClick={() => setSelectedId(dependent.id)}
                      >
                        <ChevronRight size={13} />
                        {dependent.id}
                        <StatusPill status={dependent.status} compact />
                      </button>
                    ))}
                  </div>
                ) : <p className="muted-copy">没有直接后续节点，可能是出口节点。</p>}
              </div>

              <div className="detail-actions">
                <button className="button button-secondary" type="button" onClick={() => void copySelectedId()}>
                  {copied ? <Check size={15} /> : <Copy size={15} />}
                  {copied ? "已复制" : "复制节点 ID"}
                </button>
                <button className="button button-secondary" type="button" onClick={() => setFilter("all")}>
                  <LocateFixed size={15} />
                  显示全部关系
                </button>
              </div>
            </>
          ) : (
            <div className="details-empty">
              <span className="details-kicker">NODE INSPECTOR</span>
              <div className="details-empty-orbit" aria-hidden="true">
                <div className="details-empty-icon"><MousePointerClick size={22} /></div>
              </div>
              <h2>尚未选中节点</h2>
              <p>点击画布上的任意节点，在这里查看状态、依赖与证据，并拉起 Agent 推进。</p>
              <div className="details-empty-stats" aria-label="当前任务统计">
                <span><b>{businessTasks.length}</b>业务节点</span>
                <i />
                <span><b>{releaseReadyCount}</b>可发布</span>
              </div>
              <ul className="details-empty-steps">
                <li>
                  <Search size={13} />
                  <span><b>搜索定位</b>按 ID、分组或类型找节点</span>
                </li>
                <li>
                  <MousePointerClick size={13} />
                  <span><b>点击查看</b>状态、前置与后续依赖</span>
                </li>
                <li>
                  <Terminal size={13} />
                  <span><b>下方终端</b>拉起 Agent 直接开干</span>
                </li>
              </ul>
              <div className="tip">
                <Info size={15} />
                选中节点后，画布会自动弱化无关连线。
              </div>
            </div>
          )}
        </aside>
        <AgentDagLinks agents={agentSnapshot} bindings={{ ...Object.fromEntries(Object.entries(agentTaskByPid).map(([pid, taskId]) => [String(agentSnapshot.find((agent) => String(agent.pid) === pid)?.agent ?? pid), taskId])), ...agentBindings }} taskVersion={`${tasks.length}:${scale}:${selectedId ?? ""}`} />
      </section>

      <footer className="footer-note">
        <span><Info size={14} />代码/合同就绪不等于正式可发布；当前正式可发布 {releaseReadyCount}/{businessTasks.length}。</span>
        <span>最后同步：{formatDate(lastSync)}</span>
      </footer>
    </main>
  );
}
