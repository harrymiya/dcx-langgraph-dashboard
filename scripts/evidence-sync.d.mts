export interface EvidenceSyncPayload {
  taskId: string;
  status: "code-ready" | "contract-ready";
}

export interface EvidenceSyncResult {
  tasks: Array<Record<string, unknown>>;
  taskId: string;
  status: EvidenceSyncPayload["status"];
  statusSource: "evidence-manifest";
  commit: string;
  commits?: Record<string, string>;
  report: string;
  verifiedAt: string;
  evidenceCount: number;
  changed: boolean;
}

export function reconcileEvidenceSnapshot(input: {
  tasks: Array<Record<string, unknown>>;
  manifest: Record<string, unknown>;
}): {
  tasks: Array<Record<string, unknown>>;
  changed: boolean;
};

export function buildEvidenceUpdate(input: {
  tasks: Array<Record<string, unknown>>;
  manifest: Record<string, unknown>;
  payload: EvidenceSyncPayload;
}): EvidenceSyncResult;
