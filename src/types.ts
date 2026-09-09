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
  description?: string;
  goal?: string;
  acceptance?: string;
  implementation?: string;
  section?: string;
  project?: string;
  output?: string;
  scope?: string;
  verify?: string;
  evidence?: unknown[];
  commit?: string;
  commits?: Record<string, string>;
  verifiedAt?: string;
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
  description?: unknown;
  summary?: unknown;
  goal?: unknown;
  objective?: unknown;
  target?: unknown;
  acceptance?: unknown;
  acceptance_criteria?: unknown;
  criteria?: unknown;
  implementation?: unknown;
  implementation_plan?: unknown;
  plan?: unknown;
  section?: string;
  project?: string;
  output?: string;
  scope?: string;
  verify?: string;
  evidence?: unknown[];
  commit?: string;
  commits?: Record<string, string>;
  verified_at?: string;
  [key: string]: unknown;
}
