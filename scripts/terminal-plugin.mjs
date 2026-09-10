import { existsSync } from "node:fs";
import { resolve } from "node:path";

/**
 * terminalPlugin — 页内多 Tab 命令行的 PTY 后端（成熟方案：node-pty + ws + xterm.js）。
 *
 * - 仅监听 127.0.0.1 的 Vite dev/preview 服务，前端通过相对路径连接，
 *   不暴露新端口：ws(s)://<host>/terminal-ws?cwd=APP18&cols=120&rows=30
 * - cwd 白名单：APP18/APP19/APP20（见 scripts/agent-workspaces.mjs）+ 本仓库根目录。
 *   传绝对路径时必须落在白名单目录内，防止任意目录执行。
 * - 每个 WS 连接对应一个 /bin/bash PTY；WS 关闭即 kill PTY；PTY 退出即通知前端。
 *
 * 简洁 JSON 协议（文本帧）：
 *   C -> S  { type: "input", data: string }        键盘/粘贴输入（含 agent 启动命令）
 *   C -> S  { type: "resize", cols: number, rows: number }
 *   S -> C  { type: "connected", cwd: string }
 *   S -> C  { type: "output", data: string }
 *   S -> C  { type: "exit", exitCode: number, signal?: number }
 *   S -> C  { type: "error", message: string }
 */

const TERMINAL_WS_PATH = "/terminal-ws";
const MAX_TERMINALS = 12;
const MAX_MESSAGE_BYTES = 1024 * 1024;

function clampInt(value, fallback, min, max) {
  const number = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

export function resolveTerminalCwd(raw, agentWorkspaces, dashboardRoot) {
  const allowed = [
    ...Object.values(agentWorkspaces),
    dashboardRoot,
  ].map((dir) => resolve(dir));
  if (typeof raw !== "string" || !raw.trim()) return allowed[0];
  const key = raw.trim();
  if (Object.prototype.hasOwnProperty.call(agentWorkspaces, key)) {
    return resolve(agentWorkspaces[key]);
  }
  const candidate = resolve(dashboardRoot, key);
  if (allowed.some((dir) => candidate === dir || candidate.startsWith(dir + "/"))) {
    return candidate;
  }
  return null;
}

export function terminalPlugin() {
  let WebSocketServer = null;
  let pty = null;
  const terminals = new Set();

  async function ensureDeps() {
    if (!WebSocketServer) {
      ({ WebSocketServer } = await import("ws"));
    }
    if (!pty) {
      const module = await import("node-pty");
      pty = module.default ?? module;
    }
  }

  function killAll() {
    for (const term of terminals) {
      try {
        term.kill();
      } catch {
        // 忽略关闭时的清理错误
      }
    }
    terminals.clear();
  }

  function attach(httpServer, agentWorkspaces, dashboardRoot) {
    if (!httpServer || httpServer.__dcxTerminalAttached) return;
    httpServer.__dcxTerminalAttached = true;
    const wss = new WebSocketServer({ noServer: true, maxPayload: MAX_MESSAGE_BYTES });

    httpServer.on("upgrade", (request, socket, head) => {
      let url;
      try {
        url = new URL(request.url ?? "", "http://127.0.0.1");
      } catch {
        socket.destroy();
        return;
      }
      if (url.pathname !== TERMINAL_WS_PATH) return;
      wss.handleUpgrade(request, socket, head, (ws) => {
        void handleConnection(ws, url).catch((error) => {
          try {
            ws.send(JSON.stringify({ type: "error", message: error instanceof Error ? error.message : "终端启动失败" }));
            ws.close(1011, "terminal failed");
          } catch {
            // 发送失败时直接关闭即可
          }
        });
      });
    });

    async function handleConnection(ws, url) {
      await ensureDeps();
      if (terminals.size >= MAX_TERMINALS) {
        ws.send(JSON.stringify({ type: "error", message: `终端数量已达上限（${MAX_TERMINALS}）` }));
        ws.close(1013, "too many terminals");
        return;
      }
      const params = url.searchParams;
      const cwd = resolveTerminalCwd(params.get("cwd"), agentWorkspaces, dashboardRoot);
      if (!cwd || !existsSync(cwd)) {
        ws.send(JSON.stringify({ type: "error", message: "工作目录不在 APP18/APP19/APP20 白名单中或不存在" }));
        ws.close(1008, "invalid cwd");
        return;
      }
      const cols = clampInt(params.get("cols"), 120, 20, 300);
      const rows = clampInt(params.get("rows"), 30, 5, 100);

      const shell = process.env.SHELL && existsSync(process.env.SHELL) ? process.env.SHELL : "/bin/bash";
      const term = pty.spawn(shell, [], {
        name: "xterm-256color",
        cols,
        rows,
        cwd,
        env: {
          ...process.env,
          TERM: "xterm-256color",
          COLORTERM: "truecolor",
        },
      });
      terminals.add(term);
      console.log(`[terminal] spawn pid=${term.pid} cwd=${cwd} (${terminals.size}/${MAX_TERMINALS})`);

      let closed = false;
      const send = (payload) => {
        if (closed || ws.readyState !== 1) return;
        try {
          ws.send(JSON.stringify(payload));
        } catch {
          // 发送失败由 close 清理
        }
      };

      const disposeData = term.onData((data) => send({ type: "output", data }));
      const disposeExit = term.onExit(({ exitCode, signal }) => {
        console.log(`[terminal] exit pid=${term.pid} code=${exitCode} signal=${signal ?? "-"}`);
        send({ type: "exit", exitCode, signal });
      });

      ws.on("message", (raw) => {
        let message;
        try {
          message = JSON.parse(String(raw));
        } catch {
          return;
        }
        if (!message || typeof message.type !== "string") return;
        if (message.type === "input" && typeof message.data === "string") {
          if (Buffer.byteLength(message.data, "utf8") > MAX_MESSAGE_BYTES) return;
          try {
            term.write(message.data);
          } catch {
            // PTY 已退出时忽略后续输入
          }
        } else if (message.type === "resize") {
          const nextCols = clampInt(message.cols, cols, 20, 300);
          const nextRows = clampInt(message.rows, rows, 5, 100);
          try {
            term.resize(nextCols, nextRows);
          } catch {
            // 缩放失败不影响会话
          }
        }
      });

      const cleanup = () => {
        if (closed) return;
        closed = true;
        disposeData.dispose();
        disposeExit.dispose();
        terminals.delete(term);
        try {
          term.kill();
        } catch {
          // 进程可能已退出
        }
      };
      ws.on("close", cleanup);
      ws.on("error", cleanup);

      send({ type: "connected", cwd });
    }
  }

  return {
    name: "dcx-terminal-pty",
    async configureServer(server) {
      await ensureDeps();
      const { AGENT_WORKSPACES } = await import("./agent-workspaces.mjs");
      attach(server.httpServer, AGENT_WORKSPACES, resolve(process.cwd()));
    },
    async configurePreviewServer(server) {
      await ensureDeps();
      const { AGENT_WORKSPACES } = await import("./agent-workspaces.mjs");
      attach(server.httpServer, AGENT_WORKSPACES, resolve(process.cwd()));
    },
    buildEnd() {
      killAll();
    },
  };
}
