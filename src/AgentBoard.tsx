import { useEffect, useMemo, useState } from "react";

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

export default function AgentBoard({ onAgentsChange }: { onAgentsChange?: (agents: AgentBoardSnapshot) => void }) {
  const [data, setData] = useState<BoardData>({});
  const [connected, setConnected] = useState(false);
  const [killing, setKilling] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    const load = async () => { try { const response = await fetch("/agentboard/api/data", { cache: "no-store" }); if (!response.ok) throw new Error(); if (active) { const nextData = await response.json() as BoardData; setData(nextData); onAgentsChange?.(nextData.agents ?? []); setConnected(true); } } catch { if (active) setConnected(false); } };
    void load(); const timer = window.setInterval(load, 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [onAgentsChange]);
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
  return <aside className="agent-board-panel">
    <div className="agent-board-title"><span className={`agent-live-dot ${connected ? "on" : ""}`} /><div><strong>AGENT BOARD</strong><small>实时 Agent 监控</small></div><span className="agent-total">{data.stats?.total ?? 0}</span></div>
    <div className="agent-board-stats"><span>运行 <b>{data.stats?.running ?? 0}</b></span><span>异常 <b>{data.stats?.error ?? 0}</b></span></div>
    <div className="agent-card-list">{agents.length ? agents.map((agent) => <AgentCard key={agent.agent} agent={agent} onKill={killAgent} />) : <div className="agent-board-empty">{connected ? "当前没有活动的 Agent" : "正在连接 Agent Board…"}</div>}</div>
  </aside>;
}
