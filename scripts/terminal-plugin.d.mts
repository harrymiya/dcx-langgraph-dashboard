import type { Plugin } from "vite";

export function resolveTerminalCwd(
  raw: unknown,
  agentWorkspaces: Record<string, string>,
  dashboardRoot: string,
): string | null;

export function terminalPlugin(): Plugin;
