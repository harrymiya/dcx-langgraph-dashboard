import type { Plugin } from "vite";

export function resolveTerminalCwd(
  raw: unknown,
  agentWorkspaces: Record<string, string>,
  dashboardRoot: string,
): string;

export function terminalPlugin(): Plugin;
