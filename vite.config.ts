import { spawn } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { readFile, rename, writeFile } from "node:fs/promises";
import type { IncomingMessage, ServerResponse } from "node:http";
import { join, resolve } from "node:path";
import { defineConfig } from "vite";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { resolveAgentWorkspace } from "./scripts/agent-workspaces.mjs";
import { buildEvidenceUpdate } from "./scripts/evidence-sync.mjs";

const langGraphApi = process.env.LANGGRAPH_API_URL ?? "http://127.0.0.1:8123";
const agentBoardPort = process.env.AGENTBOARD_PORT ?? "8710";
const agentBoardApi = process.env.AGENTBOARD_API_URL ?? `http://127.0.0.1:${agentBoardPort}`;
const frontendPort = Number(process.env.FRONTEND_PORT ?? 5175);
const terminalPath = "/usr/bin/konsole";
const maxPromptBytes = 64 * 1024;
const dashboardRoot = resolve(process.cwd());
const taskSnapshotPath = resolve(dashboardRoot, "backend/tasks.json");
const evidenceManifestPath = process.env.EVIDENCE_MANIFEST_PATH ?? "/mnt/data/code/dcx-web/dcx-web/.test-local/reports/langgraph-task-evidence.json";
const agentCommands = {
  opencode: "opencode",
  pi: "pi",
  codex: "codex",
} as const;
// 各 Agent 在 Konsole 里真正的调用方式（均为跑完即退出的非交互模式，
// 窗口最后用 `read` 保持，以便查看结果）：
// - opencode 的 positional 是 project 目录，prompt 必须走 `run [message]`，
//   否则会被当成目录 lstat（ENAMETOOLONG，且内容里的反引号如
//   `@dcx/well-log-react` 会触发 /bin/bash 报错）；末尾加 `--` 防止 prompt
//   首字符为 `-` 时被解析成 flag（已验证 `opencode run -- "prompt"` 可用）。
// - pi 默认进交互式 TUI（不退出，看起来像“卡住”），必须加 `-p/--print`
//   才跑完退出；`@xxx` 会被解析为文件引用，加 `--` 让 prompt 只当普通消息处理。
// - codex 不带子命令就是交互式 TUI（不退出，看起来像“卡住”），非交互必须用
//   `exec`；`--skip-git-repo-check` 允许在非 git 兜底目录也能启动；末尾 `--`
//   防止 prompt 首字符为 `-` 时被解析成 flag。
const agentInvoke = {
  opencode: 'opencode run --',
  pi: 'pi -p --',
  codex: 'codex exec --skip-git-repo-check --',
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
    try {
      const payload = JSON.parse(await readRequestBody(request)) as {
        agent?: unknown;
        taskId?: unknown;
        prompt?: unknown;
        workspace?: unknown;
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
      const agentWorkspace = resolveAgentWorkspace(payload.workspace);
      if (!agentWorkspace) {
        jsonResponse(response, 400, { error: "工作项目不在 APP18/APP19/APP20 白名单中" });
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

      const command = agentCommands[payload.agent];
      const invoke = agentInvoke[payload.agent];
      // 落盘日志：Agent 跑一次经常要数分钟（读大文档、跑验证），Konsole 里
      // 长时间没新输出看起来像“卡住”。tee 一份到 /tmp，前端把路径展示出来，
      // 用户可另开终端 tail -f 跟踪；日志文件名只用白名单字符。
      const safeTaskId = payload.taskId.trim().replace(/[^a-zA-Z0-9_.:-]/g, "_");
      const agentLogDir = resolve(dashboardRoot, "..", ".dcx-agent-logs");
      let agentLogPath = "";
      try {
        mkdirSync(agentLogDir, { recursive: true });
        agentLogPath = join(agentLogDir, `dcx-${command}-${safeTaskId}-${Date.now()}.log`);
      } catch {
        agentLogPath = "";
      }
      const shellScript = [
        "printf '\\n[DCX] " + command + " 已启动，任务 " + safeTaskId + "\\n'",
        agentLogPath
          ? "printf '[DCX] 日志：" + agentLogPath + "（可 tail -f 跟踪）\\n'"
          : "printf '[DCX] 日志落盘失败，仅 Konsole 输出\\n'",
        "printf '[DCX] 任务一般需要数分钟，请勿关闭窗口\\n\\n'",
        agentLogPath
          ? invoke + ' "$DCX_AGENT_PROMPT" 2>&1 | tee "$DCX_AGENT_LOG"; agent_status=${PIPESTATUS[0]}'
          : invoke + ' "$DCX_AGENT_PROMPT"; agent_status=$?',
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
            DCX_AGENT_LOG: agentLogPath,
          },
        },
      );
      child.unref();
      jsonResponse(response, 202, {
        ok: true,
        agent: payload.agent,
        taskId: payload.taskId,
        workspace: payload.workspace ?? "APP18",
        terminal: "konsole",
        pid: child.pid,
        ...(agentLogPath ? { log: agentLogPath } : {}),
        message:
          command +
          " 已在新的 Konsole 窗口启动" +
          (agentLogPath ? "，日志：" + agentLogPath : ""),
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

async function readJsonFile(path: string): Promise<unknown> {
  return JSON.parse(await readFile(path, "utf8"));
}

function createEvidenceSyncMiddleware() {
  return async (request: IncomingMessage, response: ServerResponse, _next: () => void) => {
    if (request.method === "OPTIONS") {
      response.statusCode = 204;
      response.end();
      return;
    }
    if (request.method !== "POST") {
      jsonResponse(response, 405, { error: "只支持 POST /api/evidence/sync" });
      return;
    }

    try {
      const payload = JSON.parse(await readRequestBody(request));
      const tasks = await readJsonFile(taskSnapshotPath);
      const manifest = await readJsonFile(evidenceManifestPath);
      const result = buildEvidenceUpdate({
        tasks: tasks as Array<Record<string, unknown>>,
        manifest: manifest as Record<string, unknown>,
        payload,
      });
      const temporaryPath = taskSnapshotPath + ".writing";
      await writeFile(temporaryPath, JSON.stringify(result.tasks) + "\n", "utf8");
      await rename(temporaryPath, taskSnapshotPath);
      jsonResponse(response, 200, {
        ok: true,
        taskId: result.taskId,
        status: result.status,
        statusSource: result.statusSource,
        commit: result.commit,
        ...(result.commits ? { commits: result.commits } : {}),
        report: result.report,
        verifiedAt: result.verifiedAt,
        evidenceCount: result.evidenceCount,
        changed: result.changed,
      });
    } catch (error) {
      const code = error && typeof error === "object" && "code" in error ? error.code : undefined;
      const status = code === "ENOENT" ? 503 : error instanceof SyntaxError ? 400 : 422;
      jsonResponse(response, status, {
        error:
          code === "ENOENT"
            ? "证据 manifest 或 dashboard task snapshot 不存在"
            : error instanceof Error
              ? error.message
              : "证据同步请求无效",
      });
    }
  };
}

function evidenceSyncPlugin(): Plugin {
  const middleware = createEvidenceSyncMiddleware();
  return {
    name: "dcx-evidence-sync",
    configureServer(server) {
      server.middlewares.use("/api/evidence/sync", middleware);
    },
    configurePreviewServer(server) {
      server.middlewares.use("/api/evidence/sync", middleware);
    },
  };
}

export default defineConfig({
  plugins: [react(), agentLauncherPlugin(), evidenceSyncPlugin()],
  server: {
    host: "127.0.0.1",
    port: frontendPort,
    strictPort: true,
    proxy: {
      "/agentboard": {
        target: agentBoardApi,
        changeOrigin: true,
        // 后端同时支持带 /agentboard 前缀和不带前缀的路径；这里统一剥离前缀，
        // 以兼容旧版 agentboard_server（仅识别 /api/*，不识别 /agentboard/*）。
        rewrite: (path) => path.replace(/^\/agentboard/, "") || "/",
      },
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
