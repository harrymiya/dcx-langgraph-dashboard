"""Standard-library synthetic SQLite tests for the DB-08 quality gates."""
from __future__ import annotations

import json
import sqlite3
import unittest
from copy import deepcopy

from domain.data_quality.health_scrm_gates import load_canonical_model, run_quality_gates


ENTITY_NAMES = (
    "plat_tenant",
    "plat_site",
    "crm_customer",
    "crm_consent_record",
    "svc_service_item",
    "svc_service_version",
    "svc_appointment",
    "svc_resource",
    "svc_resource_lock",
    "fin_service_card",
    "fin_service_card_ledger",
    "hlth_health_record",
    "hlth_record_revision",
)
EXTRA_COLUMNS = {
    "plat_tenant": {"tenant_code"},
    "plat_site": {"site_code"},
    "crm_consent_record": {"purpose_code", "recipient_code", "target_site_id", "consent_version"},
    "svc_service_item": {"service_code"},
    "svc_service_version": {"version_no"},
    "svc_appointment": {"idempotency_key", "customer_note_ciphertext", "starts_at", "ends_at"},
    "svc_resource": {"resource_code"},
    "svc_resource_lock": {"slot_start_utc", "locked_at", "expires_at", "idempotency_key_hash"},
    "fin_service_card": {"card_number_ciphertext", "card_number_hmac"},
    "fin_service_card_ledger": {
        "idempotency_key_hash", "source_type", "source_id", "delta_amount", "currency_code",
        "occurred_at", "created_at",
    },
    "hlth_health_record": {"record_type", "occurred_at", "source_key", "payload_ciphertext", "retention_until"},
    "hlth_record_revision": {"revision_no", "payload_ciphertext", "occurred_at", "created_at"},
}


def fixture_model():
    full_model = load_canonical_model()
    selected = [entity for entity in full_model["entities"] if entity["name"] in ENTITY_NAMES]
    return {**full_model, "entities": selected, "entity_count": len(selected)}


