"""Read-only, SQLite-friendly quality gates for Wish health/SCRM snapshots.

This module deliberately has no database driver dependency beyond Python's
standard library. It inspects a caller-supplied SQLite connection and never
opens a connection itself. It is intended for synthetic fixtures and offline
backup/restore verification, not production access or DDL execution.

Reports contain only schema names, counts, and SHA-256 fingerprints. Row
values (including health payloads) are never included in findings or exports.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Sequence


CONTRACT_VERSION = "db08-health-scrm-gates-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RAW_SENSITIVE_COLUMNS = frozenset(
    {
        "address",
        "display_name",
        "email",
        "email_address",
        "first_name",
        "full_name",
        "health_body",
        "health_content",
        "health_text",
        "id_card_number",
        "mobile",
        "national_id",
        "note_body",
        "patient_name",
        "payload",
        "phone",
        "phone_number",
        "last_name",
        "customer_name",
        "wechat_id",
        "union_id",
    }
)
_ALLOWED_STATES: Mapping[str, frozenset[str]] = {
    "svc_appointment": frozenset(
        {
            "DRAFT",
            "HOLD",
            "HELD",
            "PENDING_PAYMENT",
            "CONFIRMED",
            "WAITLISTED",
            "CHECKED_IN",
            "IN_SERVICE",
            "COMPLETED",
            "CANCELLED",
            "NO_SHOW",
            "EXPIRED",
            "RESCHEDULE_PENDING",
            "RESCHEDULED",
            "SUSPENDED",
        }
    ),
    "svc_appointment_hold": frozenset(
        {"HELD", "LOCKED", "CONFIRMED", "RELEASE_PENDING", "RELEASED", "EXPIRED"}
    ),
    "svc_resource_lock": frozenset(
        {"LOCKED", "CONFIRMED", "RELEASE_PENDING", "RELEASED", "EXPIRED", "MAINTENANCE", "CONFLICT"}
    ),
    "fin_service_card": frozenset(
        {"PENDING", "PENDING_ACTIVATION", "ACTIVE", "FROZEN", "EXHAUSTED", "EXPIRED", "REVOKED"}
    ),
    "fin_service_card_ledger": frozenset(
        {"ISSUANCE", "CONSUMPTION", "REFUND_REVERSAL", "MANUAL_ADJUSTMENT"}
    ),
}
_LOCK_REQUIRED_COLUMNS = frozenset(
    {
        "tenant_id",
        "site_id",
        "resource_id",
        "slot_start_utc",
        "appointment_id",
        "status",
        "locked_at",
        "expires_at",
    }
)


def load_canonical_model(path: str | Path | None = None) -> dict[str, Any]:
    """Load the checked-in DB-02 canonical model without opening a database."""
    model_path = Path(path) if path is not None else (
        Path(__file__).resolve().parents[1] / "shared" / "db" / "models" / "canonical-models.json"
    )
    return json.loads(model_path.read_text(encoding="utf-8"))


def _quote(identifier: str) -> str:
    if not _IDENTIFIER.fullmatch(identifier):
        raise ValueError("invalid SQL identifier in schema metadata")
    return f'"{identifier}"'


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row | tuple[Any, ...]]:
    return {
        str(row[1]): row
        for row in connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    }


def _primary_key(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    indexed = [
        (int(row[5]), str(row[1]))
        for row in connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        if int(row[5]) > 0
    ]
    return tuple(name for _, name in sorted(indexed))


def _unique_keys(connection: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    keys: set[tuple[str, ...]] = set()
    for index in connection.execute(f"PRAGMA index_list({_quote(table)})").fetchall():
        if int(index[2]) != 1:
            continue
        index_name = str(index[1])
        if not _IDENTIFIER.fullmatch(index_name):
            continue
        key = tuple(
            str(row[2])
            for row in connection.execute(f"PRAGMA index_info({_quote(index_name)})").fetchall()
        )
        if key:
            keys.add(key)
    pk = _primary_key(connection, table)
    if pk:
        keys.add(pk)
    return keys


def _entities(model: Mapping[str, Any]) -> list[dict[str, Any]]:
    entities = model.get("entities", [])
    return [item for item in entities if isinstance(item, dict) and isinstance(item.get("name"), str)]


def _issue(code: str, *, entity: str | None = None, table: str | None = None, count: int = 1) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "count": count}
    if entity:
        item["entity"] = entity
    if table:
        item["table"] = table
    return item


def _check(
    check_id: str,
    findings: Sequence[dict[str, Any]],
    *,
    summary: str,
    skipped: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": check_id,
        "status": "skip" if skipped else ("fail" if findings else "pass"),
        "issue_count": sum(int(item.get("count", 1)) for item in findings),
        "summary": summary,
    }
    if findings:
        result["findings"] = list(findings)
    if metadata:
        result["metadata"] = dict(metadata)
    return result


def _model_contract_check(model: Mapping[str, Any]) -> dict[str, Any]:
    allowed_writers = set(model.get("write_masters", {}).get("allowed", []))
    entities = _entities(model)
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entity in entities:
        name = entity["name"]
        if name in seen:
            findings.append(_issue("duplicate_entity_name", entity=name))
        seen.add(name)
        writer = entity.get("write_master")
        if not writer or writer not in allowed_writers:
            findings.append(_issue("missing_or_unregistered_write_owner", entity=name))
        if not entity.get("status_field"):
            findings.append(_issue("status_field_not_declared", entity=name))
        if not entity.get("pk"):
            findings.append(_issue("primary_key_not_declared", entity=name))
        if not entity.get("unique_keys"):
            findings.append(_issue("unique_key_not_declared", entity=name))
        if not entity.get("pii", {}).get("level"):
            findings.append(_issue("pii_classification_not_declared", entity=name))
        retention = entity.get("retention", {})
        if not retention.get("policy") or not isinstance(retention.get("delete_allowed"), bool):
            findings.append(_issue("retention_policy_not_declared", entity=name))
        if entity.get("owner_status") == "health_owner_confirmation_required" and entity.get("write_enabled") is not False:
            findings.append(_issue("unconfirmed_health_owner_must_remain_write_disabled", entity=name))

    masters = model.get("write_masters", {})
    if masters.get("no_multi_writer") is not True or masters.get("per_entity") != "exactly_one":
        findings.append(_issue("single_write_owner_policy_missing"))
    if not entities:
        findings.append(_issue("canonical_entities_missing"))
    return _check(
        "owner_pii_model_contract",
        findings,
        summary="Canonical owner, PII class, retention policy, state field, primary/unique keys, and health owner gates are declared.",
        metadata={"canonical_entity_count": len(entities)},
    )


def _schema_contract_check(
    connection: sqlite3.Connection, model: Mapping[str, Any], tables: set[str]
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    checked = 0
    for entity in _entities(model):
        table = entity["name"]
        if table not in tables:
            continue
        checked += 1
        columns = _columns(connection, table)
        required_columns = set(entity.get("pk", []))
        required_columns.update(
            column
            for fk in entity.get("fks", [])
            for column in fk.get("columns", [])
        )
        required_columns.update(entity.get("status_field", "") and [entity["status_field"]] or [])
        required_columns.update(entity.get("pii", {}).get("encrypted_fields", []))
        required_columns.update(entity.get("pii", {}).get("hmac_fields", []))
        if "retention_until" in entity.get("time_fields", []):
            required_columns.add("retention_until")
        missing = required_columns - columns.keys()
        if missing:
            findings.append(_issue("canonical_column_missing", entity=table, count=len(missing)))
            continue

        expected_pk = tuple(entity.get("pk", []))
        if expected_pk and _primary_key(connection, table) != expected_pk:
            findings.append(_issue("primary_key_mismatch", entity=table))
        actual_keys = _unique_keys(connection, table)
        for key in entity.get("unique_keys", []):
            if tuple(key) not in actual_keys:
                findings.append(_issue("canonical_unique_key_missing", entity=table))

        pii_columns = set(entity.get("pii", {}).get("encrypted_fields", [])) | set(
            entity.get("pii", {}).get("hmac_fields", [])
        )
        raw_columns = {
            column.lower()
            for column in columns
            if _is_plain_sensitive_column(column) and column.lower() not in pii_columns
        }
        if raw_columns:
            findings.append(_issue("plaintext_sensitive_column_present", entity=table, count=len(raw_columns)))

        if entity.get("tenant_site_required"):
            for scope_column in ("tenant_id", "site_id"):
                row = columns.get(scope_column)
                if row is not None and int(row[3]) != 1:
                    findings.append(_issue("scope_column_not_declared_not_null", entity=table))
                    break

    return _check(
        "materialized_schema_contract",
        findings,
        summary="Materialized canonical tables match declared scope, key, status, PII, and owner metadata.",
        skipped=checked == 0,
        metadata={
            "materialized_canonical_tables": checked,
            "unmaterialized_canonical_entities": max(0, len(_entities(model)) - checked),
        },
    )


def _scope_check(connection: sqlite3.Connection, model: Mapping[str, Any], tables: set[str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    checked = 0
    for entity in _entities(model):
        table = entity["name"]
        if table not in tables or not entity.get("tenant_site_required"):
            continue
        columns = _columns(connection, table)
        if not {"tenant_id", "site_id"} <= columns.keys():
            continue
        checked += 1
        missing_predicate = '"tenant_id" IS NULL OR TRIM(CAST("tenant_id" AS TEXT)) = \'\' OR "site_id" IS NULL OR TRIM(CAST("site_id" AS TEXT)) = \'\''
        count = int(connection.execute(f"SELECT COUNT(*) FROM {_quote(table)} WHERE {missing_predicate}").fetchone()[0])
        if count:
            findings.append(_issue("tenant_site_value_missing", table=table, count=count))
    return _check(
        "tenant_site_completeness",
        findings,
        summary="Business facts have non-empty tenant_id and site_id values.",
        skipped=checked == 0,
        metadata={"materialized_scoped_tables": checked},
    )


def _is_plain_sensitive_column(column: str) -> bool:
    normalized = column.lower()
    if normalized.endswith(("_ciphertext", "_cipher", "_hmac", "_hash", "_encrypted")):
        return False
    if normalized in _RAW_SENSITIVE_COLUMNS:
        return True
    return normalized.endswith(("_raw", "_plain", "_plaintext"))


def _status_check(connection: sqlite3.Connection, model: Mapping[str, Any], tables: set[str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    checked = 0
    for entity in _entities(model):
        table = entity["name"]
        status_field = entity.get("status_field")
        if table not in tables or not status_field:
            continue
        columns = _columns(connection, table)
        if status_field not in columns:
            continue
        checked += 1
        quoted_status = _quote(status_field)
        blank_count = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {_quote(table)} WHERE {quoted_status} IS NULL OR TRIM(CAST({quoted_status} AS TEXT)) = ''"
            ).fetchone()[0]
        )
        if blank_count:
            findings.append(_issue("status_value_missing", table=table, count=blank_count))
        allowed = _ALLOWED_STATES.get(table)
        if allowed:
            placeholders = ", ".join("?" for _ in allowed)
            invalid_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {_quote(table)} WHERE {quoted_status} IS NOT NULL AND UPPER(TRIM(CAST({quoted_status} AS TEXT))) NOT IN ({placeholders})",
                    tuple(sorted(allowed)),
                ).fetchone()[0]
            )
            if invalid_count:
                findings.append(_issue("state_value_outside_catalog", table=table, count=invalid_count))
    return _check(
        "state_values",
        findings,
        summary="Declared state fields are populated and known appointment/lock/card/ledger states are catalogued.",
        skipped=checked == 0,
        metadata={"materialized_state_tables": checked},
    )


def _retention_check(connection: sqlite3.Connection, model: Mapping[str, Any], tables: set[str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    checked = 0
    for entity in _entities(model):
        table = entity["name"]
        if table not in tables or "retention_until" not in entity.get("time_fields", []):
            continue
        if "retention_until" not in _columns(connection, table):
            continue
        checked += 1
        count = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {_quote(table)} WHERE \"retention_until\" IS NULL "
                "OR TRIM(CAST(\"retention_until\" AS TEXT)) = ''"
            ).fetchone()[0]
        )
        if count:
            findings.append(_issue("retention_deadline_missing", table=table, count=count))
    return _check(
        "privacy_retention",
        findings,
        summary="Sensitive records with canonical retention deadlines have a non-empty retention_until value.",
        skipped=checked == 0,
        metadata={"materialized_retention_tables": checked},
    )


def _unique_data_check(connection: sqlite3.Connection, model: Mapping[str, Any], tables: set[str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    checked = 0
    for entity in _entities(model):
        table = entity["name"]
        if table not in tables:
            continue
        columns = _columns(connection, table)
        for raw_key in entity.get("unique_keys", []):
            key = tuple(raw_key)
            if not key or not set(key) <= columns.keys():
                continue
            checked += 1
            expressions = ", ".join(_quote(name) for name in key)
            non_null = " AND ".join(f"{_quote(name)} IS NOT NULL" for name in key)
            duplicates = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM (SELECT 1 FROM {_quote(table)} WHERE {non_null} GROUP BY {expressions} HAVING COUNT(*) > 1)"
                ).fetchone()[0]
            )
            if duplicates:
                findings.append(_issue("duplicate_business_key", table=table, count=duplicates))
    return _check(
        "unique_keys",
        findings,
        summary="Canonical business keys have no duplicate non-null tuples.",
        skipped=checked == 0,
        metadata={"materialized_unique_keys_checked": checked},
    )


def _foreign_key_checks(
    connection: sqlite3.Connection, model: Mapping[str, Any], tables: set[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    orphan_findings: list[dict[str, Any]] = []
    scope_findings: list[dict[str, Any]] = []
    evaluated = 0
    for entity in _entities(model):
        child = entity["name"]
        if child not in tables:
            continue
        child_columns = _columns(connection, child)
        for fk in entity.get("fks", []):
            parent = fk.get("ref_entity")
            local_cols = tuple(fk.get("columns", []))
            parent_cols = tuple(fk.get("ref_columns", []))
            if parent not in tables or not local_cols or len(local_cols) != len(parent_cols):
                continue
            if not set(local_cols) <= child_columns.keys():
                continue
            parent_columns = _columns(connection, str(parent))
            if not set(parent_cols) <= parent_columns.keys():
                continue
            evaluated += 1
            child_ref = " AND ".join(f"c.{_quote(local)} = p.{_quote(ref)}" for local, ref in zip(local_cols, parent_cols))
            any_set = " OR ".join(f"c.{_quote(local)} IS NOT NULL" for local in local_cols)
            all_set = " AND ".join(f"c.{_quote(local)} IS NOT NULL" for local in local_cols)
            partial_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {_quote(child)} AS c WHERE ({any_set}) AND NOT ({all_set})"
                ).fetchone()[0]
            )
            if partial_count:
                orphan_findings.append(_issue("foreign_key_partially_null", table=child, count=partial_count))
            orphan_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {_quote(child)} AS c WHERE ({all_set}) AND NOT EXISTS (SELECT 1 FROM {_quote(str(parent))} AS p WHERE {child_ref})"
                ).fetchone()[0]
            )
            if orphan_count:
                orphan_findings.append(_issue("orphan_reference", table=child, count=orphan_count))

            # Identity-anchor references (for example a tenant customer) are
            # intentionally tenant-scoped and are not a grant to another site.
            if {"tenant_id", "site_id"} <= set(parent_cols):
                identity_pairs = [
                    (local, ref)
                    for local, ref in zip(local_cols, parent_cols)
                    if ref not in {"tenant_id", "site_id"}
                ]
                if identity_pairs:
                    logical_match = " AND ".join(
                        f"c.{_quote(local)} = p.{_quote(ref)}" for local, ref in identity_pairs
                    )
                    mismatch_count = int(
                        connection.execute(
                            f"SELECT COUNT(*) FROM {_quote(child)} AS c WHERE ({all_set}) "
                            f"AND EXISTS (SELECT 1 FROM {_quote(str(parent))} AS p WHERE {logical_match}) "
                            f"AND NOT EXISTS (SELECT 1 FROM {_quote(str(parent))} AS p WHERE {child_ref})"
                        ).fetchone()[0]
                    )
                    if mismatch_count:
                        scope_findings.append(_issue("cross_tenant_or_site_reference", table=child, count=mismatch_count))

    return (
        _check(
            "orphan_references",
            orphan_findings,
            summary="Canonical foreign-key references resolve within their declared scope.",
            skipped=evaluated == 0,
            metadata={"materialized_foreign_keys_checked": evaluated},
        ),
        _check(
            "cross_site_anomalies",
            scope_findings,
            summary="Tenant/site-scoped references do not resolve to a different scope.",
            skipped=evaluated == 0,
        ),
    )


def _sqlite_fk_check(connection: sqlite3.Connection) -> dict[str, Any]:
    try:
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.DatabaseError:
        violations = [()]
    return _check(
        "sqlite_foreign_key_constraints",
        [_issue("sqlite_foreign_key_violation", count=len(violations))] if violations else [],
        summary="SQLite-declared foreign keys pass PRAGMA foreign_key_check.",
        metadata={"violation_count": len(violations)},
    )


def _parse_timestamp(value: Any) -> datetime:
    if value is None:
        raise ValueError("missing timestamp")
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text.replace(" ", "T", 1))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _appointment_lock_check(connection: sqlite3.Connection, tables: set[str]) -> dict[str, Any]:
    table = "svc_resource_lock"
    if table not in tables:
        return _check(
            "five_minute_appointment_locks",
            [],
            summary="The appointment lock table is not materialized in this snapshot.",
            skipped=True,
        )
    columns = _columns(connection, table)
    missing = _LOCK_REQUIRED_COLUMNS - columns.keys()
    if missing:
        return _check(
            "five_minute_appointment_locks",
            [_issue("appointment_lock_column_missing", table=table, count=len(missing))],
            summary="Appointment locks expose their five-minute bucket and expiry fields.",
        )

    findings: list[dict[str, Any]] = []
    unaligned = 0
    invalid_timestamp = 0
    invalid_expiry = 0
    for row in connection.execute(
        'SELECT "slot_start_utc", "status", "locked_at", "expires_at" FROM "svc_resource_lock"'
    ):
        try:
            slot = _parse_timestamp(row[0])
            if slot.minute % 5 != 0 or slot.second != 0 or slot.microsecond != 0:
                unaligned += 1
        except (TypeError, ValueError, OverflowError):
            invalid_timestamp += 1
        if str(row[1]).upper() == "LOCKED":
            try:
                locked_at = _parse_timestamp(row[2])
                expires_at = _parse_timestamp(row[3])
                if expires_at <= locked_at:
                    invalid_expiry += 1
            except (TypeError, ValueError, OverflowError):
                invalid_expiry += 1
    if unaligned:
        findings.append(_issue("slot_not_aligned_to_five_minute_bucket", table=table, count=unaligned))
    if invalid_timestamp:
        findings.append(_issue("slot_timestamp_invalid", table=table, count=invalid_timestamp))
    if invalid_expiry:
        findings.append(_issue("locked_row_expiry_invalid", table=table, count=invalid_expiry))
    return _check(
        "five_minute_appointment_locks",
        findings,
        summary="Every resource lock uses a UTC-aligned five-minute bucket; active holds have a later expiry.",
        metadata={"bucket_minutes": 5},
    )


def _ledger_append_only_check(
    connection: sqlite3.Connection, tables: set[str], model: Mapping[str, Any]
) -> dict[str, Any]:
    table = "fin_service_card_ledger"
    if table not in tables:
        return _check(
            "ledger_append_only",
            [],
            summary="The service-card ledger table is not materialized in this snapshot.",
            skipped=True,
        )
    entity = next((item for item in _entities(model) if item["name"] == table), {})
    findings: list[dict[str, Any]] = []
    if entity.get("append_only") is not True or entity.get("retention", {}).get("update_allowed") is not False or entity.get("retention", {}).get("delete_allowed") is not False:
        findings.append(_issue("canonical_ledger_append_only_policy_missing", entity=table))
    triggers = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?",
        (table,),
    ).fetchall()
    events = {"update": False, "delete": False}
    for trigger in triggers:
        sql = str(trigger[0] or "").upper()
        for event in events:
            if re.search(rf"\bBEFORE\s+{event.upper()}\b", sql) and "RAISE" in sql and "ABORT" in sql:
                events[event] = True
    for event, present in events.items():
        if not present:
            findings.append(_issue(f"ledger_{event}_guard_missing", table=table))
    return _check(
        "ledger_append_only",
        findings,
        summary="The service ledger is declared append-only and SQLite rejects UPDATE and DELETE.",
        metadata={"update_guard": events["update"], "delete_guard": events["delete"]},
    )


def _normalise_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"blob_sha256": hashlib.sha256(value).hexdigest(), "byte_count": len(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def database_fingerprint(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return a data/schema fingerprint with no row contents or health payloads."""
    table_names = sorted(_table_names(connection))
    schema_rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    schema_bytes = json.dumps(
        [tuple(_normalise_value(value) for value in row) for row in schema_rows],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    table_fingerprints: dict[str, dict[str, Any]] = {}
    for table in table_names:
        columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()]
        rows = connection.execute(f"SELECT * FROM {_quote(table)}").fetchall()
        row_hashes: list[bytes] = []
        for row in rows:
            encoded = json.dumps(
                [_normalise_value(value) for value in row],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            row_hashes.append(hashlib.sha256(encoded).digest())
        table_hash = hashlib.sha256(b"".join(sorted(row_hashes))).hexdigest()
        table_fingerprints[table] = {"row_count": len(rows), "sha256": table_hash}
    return {
        "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        "tables": table_fingerprints,
    }


def _compare_fingerprints(
    left: sqlite3.Connection, right: sqlite3.Connection, *, label: str
) -> dict[str, Any]:
    left_fp = database_fingerprint(left)
    right_fp = database_fingerprint(right)
    changed_tables = sorted(
        table
        for table in set(left_fp["tables"]) | set(right_fp["tables"])
        if left_fp["tables"].get(table) != right_fp["tables"].get(table)
    )
    schema_matches = left_fp["schema_sha256"] == right_fp["schema_sha256"]
    return {
        "comparison": label,
        "status": "pass" if schema_matches and not changed_tables else "fail",
        "schema_matches": schema_matches,
        "changed_table_count": len(changed_tables),
        "changed_tables": changed_tables,
        "reference_sha256": left_fp["schema_sha256"],
        "candidate_sha256": right_fp["schema_sha256"],
    }


def _restore_check(
    seed_db: sqlite3.Connection | None,
    backup_db: sqlite3.Connection | None,
    restored_db: sqlite3.Connection | None,
) -> dict[str, Any]:
    if seed_db is None or backup_db is None or restored_db is None:
        return _check(
            "seed_backup_restore_consistency",
            [],
            summary="Seed, backup, and restored snapshots must all be supplied to compare recovery consistency.",
            skipped=True,
        )
    comparisons = [
        _compare_fingerprints(seed_db, backup_db, label="seed_vs_backup"),
        _compare_fingerprints(seed_db, restored_db, label="seed_vs_restored"),
    ]
    failures = [item for item in comparisons if item["status"] != "pass"]
    findings = [
        _issue("snapshot_mismatch", table=table, count=1)
        for item in failures
        for table in item["changed_tables"]
    ]
    if any(not item["schema_matches"] for item in failures):
        findings.append(_issue("snapshot_schema_mismatch"))
    return _check(
        "seed_backup_restore_consistency",
        findings,
        summary="Seed, backup, and restored snapshots have matching schemas and table fingerprints.",
        metadata={"comparisons": comparisons},
    )


def run_quality_gates(
    connection: sqlite3.Connection,
    *,
    canonical_model: Mapping[str, Any] | None = None,
    seed_db: sqlite3.Connection | None = None,
    backup_db: sqlite3.Connection | None = None,
    restored_db: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Evaluate DB-08 checks against a caller-owned SQLite connection.

    The connection is used read-only. Recovery comparisons are also read-only
    and are enabled only when seed, backup, and restored connections are all
    supplied. No data row or health payload is returned.
    """
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("DB-08 gates accept only a caller-supplied sqlite3.Connection")
    model = canonical_model if canonical_model is not None else load_canonical_model()
    tables = _table_names(connection)
    orphan_check, cross_scope_check = _foreign_key_checks(connection, model, tables)
    checks = [
        _model_contract_check(model),
        _schema_contract_check(connection, model, tables),
        _scope_check(connection, model, tables),
        _status_check(connection, model, tables),
        _retention_check(connection, model, tables),
        _unique_data_check(connection, model, tables),
        orphan_check,
        cross_scope_check,
        _sqlite_fk_check(connection),
        _appointment_lock_check(connection, tables),
        _ledger_append_only_check(connection, tables, model),
        _restore_check(seed_db, backup_db, restored_db),
        _check(
            "health_export_privacy",
            [],
            summary="Health payload values are excluded; exported output contains only counts, schema identifiers, and fingerprints.",
            metadata={"health_payload_exported": False, "row_values_exported": False},
        ),
    ]
    counts = Counter(item["status"] for item in checks)
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "fail" if counts["fail"] else "pass",
        "summary": {
            "check_count": len(checks),
            "passed": counts["pass"],
            "failed": counts["fail"],
            "skipped": counts["skip"],
        },
        "checks": checks,
    }


__all__ = [
    "CONTRACT_VERSION",
    "database_fingerprint",
    "load_canonical_model",
    "run_quality_gates",
]
