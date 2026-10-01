from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SOURCE = Path(__file__).parents[1] / "versions" / "scrm_service_records_and_ledger.py"
SPEC = importlib.util.spec_from_file_location("db05_scrm_service_records_and_ledger", SOURCE)
assert SPEC and SPEC.loader
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class FakeResult:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self.row = row

    def first(self) -> tuple[object, ...] | None:
        return self.row


class FakeBind:
    def __init__(self, *, missing_row_table: str | None = None, orphan: bool = False) -> None:
        self.missing_row_table = missing_row_table
        self.orphan = orphan
        self.queries: list[str] = []

    def execute(self, statement: object) -> FakeResult:
        sql = str(statement)
        self.queries.append(sql)
        if "LEFT JOIN fin_service_card_ledger" in sql:
            return FakeResult((1,) if self.orphan else None)
        if "GROUP BY tenant_id, site_id, reversal_of" in sql:
            return FakeResult()
        if "information_schema.TRIGGERS" in sql:
            return FakeResult()
        if sql.startswith("SELECT 1 FROM "):
            table = sql.split("FROM ", 1)[1].split()[0]
            return FakeResult((1,) if table == self.missing_row_table else None)
        return FakeResult()


class FakeInspector:
    def __init__(self, *, missing_table: str | None = None, collide_table: str | None = None) -> None:
        self.tables = set(MIGRATION.BASE_REQUIRED_COLUMNS) | set(MIGRATION.NEW_TABLE_DDL)
        # An upgrade starts without the DB-05 extension tables.
        self.tables -= set(MIGRATION.NEW_TABLE_DDL)
        if missing_table:
            self.tables.remove(missing_table)
        if collide_table:
            self.tables.add(collide_table)
        self.columns = {
            table: set(columns)
            for table, columns in MIGRATION.BASE_REQUIRED_COLUMNS.items()
        }
        self.primary_keys = dict(MIGRATION.BASE_REQUIRED_PRIMARY_KEYS)

    def get_table_names(self) -> list[str]:
        return sorted(self.tables)

    def get_columns(self, table: str) -> list[dict[str, str]]:
        return [{"name": name} for name in sorted(self.columns.get(table, set()))]

    def get_pk_constraint(self, table: str) -> dict[str, tuple[str, ...]]:
        return {"constrained_columns": self.primary_keys.get(table, ())}

    def get_indexes(self, table: str) -> list[dict[str, object]]:
        return []

    def get_unique_constraints(self, table: str) -> list[dict[str, object]]:
        return []

    def get_foreign_keys(self, table: str) -> list[dict[str, object]]:
        return []


class FakeOperations:
    def __init__(self, bind: FakeBind | None = None) -> None:
        self.bind = bind or FakeBind()
        self.statements: list[str] = []

    def get_bind(self) -> FakeBind:
        return self.bind

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


class MigrationTests(unittest.TestCase):
    def test_upgrade_preflights_then_adds_scope_and_append_only_objects(self) -> None:
        operations = FakeOperations()
        MIGRATION.upgrade(operations=operations, inspector=FakeInspector())
        sql = "\n".join(operations.statements)
        self.assertIn("CREATE TABLE crm_customer_followup_plan", sql)
        self.assertIn("CREATE TABLE svc_service_note", sql)
        self.assertIn("CREATE TABLE fin_service_card_consumption", sql)
        self.assertIn("FOREIGN KEY (tenant_id, site_id, reversal_of)", sql)
        self.assertIn("trg_db05_ledger_no_update", sql)
        self.assertIn("trg_db05_ledger_no_delete", sql)
        self.assertIn("trg_db05_ledger_source_guard", sql)
        self.assertNotIn("CREATE TABLE fin_card ", sql)
        self.assertNotIn("CREATE TABLE crm_customer_followup_task ", sql)

    def test_missing_canonical_prerequisite_fails_before_first_ddl(self) -> None:
        operations = FakeOperations()
        inspector = FakeInspector(missing_table="fin_service_card")
        with self.assertRaisesRegex(MIGRATION.MigrationPreconditionError, "missing"):
            MIGRATION.upgrade(operations=operations, inspector=inspector)
        self.assertEqual([], operations.statements)

    def test_orphaned_reversal_fails_before_first_ddl(self) -> None:
        operations = FakeOperations(FakeBind(orphan=True))
        with self.assertRaisesRegex(MIGRATION.MigrationPreconditionError, "orphan"):
            MIGRATION.upgrade(operations=operations, inspector=FakeInspector())
        self.assertEqual([], operations.statements)

    def test_same_name_extension_requires_reconciliation_not_parallel_table(self) -> None:
        operations = FakeOperations()
        inspector = FakeInspector(collide_table="svc_service_note")
        with self.assertRaisesRegex(MIGRATION.MigrationPreconditionError, "reconciliation"):
            MIGRATION.upgrade(operations=operations, inspector=inspector)
        self.assertEqual([], operations.statements)

    def test_downgrade_refuses_any_written_ledger_before_dropping_objects(self) -> None:
        operations = FakeOperations(FakeBind(missing_row_table="fin_service_card_ledger"))
        inspector = FakeInspector()
        inspector.tables |= set(MIGRATION.NEW_TABLE_DDL)
        with self.assertRaisesRegex(MIGRATION.MigrationPreconditionError, "business data"):
            MIGRATION.downgrade(operations=operations, inspector=inspector)
        self.assertEqual([], operations.statements)

    def test_empty_downgrade_removes_schema_objects_but_never_drops_canonical_ledger(self) -> None:
        operations = FakeOperations()
        inspector = FakeInspector()
        inspector.tables |= set(MIGRATION.NEW_TABLE_DDL)
        MIGRATION.downgrade(operations=operations, inspector=inspector)
        sql = "\n".join(operations.statements)
        self.assertIn("DROP TABLE svc_service_note_media", sql)
        self.assertIn("DROP TRIGGER IF EXISTS trg_db05_ledger_no_delete", sql)
        self.assertIn("DROP TRIGGER IF EXISTS trg_db05_ledger_source_guard", sql)
        self.assertNotIn("DROP TABLE fin_service_card_ledger", sql)
        self.assertFalse(any(statement.lstrip().upper().startswith("DELETE ") for statement in operations.statements))


if __name__ == "__main__":
    unittest.main()
