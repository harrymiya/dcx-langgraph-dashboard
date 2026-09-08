import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";
import { defineConfig } from "vite";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";

const langGraphApi = process.env.LANGGRAPH_API_URL ?? "http://127.0.0.1:8123";
const agentWorkspace = "/mnt/data/code/dcx-web/dcx-web";
const terminalPath = "/usr/bin/konsole";
const maxPromptBytes = 64 * 1024;
const agentCommands = {
  opencode: "opencode",
  pi: "pi",
  codex: "codex",
} as const;

type AgentKind = keyof typeof agentCommands;

function jsonResponse(response: ServerResponse, status: number, body: unknown) {
  response.statusCode = status;
  response.setHeader("content-type", "application/json; charset=utf-8");
  response.end(JSON.stringify(body));
}

async function readRequestBody(request: NodeJS.ReadableStream): Promise<string> {
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
    total += buffer.byteLength;
    if (total > maxPromptBytes * 2) throw new Error("请求体过大");
    chunks.push(buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function isAgentKind(value: unknown): value is AgentKind {
  return typeof value === "string" && value in agentCommands;
}

function createAgentLauncherMiddleware() {
  return async (request: IncomingMessage, response: ServerResponse, _next: () => void) => {
    if (request.method === "OPTIONS") {
      response.statusCode = 204;
      response.end();
      return;
    }
    if (request.method !== "POST") {
      jsonResponse(response, 405, { error: "只支持 POST /api/agents/launch" });
      return;
    }
    if (!existsSync(agentWorkspace)) {
      jsonResponse(response, 503, { error: "Agent 工作目录不存在：" + agentWorkspace });
      return;
    }
    if (!existsSync(terminalPath)) {
      jsonResponse(response, 503, { error: "未找到 Konsole，无法打开 Agent 终端窗口" });
      return;
    }

    try {
      const payload = JSON.parse(await readRequestBody(request)) as {
        agent?: unknown;
        taskId?: unknown;
        prompt?: unknown;
      };
      if (!isAgentKind(payload.agent)) {
        jsonResponse(response, 400, { error: "不支持的 Agent 类型" });
        return;
      }
      if (typeof payload.taskId !== "string" || !payload.taskId.trim()) {
        jsonResponse(response, 400, { error: "缺少任务节点 ID" });
        return;
      }
      if (typeof payload.prompt !== "string" || !payload.prompt.trim()) {
        jsonResponse(response, 400, { error: "缺少 Agent 工作上下文" });
        return;
      }
      if (Buffer.byteLength(payload.prompt, "utf8") > maxPromptBytes) {
        jsonResponse(response, 413, { error: "Agent 工作上下文超过 64 KiB" });
        return;
      }

      const command = agentCommands[payload.agent];
      const shellScript = [
        "printf '\\n[DCX] " + command + " 已启动，任务 " + payload.taskId.replace(/[^a-zA-Z0-9_.:-]/g, "_") + "\\n\\n'",
        command + ' "$DCX_AGENT_PROMPT"',
        "agent_status=$?",
        "printf '\\n[DCX] Agent 已退出（状态码 %s），按回车关闭窗口。\\n' \"$agent_status\"",
        "read -r",
      ].join("; ");
      const child = spawn(
        terminalPath,
        ["--separate", "--workdir", agentWorkspace, "-e", "/bin/bash", "-lc", shellScript],
        {
          cwd: agentWorkspace,
          detached: true,
          stdio: "ignore",
          env: {
            ...process.env,
            DCX_AGENT_PROMPT: payload.prompt,
            DCX_AGENT_TASK_ID: payload.taskId,
          },
        },
      );
      child.unref();
      jsonResponse(response, 202, {
        ok: true,
        agent: payload.agent,
        taskId: payload.taskId,
        terminal: "konsole",
        pid: child.pid,
        message: command + " 已在新的 Konsole 窗口启动",
      });
    } catch (error) {
      jsonResponse(response, 400, {
        error: error instanceof Error ? error.message : "Agent 启动请求无效",
      });
    }
  };
}

function agentLauncherPlugin(): Plugin {
  const middleware = createAgentLauncherMiddleware();
  return {
    name: "dcx-agent-launcher",
    configureServer(server) {
      server.middlewares.use("/api/agents/launch", middleware);
    },
    configurePreviewServer(server) {
      server.middlewares.use("/api/agents/launch", middleware);
    },
  };
}

export default defineConfig({
  plugins: [react(), agentLauncherPlugin()],
  server: {
    host: "127.0.0.1",
    port: 5175,
    strictPort: true,
    proxy: {
      "/langgraph": {
        target: langGraphApi,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/langgraph/, ""),
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4175,
    strictPort: true,
  },
});
