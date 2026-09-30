"""Self-contained LangGraph service for the refactor DAG dashboard."""

from __future__ import annotations

import json
import operator
import os
import re
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


ROOT = Path(__file__).resolve().parent
TASKS_PATH = ROOT / "tasks.json"
TASKS = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
PROJECT_RUNTIME_ROOT = Path(os.environ.get("PROJECT_RUNTIME_ROOT", ROOT / ".project-runtime"))
PROJECT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_task_snapshot_mtime_ns: dict[str, int] = {}
_task_snapshot_by_project: dict[str, dict[str, dict]] = {}


def task_snapshot(project_id: str) -> dict[str, dict]:
    """Load only the selected project's task snapshot; never mix project state."""
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ValueError("invalid project_id")
    path = PROJECT_RUNTIME_ROOT / "projects" / project_id / "tasks.json"
    if not path.is_file():
        if project_id == "default":
            return {task["id"]: task for task in TASKS}
        raise FileNotFoundError(f"project task snapshot not found: {project_id}")
    try:
        mtime_ns = path.stat().st_mtime_ns
        if project_id not in _task_snapshot_by_project or _task_snapshot_mtime_ns.get(project_id) != mtime_ns:
            tasks = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(tasks, list) and all(isinstance(task, dict) and "id" in task for task in tasks):
                _task_snapshot_by_project[project_id] = {task["id"]: task for task in tasks}
                _task_snapshot_mtime_ns[project_id] = mtime_ns
    except (OSError, json.JSONDecodeError, TypeError):
        # Keep the last known good snapshot; the sync endpoint writes atomically.
        pass
    return _task_snapshot_by_project.get(project_id, {task["id"]: task for task in TASKS})


def current_task(task_id: str, fallback: dict, project_id: str) -> dict:
    return task_snapshot(project_id).get(task_id, fallback)


class DagState(TypedDict):
    tasks: Annotated[dict, operator.or_]
    project_id: str


def build_graph():
    builder = StateGraph(DagState)

    def make_node(task_id: str, fallback_task: dict):
        def node(state: DagState) -> dict:
            project_id = state.get("project_id", "default")
            task = current_task(task_id, fallback_task, project_id)
            record = {
                "id": task["id"],
                "project_id": project_id,
                "status": task.get("status", "planned"),
                "status_source": task.get("status_source", "bundled-task-snapshot"),
                "ingestion_status": "ingested",
                "section": task.get("section", ""),
                "project": task.get("project", ""),
                "output": task.get("output", ""),
                "scope": task.get("scope", ""),
                "verify": task.get("verify", ""),
                "evidence": task.get("evidence", []),
            }
            for field in ("owner", "commit", "commits", "verified_at"):
                if field in task:
                    record[field] = task[field]
            return {"tasks": {task["id"]: record}}

        return node

    for task in TASKS:
        builder.add_node(task["id"], make_node(task["id"], task))

    ids = {task["id"] for task in TASKS}
    dependents = {task_id: [] for task_id in ids}
    for task in TASKS:
        if not task.get("deps"):
            builder.add_edge(START, task["id"])
        for dependency in task.get("deps", []):
            builder.add_edge(dependency, task["id"])
            dependents[dependency].append(task["id"])

    for task in TASKS:
        if not dependents[task["id"]]:
            builder.add_edge(task["id"], END)

    return builder


graph = build_graph().compile()
