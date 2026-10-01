"""Standard-library synthetic coverage for DEV-05 backup/restore contracts."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dev05_restore import (
    ManifestError,
    RestoreRejected,
    build_manifest,
    database_fingerprint,
    restore_isolated,
    safe_log_record,
    verify_manifest,
    verify_reference_continuity,
    verify_snapshot_chain,
)


TEST_INTEGRITY_SECRET = b"SYNTHETIC-OUT-OF-BAND-HMAC-SECRET"


def make_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE plat_tenant (
            tenant_id TEXT PRIMARY KEY, status TEXT NOT NULL
        );
        CREATE TABLE plat_site (
            tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY (tenant_id, site_id),
            FOREIGN KEY (tenant_id) REFERENCES plat_tenant (tenant_id) ON DELETE RESTRICT
        );
        CREATE TABLE svc_service_item (
            tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, service_id TEXT NOT NULL,
            status TEXT NOT NULL, PRIMARY KEY (tenant_id, site_id, service_id),
            FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT
        );
        CREATE TABLE svc_service_version (
            tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, service_version_id TEXT NOT NULL,
            service_id TEXT NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY (tenant_id, site_id, service_version_id),
            FOREIGN KEY (tenant_id, site_id, service_id)
                REFERENCES svc_service_item (tenant_id, site_id, service_id) ON DELETE RESTRICT
        );
        CREATE TABLE svc_appointment (
            tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, appointment_id TEXT NOT NULL,
            service_version_id TEXT NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY (tenant_id, site_id, appointment_id),
            FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT,
            FOREIGN KEY (tenant_id, site_id, service_version_id)
                REFERENCES svc_service_version (tenant_id, site_id, service_version_id) ON DELETE RESTRICT
        );
        CREATE TABLE fin_payment (
            tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, payment_id TEXT NOT NULL,
            appointment_id TEXT NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY (tenant_id, site_id, payment_id),
            FOREIGN KEY (tenant_id, site_id, appointment_id)
                REFERENCES svc_appointment (tenant_id, site_id, appointment_id) ON DELETE RESTRICT
        );
        CREATE TABLE fin_service_card (
            tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, card_id TEXT NOT NULL,
            status TEXT NOT NULL, PRIMARY KEY (tenant_id, site_id, card_id),
            FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT
        );
        CREATE TABLE fin_service_card_ledger (
            tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, ledger_entry_id TEXT NOT NULL,
            card_id TEXT NOT NULL, entry_type TEXT NOT NULL, delta_amount TEXT NOT NULL,
            PRIMARY KEY (tenant_id, site_id, ledger_entry_id),
            FOREIGN KEY (tenant_id, site_id, card_id)
                REFERENCES fin_service_card (tenant_id, site_id, card_id) ON DELETE RESTRICT
        );
        CREATE TRIGGER ledger_no_update BEFORE UPDATE ON fin_service_card_ledger
        BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
        CREATE TRIGGER ledger_no_delete BEFORE DELETE ON fin_service_card_ledger
        BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
        CREATE TABLE aud_audit_event (
            tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, audit_id TEXT NOT NULL,
            target_type TEXT NOT NULL, target_id TEXT NOT NULL, outcome TEXT NOT NULL,
            PRIMARY KEY (tenant_id, site_id, audit_id),
            FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT
        );
        INSERT INTO plat_tenant VALUES ('synthetic-tenant-1', 'ACTIVE');
        INSERT INTO plat_site VALUES ('synthetic-tenant-1', 'synthetic-site-1', 'ACTIVE');
        INSERT INTO svc_service_item VALUES ('synthetic-tenant-1', 'synthetic-site-1', 'synthetic-service-1', 'ACTIVE');
        INSERT INTO svc_service_version VALUES ('synthetic-tenant-1', 'synthetic-site-1', 'synthetic-version-1', 'synthetic-service-1', 'PUBLISHED');
        INSERT INTO svc_appointment VALUES ('synthetic-tenant-1', 'synthetic-site-1', 'synthetic-appointment-1', 'synthetic-version-1', 'CONFIRMED');
        INSERT INTO fin_payment VALUES ('synthetic-tenant-1', 'synthetic-site-1', 'synthetic-payment-1', 'synthetic-appointment-1', 'SETTLED');
        INSERT INTO fin_service_card VALUES ('synthetic-tenant-1', 'synthetic-site-1', 'synthetic-card-1', 'ACTIVE');
        INSERT INTO fin_service_card_ledger VALUES ('synthetic-tenant-1', 'synthetic-site-1', 'synthetic-ledger-1', 'synthetic-card-1', 'ISSUANCE', '100.00');
        INSERT INTO aud_audit_event VALUES ('synthetic-tenant-1', 'synthetic-site-1', 'synthetic-audit-1', 'svc_appointment', 'synthetic-appointment-1', 'ALLOW');
        """
    )
    connection.commit()
    return connection


