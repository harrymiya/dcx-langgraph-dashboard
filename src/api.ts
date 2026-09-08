import type {
  Assistant,
  BackendStatus,
  GraphDefinition,
  LiveTaskRecord,
} from "./types";

const configuredApi = import.meta.env.VITE_LANGGRAPH_API_URL?.replace(/\/$/, "");
export const displayApiUrl = configuredApi ?? "http://127.0.0.1:8123";
const apiPath = (path: string) => (configuredApi ? configuredApi + path : "/langgraph" + path);

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiPath(path), {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) throw new Error(response.status + " " + response.statusText);
  return response.json() as Promise<T>;
}

export async function findAssistant(): Promise<Assistant> {
  const assistants = await request<Assistant[]>("/assistants/search", {
    method: "POST",
    body: "{}",
  });
  const assistant = assistants.find((item) => item.graph_id === "refactor_dag") ?? assistants[0];
  if (!assistant) throw new Error("LangGraph 未注册可用 graph");
  return assistant;
}

export function loadGraphDefinition(assistantId: string): Promise<GraphDefinition> {
  return request<GraphDefinition>("/assistants/" + assistantId + "/graph");
}

export async function checkBackend(): Promise<BackendStatus> {
  const checkedAt = new Date().toISOString();
  try {
    await request<{ ok: boolean }>("/ok");
    const assistant = await findAssistant();
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

export async function runLangGraph(assistantId: string): Promise<LiveTaskRecord[]> {
  const thread = await request<{ thread_id: string }>("/threads", {
    method: "POST",
    body: "{}",
  });
  const result = await request<{ tasks?: Record<string, LiveTaskRecord> }>(
    "/threads/" + thread.thread_id + "/runs/wait",
    {
      method: "POST",
      body: JSON.stringify({ assistant_id: assistantId, input: {} }),
    },
  );
  return Object.values(result.tasks ?? {});
}
