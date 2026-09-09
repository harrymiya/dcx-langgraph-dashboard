export const AGENT_WORKSPACES = Object.freeze({
  APP18: "/mnt/data/code/dcx-web/dcx-web",
  APP19: "/mnt/data/code/dcx/dcx-web",
  APP20: "/mnt/data/code/well-log-platform",
});

export function resolveAgentWorkspace(value) {
  if (value === undefined) return AGENT_WORKSPACES.APP18;
  if (typeof value !== "string" || !Object.prototype.hasOwnProperty.call(AGENT_WORKSPACES, value)) return undefined;
  return AGENT_WORKSPACES[value];
}