def clone_database(source: sqlite3.Connection) -> sqlite3.Connection:
    cloned = sqlite3.connect(":memory:")
    source.backup(cloned)
    return cloned


def build_test_manifest(artifact: bytes = b"SYNTHETIC-ENCRYPTED-BACKUP-BYTES"):
    return build_manifest(
        artifact,
        backup_id="synthetic-backup-001",
        created_at="2026-10-02T02:00:00Z",
        source_environment="synthetic",
        schema_fingerprint="sha256:synthetic-schema-fingerprint",
        source_watermark="synthetic-watermark-001",
        encryption_algorithm="AES-256-GCM-envelope-test-marker",
        key_reference="kms://synthetic/dev05-backup-key",
        key_version="synthetic-key-version-1",
        retention_policy_id="synthetic-retention-policy-v1",
        retention_until="2026-11-02T02:00:00Z",
        access_policy_id="synthetic-backup-restore-roles-v1",
        allowed_roles=("backup-writer", "restore-operator", "security-auditor"),
        integrity_key=TEST_INTEGRITY_SECRET,
    )


class Dev05RestoreTests(unittest.TestCase):
    def test_manifest_is_complete_and_hashes_opaque_encrypted_artifact(self):
        artifact = b"SYNTHETIC-ENCRYPTED-BACKUP-BYTES"
        manifest = build_test_manifest(artifact)

        result = verify_manifest(manifest, artifact, integrity_key=TEST_INTEGRITY_SECRET)

        self.assertEqual("pass", result["status"])
        self.assertEqual(len(artifact), manifest["artifact"]["byte_count"])
        self.assertEqual(64, len(manifest["integrity"]["manifest_sha256"]))
        self.assertFalse(manifest["encryption"]["key_material_included"])
        self.assertEqual(
            ["backup-writer", "restore-operator", "security-auditor"],
            manifest["access"]["allowed_roles"],
        )

    def test_manifest_rejects_ciphertext_tampering_and_metadata_tampering(self):
        artifact = b"SYNTHETIC-ENCRYPTED-BACKUP-BYTES"
        manifest = build_test_manifest(artifact)
        changed_artifact = artifact[:-1] + b"X"
        with self.assertRaisesRegex(ManifestError, "artifact_hash_mismatch"):
            verify_manifest(manifest, changed_artifact, integrity_key=TEST_INTEGRITY_SECRET)

        altered = copy.deepcopy(manifest)
        altered["retention"]["retain_until"] = "2027-01-01T00:00:00Z"
        with self.assertRaisesRegex(ManifestError, "manifest_hash_mismatch"):
            verify_manifest(altered, artifact, integrity_key=TEST_INTEGRITY_SECRET)

    def test_secret_is_external_and_allowlisted_log_has_no_secret_or_row_values(self):
        manifest = build_test_manifest()
        record = safe_log_record(
            "manifest_verify", "pass", ("manifest_verified", TEST_INTEGRITY_SECRET.decode("ascii"))
        )
        serialized = json.dumps({"manifest": manifest, "log": record}, sort_keys=True)

        self.assertNotIn(TEST_INTEGRITY_SECRET.decode("ascii"), serialized)
        self.assertEqual(["manifest_verified"], record["finding_codes"])
        self.assertFalse(record["secret_values_exported"])
        self.assertFalse(record["secret_values_exported"])
        self.assertFalse(record["row_values_exported"])

    def test_manifest_rejects_production_environment_in_synthetic_harness(self):
        with self.assertRaisesRegex(ManifestError, "source_environment_not_isolated"):
            build_manifest(
                b"synthetic-ciphertext",
                backup_id="synthetic-backup-002",
                created_at="2026-10-02T02:00:00Z",
                source_environment="production",
                schema_fingerprint="synthetic-schema",
                source_watermark="synthetic-watermark",
                encryption_algorithm="AES-256-GCM-envelope-test-marker",
                key_reference="kms://synthetic/key",
                key_version="synthetic-v1",
                retention_policy_id="synthetic-retention-v1",
                retention_until="2026-11-02T02:00:00Z",
                access_policy_id="synthetic-access-v1",
                allowed_roles=("restore-operator",),
                integrity_key=TEST_INTEGRITY_SECRET,
            )

    def test_isolated_restore_preserves_tenant_site_and_business_reference_chain(self):
        seed = make_database()
        backup = clone_database(seed)
        restored, restore_report = restore_isolated(backup)
        chain = verify_snapshot_chain(seed, backup, restored)

        self.assertEqual("pass", restore_report["status"])
        self.assertEqual("pass", chain["status"])
        self.assertEqual(
            1,
            chain["continuity"]["restored"]["table_counts"]["fin_payment"],
        )
        self.assertFalse(chain["row_values_exported"])
        self.assertTrue(all(item["status"] == "pass" for item in chain["comparisons"]))
        restored.close()
        backup.close()
        seed.close()

    def test_reference_checker_rejects_cross_site_or_missing_catalog_reference(self):
        connection = make_database()
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "UPDATE svc_appointment SET site_id='synthetic-site-2' WHERE appointment_id='synthetic-appointment-1'"
        )
        report = verify_reference_continuity(connection)

        self.assertEqual("fail", report["status"])
        self.assertIn("appointment_catalog_reference", report["finding_codes"])
        self.assertNotIn("synthetic-appointment-1", json.dumps(report))
        connection.close()

    def test_failed_isolated_restore_does_not_mutate_source(self):
        original = make_database()
        damaged_source = clone_database(original)
        damaged_source.execute("PRAGMA foreign_keys = OFF")
        damaged_source.execute("DELETE FROM plat_site WHERE site_id='synthetic-site-1'")
        damaged_source.commit()
        before = database_fingerprint(damaged_source)

        with self.assertRaises(RestoreRejected):
            restore_isolated(damaged_source)

        self.assertEqual(before, database_fingerprint(damaged_source))
        self.assertEqual(1, original.execute("SELECT COUNT(*) FROM plat_site").fetchone()[0])
        damaged_source.close()
        original.close()

    def test_restored_ledger_rejects_update_and_delete(self):
        seed = make_database()
        restored, _ = restore_isolated(seed)

        with self.assertRaises(sqlite3.IntegrityError):
            restored.execute("UPDATE fin_service_card_ledger SET delta_amount='0.00'")
        with self.assertRaises(sqlite3.IntegrityError):
            restored.execute("DELETE FROM fin_service_card_ledger")
        self.assertEqual(
            "100.00",
            restored.execute("SELECT delta_amount FROM fin_service_card_ledger").fetchone()[0],
        )
        restored.close()
        seed.close()

    def test_snapshot_chain_reports_table_drift_without_row_values(self):
        seed = make_database()
        backup = clone_database(seed)
        backup.execute("UPDATE fin_payment SET status='REFUNDED'")
        backup.commit()
        restored = clone_database(backup)

        report = verify_snapshot_chain(seed, backup, restored)
        backup_comparison = next(item for item in report["comparisons"] if item["snapshot"] == "backup")

        self.assertEqual("fail", report["status"])
        self.assertIn("fin_payment", backup_comparison["changed_tables"])
        self.assertNotIn("SETTLED", json.dumps(report))
        self.assertNotIn("REFUNDED", json.dumps(report))
        restored.close()
        backup.close()
        seed.close()


if __name__ == "__main__":
    unittest.main()
