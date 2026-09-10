import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import {
  ChevronDown,
  ChevronUp,
  Eraser,
  Plus,
  RotateCcw,
  Terminal as TerminalIcon,
  X,
} from "lucide-react";
import type { AgentKind } from "./types";

export type TerminalWorkspace = "APP18" | "APP19" | "APP20";

export interface OpenAgentTerminalRequest {
  agent: AgentKind;
  taskId: string;
  prompt: string;
  workspace: TerminalWorkspace;
}

export interface TerminalPanelHandle {
  openAgentTerminal: (request: OpenAgentTerminalRequest) => string;
  openShell: (workspace?: TerminalWorkspace) => string;
}

type TabStatus = "connecting" | "connected" | "exited" | "error";

interface TerminalTab {
  id: string;
  title: string;
  workspace: TerminalWorkspace;
  agent: AgentKind | null;
  taskId: string | null;
  pendingCommand: string | null;
  sessionKey: number;
  status: TabStatus;
}

interface TerminalPanelProps {
  theme: "dark" | "light";
  defaultWorkspace: TerminalWorkspace;
}

// 与 vite.config.ts 的 agentInvoke 保持一致：均为“跑完即退出”的非交互调用，
// Agent 跑完后控制权交还给 shell，用户可在同一 Tab 继续交互。
const AGENT_INVOKE: Record<AgentKind, string> = {
  opencode: "opencode run --",
  pi: "pi -p --",
  codex: "codex exec --skip-git-repo-check --",
};

const TERMINAL_HEIGHT_KEY = "refactor-terminal-height";
const TERMINAL_COLLAPSED_KEY = "refactor-terminal-collapsed";
const MIN_HEIGHT = 160;
const MAX_HEIGHT = 560;
const DEFAULT_HEIGHT = 232;

function utf8ToB64(input: string): string {
  const bytes = new TextEncoder().encode(input);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

// prompt 可能含引号/换行/`$`，走 base64 进 shell，避免一切转义问题。
// base64 字母表不含单引号，可安全放在单引号内。
function buildAgentCommand(agent: AgentKind, taskId: string, prompt: string): string {
  const invoke = AGENT_INVOKE[agent];
  const payload = utf8ToB64(prompt);
  return (
    `printf '\\n[DCX] ${agent} ${taskId} 启动（页内终端）\\n';` +
    `__DCX_P=$(echo '${payload}'|base64 -d);` +
    `${invoke} "$__DCX_P";` +
    `__DCX_CODE=$?;` +
    `printf '\\n[DCX] Agent 已退出（状态码 %s），可继续在此终端交互。\\n' "$__DCX_CODE";` +
    `unset __DCX_P __DCX_CODE\r`
  );
}

function loadHeight(): number {
  try {
    const raw = Number(localStorage.getItem(TERMINAL_HEIGHT_KEY));
    if (Number.isFinite(raw)) return Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, raw));
  } catch {
    // 无痕/禁用 storage 时用默认值
  }
  return DEFAULT_HEIGHT;
}

