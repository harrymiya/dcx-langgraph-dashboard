import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, MouseEvent as ReactMouseEvent } from "react";
import {
  Activity,
  AlertCircle,
  Check,
  ChevronRight,
  Copy,
  Database,
  ExternalLink,
  GitBranch,
  Info,
  LocateFixed,
  PanelRight,
  RefreshCw,
  Search,
  Server,
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
  loadGraphDefinition,
  runLangGraph,
} from "./api";
import {
  groupForNode,
  isReadyStatus,
  relatedTaskIds,
  STATUS_META,
  taskMatchesFilter,
} from "./graph";
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

type TaskFilter = "all" | "blocked" | "in-progress" | "planned" | "ready";
type Theme = "dark" | "light";

const CONTROL_NODES = new Set(["__start__", "__end__"]);

const AGENT_META: Record<AgentKind, { label: string; hint: string }> = {
  opencode: { label: "OpenCode", hint: "适合直接在仓库内执行改动" },
  pi: { label: "Pi", hint: "适合快速拆解和推进单个切片" },
  codex: { label: "Codex", hint: "适合带门禁验证完成实现" },
};

const clampScale = (value: number) => Math.min(1.2, Math.max(0.58, value));

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
      section: live?.section,
      project: live?.project,
      output: live?.output,
      scope: live?.scope,
      verify: live?.verify,
      evidence: live?.evidence,
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

  const handleCanvasClick = (event: ReactMouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (!target.closest(".dag-node")) onSelect(null);
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
      title="按住 Ctrl 滚动鼠标滚轮缩放画布"
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
                Boolean(selectedId) && related.has(edge.source) && related.has(edge.target);
              const dimmed =
                Boolean(selectedId) && !highlighted && edge.source !== selectedId && edge.target !== selectedId;
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
                key={task.id}
                type="button"
                onClick={() => onSelect(task.id)}
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
                  <StatusPill status={task.status} compact />
                </span>
                <span className="node-label">{task.label}</span>
                <span className="node-meta">
                  <span>{task.type}</span>
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
  const [promptCopied, setPromptCopied] = useState(false);
  const [agentByTask, setAgentByTask] = useState<Record<string, AgentKind>>({});
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
  }, [refresh]);

  const businessTasks = useMemo(() => tasks.filter((task) => !task.isControl), [tasks]);
  const counts = useMemo(() => statusCounts(tasks), [tasks]);
  const matchedIds = useMemo(
    () =>
      new Set(
        tasks
          .filter((task) => taskMatchesFilter(task, query, filter))
          .map((task) => task.id),
      ),
    [filter, query, tasks],
  );
  const selectedTask = tasks.find((task) => task.id === selectedId) ?? null;
  const selectedDependents = selectedTask
    ? tasks.filter((task) => task.deps.includes(selectedTask.id))
    : [];
  const readyCount = businessTasks.filter((task) => isReadyStatus(task.status)).length;
  const releaseReadyCount = businessTasks.filter((task) => task.status === "release-ready").length;
  const selectedAgent = selectedTask ? agentByTask[selectedTask.id] ?? "codex" : "codex";
  const agentPrompt = selectedTask
    ? buildAgentPrompt(selectedAgent, selectedTask, tasks, assistant, displayApiUrl)
    : "";

  const copySelectedId = async () => {
    if (!selectedTask) return;
    await navigator.clipboard?.writeText(selectedTask.id);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1300);
  };

  const copyAgentPrompt = async () => {
    if (!agentPrompt) return;
    await navigator.clipboard?.writeText(agentPrompt);
    setPromptCopied(true);
    window.setTimeout(() => setPromptCopied(false), 1500);
  };

  const filterItems: Array<{ id: TaskFilter; label: string; count?: number }> = [
    { id: "all", label: "全部", count: businessTasks.length },
    { id: "blocked", label: "阻塞", count: counts.blocked ?? 0 },
    { id: "in-progress", label: "进行中", count: counts["in-progress"] ?? 0 },
    { id: "planned", label: "计划中", count: counts.planned ?? 0 },
    { id: "ready", label: "工程/合同就绪", count: readyCount },
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

      <section className="hero">
        <div className="hero-copy">
          <div className="eyebrow">
            <Activity size={14} />
            LIVE GRAPH VIEW
          </div>
          <h1>重构 DAG 控制台</h1>
          <p>
            节点、依赖和运行状态全部来自当前 LangGraph API。点击节点查看上下游关系，
            用筛选快速定位下一步工作。
          </p>
          <div className="hero-tags">
            <span><Server size={13} />后端：LangGraph</span>
            <span><GitBranch size={13} />graph：{assistant?.graph_id ?? "refactor_dag"}</span>
            <span><Database size={13} />动态节点：{businessTasks.length}</span>
          </div>
        </div>
        <div className="sync-card">
          <div className="sync-card-heading">
            <span className="live-pulse" />
            <span>实时连接</span>
            <span className="sync-time">{formatDate(lastSync)}</span>
          </div>
          <div className="sync-api">{displayApiUrl}</div>
          <div className="sync-card-foot">
            <span>{edges.length} 条依赖边</span>
            <span>API schema 动态读取</span>
          </div>
        </div>
      </section>

      {error ? (
        <div className="notice notice-warning">
          <AlertCircle size={17} />
          <span>{error}</span>
          <button type="button" onClick={() => setError("")} aria-label="关闭提示">
            <X size={15} />
          </button>
        </div>
      ) : null}

      <section className="workspace">
        <div className="graph-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <h2>完整 DAG</h2>
                <span className="api-badge">来自 /graph</span>
              </div>
              <p>横向滚动浏览所有分组；点击节点后，仅突出显示它的直接上下游，点击空白处取消选中。</p>
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
              <span className="zoom-hint">Ctrl + 滚轮</span>
            </div>
          </div>

          <div className="graph-toolbar">
            <label className="search-box">
              <Search size={16} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索任务 ID、分组或节点类型…"
                aria-label="搜索任务"
              />
              {query ? (
                <button type="button" onClick={() => setQuery("")} aria-label="清除搜索">
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
                  onClick={() => setFilter(item.id)}
                  role="tab"
                  aria-selected={filter === item.id}
                >
                  {item.label}
                  <span>{item.count}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="legend-row">
            <span>当前显示 {matchedIds.size} / {tasks.length} 个节点</span>
            <div className="legend">
              <span><i className="legend-dot" style={{ background: STATUS_META.planned.color }} />计划</span>
              <span><i className="legend-dot" style={{ background: STATUS_META["in-progress"].color }} />进行</span>
              <span><i className="legend-dot" style={{ background: STATUS_META.blocked.color }} />阻塞</span>
              <span><i className="legend-dot" style={{ background: STATUS_META["release-ready"].color }} />代码/合同就绪</span>
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
        </div>

        <aside className={"details-panel " + (selectedTask ? "has-selection" : "")}>
          {selectedTask ? (
            <>
              <div className="details-header">
                <div>
                  <span className="details-kicker">NODE INSPECTOR</span>
                  <h2>{selectedTask.id}</h2>
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
              <h3 className="task-name">{selectedTask.label}</h3>
              <div className="detail-list">
                <div><span>节点类型</span><strong>{selectedTask.type}</strong></div>
                <div><span>分组</span><strong>{selectedTask.group}</strong></div>
                <div><span>工作项目</span><strong>{selectedTask.project ?? "未返回"}</strong></div>
                <div><span>状态来源</span><strong>{selectedTask.statusSource}</strong></div>
                <div><span>数据来源</span><strong>LangGraph graph + run API</strong></div>
              </div>

              <div className="agent-block">
                <div className="section-label">
                  选择处理 Agent <span>3</span>
                </div>
                <div className="agent-options" role="radiogroup" aria-label="选择处理 Agent">
                  {(Object.keys(AGENT_META) as AgentKind[]).map((kind) => (
                    <button
                      className={selectedAgent === kind ? "active" : ""}
                      key={kind}
                      type="button"
                      onClick={() => {
                        if (!selectedTask) return;
                        setAgentByTask((current) => ({ ...current, [selectedTask.id]: kind }));
                      }}
                      role="radio"
                      aria-checked={selectedAgent === kind}
                      title={AGENT_META[kind].hint}
                    >
                      {AGENT_META[kind].label}
                    </button>
                  ))}
                </div>
                <div className="prompt-heading">
                  <span>{AGENT_META[selectedAgent].label} 执行提示词</span>
                  <span>{agentPrompt.length} 字符</span>
                </div>
                <textarea className="agent-prompt" value={agentPrompt} readOnly rows={9} />
                <button className="button button-secondary prompt-copy" type="button" onClick={() => void copyAgentPrompt()}>
                  {promptCopied ? <Check size={15} /> : <Copy size={15} />}
                  {promptCopied ? "提示词已复制" : "复制提示词给 Agent"}
                </button>
                <p className="agent-note">提示词会携带当前节点状态、依赖、验证范围和 LangGraph 上下文；选择 Agent 只改变提示词目标，不会伪造执行结果。</p>
              </div>

              <div className="relation-block">
                <div className="section-label">前置依赖 <span>{selectedTask.deps.length}</span></div>
                {selectedTask.deps.length ? (
                  <div className="relation-list">
                    {selectedTask.deps.map((dependency) => (
                      <button type="button" key={dependency} onClick={() => setSelectedId(dependency)}>
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
                      <button type="button" key={dependent.id} onClick={() => setSelectedId(dependent.id)}>
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
              <div className="details-empty-icon"><PanelRight size={21} /></div>
              <h2>节点详情</h2>
              <p>点击任意节点，查看它的状态、前置依赖和后续节点。</p>
              <div className="tip">
                <Info size={15} />
                选中节点后，画布会自动弱化无关连线。
              </div>
            </div>
          )}
        </aside>
      </section>

      <footer className="footer-note">
        <span><Info size={14} />代码/合同就绪不等于正式可发布；当前正式可发布 {releaseReadyCount}/{businessTasks.length}。</span>
        <span>最后同步：{formatDate(lastSync)}</span>
      </footer>
    </main>
  );
}
