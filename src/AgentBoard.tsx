import { useEffect, useMemo, useRef, useState } from "react";
import {
  FolderKanban,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  Users,
  X,
} from "lucide-react";
import {
  createProject,
  deleteProjectPermanently,
  emptyTrash,
  listProjects,
  restoreProject,
  trashProject,
} from "./api";
import type { AgentWorkspace } from "./api";
import { isProjectInTrash, type Project } from "./types";

export type Agent = {
  agent?: string; type?: string; pid?: string | number; dur?: number;
  cmd?: string; cls?: { group?: string; label?: string }; last?: { ts?: string; stage?: string; msg?: string };
  think?: Array<{ ts?: string; text?: string }>;
};
type BoardData = { agents?: Agent[]; stats?: { total?: number; running?: number; error?: number } };
export type AgentBoardSnapshot = Agent[];

const stateClass: Record<string, string> = { running: "run", error: "err", thinking: "think", waiting: "wait", idle: "idle" };
const brand = (name: string) => {
  const value = name.toLowerCase();
  return ["hermes", "opencode", "codex", "pi", "copilot", "prime"].find((item) => value.startsWith(item)) ?? "other";
};
const duration = (seconds = 0) => {
  const h = Math.floor(seconds / 3600); const m = Math.floor((seconds % 3600) / 60); const s = seconds % 60;
  return h ? `${h}h${String(m).padStart(2, "0")}m` : m ? `${m}m${String(s).padStart(2, "0")}s` : `${s}s`;
};

function AgentCard({ agent, onKill }: { agent: Agent; onKill: (agent: string) => void }) {
  const name = String(agent.agent ?? "unknown");
  const group = stateClass[agent.cls?.group ?? "idle"] ?? "idle";
  const recent = agent.think?.slice(-3).reverse() ?? [];
  const canKill = agent.type === "proc" && agent.cls?.group === "running" && Number(agent.pid) > 0;
  return <article className={`agent-card x-${group}`} data-agent={name}>
    <div className="agent-card-head"><span className={`agent-brand b-${brand(name)}`}>{brand(name)}</span><strong title={name}>{name}</strong><span className="agent-state">{agent.cls?.label ?? "IDLE"}</span>{canKill ? <button className="agent-kill" type="button" title="终止 Agent" aria-label={`终止 ${name}`} onClick={() => onKill(name)}>×</button> : null}</div>
    {agent.cmd ? <div className="agent-command" title={agent.cmd}>{agent.cmd}</div> : null}
    <div className="agent-thoughts">{recent.length ? recent.map((item, index) => <div key={`${item.ts}-${index}`}><time>{item.ts}</time><span>{item.text}</span></div>) : <span className="agent-empty">— 暂无活动 —</span>}</div>
    <div className="agent-card-foot"><span>{agent.pid != null ? `pid ${agent.pid}` : "会话"}</span><span>{duration(agent.dur)}</span><span>{agent.last?.stage ?? "-"}</span></div>
    {group === "run" ? <div className="agent-lights">{Array.from({ length: 6 }, (_, i) => <i key={i} />)}</div> : null}
  </article>;
}

interface AgentBoardProps {
  onAgentsChange?: (agents: AgentBoardSnapshot) => void;
  projects: Project[];
  selectedProjectId: string;
  onProjectSelect: (projectId: string) => void;
  onProjectsChange?: (projects: Project[]) => void;
}

const WORKSPACE_OPTIONS: AgentWorkspace[] = ["APP18", "APP19", "APP20"];

