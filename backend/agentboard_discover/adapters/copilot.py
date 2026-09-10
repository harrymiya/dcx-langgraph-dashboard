"""GitHub Copilot CLI process and session adapter."""

import datetime as dt
import json
import os
import re
import time

from .base import AgentAdapter, DiscoveryContext, process_cwd, read_jsonl


COPILOT_HOME = os.environ.get("AGENTBOARD_COPILOT_HOME", os.path.expanduser("~/.copilot"))
ACTIVE_WINDOW = 15.0


def _event_epoch(value):
    if isinstance(value, (int, float)):
        value = float(value)
        return value / 1000 if value > 10_000_000_000 else value
    try:
        text = str(value or "").replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _event_text(event):
    """Extract user-visible assistant/tool summaries from Copilot events."""
    data = event.get("data") or {}
    if event.get("type") == "assistant.message":
        content = data.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text") or item.get("intentionSummary")
                if text:
                    parts.append(str(text))
            return " ".join(parts)
    if event.get("type") == "tool.execution_start":
        name = data.get("toolName") or data.get("tool_name")
        return f"tool: {name}" if name else "tool execution started"
    return ""


def _session_for_pid(pid):
    root = os.path.join(COPILOT_HOME, "session-state")
    try:
        names = os.listdir(root)
    except OSError:
        return None
    lock = f"inuse.{int(pid)}.lock"
    for name in names:
        if os.path.isfile(os.path.join(root, name, lock)):
            return os.path.join(root, name, "events.jsonl")

    # A process can briefly exist before Copilot creates its in-use lock.
    cwd = process_cwd(pid)
    candidates = []
    for name in names:
        path = os.path.join(root, name, "events.jsonl")
        if not os.path.isfile(path):
            continue
        score = os.path.getmtime(path)
        if cwd:
            workspace = os.path.join(root, name, "workspace.yaml")
            try:
                with open(workspace, encoding="utf-8", errors="replace") as fh:
                    if cwd in fh.read():
                        score += 10**9
            except OSError:
                pass
        candidates.append((score, path))
    return max(candidates)[1] if candidates else None


def copilot_think(pid, limit=5):
    path = _session_for_pid(pid)
    if not path:
        return [], False
    entries = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    event = json.loads(line)
                except (TypeError, ValueError):
                    continue
                text = " ".join(_event_text(event).split())[:160]
                stamp = _event_epoch(event.get("timestamp"))
                if not text or stamp is None:
                    continue
                entries.append((stamp, time.strftime("%H:%M:%S", time.localtime(stamp)), text))
    except OSError:
        return [], False
    entries = sorted(entries, key=lambda item: item[0])[-limit:]
    return [(hms, text) for _, hms, text in entries], bool(
        entries and time.time() - entries[-1][0] <= ACTIVE_WINDOW
    )


def _subagent_cards(path):
    """Build virtual cards for task-based Copilot sub-agents in one session."""
    if not path:
        return []
    tasks = {}
    started = {}
    completed = set()
    child_activity = {}
    for event in read_jsonl(path):
        event_type = event.get("type")
        data = event.get("data") or {}
        stamp = _event_epoch(event.get("timestamp")) or 0
        if event_type == "tool.execution_start" and data.get("toolName") == "task":
            arguments = data.get("arguments") or {}
            call_id = data.get("toolCallId")
            if call_id:
                tasks[call_id] = {
                    "start": stamp,
                    "name": arguments.get("name") or arguments.get("description") or "sub-agent",
                    "description": arguments.get("description") or arguments.get("prompt") or "",
                }
        elif event_type == "subagent.started":
            call_id = data.get("toolCallId") or event.get("agentId")
            if call_id:
                started[call_id] = data
        elif event_type == "subagent.completed":
            call_id = data.get("toolCallId") or event.get("agentId")
            if call_id:
                completed.add(call_id)
        parent_call = event.get("parentToolCallId")
        if parent_call and event_type == "tool.execution_start":
            name = data.get("toolName") or "tool"
            child_activity.setdefault(parent_call, []).append((stamp, name))
        if parent_call and event_type == "assistant.message":
            text = _event_text(event)
            if text:
                child_activity.setdefault(parent_call, []).append((stamp, text))

    cards = []
    for call_id, metadata in started.items():
        task = tasks.get(call_id, {})
        display_name = metadata.get("agentDisplayName") or metadata.get("agentName") or "Sub-agent"
        short_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(call_id))[-12:] or "unknown"
        label = " ".join(str(task.get("name") or display_name).split())[:100]
        command = " ".join(str(task.get("description") or display_name).split())[:240]
        activity = sorted(child_activity.get(call_id, []), key=lambda item: item[0])
        think = []
        for stamp, text in activity[-5:]:
            if text.startswith("tool:"):
                summary = text
            elif text in ("tool", ""):
                continue
            else:
                summary = text
            think.append((time.strftime("%H:%M:%S", time.localtime(stamp)), summary[:160]))
        if not think and command:
            think = [(time.strftime("%H:%M:%S", time.localtime(task.get("start") or time.time())), command)]
        status = "done" if call_id in completed else "running"
        cards.append({"agent": f"copilot-sub-{short_id}", "start": task.get("start") or time.time(),
                      "command": f"{display_name}: {command}", "status": status,
                      "think": think, "message": label})
    return cards


class CopilotAdapter(AgentAdapter):
    """Discover Copilot CLI processes and summarize their local event stream."""

    name = "copilot"
    _executables = ("copilot", "github-copilot", "github-copilot-cli")

    def matches(self, comm, cmdline):
        first = cmdline.split()[0].rsplit("/", 1)[-1] if cmdline.split() else ""
        if comm in self._executables or first in self._executables:
            return True
        if (re.search(r"(?:^|\s)copilot(?:\s|$)", cmdline) or
                any(re.search(rf"(?:^|\s)(?:\S*/)?{re.escape(name)}(?:\s|$)", cmdline)
                    for name in self._executables[1:])):
            return True
        # VS Code hosts Copilot in a path such as @github/copilot-linux-x64.
        return bool(re.search(r"(?:^|/)@github/copilot(?:[-/\s]|$)", cmdline) or
                    re.search(r"(?:^|\s)gh(?:\s+[^\s]+)*\s+copilot(?:\s|$)", cmdline))

    def discover(self, context: DiscoveryContext, processes):
        count = 0
        for process in processes:
            if process.kind != self.name:
                continue
            think, active = copilot_think(process.pid)
            status = "running" if active else "idle"
            events = []
            if think:
                events.append((think[-1][0], "active", status, think[-1][1]))
            context.write_process(process, self.name, status=status, think=think, events=events)
            for subagent in _subagent_cards(_session_for_pid(process.pid)):
                context.write_virtual(subagent["agent"], subagent["start"], subagent["command"],
                                      subagent["status"], subagent["think"], subagent["message"])
                count += 1
            count += 1
        return count
