import type {
  Assistant,
  AgentKind,
  BackendStatus,
  GraphDefinition,
  LiveTaskRecord,
  Project,
} from "./types";

const configuredApi = import.meta.env.VITE_LANGGRAPH_API_URL?.replace(/\/$/, "");
export const displayApiUrl = configuredApi ?? "http://127.0.0.1:8123";
const apiPath = (path: string) => (configuredApi ? configuredApi + path : "/langgraph" + path);

// 默认请求超时：防止后端 hang 住时 fetch 永远挂起、堆积成多个 in-flight
// 请求吃掉内存和连接，最终把标签页拖崩。runs/wait 是长轮询，需要更宽松的超时。
const DEFAULT_TIMEOUT_MS = 15_000;
const RUN_TIMEOUT_MS = 90_000;

export interface RequestOptions extends RequestInit {
  timeoutMs?: number;
}

function timeoutError(url: string, timeoutMs: number): Error {
  const error = new Error(`请求超时（${Math.round(timeoutMs / 1000)}s）：${url}`);
  error.name = "TimeoutError";
  return error;
}

async function fetchJson<T>(url: string, init: RequestOptions = {}, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const timeout = init.timeoutMs ?? timeoutMs;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  const externalSignal = init.signal;
  const onExternalAbort = () => controller.abort(externalSignal instanceof AbortSignal ? externalSignal.reason : undefined);
  if (externalSignal) {
    if (externalSignal.aborted) {
      window.clearTimeout(timer);
      throw externalSignal.reason instanceof Error ? externalSignal.reason : new Error("请求已取消：" + url);
    }
    externalSignal.addEventListener("abort", onExternalAbort, { once: true });
  }
  try {
    const { timeoutMs: _ignored, ...fetchInit } = init;
    const response = await fetch(url, { ...fetchInit, signal: controller.signal });
    if (!response.ok) throw new Error(response.status + " " + response.statusText);
    return response.json() as Promise<T>;
  } catch (error) {
    if (controller.signal.aborted && !externalSignal?.aborted) throw timeoutError(url, timeout);
    throw error;
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const url = apiPath(path);
  try {
    return await fetchJson<T>(url, {
      ...init,
      headers: {
        "content-type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "TimeoutError") throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求已取消：" + url);
    }
    throw error;
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  let detail = response.status + " " + response.statusText;
  try {
    const body = (await response.json()) as { error?: string };
    if (body.error) detail += ": " + body.error;
  } catch {
    // Keep the HTTP status when the launcher cannot return JSON.
  }
  return detail;
}

async function requestLocal<T>(path: string, init?: RequestOptions): Promise<T> {
  const timeout = init?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  const externalSignal = init?.signal;
  const onExternalAbort = () => controller.abort(externalSignal instanceof AbortSignal ? externalSignal.reason : undefined);
  if (externalSignal) {
    if (externalSignal.aborted) {
      window.clearTimeout(timer);
      throw new Error("请求已取消：" + path);
    }
    externalSignal.addEventListener("abort", onExternalAbort, { once: true });
  }
  try {
    const { timeoutMs: _ignored, ...fetchInit } = init ?? {};
    const response = await fetch(path, {
      ...fetchInit,
      signal: controller.signal,
      headers: {
        "content-type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
    if (!response.ok) throw new Error(await readErrorDetail(response));
    return response.json() as Promise<T>;
  } catch (error) {
    if (controller.signal.aborted && !externalSignal?.aborted) throw timeoutError(path, timeout);
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("请求已取消：" + path);
    throw error;
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}

export async function findAssistant(signal?: AbortSignal): Promise<Assistant> {
  const assistants = await request<Assistant[]>("/assistants/search", {
    method: "POST",
    body: "{}",
    signal,
  });
  const assistant = assistants.find((item) => item.graph_id === "refactor_dag") ?? assistants[0];
  if (!assistant) throw new Error("LangGraph 未注册可用 graph");
  return assistant;
}

export function loadGraphDefinition(assistantId: string, signal?: AbortSignal): Promise<GraphDefinition> {
  return request<GraphDefinition>("/assistants/" + assistantId + "/graph", { signal });
}

export async function checkBackend(signal?: AbortSignal): Promise<BackendStatus> {
  const checkedAt = new Date().toISOString();
  try {
    await request<{ ok: boolean }>("/ok", { signal });
    const assistant = await findAssistant(signal);
    return {
      connected: true,
      graphId: assistant.graph_id,
      assistantId: assistant.assistant_id,
      checkedAt,
    };
  } catch (error) {
    return {
      connected: false,
      checkedAt,
      error: error instanceof Error ? error.message : "LangGraph 服务不可用",
    };
  }
}

export async function runLangGraph(
  assistantId: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<LiveTaskRecord[]> {
  const thread = await request<{ thread_id: string }>("/threads", {
    method: "POST",
    body: JSON.stringify({ metadata: { project_id: projectId } }),
    signal,
  });
  const result = await request<{ tasks?: Record<string, LiveTaskRecord> }>(
    "/threads/" + thread.thread_id + "/runs/wait",
    {
      method: "POST",
      body: JSON.stringify({
        assistant_id: assistantId,
        input: { project_id: projectId },
        metadata: { project_id: projectId },
        config: { configurable: { project_id: projectId, checkpoint_ns: `project:${projectId}` } },
      }),
      signal,
      // runs/wait 是服务端长轮询，等图跑完才返回，必须给足超时。
      timeoutMs: RUN_TIMEOUT_MS,
    },
  );
  return Object.values(result.tasks ?? {});
}

export function listProjects(): Promise<Project[]> {
  return requestLocal<Project[]>("/api/projects");
}

export interface CreateProjectRequest {
  id: string;
  name: string;
  description?: string;
  workspace?: AgentWorkspace;
  sourceProjectId?: string;
}

export function createProject(payload: CreateProjectRequest): Promise<Project> {
  return requestLocal<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function archiveProject(projectId: string): Promise<Project> {
  return trashProject(projectId);
}

export function trashProject(projectId: string): Promise<Project> {
  return requestLocal<Project>("/api/projects/" + encodeURIComponent(projectId) + "/trash", {
    method: "POST",
    body: "{}",
  });
}

export function restoreProject(projectId: string): Promise<Project> {
  return requestLocal<Project>("/api/projects/" + encodeURIComponent(projectId) + "/restore", {
    method: "POST",
    body: "{}",
  });
}

export function deleteProjectPermanently(projectId: string): Promise<{ id: string; deleted: boolean }> {
  return requestLocal<{ id: string; deleted: boolean }>("/api/projects/" + encodeURIComponent(projectId), {
    method: "DELETE",
  });
}

export function emptyTrash(): Promise<{ deleted: string[] }> {
  return requestLocal<{ deleted: string[] }>("/api/projects/trash/empty", {
    method: "POST",
    body: "{}",
  });
}

export function updateProject(
  projectId: string,
  payload: { name?: string; description?: string; workspace?: string },
): Promise<Project> {
  return requestLocal<Project>("/api/projects/" + encodeURIComponent(projectId), {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export interface AgentLaunchRequest {
  agent: AgentKind;
  taskId: string;
  prompt: string;
  workspace?: AgentWorkspace;
  projectId: string;
}

export interface AgentLaunchResponse {
  ok: boolean;
  agent: AgentKind;
  taskId: string;
  workspace: AgentWorkspace;
  terminal: string;
  pid?: number;
  log?: string;
  message?: string;
}

export type AgentWorkspace = "APP18" | "APP19" | "APP20";

export function launchAgent(payload: AgentLaunchRequest): Promise<AgentLaunchResponse> {
  return requestLocal<AgentLaunchResponse>("/api/agents/launch", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type EvidenceReadyStatus = "code-ready" | "contract-ready";

export interface EvidenceSyncRequest {
  taskId: string;
  status: EvidenceReadyStatus;
  projectId: string;
}

export interface EvidenceSyncResponse {
  ok: boolean;
  taskId: string;
  status: EvidenceReadyStatus;
  statusSource: "evidence-manifest";
  commit: string;
  commits?: Record<string, string>;
  report: string;
  verifiedAt: string;
  evidenceCount: number;
  changed: boolean;
}

export function syncTaskEvidence(payload: EvidenceSyncRequest): Promise<EvidenceSyncResponse> {
  return requestLocal<EvidenceSyncResponse>("/api/evidence/sync", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
