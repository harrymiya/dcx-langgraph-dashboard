from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).parents[1] / "versions" / "tenant_site_constraints.py"


def load_migration_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("db03_tenant_site_constraints", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = load_migration_module()


def sqlite_schema_for(entity_names: set[str]) -> list[str]:
    manifest = {entity["name"]: entity for entity in MIGRATION.CONSTRAINT_MANIFEST["entities"]}
    included = set(entity_names)
    pending = list(entity_names)
    while pending:
        entity = manifest[pending.pop()]
        for fk in entity["fks"]:
            parent = fk["ref_entity"]
            if parent not in included:
                included.add(parent)
                pending.append(parent)

    statements: list[str] = []
    for table in MIGRATION.CONSTRAINT_MANIFEST["entities"]:
        if table["name"] not in included:
            continue
        columns: set[str] = set(table["pk"])
        for key in table["unique_keys"]:
            columns.update(key)
        for fk in table["fks"]:
            columns.update(fk["columns"])
        definitions = [f'"{column}" TEXT' for column in sorted(columns)]
        definitions.append("PRIMARY KEY (" + ", ".join(f'"{c}"' for c in table["pk"]) + ")")
        for key in table["unique_keys"]:
            definitions.append("UNIQUE (" + ", ".join(f'"{c}"' for c in key) + ")")
        for fk in table["fks"]:
            definitions.append(
                "FOREIGN KEY ("
                + ", ".join(f'"{c}"' for c in fk["columns"])
                + f') REFERENCES "{fk["ref_entity"]}" ('
                + ", ".join(f'"{c}"' for c in fk["ref_columns"])
                + ") ON DELETE RESTRICT ON UPDATE RESTRICT"
            )
        statements.append(f'CREATE TABLE "{table["name"]}" (' + ", ".join(definitions) + ")")
    return statements


class FakeResult:
    def __init__(self, has_row: bool = False) -> None:
        self.has_row = has_row

    def first(self) -> tuple[int] | None:
        return (1,) if self.has_row else None


class FakeBind:
    def __init__(self, conflict: tuple[str, str] | None = None) -> None:
        self.conflict = conflict
        self.queries: list[str] = []
        self.dialect = None

    def execute(self, statement: object) -> FakeResult:
        sql = str(statement)
        self.queries.append(sql)
        has_row = False
        if self.conflict:
            mode, table = self.conflict
            is_target = f"FROM {table}" in sql
            has_row = is_target and (
                (mode == "unique" and "GROUP BY" in sql)
                or (mode == "foreign_key" and "LEFT JOIN" in sql)
            )
        return FakeResult(has_row)


class FakeInspector:
    def __init__(self, *, missing_table: str | None = None) -> None:
        self.entities = {
            entity["name"]: entity for entity in MIGRATION.CONSTRAINT_MANIFEST["entities"]
        }
        self.tables = set(self.entities)
        if missing_table:
            self.tables.remove(missing_table)
        self.columns: dict[str, list[dict[str, object]]] = {}
        self.primary_keys: dict[str, tuple[str, ...]] = {}
        self.uniques: dict[str, list[dict[str, object]]] = {name: [] for name in self.entities}
        self.indexes: dict[str, list[dict[str, object]]] = {name: [] for name in self.entities}
        self.foreign_keys: dict[str, list[dict[str, object]]] = {name: [] for name in self.entities}
        for name, entity in self.entities.items():
            names = set(entity["pk"])
            for key in entity["unique_keys"]:
                names.update(key)
            for fk in entity["fks"]:
                names.update(fk["columns"])
            self.columns[name] = [
                {"name": column, "nullable": False} for column in sorted(names)
            ]
            self.primary_keys[name] = tuple(entity["pk"])

    def get_table_names(self) -> list[str]:
        return sorted(self.tables)

    def get_columns(self, table: str) -> list[dict[str, object]]:
        return self.columns[table]

    def get_pk_constraint(self, table: str) -> dict[str, object]:
        return {"constrained_columns": self.primary_keys[table]}

    def get_unique_constraints(self, table: str) -> list[dict[str, object]]:
        return self.uniques[table]

    def get_indexes(self, table: str) -> list[dict[str, object]]:
        return self.indexes[table]

    def get_foreign_keys(self, table: str) -> list[dict[str, object]]:
        return self.foreign_keys[table]


class FakeOperations:
    def __init__(self, inspector: FakeInspector, bind: FakeBind | None = None) -> None:
        self.inspector = inspector
        self.bind = bind or FakeBind()
        self.calls: list[tuple[object, ...]] = []

    def get_bind(self) -> FakeBind:
        return self.bind

    def create_unique_constraint(self, name: str, table: str, columns: list[str]) -> None:
        self.calls.append(("create_unique", name, table, tuple(columns)))
        self.inspector.uniques[table].append({"name": name, "column_names": tuple(columns)})

    def create_index(self, name: str, table: str, columns: list[str]) -> None:
        self.calls.append(("create_index", name, table, tuple(columns)))
        self.inspector.indexes[table].append(
            {"name": name, "column_names": tuple(columns), "unique": False}
        )

    def create_foreign_key(
        self,
        name: str,
        table: str,
        referred_table: str,
        columns: list[str],
        referred_columns: list[str],
        **options: object,
    ) -> None:
        self.calls.append(("create_fk", name, table, tuple(columns), referred_table))
        self.inspector.foreign_keys[table].append(
            {
                "name": name,
                "constrained_columns": tuple(columns),
                "referred_table": referred_table,
                "referred_columns": tuple(referred_columns),
                "options": options,
            }
        )

    def drop_constraint(self, name: str, table: str, *, type_: str) -> None:
        self.calls.append(("drop_constraint", name, table, type_))
        target = self.inspector.foreign_keys[table] if type_ == "foreignkey" else self.inspector.uniques[table]
        target[:] = [item for item in target if item.get("name") != name]

    def drop_index(self, name: str, *, table_name: str) -> None:
        self.calls.append(("drop_index", name, table_name))
        self.inspector.indexes[table_name][:] = [
            item for item in self.inspector.indexes[table_name] if item.get("name") != name
        ]


def sqlalchemy_text_stub() -> types.ModuleType:
    module = types.ModuleType("sqlalchemy")
    module.text = lambda sql: sql  # type: ignore[attr-defined]
    return module


class TenantSiteConstraintTests(unittest.TestCase):
    def test_identical_business_code_is_unique_only_inside_its_tenant_and_site(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in sqlite_schema_for({"svc_service_item"}):
            connection.execute(statement)

        connection.executemany(
            "INSERT INTO plat_tenant (tenant_id, tenant_code) VALUES (?, ?)",
            [("t1", "TENANT-1"), ("t2", "TENANT-2")],
        )
        connection.executemany(
            "INSERT INTO plat_site (tenant_id, site_id, site_code) VALUES (?, ?, ?)",
            [("t1", "s1", "SITE-1"), ("t1", "s2", "SITE-2"), ("t2", "s1", "SITE-1")],
        )
        connection.executemany(
            "INSERT INTO svc_service_item (tenant_id, site_id, service_id, service_code) VALUES (?, ?, ?, ?)",
            [
                ("t1", "s1", "service-1", "CONSULT"),
                ("t1", "s2", "service-2", "CONSULT"),
                ("t2", "s1", "service-3", "CONSULT"),
            ],
        )
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO svc_service_item (tenant_id, site_id, service_id, service_code) VALUES (?, ?, ?, ?)",
                ("t1", "s1", "service-4", "CONSULT"),
            )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM svc_service_item WHERE service_code = 'CONSULT'").fetchone()[0],
            3,
        )
        connection.close()

    def test_composite_foreign_key_rejects_a_parent_from_another_scope(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in sqlite_schema_for({"svc_service_version"}):
            connection.execute(statement)
        connection.executemany(
            "INSERT INTO plat_tenant (tenant_id, tenant_code) VALUES (?, ?)",
            [("t1", "TENANT-1"), ("t2", "TENANT-2")],
        )
        connection.executemany(
            "INSERT INTO plat_site (tenant_id, site_id, site_code) VALUES (?, ?, ?)",
            [("t1", "s1", "SITE-1"), ("t1", "s2", "SITE-2"), ("t2", "s1", "SITE-1")],
        )
        connection.executemany(
            "INSERT INTO svc_service_item (tenant_id, site_id, service_id, service_code) VALUES (?, ?, ?, ?)",
            [
                ("t1", "s1", "service-1", "CODE-1"),
                ("t1", "s2", "service-2", "CODE-2"),
                ("t2", "s1", "service-3", "CODE-3"),
            ],
        )

        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO svc_service_version (tenant_id, site_id, service_version_id, service_id, version_no) VALUES (?, ?, ?, ?, ?)",
                ("t1", "s1", "version-x", "service-2", "1"),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO svc_service_version (tenant_id, site_id, service_version_id, service_id, version_no) VALUES (?, ?, ?, ?, ?)",
                ("t1", "s1", "version-y", "service-3", "1"),
            )
        connection.close()

    def test_preflight_failure_happens_before_any_ddl(self) -> None:
        inspector = FakeInspector()
        bind = FakeBind(conflict=("unique", "svc_service_item"))
        operations = FakeOperations(inspector, bind)

        with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy_text_stub()}):
            with self.assertRaisesRegex(MIGRATION.MigrationPreconditionError, "duplicate rows"):
                MIGRATION.upgrade(operations=operations, inspector=inspector)

        self.assertEqual(operations.calls, [])
        self.assertTrue(bind.queries)

    def test_preflight_rejects_cross_scope_fk_orphans_before_any_ddl(self) -> None:
        inspector = FakeInspector()
        bind = FakeBind(conflict=("foreign_key", "svc_service_version"))
        operations = FakeOperations(inspector, bind)

        with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy_text_stub()}):
            with self.assertRaisesRegex(MIGRATION.MigrationPreconditionError, "missing same-scope FK"):
                MIGRATION.upgrade(operations=operations, inspector=inspector)

        self.assertEqual(operations.calls, [])

    def test_preflight_rejects_incomplete_schema_without_queries_or_ddl(self) -> None:
        inspector = FakeInspector(missing_table="svc_service_version")
        bind = FakeBind()
        operations = FakeOperations(inspector, bind)

        with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy_text_stub()}):
            with self.assertRaisesRegex(MIGRATION.MigrationPreconditionError, "missing tables"):
                MIGRATION.upgrade(operations=operations, inspector=inspector)

        self.assertEqual(bind.queries, [])
        self.assertEqual(operations.calls, [])

    def test_fake_upgrade_then_downgrade_rolls_back_revision_owned_objects(self) -> None:
        inspector = FakeInspector()
        operations = FakeOperations(inspector)

        with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy_text_stub()}):
            MIGRATION.upgrade(operations=operations, inspector=inspector)
            creates = list(operations.calls)
            self.assertTrue(any(call[0] == "create_unique" for call in creates))
            self.assertTrue(any(call[0] == "create_index" for call in creates))
            self.assertTrue(any(call[0] == "create_fk" for call in creates))

            MIGRATION.downgrade(operations=operations, inspector=inspector)
            drops = operations.calls[len(creates):]

        self.assertEqual(
            sum(call[0] == "create_unique" for call in creates),
            sum(call[0] == "drop_constraint" and call[3] == "unique" for call in drops),
        )
        self.assertEqual(
            sum(call[0] == "create_index" for call in creates),
            sum(call[0] == "drop_index" for call in drops),
        )
        self.assertEqual(
            sum(call[0] == "create_fk" for call in creates),
            sum(call[0] == "drop_constraint" and call[3] == "foreignkey" for call in drops),
        )
        self.assertTrue(all(not inspector.uniques[name] for name in inspector.entities))
        self.assertTrue(all(not inspector.indexes[name] for name in inspector.entities))
        self.assertTrue(all(not inspector.foreign_keys[name] for name in inspector.entities))

    def test_downgrade_conflict_is_found_before_any_drop(self) -> None:
        inspector = FakeInspector()
        table = "rpt_customer_service_summary"
        inspector.uniques[table].append(
            {
                "name": MIGRATION._unique_name(table, 0),
                "column_names": ("tenant_id", "site_id", "wrong_column"),
            }
        )
        operations = FakeOperations(inspector)

        with self.assertRaisesRegex(MIGRATION.MigrationPreconditionError, "conflicting reserved DB-03"):
            MIGRATION.downgrade(operations=operations, inspector=inspector)

        self.assertEqual(operations.calls, [])
        self.assertEqual(len(inspector.uniques[table]), 1)

    def test_module_import_is_side_effect_free_and_ddl_is_recorded_by_fake_operations(self) -> None:
        inspector = FakeInspector()
        operations = FakeOperations(inspector)
        self.assertEqual(operations.calls, [])
        self.assertFalse(hasattr(operations.bind, "connection"))

        with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy_text_stub()}):
            MIGRATION.upgrade(operations=operations, inspector=inspector)

        self.assertTrue(operations.calls)
        self.assertTrue(all(query.startswith("SELECT 1") for query in operations.bind.queries))
        self.assertFalse(hasattr(operations.bind, "connection"))


if __name__ == "__main__":
    unittest.main()
