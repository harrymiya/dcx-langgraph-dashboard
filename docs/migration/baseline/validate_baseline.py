#!/usr/bin/env python3
"""Validate the GOV-01 source and zero-deletion baseline using only stdlib."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


EXPECTED_ROUTES = [f"MP{number:03d}" for number in range(1, 164)]
PROTECTED_PATHS = {
    "pages/auth/login.uvue",
    "foundation/network/client.uts",
}
SOURCE_LEDGER_FIELDS = [
    "route_id",
    "source_route",
    "source_file",
    "function_domain",
    "legacy_entry_or_deep_link",
    "migration_target_page_or_module",
    "app_shell_entry",
    "phase",
    "auth_and_backend_ownership",
    "platform_dependencies",
    "dag_task_ids",
    "compatibility_and_fallback",
    "current_status",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True
    ).strip()


def clean_cell(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def inventory_rows(path: Path) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| MP"):
            cells = [clean_cell(cell) for cell in line.strip().strip("|").split("|")]
            require(len(cells) == 13, f"unexpected inventory row width: {len(cells)}")
            rows.append(cells)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[3]
    baseline = Path(__file__).resolve().parent
    source_root = args.source_root.resolve()
    for csv_path in baseline.glob("*.csv"):
        require(b"\r" not in csv_path.read_bytes(), f"CSV must use LF line endings: {csv_path.name}")
    snapshot = json.loads((baseline / "source-snapshot.json").read_text(encoding="utf-8"))
    task_list = json.loads((repo / "backend/tasks.json").read_text(encoding="utf-8"))
    gov01 = next(task for task in task_list if task.get("id") == "GOV-01")
    expected_sha_match = re.search(r"([0-9a-f]{40})", gov01["data"]["inputs"])
    require(expected_sha_match is not None, "GOV-01 input does not declare a source SHA")
    expected_sha = expected_sha_match.group(1)

    inventory_path = source_root / "docs/migration/mapp-page-migration-inventory.md"
    inventory_text = inventory_path.read_text(encoding="utf-8")
    declared_sha_match = re.search(r"固定 SHA `([0-9a-f]{40})`", inventory_text)
    require(declared_sha_match is not None, "inventory does not declare a fixed source SHA")
    declared_sha = declared_sha_match.group(1)
    require(expected_sha == declared_sha, "GOV-01 source SHA differs from inventory declaration")
    require(
        snapshot["declared_mapp_source_snapshot"]["expected_sha_from_GOV_01_input"]
        == expected_sha,
        "snapshot source SHA differs from GOV-01 input",
    )

    rows = inventory_rows(inventory_path)
    route_ids = [row[0] for row in rows]
    require(route_ids == EXPECTED_ROUTES, "inventory IDs are not unique MP001–MP163 sequence")
    require(len(rows) == 163, f"expected 163 inventory rows, got {len(rows)}")
    require(
        re.search(r"主包 6、分包 157、有效路由 163、分包根 11", inventory_text)
        is not None,
        "inventory package route counts differ from 6/157/163/11",
    )

    with (baseline / "zero-deletion-ledger.csv").open(encoding="utf-8", newline="") as f:
        ledger = list(csv.DictReader(f))
    require(len(ledger) == len(rows), "zero-deletion ledger row count differs from inventory")
    require([row["route_id"] for row in ledger] == route_ids, "ledger route IDs differ from inventory")
    for source_row, ledger_row in zip(rows, ledger, strict=True):
        for field, value in zip(SOURCE_LEDGER_FIELDS, source_row, strict=True):
            require(ledger_row[field] == value, f"inventory fact mismatch ({field}): {source_row[0]}")
        require(ledger_row["baseline_disposition"] == "retain-source-route", f"bad disposition: {source_row[0]}")
        require(ledger_row["deletion_approval"] == "none", f"unexpected deletion approval: {source_row[0]}")
        require(ledger_row["deletion_status"] == "not-deleted", f"route not protected: {source_row[0]}")

    with (baseline / "protected-paths.csv").open(encoding="utf-8", newline="") as f:
        protected = list(csv.DictReader(f))
    protected_by_path = {row["source_repository_path"]: row for row in protected}
    require(set(protected_by_path) == PROTECTED_PATHS, "login/network protected paths are incomplete")
    for path, row in protected_by_path.items():
        protected_file = source_root / path
        require(protected_file.is_file(), f"protected file missing at capture: {path}")
        require(row["exists_at_capture"] == "true", f"protected file not recorded as present: {path}")
        require(row["sha256_at_capture"] == sha256(protected_file), f"protected file changed: {path}")
        expected_protected = next(
            item for item in snapshot["protected_paths"] if item["path"] == path
        )
        require(expected_protected["sha256"] == sha256(protected_file), f"protected snapshot changed: {path}")

    with (baseline / "workspace-change-register.csv").open(encoding="utf-8", newline="") as f:
        changes = list(csv.DictReader(f))
    require(len(changes) >= 2, "workspace change register must capture both worktrees")
    by_root = {row["workspace_root"]: row for row in changes}
    source_snapshot = snapshot["inventory_repository_snapshot"]
    target_snapshot = snapshot["target_repository"]
    for root in (target_snapshot["root"], source_snapshot["root"]):
        require(root in by_root, f"workspace snapshot missing: {root}")
        require(by_root[root]["status"] == "clean", f"workspace not recorded clean: {root}")
    with (baseline / "workspace-change-register-template.csv").open(
        encoding="utf-8", newline=""
    ) as f:
        template_headers = next(csv.reader(f))
    require(template_headers == list(changes[0]), "change-register template fields differ")

    require(snapshot["route_baseline"]["baseline_route_deletion_count"] == 0, "snapshot deletion count is not zero")
    require(snapshot["route_baseline"]["deletion_approval_recorded"] is False, "snapshot claims deletion approval")
    require(snapshot["implementation_evidence"] is False, "snapshot must not claim implementation evidence")
    source_hashes = {
        "route_inventory_sha256": inventory_path,
        "overall_design_sha256": source_root / "docs/ruixin-health-app-scrm-complete-design.md",
        "cross_project_architecture_sha256": source_root / "docs/architecture/health-scrm-cross-project-architecture.md",
    }
    for field, path in source_hashes.items():
        require(source_snapshot[field] == sha256(path), f"captured source SHA-256 differs: {path}")
    require(git(source_root, "rev-parse", "HEAD") == source_snapshot["head"], "inventory source checkout drifted")
    require(not git(source_root, "status", "--porcelain=v1"), "inventory source worktree is dirty")

    result = {
        "status": "passed",
        "checks": {
            "task_input_sha_matches_inventory_declaration": "passed",
            "163_route_ids_unique_contiguous_and_mirrored": "passed",
            "all_inventory_facts_mirrored_in_zero_deletion_ledger": "passed",
            "zero_deletion_rows_and_no_approval": "passed",
            "login_and_network_paths_exist_and_match_captured_sha256": "passed",
            "both_worktrees_recorded_and_template_present": "passed",
            "captured_inventory_snapshot_unchanged": "passed",
        },
        "mapp_source_sha": expected_sha,
        "route_rows": len(rows),
        "unique_route_ids": len(set(route_ids)),
        "deletion_count": 0,
        "protected_paths": sorted(PROTECTED_PATHS),
        "inventory_repository_head": source_snapshot["head"],
        "mapp_git_object_directly_verified": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
