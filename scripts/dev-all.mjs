import { existsSync } from "node:fs";
import { createServer } from "node:net";
import { delimiter, join, resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const root = resolve(import.meta.dirname, "..");
const backendRoot = join(root, "backend");
const backendConfig = join(backendRoot, "langgraph.json");
const virtualEnvironment = join(backendRoot, ".venv");
const isWindows = process.platform === "win32";
const executableSuffix = isWindows ? ".cmd" : "";
const pythonInVenv = join(virtualEnvironment, isWindows ? "Scripts" : "bin", "python" + (isWindows ? ".exe" : ""));
const langgraphInVenv = join(virtualEnvironment, isWindows ? "Scripts" : "bin", "langgraph" + executableSuffix);
const frontendPort = process.env.FRONTEND_PORT ?? "5175";
const backendPort = process.env.LANGGRAPH_PORT ?? "8123";

let backendProcess;
let frontendProcess;
let shuttingDown = false;

function findExecutable(command) {
  if (command.includes("/") || command.includes("\\")) {
    return existsSync(command) ? command : null;
  }

  const pathEntries = (process.env.PATH ?? "").split(delimiter).filter(Boolean);
  const suffixes = isWindows ? [".exe", ".cmd", ".bat", ""] : [""];
  for (const directory of pathEntries) {
    for (const suffix of suffixes) {
      const candidate = join(directory, command + suffix);
      if (existsSync(candidate)) return candidate;
    }
  }
  return null;
}

function run(command, args, label) {
  console.log(`[setup] ${label}`);
  const result = spawnSync(command, args, {
    cwd: root,
    env: process.env,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${label}失败，退出码：${result.status ?? "unknown"}`);
  }
}

function assertValidPort(value, label) {
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${label}端口无效：${value}`);
  }
  return port;
}

function isPortAvailable(port) {
  return new Promise((resolvePort) => {
    const server = createServer();
    server.once("error", () => resolvePort(false));
    server.listen(port, "127.0.0.1", () => {
      server.close(() => resolvePort(true));
    });
  });
}

async function assertPortsAvailable() {
  const backendPortNumber = assertValidPort(backendPort, "LangGraph");
  const frontendPortNumber = assertValidPort(frontendPort, "Vite");
  const [backendAvailable, frontendAvailable] = await Promise.all([
    isPortAvailable(backendPortNumber),
    isPortAvailable(frontendPortNumber),
  ]);
  if (!backendAvailable) {
    throw new Error(
      `LangGraph 端口 ${backendPort} 已被占用；请停止旧服务，或使用 LANGGRAPH_PORT=其他端口 npm run dev:all。`,
    );
  }
  if (!frontendAvailable) {
    throw new Error(
      `Vite 端口 ${frontendPort} 已被占用；请停止旧服务，或使用 FRONTEND_PORT=其他端口 npm run dev:all。`,
    );
  }
}

function ensureLangGraph() {
  const configured = process.env.LANGGRAPH_BIN
    ? findExecutable(process.env.LANGGRAPH_BIN)
    : null;
  if (configured) return configured;

  if (existsSync(langgraphInVenv)) return langgraphInVenv;

  const systemLangGraph = findExecutable("langgraph");
  if (systemLangGraph) return systemLangGraph;

  const configuredPython = process.env.LANGGRAPH_PYTHON
    ? findExecutable(process.env.LANGGRAPH_PYTHON)
    : null;
  const python = configuredPython ?? findExecutable(isWindows ? "python" : "python3") ?? findExecutable("python");
  if (!python) {
    throw new Error("未找到 Python。请安装 Python 3.10+，或设置 LANGGRAPH_PYTHON。");
  }

  if (!existsSync(pythonInVenv)) {
    run(python, ["-m", "venv", virtualEnvironment], "创建 backend/.venv");
  }
  run(
    pythonInVenv,
    ["-m", "pip", "install", "-r", join(backendRoot, "requirements.txt")],
    "安装 LangGraph 依赖",
  );
  if (!existsSync(langgraphInVenv)) {
    throw new Error("LangGraph 安装后仍未找到可执行文件：" + langgraphInVenv);
  }
  return langgraphInVenv;
}

async function waitForBackend() {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (backendProcess?.exitCode !== null) {
      throw new Error("LangGraph 服务启动失败，请查看上方后端日志。");
    }
    try {
      const response = await fetch(`http://127.0.0.1:${backendPort}/ok`);
      if (response.ok) return;
    } catch {
      // The API can take a few seconds to import and compile the graph.
    }
    await delay(500);
  }
  throw new Error(`LangGraph 服务在 ${backendPort} 端口启动超时。`);
}

function stopProcess(child) {
  if (child && child.exitCode === null && !child.killed) child.kill("SIGTERM");
}

function shutdown(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  stopProcess(frontendProcess);
  stopProcess(backendProcess);
  process.exitCode = code;
}

async function main() {
  await assertPortsAvailable();
  const langgraph = ensureLangGraph();
  const sharedEnv = {
    ...process.env,
    LANGGRAPH_API_URL: process.env.LANGGRAPH_API_URL ?? `http://127.0.0.1:${backendPort}`,
    PYTHONUNBUFFERED: "1",
  };

  console.log(`[backend] LangGraph API ${backendPort} 启动中…`);
  backendProcess = spawn(
    langgraph,
    ["dev", "--config", backendConfig, "--host", "127.0.0.1", "--port", backendPort, "--no-browser"],
    { cwd: backendRoot, env: sharedEnv, stdio: "inherit" },
  );
  backendProcess.on("error", (error) => {
    if (!shuttingDown) {
      console.error("[backend] 启动失败：", error.message);
      shutdown(1);
    }
  });
  backendProcess.on("exit", (code) => {
    if (!shuttingDown) {
      console.error(`[backend] 已退出（状态码：${code ?? "unknown"}）`);
      shutdown(code ?? 1);
    }
  });

  await waitForBackend();
  console.log(`[frontend] Vite ${frontendPort} 启动中…`);
  const npm = isWindows ? "npm.cmd" : "npm";
  frontendProcess = spawn(npm, ["run", "dev"], {
    cwd: root,
    env: { ...sharedEnv, FRONTEND_PORT: frontendPort },
    stdio: "inherit",
  });
  frontendProcess.on("error", (error) => {
    if (!shuttingDown) {
      console.error("[frontend] 启动失败：", error.message);
      shutdown(1);
    }
  });
  frontendProcess.on("exit", (code) => {
    if (!shuttingDown) shutdown(code ?? 0);
  });
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

main().catch((error) => {
  console.error("\n一键启动失败：", error instanceof Error ? error.message : error);
  shutdown(1);
});