function formatTrashTime(value?: string) {
  if (!value) return "未知时间";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export default function AgentBoard({
  onAgentsChange,
  projects,
  selectedProjectId,
  onProjectSelect,
  onProjectsChange,
}: AgentBoardProps) {
  const [data, setData] = useState<BoardData>({});
  const [connected, setConnected] = useState(false);
  const [killing, setKilling] = useState<string | null>(null);
  const [tab, setTab] = useState<"agents" | "projects">("agents");
  // 项目管理本地状态
  const [projectQuery, setProjectQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showTrash, setShowTrash] = useState(true);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newWorkspace, setNewWorkspace] = useState<AgentWorkspace>("APP18");
  const [operatingId, setOperatingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [projectError, setProjectError] = useState("");
  // onAgentsChange 是父组件的内联回调，每次渲染引用都变。用 ref 承接，
  // effect 只挂载一次，避免“渲染→重建 interval→立即 fetch→setState→渲染”的自激循环。
  const agentsChangeRef = useRef(onAgentsChange);
  agentsChangeRef.current = onAgentsChange;
  const projectsChangeRef = useRef(onProjectsChange);
  projectsChangeRef.current = onProjectsChange;
  const selectedProjectRef = useRef(selectedProjectId);
  selectedProjectRef.current = selectedProjectId;
  const lastAgentsRef = useRef<string>("");
  const lastStatsRef = useRef<string>("");
  useEffect(() => {
    let active = true;
    let inFlight = false;
    const load = async () => {
      // 后台标签页暂停轮询：不可见时 fetch + setState 只会堆积渲染压力。
      if (document.hidden || inFlight) return;
      inFlight = true;
      try {
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), 10_000);
        try {
          const response = await fetch("/agentboard/api/data", { cache: "no-store", signal: controller.signal });
          if (!response.ok) throw new Error();
          const nextData = await response.json() as BoardData;
          if (!active) return;
          // 载荷无变化时不 setState：否则每 3s 产生新引用，父组件全树重渲染，
          // 连带 DagCanvas、AgentDagLinks 做全量 DOM 测量，是标签页卡死的主因之一。
          const agentsPayload = JSON.stringify(nextData.agents ?? []);
          const statsPayload = JSON.stringify(nextData.stats ?? {});
          if (agentsPayload !== lastAgentsRef.current || statsPayload !== lastStatsRef.current) {
            lastAgentsRef.current = agentsPayload;
            lastStatsRef.current = statsPayload;
            setData(nextData);
            agentsChangeRef.current?.(nextData.agents ?? []);
          }
          setConnected(true);
        } finally {
          window.clearTimeout(timeout);
        }
      } catch {
        if (active) setConnected(false);
      } finally {
        inFlight = false;
      }
    };
    void load();
    // 1s 高频轮询是 CPU/布局抖动的直接来源；Agent 状态秒级精度没有业务意义，降到 3s。
    const timer = window.setInterval(load, 3000);
    const onVisibility = () => { if (!document.hidden) void load(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => { active = false; window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisibility); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const agents = useMemo(() => (data.agents ?? []).filter((agent) => String(agent.cls?.label ?? "").toUpperCase() !== "DONE"), [data]);
  const killAgent = async (name: string) => {
    if (killing || !window.confirm(`确定终止 Agent「${name}」吗？`)) return;
    setKilling(name);
    try {
      const response = await fetch(`/agentboard/api/agents/${encodeURIComponent(name)}/kill`, { method: "POST" });
      if (!response.ok) { const result = await response.json().catch(() => ({})); throw new Error(result.error ?? "终止失败"); }
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "终止失败");
    } finally { setKilling(null); }
  };

  const activeProjects = useMemo(
    () => projects.filter((project) => !isProjectInTrash(project)),
    [projects],
  );
  const trashedProjects = useMemo(
    () => projects.filter((project) => isProjectInTrash(project)),
    [projects],
  );
  const filteredActive = useMemo(() => {
    const needle = projectQuery.trim().toLowerCase();
    if (!needle) return activeProjects;
    return activeProjects.filter((project) =>
      project.id.toLowerCase().includes(needle) ||
      project.name.toLowerCase().includes(needle) ||
      (project.description ?? "").toLowerCase().includes(needle),
    );
  }, [activeProjects, projectQuery]);
  const filteredTrash = useMemo(() => {
    const needle = projectQuery.trim().toLowerCase();
    if (!needle) return trashedProjects;
    return trashedProjects.filter((project) =>
      project.id.toLowerCase().includes(needle) ||
      project.name.toLowerCase().includes(needle),
    );
  }, [trashedProjects, projectQuery]);

  const refreshProjects = async () => {
    try {
      const next = await listProjects();
      projectsChangeRef.current?.(next);
      return next;
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "项目列表刷新失败");
      return null;
    }
  };

  const handleCreate = async () => {
    const id = newId.trim();
    const name = newName.trim() || id;
    if (!id) {
      setProjectError("项目 ID 不能为空（字母/数字/-/_, 1-64 位）");
      return;
    }
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(id)) {
      setProjectError("项目 ID 只能使用字母、数字、- 或 _，且以字母数字开头");
      return;
    }
    if (!name) {
      setProjectError("项目名称不能为空");
      return;
    }
    setCreating(true);
    setProjectError("");
    try {
      const created = await createProject({
        id,
        name,
        description: newDescription.trim() || undefined,
        workspace: newWorkspace,
        sourceProjectId: selectedProjectRef.current || "default",
      });
      setNewId("");
      setNewName("");
      setNewDescription("");
      setShowCreate(false);
      const next = await refreshProjects();
      // 新建后直接切换过去，DAG 画布跟随新项目上下文。
      if (next?.some((project) => project.id === created.id)) {
        onProjectSelect(created.id);
      }
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "创建项目失败");
    } finally {
      setCreating(false);
    }
  };

  const handleTrash = async (project: Project) => {
    if (project.id === "default") {
      setProjectError("默认项目不能删除");
      return;
    }
    if (!window.confirm(`把项目「${project.name}（${project.id}）」移入回收站吗？\n任务数据会保留，可随时恢复。`)) return;
    setOperatingId(project.id);
    setProjectError("");
    try {
      await trashProject(project.id);
      const next = await refreshProjects();
      // 被删除的正好是当前选中：自动切到 default / 第一个 active 项目。
      if (selectedProjectRef.current === project.id && next) {
        const fallback = next.find((item) => !isProjectInTrash(item));
        if (fallback) onProjectSelect(fallback.id);
      }
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "移入回收站失败");
    } finally {
      setOperatingId(null);
    }
  };

  const handleRestore = async (project: Project) => {
    setOperatingId(project.id);
    setProjectError("");
    try {
      await restoreProject(project.id);
      await refreshProjects();
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "恢复项目失败");
    } finally {
      setOperatingId(null);
    }
  };

  const handlePermanentDelete = async (project: Project) => {
    if (!window.confirm(`彻底删除项目「${project.name}（${project.id}）」吗？\n这是不可恢复操作，任务快照会被清空。`)) return;
    if (!window.confirm(`二次确认：真的要永久删除「${project.id}」吗？`)) return;
    setOperatingId(project.id);
    setProjectError("");
    try {
      await deleteProjectPermanently(project.id);
      await refreshProjects();
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "彻底删除失败");
    } finally {
      setOperatingId(null);
    }
  };

  const handleEmptyTrash = async () => {
    if (!trashedProjects.length) return;
    if (!window.confirm(`清空回收站吗？将永久删除 ${trashedProjects.length} 个项目，不可恢复。`)) return;
    setOperatingId("__empty__");
    setProjectError("");
    try {
      await emptyTrash();
      await refreshProjects();
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "清空回收站失败");
    } finally {
      setOperatingId(null);
    }
  };

  return <aside className="agent-board-panel">
    <div className="agent-board-title"><span className={`agent-live-dot ${connected ? "on" : ""}`} /><div><strong>AGENT CONTROL</strong><small>实时 Agent 与项目上下文</small></div><span className="agent-total">{tab === "agents" ? data.stats?.total ?? 0 : `${activeProjects.length}/${projects.length}`}</span></div>
    <div className="agent-board-tabs" role="tablist" aria-label="Agent 控制区域">
      <button type="button" className={tab === "agents" ? "active" : ""} role="tab" aria-selected={tab === "agents"} onClick={() => setTab("agents")}><Users size={13} />Agent 实例</button>
      <button type="button" className={tab === "projects" ? "active" : ""} role="tab" aria-selected={tab === "projects"} onClick={() => setTab("projects")}><FolderKanban size={13} />项目管理{trashedProjects.length ? ` · ${trashedProjects.length}` : ""}</button>
    </div>
    {tab === "agents" ? <>
      <div className="agent-board-stats"><span>运行 <b>{data.stats?.running ?? 0}</b></span><span>异常 <b>{data.stats?.error ?? 0}</b></span></div>
      <div className="agent-card-list">{agents.length ? agents.map((agent) => <AgentCard key={agent.agent} agent={agent} onKill={killAgent} />) : <div className="agent-board-empty">{connected ? "当前没有活动的 Agent" : "正在连接 Agent Board…"}</div>}</div>
    </> : <div className="project-manage">
      <div className="project-toolbar">
        <label className="project-search">
          <Search size={13} />
          <input
            value={projectQuery}
            onChange={(event) => setProjectQuery(event.target.value)}
            placeholder="搜索项目 ID / 名称…"
            aria-label="搜索项目"
          />
          {projectQuery ? (
            <button type="button" onClick={() => setProjectQuery("")} aria-label="清除搜索" className="project-search-clear">
              <X size={12} />
            </button>
          ) : null}
        </label>
        <button
          type="button"
          className={`project-new-toggle ${showCreate ? "open" : ""}`}
          onClick={() => setShowCreate((value) => !value)}
          title="新建 Agent 管理项目"
        >
          <Plus size={13} />
          新建
        </button>
      </div>

      {showCreate ? (
        <div className="project-create">
          <div className="project-create-title">新建项目 <small>从当前项目复制任务快照</small></div>
          <label>项目 ID <em>*</em>
            <input value={newId} onChange={(event) => setNewId(event.target.value)} placeholder="如 dcx-phase2" spellCheck={false} />
          </label>
          <label>项目名称 <em>*</em>
            <input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="如 DCX 第二阶段" />
          </label>
          <label>描述
            <input value={newDescription} onChange={(event) => setNewDescription(event.target.value)} placeholder="可选，一句话说明用途" />
          </label>
          <label>白名单工作区
            <select value={newWorkspace} onChange={(event) => setNewWorkspace(event.target.value as AgentWorkspace)}>
              {WORKSPACE_OPTIONS.map((workspace) => <option key={workspace} value={workspace}>{workspace}</option>)}
            </select>
          </label>
          <div className="project-create-actions">
            <button type="button" className="project-btn primary" disabled={creating} onClick={() => void handleCreate()}>
              {creating ? "创建中…" : "创建并切换"}
            </button>
            <button type="button" className="project-btn" disabled={creating} onClick={() => setShowCreate(false)}>取消</button>
          </div>
        </div>
      ) : null}

      {projectError ? (
        <div className="project-error" role="alert">
          <span>{projectError}</span>
          <button type="button" onClick={() => setProjectError("")} aria-label="关闭错误提示"><X size={12} /></button>
        </div>
      ) : null}

      <div className="project-list-scroll">
        <div className="project-section-label">
          <span>进行中的项目 · {filteredActive.length}</span>
          <small>点击切换 DAG 上下文</small>
        </div>
        {filteredActive.map((project) => {
          const isSelected = selectedProjectId === project.id;
          const isDefault = project.id === "default";
          const busy = operatingId === project.id;
          return (
            <div key={project.id} className={`project-item ${isSelected ? "active" : ""}`}>
              <button type="button" className="project-item-main" onClick={() => onProjectSelect(project.id)} title={project.description || project.id}>
                <span className="project-status" />
                <span className="project-item-copy">
                  <strong>{project.name}</strong>
                  <small>{project.id} · {project.taskCount ?? 0} 个节点{project.workspace ? ` · ${project.workspace}` : ""}</small>
                </span>
                <span className="project-managed">Agent</span>
              </button>
              {!isDefault ? (
                <button
                  type="button"
                  className="project-icon-btn danger"
                  disabled={busy}
                  onClick={() => void handleTrash(project)}
                  title="删除到回收站（保留数据，可恢复）"
                  aria-label={`删除项目 ${project.id} 到回收站`}
                >
                  <Trash2 size={13} />
                </button>
              ) : (
                <span className="project-default-badge" title="默认项目不可删除">默认</span>
              )}
            </div>
          );
        })}
        {!filteredActive.length ? (
          <div className="agent-board-empty">{projectQuery ? "没有匹配的进行中项目" : "暂无进行中的项目，可新建一个"}</div>
        ) : null}

        <div className="project-section-label trash">
          <button type="button" className="project-trash-toggle" onClick={() => setShowTrash((value) => !value)} aria-expanded={showTrash}>
            <Trash2 size={12} />
            回收站 · {trashedProjects.length}
            <span className={`chevron ${showTrash ? "open" : ""}`}>▾</span>
          </button>
          {trashedProjects.length ? (
            <button
              type="button"
              className="project-btn link-danger"
              disabled={operatingId === "__empty__"}
              onClick={() => void handleEmptyTrash()}
              title="永久删除回收站内所有项目，不可恢复"
            >
              {operatingId === "__empty__" ? "清空中…" : "清空"}
            </button>
          ) : null}
        </div>
        {showTrash ? (
          filteredTrash.length ? filteredTrash.map((project) => {
            const busy = operatingId === project.id;
            return (
              <div key={project.id} className="project-item trashed">
                <span className="project-status trashed" />
                <span className="project-item-copy">
                  <strong title={project.id}>{project.name}</strong>
                  <small>{project.id} · {project.taskCount ?? 0} 个节点 · {formatTrashTime(project.trashedAt ?? project.updatedAt)}移入</small>
                </span>
                <span className="project-trash-actions">
                  <button
                    type="button"
                    className="project-icon-btn restore"
                    disabled={busy}
                    onClick={() => void handleRestore(project)}
                    title="从回收站恢复"
                    aria-label={`恢复项目 ${project.id}`}
                  >
                    <RotateCcw size={13} />
                  </button>
                  <button
                    type="button"
                    className="project-icon-btn danger"
                    disabled={busy}
                    onClick={() => void handlePermanentDelete(project)}
                    title="彻底删除（不可恢复）"
                    aria-label={`彻底删除项目 ${project.id}`}
                  >
                    <X size={13} />
                  </button>
                </span>
              </div>
            );
          }) : (
            <div className="agent-board-empty small">{projectQuery ? "回收站无匹配项目" : "回收站是空的，删除的项目会先到这里"}</div>
          )
        ) : null}
      </div>
    </div>}
  </aside>;
}
