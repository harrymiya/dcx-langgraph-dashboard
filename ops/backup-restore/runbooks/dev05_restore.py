"""Synthetic-only manifest and isolated SQLite restore checks for DEV-05.

This module does not connect to a database or object store and does not encrypt
backup bytes. A production adapter must use the approved external envelope
encryption/KMS service and supply only a key reference here. All report fields
are aggregate metadata; row values and exception messages are never returned.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
import re
import sqlite3
from typing import Any, Mapping


MANIFEST_VERSION = 1
REQUIRED_TABLES = (
    "plat_tenant",
    "plat_site",
    "svc_service_item",
    "svc_service_version",
    "svc_appointment",
    "fin_payment",
    "fin_service_card",
    "fin_service_card_ledger",
    "aud_audit_event",
)
_ALLOWED_ENVIRONMENTS = frozenset({"dev", "test", "synthetic"})
_LOG_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_LOG_CODES = frozenset({
    "manifest_verified", "reference_continuity_failed", "snapshot_mismatch",
    "artifact_missing", "integrity_key_unavailable", "source_environment_missing",
    "source_environment_not_isolated", "access_roles_missing", "access_role_invalid",
    "access_roles_duplicate", "backup_id_missing", "created_at_invalid",
    "source_watermark_missing", "schema_fingerprint_missing",
    "encryption_algorithm_missing", "key_reference_missing", "key_version_missing",
    "retention_policy_missing", "retention_until_invalid", "access_policy_missing",
    "manifest_or_artifact_invalid", "manifest_incomplete_or_unknown_fields",
    "manifest_section_invalid", "artifact_manifest_incomplete",
    "encryption_manifest_incomplete", "key_material_must_be_external",
    "retention_manifest_incomplete", "access_manifest_incomplete",
    "manifest_integrity_incomplete", "artifact_must_be_encrypted",
    "artifact_manifest_invalid", "artifact_length_mismatch", "artifact_hash_mismatch",
    "manifest_hash_mismatch", "manifest_authentication_failed",
    "required_table_missing", "site_tenant_reference", "catalog_site_reference",
    "catalog_version_reference", "appointment_catalog_reference",
    "payment_appointment_reference", "ledger_card_reference",
    "audit_appointment_reference", "sqlite_foreign_key_integrity",
    "ledger_append_only_guards", "isolated_restore_failed", "generic_failure",
})


class ManifestError(ValueError):
    """A manifest check failed without including caller data in the message."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class RestoreRejected(RuntimeError):
    """An isolated candidate failed validation; its source was not modified."""

    def __init__(self, codes: tuple[str, ...]):
        self.codes = codes
        super().__init__("isolated restore rejected")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(code)
    return value.strip()


def _parse_utc(value: str, code: str) -> str:
    text = _require_text(value, code)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ManifestError(code)
    return parsed.isoformat().replace("+00:00", "Z")


def build_manifest(
    encrypted_artifact: bytes,
    *,
    backup_id: str,
    created_at: str,
    source_environment: str,
    schema_fingerprint: str,
    source_watermark: str,
    encryption_algorithm: str,
    key_reference: str,
    key_version: str,
    retention_policy_id: str,
    retention_until: str,
    access_policy_id: str,
    allowed_roles: tuple[str, ...],
    integrity_key: bytes,
    legal_hold: bool = False,
) -> dict[str, Any]:
    """Build a complete manifest; integrity_key is external and never stored."""
    if not isinstance(encrypted_artifact, bytes) or not encrypted_artifact:
        raise ManifestError("artifact_missing")
    if not isinstance(integrity_key, bytes) or len(integrity_key) < 16:
        raise ManifestError("integrity_key_unavailable")
    environment = _require_text(source_environment, "source_environment_missing")
    if environment not in _ALLOWED_ENVIRONMENTS:
        raise ManifestError("source_environment_not_isolated")
    if not isinstance(allowed_roles, tuple) or not allowed_roles:
        raise ManifestError("access_roles_missing")
    if not isinstance(legal_hold, bool):
        raise ManifestError("retention_manifest_invalid")
    roles = sorted({_require_text(role, "access_role_invalid") for role in allowed_roles})
    if len(roles) != len(allowed_roles):
        raise ManifestError("access_roles_duplicate")

    body: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "backup_id": _require_text(backup_id, "backup_id_missing"),
        "created_at": _parse_utc(created_at, "created_at_invalid"),
        "source_environment": environment,
        "source_watermark": _require_text(source_watermark, "source_watermark_missing"),
        "schema_fingerprint": _require_text(schema_fingerprint, "schema_fingerprint_missing"),
        "artifact": {
            "format": "opaque_encrypted_snapshot",
            "byte_count": len(encrypted_artifact),
            "sha256": hashlib.sha256(encrypted_artifact).hexdigest(),
        },
        "encryption": {
            "algorithm": _require_text(encryption_algorithm, "encryption_algorithm_missing"),
            "key_reference": _require_text(key_reference, "key_reference_missing"),
            "key_version": _require_text(key_version, "key_version_missing"),
            "key_material_included": False,
        },
        "retention": {
            "policy_id": _require_text(retention_policy_id, "retention_policy_missing"),
            "retain_until": _parse_utc(retention_until, "retention_until_invalid"),
            "legal_hold": legal_hold,
        },
        "access": {
            "policy_id": _require_text(access_policy_id, "access_policy_missing"),
            "allowed_roles": roles,
        },
    }
    digest = hashlib.sha256(_canonical_json(body)).hexdigest()
    auth_tag = hmac.new(integrity_key, digest.encode("ascii"), hashlib.sha256).hexdigest()
    body["integrity"] = {
        "manifest_sha256": digest,
        "auth_tag_hmac_sha256": auth_tag,
    }
    return body