function terminalWsUrl(workspace: TerminalWorkspace): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/terminal-ws?cwd=${workspace}&cols=120&rows=30`;
}

const XTERM_THEMES = {
  dark: {
    background: "#0a1120",
    foreground: "#cbd5e1",
    cursor: "#67e8f9",
    cursorAccent: "#0a1120",
    selectionBackground: "rgba(103, 232, 249, 0.28)",
    black: "#0a1120",
    brightBlack: "#475569",
    blue: "#7dd3fc",
    brightBlue: "#a5f3fc",
    green: "#34d399",
    brightGreen: "#6ee7b7",
  },
  light: {
    background: "#f8fafc",
    foreground: "#1e293b",
    cursor: "#0e7490",
    cursorAccent: "#f8fafc",
    selectionBackground: "rgba(14, 165, 233, 0.22)",
    black: "#f8fafc",
    brightBlack: "#94a3b8",
    blue: "#0369a1",
    brightBlue: "#0284c7",
    green: "#047857",
    brightGreen: "#059669",
  },
} as const;

interface TerminalViewProps {
  tab: TerminalTab;
  active: boolean;
  theme: "dark" | "light";
  onStatus: (id: string, status: TabStatus) => void;
  registerTerm: (id: string, term: Terminal | null) => void;
}

function TerminalView({ tab, active, theme, onStatus, registerTerm }: TerminalViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);

  // 应用深浅色切换时，已挂载的终端实时换肤（挂载 effect 只跑一次，不能处理切换）。
  // xterm v6 用 options 赋值（对象须换新引用才生效）。
  useEffect(() => {
    const term = termRef.current;
    if (term) term.options.theme = { ...XTERM_THEMES[theme] };
  }, [theme]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let disposed = false;
    let socket: WebSocket | null = null;
    let resizeTimer = 0;

    const term = new Terminal({
      fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
      fontSize: 13,
      lineHeight: 1.35,
      cursorBlink: true,
      cursorStyle: "bar",
      scrollback: 5000,
      theme: { ...XTERM_THEMES[theme] },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.loadAddon(new WebLinksAddon());
    term.open(container);
    termRef.current = term;
    registerTerm(tab.id, term);

    const sendResize = () => {
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      try {
        const { cols, rows } = term;
        if (cols >= 20 && rows >= 5) socket.send(JSON.stringify({ type: "resize", cols, rows }));
      } catch {
        // 缩放失败不影响会话
      }
    };
    const fitAndResize = () => {
      if (disposed || !active) return;
      try {
        fit.fit();
      } catch {
        return;
      }
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(sendResize, 120);
    };

    term.writeln(`\x1b[90m[连接 ${tab.workspace} 中…]\x1b[0m`);
    onStatus(tab.id, "connecting");
    try {
      socket = new WebSocket(terminalWsUrl(tab.workspace));
    } catch {
      term.writeln("\x1b[31m[终端连接失败，点击重连重试]\x1b[0m");
      onStatus(tab.id, "error");
    }

    let inputDisposable = term.onData((data) => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        try {
          socket.send(JSON.stringify({ type: "input", data }));
        } catch {
          // 发送失败由 onclose 统一处理
        }
      }
    });

    if (socket) {
      socket.onopen = () => {
        if (disposed) return;
        fitAndResize();
        // 等 shell 就绪再喂命令，避免首屏 banner 吞掉输入。
        if (tab.pendingCommand && tab.sessionKey === 0) {
          const command = tab.pendingCommand;
          window.setTimeout(() => {
            if (disposed || !socket || socket.readyState !== WebSocket.OPEN) return;
            try {
              socket.send(JSON.stringify({ type: "input", data: command }));
            } catch {
              // 发送失败由 onclose 统一处理
            }
          }, 450);
        }
      };
      socket.onmessage = (event) => {
        if (disposed) return;
        let message: { type?: string; data?: string; exitCode?: number; message?: string };
        try {
          message = JSON.parse(String(event.data));
        } catch {
          return;
        }
        if (message.type === "output" && typeof message.data === "string") {
          term.write(message.data);
        } else if (message.type === "connected") {
          onStatus(tab.id, "connected");
          fitAndResize();
        } else if (message.type === "exit") {
          term.writeln(`\x1b[90m\r\n[PTY 已退出（${message.exitCode ?? "?"}），点击重连可开新 shell]\x1b[0m`);
          onStatus(tab.id, "exited");
        } else if (message.type === "error") {
          term.writeln(`\x1b[31m[终端错误：${message.message ?? "未知错误"}]\x1b[0m`);
          onStatus(tab.id, "error");
        }
      };
      socket.onclose = () => {
        if (disposed) return;
        onStatus(tab.id, "exited");
      };
      socket.onerror = () => {
        if (disposed) return;
        onStatus(tab.id, "error");
      };
    }

    const observer = new ResizeObserver(fitAndResize);
    observer.observe(container);
    window.addEventListener("resize", fitAndResize);
    // 从隐藏 Tab 切回来时容器尺寸从 0 恢复，必须重新 fit。
    if (active) window.requestAnimationFrame(fitAndResize);

    return () => {
      disposed = true;
      window.clearTimeout(resizeTimer);
      observer.disconnect();
      window.removeEventListener("resize", fitAndResize);
      inputDisposable.dispose();
      try {
        socket?.close();
      } catch {
        // 关闭时忽略
      }
      termRef.current = null;
      registerTerm(tab.id, null);
      term.dispose();
    };
    // sessionKey 变化 = 重连；active 变化由下面的 effect 处理 fit。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab.sessionKey]);

  useEffect(() => {
    if (active) {
      // 切 Tab 后让 xterm 重新计算列宽并聚焦，保证即刻可 typing。
      const frame = window.requestAnimationFrame(() => {
        window.dispatchEvent(new Event("resize"));
      });
      return () => window.cancelAnimationFrame(frame);
    }
  }, [active]);

  return <div ref={containerRef} className="terminal-xterm" />;
}

let tabSequence = 0;
function nextTabId(prefix: string): string {
  tabSequence += 1;
  return `${prefix}-${Date.now().toString(36)}-${tabSequence}`;
}

const TerminalPanel = forwardRef<TerminalPanelHandle, TerminalPanelProps>(function TerminalPanel(
  { theme, defaultWorkspace },
  ref,
) {
  const [tabs, setTabs] = useState<TerminalTab[]>(() => [
    {
      id: nextTabId("shell"),
      title: `shell·${defaultWorkspace}`,
      workspace: defaultWorkspace,
      agent: null,
      taskId: null,
      pendingCommand: null,
      sessionKey: 0,
      status: "connecting",
    },
  ]);
  const [activeId, setActiveId] = useState<string | null>(() => null);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(TERMINAL_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [height, setHeight] = useState(loadHeight);
  const [newWorkspace, setNewWorkspace] = useState<TerminalWorkspace>(defaultWorkspace);
  const termsRef = useRef(new Map<string, Terminal>());
  const dragRef = useRef({ dragging: false, startY: 0, startHeight: 0 });

  const currentActiveId = activeId ?? tabs[0]?.id ?? null;

  useEffect(() => {
    setNewWorkspace(defaultWorkspace);
  }, [defaultWorkspace]);

  useEffect(() => {
    try {
      localStorage.setItem(TERMINAL_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // 忽略持久化失败
    }
  }, [collapsed]);

  const updateStatus = useCallback((id: string, status: TabStatus) => {
    setTabs((current) => (current.some((tab) => tab.id === id) ? current.map((tab) => (tab.id === id ? { ...tab, status } : tab)) : current));
  }, []);

  const registerTerm = useCallback((id: string, term: Terminal | null) => {
    if (term) termsRef.current.set(id, term);
    else termsRef.current.delete(id);
  }, []);

  const openShell = useCallback(
    (workspace?: TerminalWorkspace): string => {
      const target = workspace ?? defaultWorkspace;
      const id = nextTabId("shell");
      setTabs((current) => [
        ...current,
        {
          id,
          title: `shell·${target}`,
          workspace: target,
          agent: null,
          taskId: null,
          pendingCommand: null,
          sessionKey: 0,
          status: "connecting",
        },
      ]);
      setActiveId(id);
      setCollapsed(false);
      return id;
    },
    [defaultWorkspace],
  );

  const openAgentTerminal = useCallback((request: OpenAgentTerminalRequest): string => {
    const id = nextTabId("agent");
    setTabs((current) => [
      ...current,
      {
        id,
        title: `${request.agent}·${request.taskId}`,
        workspace: request.workspace,
        agent: request.agent,
        taskId: request.taskId,
        pendingCommand: buildAgentCommand(request.agent, request.taskId, request.prompt),
        sessionKey: 0,
        status: "connecting",
      },
    ]);
    setActiveId(id);
    setCollapsed(false);
    return id;
  }, []);

  useImperativeHandle(ref, () => ({ openAgentTerminal, openShell }), [openAgentTerminal, openShell]);

  const closeTab = (id: string) => {
    setTabs((current) => {
      const index = current.findIndex((tab) => tab.id === id);
      if (index < 0) return current;
      const next = current.filter((tab) => tab.id !== id);
      if (currentActiveId === id) {
        const fallback = next[Math.min(index, next.length - 1)] ?? null;
        setActiveId(fallback ? fallback.id : null);
      }
      return next;
    });
  };

  const reconnectTab = (id: string) => {
    setTabs((current) => current.map((tab) => (tab.id === id ? { ...tab, sessionKey: tab.sessionKey + 1, status: "connecting" as TabStatus } : tab)));
    setActiveId(id);
  };

  const clearActive = () => {
    if (currentActiveId) termsRef.current.get(currentActiveId)?.clear();
  };

  const focusActive = () => {
    if (currentActiveId) termsRef.current.get(currentActiveId)?.focus();
  };

  const handleResizeStart = (event: React.MouseEvent) => {
    if (collapsed) return;
    event.preventDefault();
    dragRef.current = { dragging: true, startY: event.clientY, startHeight: height };
    const handleMove = (moveEvent: MouseEvent) => {
      if (!dragRef.current.dragging) return;
      const next = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, dragRef.current.startHeight + (dragRef.current.startY - moveEvent.clientY)));
      setHeight(next);
    };
    const handleUp = () => {
      dragRef.current.dragging = false;
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
      try {
        localStorage.setItem(TERMINAL_HEIGHT_KEY, String(height));
      } catch {
        // 忽略持久化失败
      }
      window.dispatchEvent(new Event("resize"));
    };
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
  };

  useEffect(() => {
    try {
      localStorage.setItem(TERMINAL_HEIGHT_KEY, String(height));
    } catch {
      // 忽略持久化失败
    }
  }, [height]);

  return (
    <section className={"terminal-panel" + (collapsed ? " collapsed" : "")} aria-label="页内命令行">
      {!collapsed && <div className="terminal-resize-handle" onMouseDown={handleResizeStart} title="拖拽调整高度" />}
      <header className="terminal-header">
        <button
          type="button"
          className="terminal-collapse"
          onClick={() => setCollapsed((value) => !value)}
          title={collapsed ? "展开命令行" : "折叠命令行"}
          aria-expanded={!collapsed}
        >
          {collapsed ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        <span className="terminal-title">
          <TerminalIcon size={14} />
          命令行
          <em>{tabs.length}</em>
        </span>
        <div className="terminal-tabs" role="tablist" aria-label="终端会话">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              role="tab"
              aria-selected={tab.id === currentActiveId}
              className={"terminal-tab" + (tab.id === currentActiveId ? " active" : "") + ` st-${tab.status}`}
              onClick={() => {
                setActiveId(tab.id);
                setCollapsed(false);
              }}
              title={`${tab.title}（${tab.workspace}）`}
            >
              <i className="terminal-dot" />
              <span className="terminal-tab-name">{tab.title}</span>
              <button
                type="button"
                className="terminal-tab-close"
                aria-label={`关闭 ${tab.title}`}
                onClick={(event) => {
                  event.stopPropagation();
                  closeTab(tab.id);
                }}
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
        <label className="terminal-workspace">
          <select value={newWorkspace} onChange={(event) => setNewWorkspace(event.target.value as TerminalWorkspace)} aria-label="新终端工作目录">
            <option value="APP18">APP18</option>
            <option value="APP19">APP19</option>
            <option value="APP20">APP20</option>
          </select>
        </label>
        <button type="button" className="terminal-new" onClick={() => openShell(newWorkspace)} title={`在 ${newWorkspace} 新开终端`}>
          <Plus size={14} />
          新终端
        </button>
        <div className="terminal-actions">
          <button type="button" onClick={clearActive} title="清空当前终端" disabled={!currentActiveId}>
            <Eraser size={14} />
          </button>
          <button
            type="button"
            onClick={() => currentActiveId && reconnectTab(currentActiveId)}
            title="重连当前终端（开新 shell）"
            disabled={!currentActiveId}
          >
            <RotateCcw size={14} />
          </button>
        </div>
      </header>
      {!collapsed && (
        <div className="terminal-body" style={{ height }} onClick={focusActive}>
          {tabs.length === 0 && <div className="terminal-empty">暂无终端会话，点击「新终端」开始。</div>}
          {tabs.map((tab) => (
            <div key={tab.id} className="terminal-pane" hidden={tab.id !== currentActiveId}>
              {/* 非活跃 Tab 保持挂载不断连，仅隐藏画面 */}
              <TerminalView tab={tab} active={tab.id === currentActiveId} theme={theme} onStatus={updateStatus} registerTerm={registerTerm} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
});

export default TerminalPanel;
