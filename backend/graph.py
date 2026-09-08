"""Self-contained LangGraph service for the refactor DAG dashboard."""

from __future__ import annotations

import json
import operator
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


ROOT = Path(__file__).resolve().parent
TASKS = json.loads((ROOT / "tasks.json").read_text(encoding="utf-8"))
for task in TASKS:
    task["status_source"] = "bundled-task-snapshot"


class DagState(TypedDict):
    tasks: Annotated[dict, operator.or_]


def build_graph():
    builder = StateGraph(DagState)

    def make_node(task: dict):
        def node(_: DagState) -> dict:
            return {
                "tasks": {
                    task["id"]: {
                        "id": task["id"],
                        "status": task.get("status", "planned"),
                        "status_source": "bundled-task-snapshot",
                        "ingestion_status": "ingested",
                        "section": task.get("section", ""),
                        "project": task.get("project", ""),
                        "output": task.get("output", ""),
                        "scope": task.get("scope", ""),
                        "verify": task.get("verify", ""),
                        "evidence": [],
                    }
                }
            }

        return node

    for task in TASKS:
        builder.add_node(task["id"], make_node(task))

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