def verify_manifest(
    manifest: Mapping[str, Any], encrypted_artifact: bytes, *, integrity_key: bytes
) -> dict[str, str | int]:
    """Verify manifest completeness, external HMAC, and encrypted artifact hash."""
    if not isinstance(manifest, Mapping) or not isinstance(encrypted_artifact, bytes):
        raise ManifestError("manifest_or_artifact_invalid")
    if not isinstance(integrity_key, bytes) or len(integrity_key) < 16:
        raise ManifestError("integrity_key_unavailable")
    expected_keys = {
        "manifest_version", "backup_id", "created_at", "source_environment",
        "source_watermark", "schema_fingerprint", "artifact", "encryption",
        "retention", "access", "integrity",
    }
    if set(manifest) != expected_keys or manifest.get("manifest_version") != MANIFEST_VERSION:
        raise ManifestError("manifest_incomplete_or_unknown_fields")
    artifact = manifest.get("artifact")
    encryption = manifest.get("encryption")
    retention = manifest.get("retention")
    access = manifest.get("access")
    integrity = manifest.get("integrity")
    if not all(isinstance(item, Mapping) for item in (artifact, encryption, retention, access, integrity)):
        raise ManifestError("manifest_section_invalid")
    if set(artifact) != {"format", "byte_count", "sha256"}:
        raise ManifestError("artifact_manifest_incomplete")
    if set(encryption) != {"algorithm", "key_reference", "key_version", "key_material_included"}:
        raise ManifestError("encryption_manifest_incomplete")
    if encryption.get("key_material_included") is not False:
        raise ManifestError("key_material_must_be_external")
    if set(retention) != {"policy_id", "retain_until", "legal_hold"}:
        raise ManifestError("retention_manifest_incomplete")
    if set(access) != {"policy_id", "allowed_roles"}:
        raise ManifestError("access_manifest_incomplete")
    if set(integrity) != {"manifest_sha256", "auth_tag_hmac_sha256"}:
        raise ManifestError("manifest_integrity_incomplete")
    for field in ("backup_id", "created_at", "source_environment", "source_watermark", "schema_fingerprint"):
        _require_text(manifest.get(field), f"{field}_missing")
    if manifest["source_environment"] not in _ALLOWED_ENVIRONMENTS:
        raise ManifestError("source_environment_not_isolated")
    _parse_utc(manifest["created_at"], "created_at_invalid")
    if artifact.get("format") != "opaque_encrypted_snapshot":
        raise ManifestError("artifact_must_be_encrypted")
    if not isinstance(artifact.get("byte_count"), int) or artifact["byte_count"] < 1 or not isinstance(artifact.get("sha256"), str):
        raise ManifestError("artifact_manifest_invalid")
    for field in ("algorithm", "key_reference", "key_version"):
        _require_text(encryption.get(field), f"encryption_{field}_missing")
    _require_text(retention.get("policy_id"), "retention_policy_missing")
    _parse_utc(retention.get("retain_until"), "retention_until_invalid")
    if not isinstance(retention.get("legal_hold"), bool):
        raise ManifestError("retention_manifest_invalid")
    _require_text(access.get("policy_id"), "access_policy_missing")
    roles = access.get("allowed_roles")
    if not isinstance(roles, list) or not roles or any(not isinstance(role, str) or not role.strip() for role in roles):
        raise ManifestError("access_roles_missing")
    if len(roles) != len(set(roles)):
        raise ManifestError("access_roles_duplicate")
    if not encrypted_artifact or artifact["byte_count"] != len(encrypted_artifact):
        raise ManifestError("artifact_length_mismatch")
    actual_artifact_digest = hashlib.sha256(encrypted_artifact).hexdigest()
    if not hmac.compare_digest(artifact["sha256"], actual_artifact_digest):
        raise ManifestError("artifact_hash_mismatch")

    body = dict(manifest)
    body.pop("integrity")
    digest = hashlib.sha256(_canonical_json(body)).hexdigest()
    if not hmac.compare_digest(str(integrity["manifest_sha256"]), digest):
        raise ManifestError("manifest_hash_mismatch")
    expected_tag = hmac.new(integrity_key, digest.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(integrity["auth_tag_hmac_sha256"]), expected_tag):
        raise ManifestError("manifest_authentication_failed")
    return {"status": "pass", "manifest_sha256": digest, "artifact_bytes": len(encrypted_artifact)}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def verify_reference_continuity(connection: sqlite3.Connection) -> dict[str, Any]:
    """Check the required tenant/site/catalog/appointment/payment/ledger/audit chain."""
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("SQLite connection required")
    tables = _table_names(connection)
    missing = sorted(set(REQUIRED_TABLES) - tables)
    findings: list[str] = ["required_table_missing"] if missing else []
    checks: list[dict[str, Any]] = []
    if not missing:
        reference_queries = (
            ("site_tenant_reference", """
                SELECT COUNT(*) FROM plat_site s
                WHERE NOT EXISTS (SELECT 1 FROM plat_tenant t WHERE t.tenant_id=s.tenant_id)
            """),
            ("catalog_site_reference", """
                SELECT COUNT(*) FROM svc_service_item i
                WHERE NOT EXISTS (SELECT 1 FROM plat_site s
                  WHERE s.tenant_id=i.tenant_id AND s.site_id=i.site_id)
            """),
            ("catalog_version_reference", """
                SELECT COUNT(*) FROM svc_service_version v
                WHERE NOT EXISTS (SELECT 1 FROM svc_service_item i
                  WHERE i.tenant_id=v.tenant_id AND i.site_id=v.site_id AND i.service_id=v.service_id)
            """),
            ("appointment_catalog_reference", """
                SELECT COUNT(*) FROM svc_appointment a
                WHERE NOT EXISTS (SELECT 1 FROM plat_site s
                    WHERE s.tenant_id=a.tenant_id AND s.site_id=a.site_id)
                  OR NOT EXISTS (SELECT 1 FROM svc_service_version v
                    WHERE v.tenant_id=a.tenant_id AND v.site_id=a.site_id
                      AND v.service_version_id=a.service_version_id)
            """),
            ("payment_appointment_reference", """
                SELECT COUNT(*) FROM fin_payment p
                WHERE NOT EXISTS (SELECT 1 FROM svc_appointment a
                    WHERE a.tenant_id=p.tenant_id AND a.site_id=p.site_id
                      AND a.appointment_id=p.appointment_id)
            """),
            ("ledger_card_reference", """
                SELECT COUNT(*) FROM fin_service_card_ledger l
                WHERE NOT EXISTS (SELECT 1 FROM fin_service_card c
                    WHERE c.tenant_id=l.tenant_id AND c.site_id=l.site_id AND c.card_id=l.card_id)
            """),
            ("audit_appointment_reference", """
                SELECT COUNT(*) FROM aud_audit_event e
                WHERE e.target_type='svc_appointment' AND NOT EXISTS (
                    SELECT 1 FROM svc_appointment a WHERE a.tenant_id=e.tenant_id
                      AND a.site_id=e.site_id AND a.appointment_id=e.target_id)
            """),
        )
        for check_id, query in reference_queries:
            count = int(connection.execute(query).fetchone()[0])
            checks.append({"id": check_id, "status": "fail" if count else "pass", "issue_count": count})
            if count:
                findings.append(check_id)

        fk_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        fk_count = len(fk_violations)
        checks.append({"id": "sqlite_foreign_key_integrity", "status": "fail" if fk_count else "pass", "issue_count": fk_count})
        if fk_count:
            findings.append("sqlite_foreign_key_integrity")

        trigger_rows = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name='fin_service_card_ledger'"
        ).fetchall()
        trigger_sql = [str(row[0] or "").upper() for row in trigger_rows]
        guard_status: dict[str, bool] = {}
        for event in ("UPDATE", "DELETE"):
            guard_status[event.lower()] = any(
                re.search(rf"\bBEFORE\s+{event}\b", sql) and "RAISE" in sql and "ABORT" in sql
                for sql in trigger_sql
            )
        guard_failures = sum(not present for present in guard_status.values())
        checks.append({"id": "ledger_append_only_guards", "status": "fail" if guard_failures else "pass", "issue_count": guard_failures})
        if guard_failures:
            findings.append("ledger_append_only_guards")
    else:
        checks.append({"id": "required_reference_tables", "status": "fail", "issue_count": len(missing)})

    table_counts = {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in REQUIRED_TABLES
        if table in tables
    }
    return {
        "status": "fail" if findings else "pass",
        "required_tables_present": not missing,
        "missing_tables": missing,
        "table_counts": table_counts,
        "checks": checks,
        "finding_codes": sorted(set(findings)),
        "row_values_exported": False,
    }


