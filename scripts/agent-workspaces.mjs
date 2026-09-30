import { homedir } from "node:os";
import { resolve } from "node:path";

// 常用工作目录预设，仅作为输入快捷方式；不是白名单，任何目录都可以直接填。
export const AGENT_WORKSPACES = Object.freeze({
  APP18: "/mnt/data/code/dcx-web/dcx-web",
  APP19: "/mnt/data/code/dcx/dcx-web",
  APP20: "/mnt/data/code/well-log-platform",
});

export function expandHome(input) {
  if (input === "~") return homedir();
  if (input.startsWith("~/") || input.startsWith("~\\")) return resolve(homedir(), input.slice(2));
  return input;
}

// 输入预设名（APP18/APP19/APP20）返回对应路径；其他输入一律当作任意目录处理。
export function resolveAgentWorkspace(value) {
  if (value === undefined || value === null) return AGENT_WORKSPACES.APP18;
  if (typeof value !== "string") return undefined;
  const key = value.trim();
  if (!key) return AGENT_WORKSPACES.APP18;
  if (Object.prototype.hasOwnProperty.call(AGENT_WORKSPACES, key)) {
    return resolve(AGENT_WORKSPACES[key]);
  }
  return resolve(expandHome(key));
}
