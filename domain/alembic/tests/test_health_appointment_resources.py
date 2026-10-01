"""DB-04 migration contract tests; operations are fake and execute no DDL."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MIGRATION_PATH = Path(__file__).parents[1] / "versions" / "health_appointment_resources.py"
SPEC = importlib.util.spec_from_file_location("health_appointment_resources", MIGRATION_PATH)
MIGRATION = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MIGRATION)


BASE_COLUMNS = {
    "plat_site": ("tenant_id", "site_id"),
    "crm_customer": ("tenant_id", "customer_id"),
    "plat_staff_identity": ("tenant_id", "staff_id"),
    "svc_service_version": ("tenant_id", "site_id", "service_version_id"),
    "svc_resource": ("tenant_id", "site_id", "resource_id"),
    "svc_appointment": (
        "tenant_id", "site_id", "appointment_id", "customer_id", "subject_customer_id",
        "service_version_id", "idempotency_key", "status", "version_no", "starts_at", "ends_at",
        "hold_until", "requested_at", "confirmed_at", "created_at", "updated_at",
    ),
    "svc_resource_lock": (
        "tenant_id", "site_id", "lock_id", "resource_id", "slot_start_utc", "appointment_id",
        "idempotency_key_hash", "status", "lock_version", "locked_at", "expires_at", "updated_at",
    ),
}
BASE_PKS = {
    "plat_site": ("tenant_id", "site_id"),
    "crm_customer": ("tenant_id", "customer_id"),
    "plat_staff_identity": ("tenant_id", "staff_id"),
    "svc_service_version": ("tenant_id", "site_id", "service_version_id"),
    "svc_resource": ("tenant_id", "site_id", "resource_id"),
    "svc_appointment": ("tenant_id", "site_id", "appointment_id"),
    "svc_resource_lock": ("tenant_id", "site_id", "lock_id"),
}


class FakeInspector:
    def __init__(self, *, include_targets: bool = False) -> None:
        self.tables = set(BASE_COLUMNS)
        if include_targets:
            self.tables.update(MIGRATION.TABLE_DDL)
        self.columns = {table: set(names) for table, names in BASE_COLUMNS.items()}
        for table, statement in MIGRATION.TABLE_DDL.items():
            if include_targets:
                # Downgrade only needs to prove each revision-owned object exists.
                self.columns[table] = {"tenant_id", "site_id", "id"}
        self.unique = {
            "svc_resource_lock": [MIGRATION.LOCK_SLOT_UNIQUE_KEY],
            "svc_appointment": [MIGRATION.APPOINTMENT_IDEMPOTENCY_KEY],
        }
        self.indexes: dict[str, list[dict[str, object]]] = {table: [] for table in self.tables}
        self.primary_keys = dict(BASE_PKS)

    def get_table_names(self):
        return sorted(self.tables)

    def get_columns(self, table):
        return [{"name": name, "nullable": False} for name in sorted(self.columns.get(table, set()))]

    def get_pk_constraint(self, table):
        return {"constrained_columns": self.primary_keys.get(table, ())}

    def get_unique_constraints(self, table):
        return [{"column_names": key} for key in self.unique.get(table, ())]

    def get_indexes(self, table):
        return self.indexes.get(table, [])


class EmptyResult:
    def first(self):
        return None


class FakeBind:
    def __init__(self, populated=()):
        self.populated = set(populated)
        self.queries = []

    def execute(self, statement):
        sql = str(statement)
        self.queries.append(sql)
        table = next((name for name in MIGRATION.TABLE_DDL if f"FROM {name} " in sql), None)
        return FakeRows([("row",)] if table in self.populated else [])


class FakeRows:
    def __init__(self, rows):
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None

    def fetchone(self):
        return self.first()

    def __iter__(self):
        return iter(self.rows)


class FakeOperations:
    def __init__(self, *, fail_at=None, bind=None):
        self.statements = []
        self.fail_at = fail_at
        self.bind = bind or FakeBind()

    def execute(self, statement):
        sql = str(statement).strip()
        self.statements.append(sql)
        if self.fail_at == len(self.statements):
            raise RuntimeError("synthetic DDL failure")

    def get_bind(self):
        return self.bind


class HealthAppointmentMigrationTests(unittest.TestCase):
    def test_preflight_rejects_missing_bucket_unique_before_ddl(self):
        inspector = FakeInspector()
        inspector.unique["svc_resource_lock"] = []
        operations = FakeOperations()

        with self.assertRaisesRegex(MIGRATION.MigrationPreconditionError, "tenant/site/resource/slot"):
            MIGRATION.upgrade(operations=operations, inspector=inspector)

        self.assertEqual([], operations.statements)

    def test_upgrade_creates_only_scoped_support_tables_and_not_parallel_booking_tables(self):
        operations = FakeOperations()
        MIGRATION.upgrade(operations=operations, inspector=FakeInspector())

        sql = "\n".join(operations.statements)
        self.assertIn("CREATE TABLE svc_appointment_context", sql)
        self.assertIn("CREATE TABLE svc_appointment_resource_requirement", sql)
        self.assertIn("CREATE TABLE svc_appointment_resource_assignment", sql)
        self.assertIn("CREATE TABLE svc_appointment_hold", sql)
        self.assertIn("CREATE TABLE svc_resource_lock_history", sql)
        self.assertIn("CREATE INDEX ix_db04_resource_lock_expiry", sql)
        self.assertNotIn("CREATE TABLE svc_appointment (", sql)
        self.assertNotIn("CREATE TABLE svc_resource_lock (", sql)

    def test_upgrade_compensates_prior_ddl_if_a_later_statement_fails(self):
        operations = FakeOperations(fail_at=4)

        with self.assertRaisesRegex(RuntimeError, "synthetic DDL failure"):
            MIGRATION.upgrade(operations=operations, inspector=FakeInspector())

        drops = [statement for statement in operations.statements if statement.startswith("DROP TABLE")]
        self.assertEqual(
            ["DROP TABLE svc_appointment_resource_requirement", "DROP TABLE svc_appointment_context", "DROP TABLE svc_location"],
            drops,
        )

    def test_downgrade_refuses_populated_snapshots_before_dropping_anything(self):
        inspector = FakeInspector(include_targets=True)
        operations = FakeOperations(bind=FakeBind(populated={"svc_appointment_context"}))

        with self.assertRaisesRegex(MIGRATION.MigrationPreconditionError, "preserve existing bookings"):
            MIGRATION.downgrade(operations=operations, inspector=inspector)

        self.assertEqual([], operations.statements)

    def test_downgrade_checks_every_table_then_drops_only_db04_objects(self):
        inspector = FakeInspector(include_targets=True)
        inspector.indexes["svc_resource_lock"] = [
            {"name": MIGRATION.LOCK_EXPIRY_INDEX, "column_names": MIGRATION._LOCK_EXPIRY_COLUMNS}
        ]
        operations = FakeOperations(bind=FakeBind())

        MIGRATION.downgrade(operations=operations, inspector=inspector)

        self.assertEqual(MIGRATION._LOCK_EXPIRY_INDEX_DROP, operations.statements[0])
        self.assertEqual(
            [f"DROP TABLE {table}" for table in MIGRATION._TABLE_DROP_ORDER],
            operations.statements[1:],
        )


if __name__ == "__main__":
    unittest.main()