def _normalise_sqlite_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "byte_count": len(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def database_fingerprint(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return schema and row fingerprints without serializing row contents."""
    tables = sorted(_table_names(connection))
    schema = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    schema_digest = hashlib.sha256(
        _canonical_json([[_normalise_sqlite_value(value) for value in row] for row in schema])
    ).hexdigest()
    table_fingerprints: dict[str, dict[str, Any]] = {}
    for table in tables:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            raise ValueError("invalid SQLite table name in snapshot")
        rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
        row_digests = [
            hashlib.sha256(_canonical_json([_normalise_sqlite_value(value) for value in row])).digest()
            for row in rows
        ]
        table_fingerprints[table] = {
            "row_count": len(rows),
            "sha256": hashlib.sha256(b"".join(sorted(row_digests))).hexdigest(),
        }
    return {"schema_sha256": schema_digest, "tables": table_fingerprints}


def verify_snapshot_chain(
    seed: sqlite3.Connection,
    backup: sqlite3.Connection,
    restored: sqlite3.Connection,
) -> dict[str, Any]:
    """Compare seed, backup, and isolated restore, then check reference continuity."""
    snapshots = {"seed": seed, "backup": backup, "restored": restored}
    fingerprints = {name: database_fingerprint(connection) for name, connection in snapshots.items()}
    baseline = fingerprints["seed"]
    comparisons = []
    for name in ("backup", "restored"):
        candidate = fingerprints[name]
        changed_tables = sorted(
            table for table in set(baseline["tables"]) | set(candidate["tables"])
            if baseline["tables"].get(table) != candidate["tables"].get(table)
        )
        schema_matches = baseline["schema_sha256"] == candidate["schema_sha256"]
        comparisons.append({
            "snapshot": name,
            "status": "pass" if schema_matches and not changed_tables else "fail",
            "schema_matches": schema_matches,
            "changed_table_count": len(changed_tables),
            "changed_tables": changed_tables,
        })
    continuity = {name: verify_reference_continuity(connection) for name, connection in snapshots.items()}
    all_pass = all(item["status"] == "pass" for item in comparisons) and all(
        item["status"] == "pass" for item in continuity.values()
    )
    return {
        "status": "pass" if all_pass else "fail",
        "comparisons": comparisons,
        "continuity": continuity,
        "fingerprints": {
            name: {
                "schema_sha256": value["schema_sha256"],
                "tables": value["tables"],
            }
            for name, value in fingerprints.items()
        },
        "row_values_exported": False,
    }


def restore_isolated(snapshot: sqlite3.Connection) -> tuple[sqlite3.Connection, dict[str, Any]]:
    """Restore to a fresh in-memory SQLite target and reject invalid candidates."""
    if not isinstance(snapshot, sqlite3.Connection):
        raise TypeError("SQLite connection required")
    target = sqlite3.connect(":memory:")
    try:
        snapshot.backup(target)
        report = verify_reference_continuity(target)
        if report["status"] != "pass":
            raise RestoreRejected(tuple(report["finding_codes"]))
        return target, report
    except RestoreRejected:
        target.close()
        raise
    except sqlite3.Error as exc:
        target.close()
        raise RestoreRejected(("isolated_restore_failed",)) from exc


def safe_log_record(stage: str, status: str, codes: tuple[str, ...] = ()) -> dict[str, Any]:
    """Build an allowlisted log record that cannot carry secrets or row values."""
    if stage not in {"manifest_verify", "restore", "continuity"}:
        stage = "operation"
    if status not in {"pass", "fail", "rejected"}:
        status = "fail"
    safe_codes = sorted({
        code for code in codes
        if isinstance(code, str) and _LOG_CODE.fullmatch(code) and code in _SAFE_LOG_CODES
    })
    if codes and not safe_codes:
        safe_codes = ["generic_failure"]
    return {
        "component": "dev05_backup_restore",
        "stage": stage,
        "status": status,
        "finding_codes": safe_codes,
        "row_values_exported": False,
        "secret_values_exported": False,
    }


__all__ = [
    "MANIFEST_VERSION",
    "ManifestError",
    "RestoreRejected",
    "build_manifest",
    "database_fingerprint",
    "restore_isolated",
    "safe_log_record",
    "verify_manifest",
    "verify_reference_continuity",
    "verify_snapshot_chain",
]
