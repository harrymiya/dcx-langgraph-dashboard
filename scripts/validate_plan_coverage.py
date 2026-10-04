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
EXPECTED_MVP_COUNTS = {"MVP必须": 98, "MVP后续": 75}
EXPECTED_TASK_COUNT = 173
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


def parse_inventory(inventory_path: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    """Return task -> pages, page -> tasks, and business category -> pages."""
    lines = inventory_path.read_text(encoding="utf-8").splitlines()
    header_index = next(
        (i for i, line in enumerate(lines) if "DAG task ID" in line and line.lstrip().startswith("|")),
        None,
    )
    require(header_index is not None, f"inventory has no DAG task ID table: {inventory_path}")
    header = [cell.strip() for cell in lines[header_index].strip().strip("|").split("|")]
    task_column = next((i for i, cell in enumerate(header) if cell == "DAG task ID"), None)
    require(task_column is not None, "inventory table is missing its DAG task ID column")
    category_column = next((i for i, cell in enumerate(header) if cell in {"业务分类", "分类", "垂直业务"}), 3)
    page_to_tasks: dict[str, set[str]] = {}
    category_to_pages: dict[str, set[str]] = {}
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
        require(page_id not in page_to_tasks, f"inventory contains duplicate route page ID: {page_id}")
        require(len(cells) > category_column, f"{page_id}: inventory row has no business category")
        category = cells[category_column]
        require(bool(category), f"{page_id}: inventory business category is empty")
        category_to_pages.setdefault(category, set()).add(page_id)
        for task_id in task_token.findall(cells[task_column]):
            page_to_tasks.setdefault(page_id, set()).add(task_id)
    task_to_pages: dict[str, set[str]] = {}
    for page_id, task_ids in page_to_tasks.items():
        for task_id in task_ids:
            task_to_pages.setdefault(task_id, set()).add(page_id)
    return task_to_pages, page_to_tasks, category_to_pages


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
    task_to_pages, page_to_tasks, _ = parse_inventory(inventory_path)
    expected_page_ids = {f"MP{page:03d}" for page in range(1, 164)}
    require(set(page_to_tasks) == expected_page_ids, "inventory must map every route MP001–MP163 exactly once")
    referenced_task_ids = set(task_to_pages)
    route_policy = tasks_by_id["GOV-01"]["data"]["migration_scope_policy"]
    require(
        referenced_task_ids == set(route_policy["route_coverage_task_ids"]),
        "GOV-01 route_coverage_task_ids do not match inventory task references",
    )
    require(
        len(referenced_task_ids) == route_policy.get("route_coverage_task_count"),
        "GOV-01 route_coverage_task_count does not match route task references",
    )
    for page_id, task_ids in sorted(page_to_tasks.items()):
        require(task_ids, f"{page_id}: inventory route has no DAG task ID")
        for task_id in sorted(task_ids):
            require(task_id in tasks_by_id, f"{page_id}: inventory references missing task {task_id}")
    for task_id in sorted(referenced_task_ids):
        data = tasks_by_id[task_id].get("data", {})
        declared_routes = data.get("route_inventory_page_ids")
        require(isinstance(declared_routes, list) and declared_routes, f"{task_id}: route_inventory_page_ids is empty")
        require(len(declared_routes) == len(set(declared_routes)), f"{task_id}: duplicate route inventory page ID")
        require(set(declared_routes) == task_to_pages[task_id], f"{task_id}: route inventory page IDs do not match inventory")
    for task_id in sorted(selected_ids):
        data = tasks_by_id[task_id].get("data", {})
        declared = data.get("migration_source_page_ids")
        require(isinstance(declared, list) and declared, f"{task_id}: migration_source_page_ids is empty")
        require(len(declared) == len(set(declared)), f"{task_id}: duplicate migration source page ID")
        require(set(declared) == task_to_pages.get(task_id, set()), f"{task_id}: migration page IDs do not match inventory")
    formal_pages = {page_id for task_id in selected_ids for page_id in task_to_pages[task_id]}
    require(len(formal_pages) == 159, f"formal MAPP migration must cover 159 inventory pages; found {len(formal_pages)}")
    require(
        len(page_to_tasks) == tasks_by_id["GOV-01"]["data"]["migration_scope_policy"]["mapp_inventory_route_count"],
        "GOV-01 MAPP inventory route count does not match inventory",
    )
    require(
        len(formal_pages) == tasks_by_id["GOV-01"]["data"]["migration_scope_policy"]["formal_mapp_page_count"],
        "GOV-01 formal MAPP page count does not match selected migration tasks",
    )
    return f"inventory routes mapped and declared ({len(page_to_tasks)} pages; {len(formal_pages)} formal MAPP pages; {len(referenced_task_ids)} route tasks)"



def validate_vertical_closures(
    source_root: Path | None,
    tasks_by_id: dict[str, dict],
) -> str:
    registry = tasks_by_id["GOV-01"].get("data", {}).get("vertical_closure_registry")
    require(isinstance(registry, dict), "GOV-01.data.vertical_closure_registry is missing")
    required_layers = registry.get("required_layers")
    require(isinstance(required_layers, list) and required_layers, "vertical closure required_layers is empty")
    expected_layers = {
        "app_task_ids",
        "admin_frontend_task_ids",
        "backend_api_domain_task_ids",
        "database_task_ids",
        "navigation_task_ids",
        "integration_acceptance_task_ids",
    }
    require(set(required_layers) == expected_layers, "vertical closure required layers are incomplete or unexpected")
    verticals = registry.get("verticals")
    require(isinstance(verticals, list) and verticals, "vertical closure registry has no verticals")
    vertical_ids = [v.get("vertical_id") for v in verticals]
    require(all(isinstance(v, str) and v for v in vertical_ids), "vertical closure row has an empty vertical_id")
    require(len(vertical_ids) == len(set(vertical_ids)), "vertical closure IDs are duplicated")

    registered_task_ids: set[str] = set()
    assigned_categories: list[str] = []
    assigned_pages: set[str] = set()
    for vertical in verticals:
        vertical_id = vertical["vertical_id"]
        require(bool(vertical.get("name")), f"{vertical_id}: name is empty")
        require(bool(vertical.get("authoritative_backend")), f"{vertical_id}: authoritative backend is empty")
        require(bool(vertical.get("authoritative_database")), f"{vertical_id}: authoritative database is empty")
        for layer in required_layers:
            ids = vertical.get(layer)
            require(isinstance(ids, list) and ids, f"{vertical_id}: {layer} is empty")
            require(len(ids) == len(set(ids)), f"{vertical_id}: duplicate task in {layer}")
            for task_id in ids:
                require(task_id in tasks_by_id, f"{vertical_id}: {layer} references missing task {task_id}")
                registered_task_ids.add(task_id)
        nav = vertical.get("admin_navigation")
        require(isinstance(nav, dict), f"{vertical_id}: admin_navigation is missing")
        for field in ("system", "primary_group", "menu_items", "source_routes"):
            value = nav.get(field)
            require(bool(value), f"{vertical_id}: admin_navigation.{field} is empty")
        require(isinstance(nav["menu_items"], list) and nav["menu_items"], f"{vertical_id}: no admin menu items")
        require(
            set(vertical["navigation_task_ids"]).issubset(set(vertical["admin_frontend_task_ids"])),
            f"{vertical_id}: navigation tasks must be registered admin frontend tasks",
        )
        categories = vertical.get("inventory_categories")
        require(isinstance(categories, list), f"{vertical_id}: inventory_categories must be a list")
        assigned_categories.extend(categories)
        route_pages = vertical.get("route_page_ids")
        route_tasks = vertical.get("route_task_ids")
        require(isinstance(route_pages, list) and isinstance(route_tasks, list), f"{vertical_id}: route mapping must be lists")
        require(len(route_pages) == len(set(route_pages)), f"{vertical_id}: duplicate route page ID")
        require(len(route_tasks) == len(set(route_tasks)), f"{vertical_id}: duplicate route task ID")
        require(set(route_tasks).issubset(set(vertical["app_task_ids"])), f"{vertical_id}: route tasks are absent from app layer")
        assigned_pages.update(route_pages)

        # MAPP integration must depend on APP/admin work and on explicit evidence
        # that the original API and database remain the shared write path.
        for integration_id in vertical["integration_acceptance_task_ids"]:
            task = tasks_by_id[integration_id]
            if task.get("data", {}).get("migration_lane") == "mapp-vertical-closure":
                required_deps = set(vertical["app_task_ids"])
                for layer in ("admin_frontend_task_ids", "backend_api_domain_task_ids", "database_task_ids"):
                    required_deps.update(vertical[layer])
                require(
                    required_deps.issubset(set(task.get("deps", []))),
                    f"{vertical_id}: {integration_id} does not depend on every APP/admin/API/database task",
                )

    require(len(assigned_categories) == len(set(assigned_categories)), "an inventory business category is assigned to multiple verticals")
    policy = tasks_by_id["GOV-01"].get("data", {}).get("migration_scope_policy", {})
    mapp_ids = set(policy.get("mapp_vertical_closure_task_ids", []))
    actual_mapp_ids = {
        task_id for task_id, task in tasks_by_id.items()
        if task.get("data", {}).get("migration_lane") == "mapp-vertical-closure"
    }
    require(mapp_ids == actual_mapp_ids, "GOV-01 MAPP vertical closure task IDs do not match DAG lane")
    require(policy.get("mapp_vertical_closure_task_count") == len(mapp_ids), "MAPP vertical closure task count is stale")
    require(mapp_ids.issubset(registered_task_ids), "MAPP closure task is absent from the vertical matrix")
    mapp_reuse_policy = registry.get("mapp_migration_backend_policy")
    require(isinstance(mapp_reuse_policy, dict), "MAPP migration backend reuse policy is missing")
    prohibited = mapp_reuse_policy.get("prohibit", [])
    require(
        mapp_reuse_policy.get("app_backend") == "reuse-original-mapp-server-api"
        and mapp_reuse_policy.get("database") == "reuse-original-mapp-database"
        and mapp_reuse_policy.get("admin_gap_extension") == "extend-original-mapp-owner-code-only-after-a-confirmed-gap"
        and "migration-dedicated-backend" in prohibited
        and "parallel-database" in prohibited
        and "duplicate-write-master" in prohibited,
        "MAPP migration must reuse the original API/database without a parallel writer",
    )
    mapp_verticals = [vertical for vertical in verticals if vertical.get("owner", "").startswith("MAPP")]
    require(len(mapp_verticals) == 6, f"expected six MAPP verticals using the original backend, found {len(mapp_verticals)}")
    for vertical in mapp_verticals:
        require(
            vertical.get("backend_database_mode") == "reuse-original-mapp-server-and-database",
            f"{vertical['vertical_id']}: must reuse original MAPP backend/database",
        )
        require(bool(vertical.get("backend_gap_policy")), f"{vertical['vertical_id']}: original backend extension policy is missing")
    for task_id in sorted(mapp_ids):
        data = tasks_by_id[task_id].get("data", {})
        if task_id.endswith("-02"):
            require(data.get("backend_reuse_mode") == "reuse-original-mapp-server", f"{task_id}: must reuse original MAPP server/API")
        elif task_id.endswith("-03"):
            require(data.get("database_reuse_mode") == "reuse-original-mapp-database", f"{task_id}: must reuse original MAPP database")
        elif task_id.endswith("-04"):
            require(data.get("backend_database_mode") == "shared-original-mapp-server-and-database", f"{task_id}: integration must use original MAPP backend/database")
    require(len(verticals) == len(policy.get("vertical_registry_ids", [])), "vertical registry ID summary is stale")
    require(set(vertical_ids) == set(policy.get("vertical_registry_ids", [])), "vertical registry ID summary differs")

    checked_target_paths = 0
    if source_root is not None:
        workspace_root = source_root.parent.resolve()
        mapp_repo_roots = {"mapp_plat_web", "mapp_mer_web", "mapp_server"}
        for task_id in sorted(mapp_ids):
            if not re.fullmatch(r"V(?:COM|ORD|MEM|CNT|USR|MER)-0[123]", task_id):
                continue
            data = tasks_by_id[task_id].get("data", {})
            raw_paths = data.get("target_paths_or_modules")
            require(isinstance(raw_paths, str) and raw_paths.strip(), f"{task_id}: target_paths_or_modules is empty")
            target_paths = [part.strip() for part in raw_paths.split(";") if part.strip()]
            require(bool(target_paths), f"{task_id}: target_paths_or_modules has no paths")
            for raw_path in target_paths:
                relative_path = Path(raw_path)
                require(not relative_path.is_absolute(), f"{task_id}: target path must be workspace-relative: {raw_path}")
                require(".." not in relative_path.parts, f"{task_id}: target path escapes workspace: {raw_path}")
                require(
                    relative_path.parts and relative_path.parts[0] in mapp_repo_roots,
                    f"{task_id}: target path is outside the MAPP implementation repositories: {raw_path}",
                )
                target_path = (workspace_root / relative_path).resolve()
                require(
                    target_path.is_relative_to(workspace_root),
                    f"{task_id}: target path escapes workspace after resolution: {raw_path}",
                )
                require(target_path.exists(), f"{task_id}: target path does not exist: {raw_path}")
                checked_target_paths += 1

    if source_root is not None:
        inventory_path = source_root / "docs" / "migration" / "mapp-page-migration-inventory.md"
        if inventory_path.is_file():
            _, page_to_tasks, category_to_pages = parse_inventory(inventory_path)
            require(set(assigned_categories) == set(category_to_pages), "vertical registry does not cover every inventory business category")
            category_to_tasks: dict[str, set[str]] = {}
            for category, pages in category_to_pages.items():
                category_to_tasks[category] = {task_id for page in pages for task_id in page_to_tasks[page]}
            for vertical in verticals:
                categories = vertical["inventory_categories"]
                expected_pages = {page for category in categories for page in category_to_pages[category]}
                expected_tasks = {task_id for category in categories for task_id in category_to_tasks[category]}
                require(set(vertical["route_page_ids"]) == expected_pages, f"{vertical['vertical_id']}: route pages do not match source categories")
                require(set(vertical["route_task_ids"]) == expected_tasks, f"{vertical['vertical_id']}: route tasks do not match source categories")
            require(len(assigned_pages) == 163, f"vertical closure matrix must assign all 163 source routes; found {len(assigned_pages)}")
            require(assigned_pages == set(page_to_tasks), "vertical closure matrix route pages differ from source inventory")
        else:
            require(not assigned_categories, "cannot validate vertical categories without source inventory")
    target_summary = f"; {checked_target_paths} MAPP implementation target paths exist" if checked_target_paths else ""
    return f"vertical closures: {len(verticals)} domains; {len(mapp_ids)} MAPP admin/original-backend reuse/integration tasks; all 163 source routes assigned{target_summary}"

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
    require(len(selected_ids) == 40 and formal_ids == selected_ids, "formal-app-migration must equal the 40-task allowlist")
    require(data_policy.get("selected_task_count") == len(selected_ids), "GOV-01 selected_task_count does not match selected_task_ids")
    require(data_policy.get("unassigned_route_count") == 0, "GOV-01 must not leave MAPP routes without a DAG task")
    require(len(wish_ids) == 13 and native_ids == wish_ids, "wish-formal-business must equal the 13-task native allowlist")
    admin_sso = tasks_by_id.get("WADM-17")
    require(admin_sso is not None, "WADM-17 admin SSO delivery task is required")
    require(
        {"ARCH-14-ADMIN-SSO-DELIVERY", "OUT-04-ADMIN-SSO"}.issubset(
            set(admin_sso.get("data", {}).get("source_item_ids", []))
        ),
        "WADM-17 must cover both admin SSO source requirements",
    )
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
    vertical_result = validate_vertical_closures(source_root, tasks_by_id)
    return [
        f"PASS tasks: {len(tasks)} (planned={task_statuses['planned']}, MVP必须={scope_counts['MVP必须']}, MVP后续={scope_counts['MVP后续']})",
        f"PASS dependencies: all references exist; DAG is acyclic; data.depends_on matches deps",
        f"PASS coverage: {len(registry)} non-empty requirements; {len(tasks)} tasks linked bidirectionally; no unmapped task or registry item",
        f"PASS migration lanes: {len(formal_ids)} MAPP-selected tasks; {len(wish_ids)} Wish-native tasks; external and excluded lanes registered",
        f"PASS coverage statuses: {', '.join(sorted(ALLOWED_COVERAGE_STATUSES))}",
        f"PASS {inventory_result}",
        f"PASS {vertical_result}",
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
