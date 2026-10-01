from __future__ import annotations

import copy
import json
import unittest
import uuid
from pathlib import Path

from domain.seeds.health_service_catalog.seed_loader import (
    BookingBlocked,
    PublicationBlocked,
    SERVICE_NAMES,
    SeedConflict,
    SeedRollbackBlocked,
    SiteScopeDenied,
    apply_seed,
    open_synthetic_fixture,
    read_scoped_fixture,
    require_bookable,
    require_publishable,
    rollback_seed,
)


SEED_DIR = Path(__file__).parents[1]
TENANT_SEED_PATH = SEED_DIR.parent / "tenant_site" / "seed.json"
CATALOG_SEED_PATH = SEED_DIR / "seed.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def site_id_for(connection, site_code: str) -> str:
    return connection.execute(
        "SELECT site_id FROM plat_site WHERE site_code = ?", (site_code,)
    ).fetchone()[0]


def row_dict(connection, sql: str, params: tuple = ()) -> dict:
    row = connection.execute(sql, params).fetchone()
    if row is None:
        raise AssertionError(f"expected row for query: {sql}")
    return dict(row)


class DB07SeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_synthetic_fixture()
        apply_seed(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_names_match_prototype_verbatim_and_only_seeded_at_phoenix_valley(self) -> None:
        names = tuple(
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM svc_service_item ORDER BY service_code"
            ).fetchall()
        )
        self.assertEqual(names, SERVICE_NAMES)
        self.assertEqual(len(names), 9)
        site_b = site_id_for(self.connection, "site-b")
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM svc_service_item WHERE site_id = ?", (site_b,)
            ).fetchone()[0],
            0,
        )

    def test_repeat_import_is_idempotent_and_rejects_seed_drift(self) -> None:
        before = {
            table: self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("plat_tenant", "plat_site", "svc_service_item", "svc_service_version")
        }
        apply_seed(self.connection)
        after = {
            table: self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in before
        }
        self.assertEqual(before, {"plat_tenant": 1, "plat_site": 2, "svc_service_item": 9, "svc_service_version": 9})
        self.assertEqual(after, before)

        changed = load_json(CATALOG_SEED_PATH)
        changed["services"][0]["service_code"] = "DEMO-PHX-01-DRIFT"
        with self.assertRaises(SeedConflict):
            apply_seed(self.connection, catalog_seed=changed)

    def test_unconfirmed_fields_stay_null_and_pending_versions_cannot_publish_or_book(self) -> None:
        rows = self.connection.execute(
            """SELECT i.status AS service_status, v.*
               FROM svc_service_item i
               JOIN svc_service_version v USING (tenant_id, site_id, service_id)
               ORDER BY i.service_code"""
        ).fetchall()
        self.assertEqual(len(rows), 9)
        for row in rows:
            version = dict(row)
            for field in (
                "duration_minutes",
                "price_amount",
                "currency_code",
                "eligibility_rule_version",
                "qualification_requirements_json",
                "service_location_ids_json",
                "capacity_policy_version",
                "preparation",
                "onsite_rules_version",
                "cancellation_policy_version",
                "effective_from",
            ):
                self.assertIsNone(version[field], f"{version['service_version_id']}.{field}")
            self.assertEqual(version["approval_status"], "pending")
            self.assertEqual(version["publication_status"], "unpublished")
            with self.assertRaises(PublicationBlocked):
                require_publishable(version)
            with self.assertRaises(BookingBlocked):
                require_bookable(version, version)
            # Even a broken upstream writer cannot make a pending version bookable
            # by setting active/published flags without an approval decision.
            forged_publication = dict(version, status="published", publication_status="published")
            with self.assertRaises(BookingBlocked):
                require_bookable({"status": "active"}, forged_publication)

    def test_site_b_cannot_read_phoenix_customers_resources_or_ledger(self) -> None:
        tenant_id = self.connection.execute(
            "SELECT tenant_id FROM plat_tenant WHERE tenant_code = 'tenant-demo'"
        ).fetchone()[0]
        site_a = site_id_for(self.connection, "site-a")
        site_b = site_id_for(self.connection, "site-b")
        for kind in ("customer", "resource", "ledger"):
            self.connection.execute(
                "INSERT INTO db07_scope_fixture (tenant_id, site_id, kind, fixture_key) VALUES (?, ?, ?, ?)",
                (tenant_id, site_a, kind, f"synthetic-{kind}-a"),
            )
            rows = read_scoped_fixture(
                self.connection,
                tenant_id=tenant_id,
                authorized_site_id=site_b,
                kind=kind,
            )
            self.assertEqual(rows, [], kind)
            with self.assertRaises(SiteScopeDenied):
                read_scoped_fixture(
                    self.connection,
                    tenant_id=tenant_id,
                    authorized_site_id=site_b,
                    requested_site_id=site_a,
                    kind=kind,
                )
        phoenix_rows = read_scoped_fixture(
            self.connection,
            tenant_id=tenant_id,
            authorized_site_id=site_a,
            kind="customer",
        )
        self.assertEqual(len(phoenix_rows), 1)

    def test_new_draft_version_does_not_rewrite_historical_appointment_snapshot(self) -> None:
        tenant_id = self.connection.execute(
            "SELECT tenant_id FROM plat_tenant WHERE tenant_code = 'tenant-demo'"
        ).fetchone()[0]
        site_a = site_id_for(self.connection, "site-a")
        old_version = row_dict(
            self.connection,
            "SELECT * FROM svc_service_version WHERE service_id = ? AND version_no = 1",
            (load_json(CATALOG_SEED_PATH)["services"][0]["service_id"],),
        )
        # This test-only transition stands for an already-booked version later retired.
        # It does not create a new booking from an unapproved seed version.
        self.connection.execute(
            "UPDATE svc_service_version SET status = 'retired', approval_status = 'approved', publication_status = 'retired' WHERE tenant_id = ? AND site_id = ? AND service_version_id = ?",
            (tenant_id, site_a, old_version["service_version_id"]),
        )
        frozen_snapshot = {
            "service_id": old_version["service_id"],
            "service_version_id": old_version["service_version_id"],
            "service_name": SERVICE_NAMES[0],
            "price_amount": None,
            "currency_code": None,
        }
        snapshot_text = json.dumps(frozen_snapshot, ensure_ascii=False, sort_keys=True)
        appointment_id = "db07-synthetic-historical-appointment"
        self.connection.execute(
            "INSERT INTO svc_appointment (tenant_id, site_id, appointment_id, service_version_id, status, snapshot_json) VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, site_a, appointment_id, old_version["service_version_id"], "已确认", snapshot_text),
        )

        catalog_v2 = copy.deepcopy(load_json(CATALOG_SEED_PATH))
        second_version = copy.deepcopy(catalog_v2["services"][0]["versions"][0])
        second_version["service_version_id"] = str(
            uuid.uuid5(uuid.UUID(catalog_v2["services"][0]["service_id"]), "db07-test-version-2")
        )
        second_version["version_no"] = 2
        catalog_v2["services"][0]["versions"] = [second_version]

        apply_seed(
            self.connection,
            tenant_seed=load_json(TENANT_SEED_PATH),
            catalog_seed=catalog_v2,
        )

        stored_snapshot = self.connection.execute(
            "SELECT snapshot_json FROM svc_appointment WHERE appointment_id = ?", (appointment_id,)
        ).fetchone()[0]
        self.assertEqual(stored_snapshot, snapshot_text)
        old_after = row_dict(
            self.connection,
            "SELECT * FROM svc_service_version WHERE service_version_id = ?",
            (old_version["service_version_id"],),
        )
        self.assertEqual(old_after["status"], "retired")
        self.assertEqual(old_after["publication_status"], "retired")
        new_after = row_dict(
            self.connection,
            "SELECT * FROM svc_service_version WHERE service_version_id = ?",
            (second_version["service_version_id"],),
        )
        self.assertEqual(new_after["approval_status"], "pending")
        self.assertEqual(new_after["publication_status"], "unpublished")

        with self.assertRaises(SeedRollbackBlocked):
            rollback_seed(self.connection)
        self.assertEqual(
            self.connection.execute(
                "SELECT snapshot_json FROM svc_appointment WHERE appointment_id = ?", (appointment_id,)
            ).fetchone()[0],
            snapshot_text,
        )

    def test_rollback_then_reapply_restores_identical_seed_rows(self) -> None:
        managed_tables = ("plat_tenant", "plat_site", "svc_service_item", "svc_service_version")
        before = {
            table: [tuple(row) for row in self.connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
            for table in managed_tables
        }
        rollback_seed(self.connection)
        self.assertEqual(
            [self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in managed_tables],
            [0, 0, 0, 0],
        )
        apply_seed(self.connection)
        after = {
            table: [tuple(row) for row in self.connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
            for table in managed_tables
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
