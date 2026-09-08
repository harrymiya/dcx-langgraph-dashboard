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
  ingestionStatus: IngestionStatus;
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
  ingestion_status?: IngestionStatus;
  [key: string]: unknown;
}