def make_database(*, include_ledger_guards: bool = True) -> sqlite3.Connection:
    model = fixture_model()
    names = {entity["name"] for entity in model["entities"]}
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    for entity in model["entities"]:
        table = entity["name"]
        columns = set(entity.get("pk", []))
        columns.update(column for fk in entity.get("fks", []) for column in fk["columns"])
        columns.update(column for key in entity.get("unique_keys", []) for column in key)
        columns.update(entity.get("pii", {}).get("encrypted_fields", []))
        columns.update(entity.get("pii", {}).get("hmac_fields", []))
        columns.update(EXTRA_COLUMNS.get(table, set()))
        if entity.get("status_field"):
            columns.add(entity["status_field"])

        declarations = []
        pk = tuple(entity.get("pk", []))
        scope = {"tenant_id", "site_id"} if entity.get("tenant_site_required") else set()
        non_null = set(pk) | scope
        if entity.get("status_field"):
            non_null.add(entity["status_field"])
        for column in sorted(columns):
            suffix = " NOT NULL" if column in non_null else ""
            declarations.append(f'"{column}" TEXT{suffix}')
        constraints = []
        if pk:
            constraints.append("PRIMARY KEY (" + ", ".join(f'"{column}"' for column in pk) + ")")
        for key in entity.get("unique_keys", []):
            constraints.append("UNIQUE (" + ", ".join(f'"{column}"' for column in key) + ")")
        for fk in entity.get("fks", []):
            parent = fk["ref_entity"]
            if parent not in names:
                continue
            local = ", ".join(f'"{column}"' for column in fk["columns"])
            remote = ", ".join(f'"{column}"' for column in fk["ref_columns"])
            constraints.append(
                f"FOREIGN KEY ({local}) REFERENCES \"{parent}\" ({remote}) ON DELETE RESTRICT"
            )
        all_declarations = declarations + constraints
        connection.execute(f'CREATE TABLE "{table}" ({", ".join(all_declarations)})')

    if include_ledger_guards:
        connection.executescript(
            "CREATE TRIGGER db08_ledger_no_update BEFORE UPDATE ON fin_service_card_ledger "
            "BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;"
            "CREATE TRIGGER db08_ledger_no_delete BEFORE DELETE ON fin_service_card_ledger "
            "BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;"
        )

    values = {
        "plat_tenant": {"tenant_id": "tenant-1", "tenant_code": "T1", "status": "ACTIVE"},
        "plat_site": {"tenant_id": "tenant-1", "site_id": "site-1", "site_code": "S1", "status": "ACTIVE"},
        "crm_customer": {
            "tenant_id": "tenant-1", "customer_id": "customer-1", "phone_ciphertext": "cipher-phone",
            "profile_ciphertext": "cipher-profile", "phone_hmac": "hash-phone", "status": "ACTIVE",
        },
        "crm_consent_record": {
            "tenant_id": "tenant-1", "site_id": "site-1", "consent_id": "consent-1",
            "subject_customer_id": "customer-1", "grantor_customer_id": "customer-1",
            "purpose_code": "HEALTH_SERVICE", "recipient_code": "WISH", "target_site_id": "site-1",
            "consent_version": "1", "evidence_ref_ciphertext": "cipher-consent", "status": "ACTIVE",
        },
        "svc_service_item": {
            "tenant_id": "tenant-1", "site_id": "site-1", "service_id": "service-1",
            "service_code": "SVC1", "status": "ACTIVE",
        },
        "svc_service_version": {
            "tenant_id": "tenant-1", "site_id": "site-1", "service_version_id": "version-1",
            "service_id": "service-1", "version_no": "1", "status": "PUBLISHED",
        },
        "svc_appointment": {
            "tenant_id": "tenant-1", "site_id": "site-1", "appointment_id": "appointment-1",
            "customer_id": "customer-1", "subject_customer_id": "customer-1",
            "service_version_id": "version-1", "idempotency_key": "appointment-idem-1",
            "customer_note_ciphertext": "cipher-note", "starts_at": "2026-10-02T10:00:00Z",
            "ends_at": "2026-10-02T10:30:00Z", "status": "CONFIRMED",
        },
        "svc_resource": {
            "tenant_id": "tenant-1", "site_id": "site-1", "resource_id": "resource-1",
            "resource_code": "ROOM1", "status": "ACTIVE",
        },
        "svc_resource_lock": {
            "tenant_id": "tenant-1", "site_id": "site-1", "lock_id": "lock-1",
            "resource_id": "resource-1", "slot_start_utc": "2026-10-02T10:00:00.000Z",
            "appointment_id": "appointment-1", "idempotency_key_hash": "hash-lock",
            "status": "CONFIRMED", "locked_at": "2026-10-02T09:59:00Z", "expires_at": None,
        },
        "fin_service_card": {
            "tenant_id": "tenant-1", "site_id": "site-1", "card_id": "card-1",
            "customer_id": "customer-1", "card_number_ciphertext": "cipher-card",
            "card_number_hmac": "hash-card", "status": "ACTIVE",
        },
        "fin_service_card_ledger": {
            "tenant_id": "tenant-1", "site_id": "site-1", "ledger_entry_id": "ledger-1",
            "card_id": "card-1", "entry_type": "ISSUANCE", "idempotency_key_hash": "hash-ledger",
            "source_type": "SERVICE_CARD_ISSUANCE", "source_id": "issue-1", "delta_amount": "100.00",
            "currency_code": "CNY", "occurred_at": "2026-10-02T10:00:00Z", "created_at": "2026-10-02T10:00:01Z",
        },
        "hlth_health_record": {
            "tenant_id": "tenant-1", "site_id": "site-1", "health_record_id": "health-1",
            "customer_id": "customer-1", "consent_id": "consent-1", "record_type": "MEASUREMENT",
            "occurred_at": "2026-10-02T10:00:00Z", "source_key": "source-hash",
            "payload_ciphertext": "HEALTH-BODY-MUST-NEVER-APPEAR-IN-REPORT", "status": "ACTIVE",
            "retention_until": "2027-10-02T00:00:00Z",
        },
        "hlth_record_revision": {
            "tenant_id": "tenant-1", "site_id": "site-1", "revision_id": "revision-1",
            "health_record_id": "health-1", "revision_no": "1", "revision_state": "AMENDED",
            "payload_ciphertext": "ANOTHER-HEALTH-BODY-MUST-NEVER-APPEAR",
            "occurred_at": "2026-10-02T10:00:00Z", "created_at": "2026-10-02T10:00:01Z",
        },
    }
    for table, row in values.items():
        sql = f'INSERT INTO "{table}" (' + ", ".join(f'"{name}"' for name in row) + ") VALUES (" + ", ".join("?" for _ in row) + ")"
        connection.execute(sql, tuple(row.values()))
    connection.commit()
    return connection


