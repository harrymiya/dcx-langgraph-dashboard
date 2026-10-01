#!/usr/bin/env python3
"""Validate overall-plan coverage, DAG integrity, and migration lane boundaries."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = ROOT / "backend" / "tasks.json"
ALLOWED_COVERAGE_STATUSES = {
    "planned",
    "current-state-retained",
    "out-of-scope-with-reason",
}
EXPECTED_MVP_COUNTS = {"MVP必须": 97, "MVP后续": 46}
EXPECTED_TASK_COUNT = 143
EXPECTED_WISH_CHAIN = [
    "APP",
    "Wish APP BFF",
    "Wish API/application service",
    "DDD",
]


class ValidationError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def read_tasks(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read tasks JSON: {exc}") from exc
    require(isinstance(payload, list), "backend/tasks.json must remain a task array")
    return payload


def split_display_deps(value: object) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def ensure_acyclic(tasks_by_id: dict[str, dict]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValidationError(f"dependency cycle detected at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in tasks_by_id[task_id].get("deps", []):
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in tasks_by_id:
        visit(task_id)


def parse_inventory(inventory_path: Path) -> dict[str, set[str]]:
    """Return inventory task ID -> MP page IDs from the source table."""
    lines = inventory_path.read_text(encoding="utf-8").splitlines()
    header_index = next(
        (i for i, line in enumerate(lines) if "DAG task ID" in line and line.lstrip().startswith("|")),
        None,
    )
    require(header_index is not None, f"inventory has no DAG task ID table: {inventory_path}")
    header = [cell.strip() for cell in lines[header_index].strip().strip("|").split("|")]
    task_column = next((i for i, cell in enumerate(header) if cell == "DAG task ID"), None)
    require(task_column is not None, "inventory table is missing its DAG task ID column")
    page_to_tasks: dict[str, set[str]] = {}
    task_token = re.compile(r"\b[A-Z][A-Z0-9]*-\d{2}\b")
    page_token = re.compile(r"\bMP\d{3}\b")
    for line in lines[header_index + 1 :]:
        if not line.lstrip().startswith("| MP"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) <= task_column:
            continue
        page_match = page_token.search(cells[0])
        if not page_match:
            continue
        page_id = page_match.group(0)
        for task_id in task_token.findall(cells[task_column]):
            page_to_tasks.setdefault(page_id, set()).add(task_id)
    task_to_pages: dict[str, set[str]] = {}
    for page_id, task_ids in page_to_tasks.items():
        for task_id in task_ids:
            task_to_pages.setdefault(task_id, set()).add(page_id)
    return task_to_pages


def validate_inventory_source(
    source_root: Path | None,
    tasks_by_id: dict[str, dict],
    selected_ids: set[str],
) -> str | None:
    if source_root is None:
        return "inventory source check skipped (no --source-root supplied)"
    inventory_path = source_root / "docs" / "migration" / "mapp-page-migration-inventory.md"
    if not inventory_path.is_file():
        return f"inventory source check skipped (not found: {inventory_path})"
    task_to_pages = parse_inventory(inventory_path)
    for task_id in sorted(selected_ids):
        data = tasks_by_id[task_id].get("data", {})
        declared = data.get("migration_source_page_ids")
        require(isinstance(declared, list) and declared, f"{task_id}: migration_source_page_ids is empty")
        require(len(declared) == len(set(declared)), f"{task_id}: duplicate migration source page ID")
        require(set(declared) == task_to_pages.get(task_id, set()), f"{task_id}: migration page IDs do not match inventory")
    return f"inventory source page mapping checked ({len(selected_ids)} selected tasks)"


def validate(path: Path, source_root: Path | None) -> list[str]:
    tasks = read_tasks(path)
    require(len(tasks) == EXPECTED_TASK_COUNT, f"expected {EXPECTED_TASK_COUNT} tasks, found {len(tasks)}")
    task_ids = [task.get("id") for task in tasks]
    require(all(isinstance(task_id, str) and task_id for task_id in task_ids), "every task needs a non-empty id")
    require(len(task_ids) == len(set(task_ids)), "task IDs are not unique")
    tasks_by_id = {task["id"]: task for task in tasks}

    task_statuses = Counter(task.get("status") for task in tasks)
    require(task_statuses == Counter({"planned": EXPECTED_TASK_COUNT}), f"all tasks must stay planned; found {dict(task_statuses)}")
    scope_counts = Counter(task.get("data", {}).get("scope") for task in tasks)
    require(scope_counts == Counter(EXPECTED_MVP_COUNTS), f"MVP scope counts differ: {dict(scope_counts)}")

    for task in tasks:
        task_id = task["id"]
        deps = task.get("deps")
        require(isinstance(deps, list), f"{task_id}: deps must be an array")
        require(len(deps) == len(set(deps)), f"{task_id}: duplicate dependency")
        for dependency in deps:
            require(dependency in tasks_by_id, f"{task_id}: missing dependency {dependency}")
        displayed = split_display_deps(task.get("data", {}).get("depends_on"))
        require(displayed == deps, f"{task_id}: data.depends_on does not match deps")
    ensure_acyclic(tasks_by_id)

    gov01 = tasks_by_id.get("GOV-01", {})
    coverage = gov01.get("data", {}).get("overall_plan_coverage")
    require(isinstance(coverage, dict), "GOV-01.data.overall_plan_coverage is missing")
    registry = coverage.get("requirements_registry")
    require(isinstance(registry, list) and registry, "overall-plan requirements registry is empty")
    source_files = {
        source.get("source_file")
        for source in coverage.get("source_docs", [])
        if isinstance(source, dict) and source.get("source_file")
    }
    require(len(source_files) == 3, "source_docs must register all three upper-level source documents")
    status_values = set(coverage.get("coverage_status_values", []))
    require(status_values == ALLOWED_COVERAGE_STATUSES, "coverage_status_values must match the allowed status set")
    lane_values = set(coverage.get("migration_lane_values", []))

    entries_by_id: dict[str, dict] = {}
    expected_reverse: dict[str, set[str]] = {task_id: set() for task_id in tasks_by_id}
    for entry in registry:
        source_id = entry.get("source_id")
        require(isinstance(source_id, str) and source_id, "registry item has an empty source_id")
        require(source_id not in entries_by_id, f"duplicate registry source_id: {source_id}")
        entries_by_id[source_id] = entry
        require(entry.get("source_file") in source_files, f"{source_id}: source_file is not registered in source_docs")
        require(bool(entry.get("source_section")), f"{source_id}: source_section is empty")
        require(bool(entry.get("requirement")), f"{source_id}: requirement text is empty")
        require(entry.get("coverage_status") in ALLOWED_COVERAGE_STATUSES, f"{source_id}: invalid coverage_status")
        require("client" in entry and entry["client"] is not None and entry["client"] != "", f"{source_id}: client is empty")
        require("backend_target" in entry, f"{source_id}: backend_target field is missing")
        require(entry.get("migration_lane") in lane_values, f"{source_id}: invalid migration_lane")
        if entry.get("coverage_status") == "out-of-scope-with-reason":
            require(bool(entry.get("coverage_reason")), f"{source_id}: out-of-scope item needs coverage_reason")
        mapped = entry.get("mapped_task_ids")
        require(isinstance(mapped, list) and mapped, f"{source_id}: mapped_task_ids is empty")
        require(len(mapped) == len(set(mapped)), f"{source_id}: duplicate mapped task ID")
        for task_id in mapped:
            require(task_id in tasks_by_id, f"{source_id}: mapped task does not exist: {task_id}")
            expected_reverse[task_id].add(source_id)

    for task_id, task in tasks_by_id.items():
        data = task.get("data", {})
        linked = data.get("source_item_ids")
        require(isinstance(linked, list) and linked, f"{task_id}: source_item_ids is empty")
        require(len(linked) == len(set(linked)), f"{task_id}: duplicate source_item_id")
        for source_id in linked:
            require(source_id in entries_by_id, f"{task_id}: source_item_id does not exist: {source_id}")
        require(set(linked) == expected_reverse[task_id], f"{task_id}: task/registry coverage links are not bidirectional")
        require(data.get("coverage_status") in ALLOWED_COVERAGE_STATUSES, f"{task_id}: invalid task coverage_status")
        if data.get("coverage_status") == "out-of-scope-with-reason":
            require(
                any(
                    entries_by_id[source_id].get("coverage_status") == "out-of-scope-with-reason"
                    and entries_by_id[source_id].get("coverage_reason")
                    for source_id in linked
                ),
                f"{task_id}: out-of-scope task coverage needs a linked reason",
            )
        truth = data.get("source_of_truth")
        require(isinstance(truth, list) and truth and all(truth), f"{task_id}: source_of_truth is empty")
        expected_truth = list(dict.fromkeys(entries_by_id[source_id]["source_file"] for source_id in linked))
        require(truth == expected_truth, f"{task_id}: source_of_truth does not resolve from source_item_ids")

    policy = data_policy = gov01.get("data", {}).get("migration_scope_policy", {})
    selected_ids = set(data_policy.get("selected_task_ids", []))
    wish_ids = set(data_policy.get("wish_native_task_ids", []))
    formal_ids = {task_id for task_id, task in tasks_by_id.items() if task.get("data", {}).get("migration_lane") == "formal-app-migration"}
    native_ids = {task_id for task_id, task in tasks_by_id.items() if task.get("data", {}).get("migration_lane") == "wish-formal-business"}
    require(len(selected_ids) == 35 and formal_ids == selected_ids, "formal-app-migration must equal the 35-task allowlist")
    require(len(wish_ids) == 13 and native_ids == wish_ids, "wish-formal-business must equal the 13-task native allowlist")
    require(not any(task_id.startswith("AUTH-") for task_id in tasks_by_id), "AUTH tasks are out of scope")
    for task_id in sorted(formal_ids):
        data = tasks_by_id[task_id].get("data", {})
        require(data.get("migration_scope") == "selected-page", f"{task_id}: migration_scope must be selected-page")
        require(data.get("migration_backend") == "MAPP server", f"{task_id}: migration_backend must be MAPP server")
        require(data.get("migration_source_file"), f"{task_id}: migration_source_file is empty")
        require(isinstance(data.get("migration_source_page_ids"), list) and data["migration_source_page_ids"], f"{task_id}: migration_source_page_ids is empty")
        require(not (set(tasks_by_id[task_id]["deps"]) & wish_ids), f"{task_id}: migration task directly depends on Wish-native task")
        require("Wish" not in str(data.get("backend_target_chain", [])), f"{task_id}: migration backend chain must not include Wish")
    for task_id in sorted(wish_ids):
        data = tasks_by_id[task_id].get("data", {})
        require(data.get("migration_scope") == "wish-native", f"{task_id}: migration_scope must be wish-native")
        require(data.get("migration_backend") is None, f"{task_id}: migration_backend must be null")
        require(data.get("backend_target_chain") == EXPECTED_WISH_CHAIN, f"{task_id}: invalid Wish backend chain")
        require("MAPP server" not in json.dumps(data.get("backend_target_chain"), ensure_ascii=False), f"{task_id}: Wish task references MAPP server")

    inventory_result = validate_inventory_source(source_root, tasks_by_id, selected_ids)
    return [
        f"PASS tasks: {len(tasks)} (planned={task_statuses['planned']}, MVP必须={scope_counts['MVP必须']}, MVP后续={scope_counts['MVP后续']})",
        f"PASS dependencies: all references exist; DAG is acyclic; data.depends_on matches deps",
        f"PASS coverage: {len(registry)} non-empty requirements; {len(tasks)} tasks linked bidirectionally; no unmapped task or registry item",
        f"PASS migration lanes: {len(formal_ids)} MAPP-selected tasks; {len(wish_ids)} Wish-native tasks; external and excluded lanes registered",
        f"PASS coverage statuses: {', '.join(sorted(ALLOWED_COVERAGE_STATUSES))}",
        f"PASS {inventory_result}",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=TASKS_PATH)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("/home/agent/code/jiankang_app_uniapp"),
        help="source repository root for exact selected-page ID verification",
    )
    args = parser.parse_args()
    source_root = args.source_root if args.source_root.exists() else None
    try:
        for result in validate(args.tasks, source_root):
            print(result)
    except ValidationError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
