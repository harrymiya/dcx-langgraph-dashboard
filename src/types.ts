export type DagStatus =
  | "planned"
  | "in-progress"
  | "blocked"
  | "code-ready"
  | "contract-ready"
  | "release-ready"
  | "unknown"
  | "control";

export type IngestionStatus = "ingested" | "not-ingested" | "unknown";

export type AgentKind = "opencode" | "pi" | "codex";

export interface GraphNode {
  id: string;
  type?: string;
  data?: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
}

export interface GraphDefinition {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface DagTask {
  id: string;
  label: string;
  type: string;
  group: string;
  isControl: boolean;
  deps: string[];
  status: DagStatus;
  statusSource: string;
  ingestionStatus: IngestionStatus;
  section?: string;
  project?: string;
  output?: string;
  scope?: string;
  verify?: string;
  evidence?: unknown[];
  data: Record<string, unknown>;
}

export interface BackendStatus {
  connected: boolean;
  graphId?: string;
  assistantId?: string;
  checkedAt: string;
  error?: string;
}

export interface Assistant {
  assistant_id: string;
  graph_id: string;
  name?: string;
}

export interface LiveTaskRecord {
  id: string;
  status?: DagStatus;
  status_source?: string;
  ingestion_status?: IngestionStatus;
  section?: string;
  project?: string;
  output?: string;
  scope?: string;
  verify?: string;
  evidence?: unknown[];
  [key: string]: unknown;
}