def clone_database(source: sqlite3.Connection) -> sqlite3.Connection:
    cloned = sqlite3.connect(":memory:")
    cloned.row_factory = sqlite3.Row
    source.backup(cloned)
    return cloned


def by_id(report, check_id):
    return next(check for check in report["checks"] if check["id"] == check_id)


class HealthScrmGateTests(unittest.TestCase):
    def test_clean_fixture_passes_and_never_exports_health_content(self):
        seed = make_database()
        backup = clone_database(seed)
        restored = clone_database(backup)

        report = run_quality_gates(
            restored,
            canonical_model=fixture_model(),
            seed_db=seed,
            backup_db=backup,
            restored_db=restored,
        )

        self.assertEqual("pass", report["status"])
        self.assertEqual("pass", by_id(report, "five_minute_appointment_locks")["status"])
        self.assertEqual("pass", by_id(report, "ledger_append_only")["status"])
        self.assertEqual("pass", by_id(report, "seed_backup_restore_consistency")["status"])
        self.assertFalse(by_id(report, "health_export_privacy")["metadata"]["health_payload_exported"])
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("HEALTH-BODY-MUST-NEVER-APPEAR-IN-REPORT", serialized)
        self.assertNotIn("ANOTHER-HEALTH-BODY-MUST-NEVER-APPEAR", serialized)
        for connection in (seed, backup, restored):
            connection.close()

    def test_status_orphan_cross_site_and_plaintext_pii_findings_are_machine_readable(self):
        connection = make_database()
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("ALTER TABLE crm_customer ADD COLUMN phone TEXT")
        connection.execute("UPDATE crm_customer SET phone = 'synthetic-plaintext-phone'")
        connection.execute("UPDATE svc_appointment SET status = 'NOT_A_STATE'")
        connection.execute(
            "INSERT INTO plat_site (tenant_id, site_id, site_code, status) VALUES ('tenant-1', 'site-2', 'S2', 'ACTIVE')"
        )
        connection.execute(
            "INSERT INTO svc_resource (tenant_id, site_id, resource_id, resource_code, status) "
            "VALUES ('tenant-1', 'site-2', 'resource-1', 'ROOM1', 'ACTIVE')"
        )
        connection.execute("UPDATE svc_resource_lock SET site_id = 'site-missing'")
        connection.execute("UPDATE svc_resource_lock SET site_id = 'site-2'")
        connection.commit()

        report = run_quality_gates(connection, canonical_model=fixture_model())

        self.assertEqual("fail", report["status"])
        codes = {
            finding["code"]
            for check in report["checks"]
            for finding in check.get("findings", [])
        }
        self.assertIn("plaintext_sensitive_column_present", codes)
        self.assertIn("state_value_outside_catalog", codes)
        self.assertIn("orphan_reference", codes)
        self.assertIn("cross_tenant_or_site_reference", codes)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("synthetic-plaintext-phone", serialized)
        connection.close()

    def test_five_minute_bucket_alignment_is_checked(self):
        connection = make_database()
        connection.execute(
            "UPDATE svc_resource_lock SET slot_start_utc = '2026-10-02T10:02:00.000Z' WHERE lock_id = 'lock-1'"
        )
        connection.commit()

        report = run_quality_gates(connection, canonical_model=fixture_model())

        lock_check = by_id(report, "five_minute_appointment_locks")
        self.assertEqual("fail", lock_check["status"])
        self.assertEqual("slot_not_aligned_to_five_minute_bucket", lock_check["findings"][0]["code"])
        connection.close()

    def test_health_retention_deadline_is_required(self):
        connection = make_database()
        connection.execute("UPDATE hlth_health_record SET retention_until = NULL")
        connection.commit()

        report = run_quality_gates(connection, canonical_model=fixture_model())

        retention = by_id(report, "privacy_retention")
        self.assertEqual("fail", retention["status"])
        self.assertEqual("retention_deadline_missing", retention["findings"][0]["code"])
        connection.close()

    def test_missing_ledger_guards_and_restore_drift_fail_closed(self):
        seed = make_database(include_ledger_guards=False)
        backup = clone_database(seed)
        restored = clone_database(backup)
        restored.execute("UPDATE fin_service_card_ledger SET delta_amount = '90.00' WHERE ledger_entry_id = 'ledger-1'")
        restored.commit()

        report = run_quality_gates(
            restored,
            canonical_model=fixture_model(),
            seed_db=seed,
            backup_db=backup,
            restored_db=restored,
        )

        self.assertEqual("fail", by_id(report, "ledger_append_only")["status"])
        recovery = by_id(report, "seed_backup_restore_consistency")
        self.assertEqual("fail", recovery["status"])
        self.assertEqual(1, recovery["metadata"]["comparisons"][1]["changed_table_count"])
        self.assertNotIn("90.00", json.dumps(report))
        for connection in (seed, backup, restored):
            connection.close()

    def test_data_duplicates_are_detected_even_when_database_lacks_unique_index(self):
        model = fixture_model()
        model["entities"] = [next(entity for entity in model["entities"] if entity["name"] == "svc_resource_lock")]
        model["entity_count"] = 1
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE svc_resource_lock (tenant_id TEXT NOT NULL, site_id TEXT, resource_id TEXT NOT NULL, "
            "slot_start_utc TEXT NOT NULL, appointment_id TEXT NOT NULL, status TEXT NOT NULL, locked_at TEXT, "
            "expires_at TEXT, lock_id TEXT PRIMARY KEY, idempotency_key_hash TEXT)"
        )
        connection.executemany(
            "INSERT INTO svc_resource_lock VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("tenant-1", "site-1", "resource-1", "2026-10-02T10:00:00Z", "a1", "CONFIRMED", "t", None, "l1", "hash-1"),
                ("tenant-1", "site-1", "resource-1", "2026-10-02T10:00:00Z", "a2", "CONFIRMED", "t", None, "l2", "hash-2"),
            ],
        )

        report = run_quality_gates(connection, canonical_model=model)

        self.assertIn(
            "duplicate_business_key",
            {finding["code"] for finding in by_id(report, "unique_keys").get("findings", [])},
        )
        schema_codes = {
            finding["code"]
            for finding in by_id(report, "materialized_schema_contract").get("findings", [])
        }
        self.assertIn("scope_column_not_declared_not_null", schema_codes)
        connection.close()

    def test_unconfirmed_health_owner_cannot_be_enabled(self):
        model = deepcopy(fixture_model())
        health = next(entity for entity in model["entities"] if entity["name"] == "hlth_health_record")
        health["write_enabled"] = True
        health["write_master"] = "unknown-writer"
        connection = sqlite3.connect(":memory:")

        report = run_quality_gates(connection, canonical_model=model)

        codes = {
            finding["code"]
            for finding in by_id(report, "owner_pii_model_contract").get("findings", [])
        }
        self.assertIn("unconfirmed_health_owner_must_remain_write_disabled", codes)
        self.assertIn("missing_or_unregistered_write_owner", codes)
        connection.close()


if __name__ == "__main__":
    unittest.main()
