export const AGENT_WORKSPACES: Readonly<{
  APP18: "/mnt/data/code/dcx-web/dcx-web";
  APP19: "/mnt/data/code/dcx/dcx-web";
  APP20: "/mnt/data/code/well-log-platform";
}>;

export type AgentWorkspace = keyof typeof AGENT_WORKSPACES;

export function resolveAgentWorkspace(value?: unknown): string | undefined;
