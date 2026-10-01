from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE = Path(__file__).parents[1] / "scoped_repository.py"


@dataclass(frozen=True)
class Predicate:
    column: str
    value: object

    def matches(self, row: object) -> bool:
        return getattr(row, self.column) == self.value

    def __and__(self, other: "Predicate | CombinedPredicate") -> "CombinedPredicate":
        return CombinedPredicate((self, other))


@dataclass(frozen=True)
class CombinedPredicate:
    predicates: tuple[object, ...]

    def matches(self, row: object) -> bool:
        return all(predicate.matches(row) for predicate in self.predicates)

    def __and__(self, other: object) -> "CombinedPredicate":
        return CombinedPredicate(self.predicates + (other,))


class FakeColumn:
    def __init__(self, name: str, nullable: bool = False) -> None:
        self.name = name
        self.nullable = nullable

    def __eq__(self, value: object) -> object:  # type: ignore[override]
        if isinstance(value, FakeColumn):
            return self is value
        return Predicate(self.name, value)


class FakeColumns(dict[str, FakeColumn]):
    def __getattr__(self, name: str) -> FakeColumn:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error


class FakeSelect:
    def __init__(self, model: type[object]) -> None:
        self.model = model
        self.predicates: list[object] = []

    def where(self, *predicates: object) -> "FakeSelect":
        self.predicates.extend(predicates)
        return self


class FakeExecution:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> "FakeExecution":
        return self

    def all(self) -> list[object]:
        return self._rows

    def scalar_one_or_none(self) -> object | None:
        if len(self._rows) > 1:
            raise AssertionError("query returned more than one row")
        return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.statements: list[FakeSelect] = []
        self.added: list[object] = []

    def execute(self, statement: FakeSelect) -> FakeExecution:
        self.statements.append(statement)
        matched = [
            row
            for row in self.rows
            if all(predicate.matches(row) for predicate in statement.predicates)
        ]
        return FakeExecution(matched)

    def add(self, entity: object) -> None:
        self.added.append(entity)


def flatten_predicates(predicates: list[object]) -> list[Predicate]:
    flattened: list[Predicate] = []
    for predicate in predicates:
        if isinstance(predicate, CombinedPredicate):
            flattened.extend(flatten_predicates(list(predicate.predicates)))
        else:
            assert isinstance(predicate, Predicate)
            flattened.append(predicate)
    return flattened


def load_repository_module() -> types.ModuleType:
    sqlalchemy = types.ModuleType("sqlalchemy")
    sqlalchemy.select = FakeSelect  # type: ignore[attr-defined]
    spec = importlib.util.spec_from_file_location("db03_scoped_repository", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy, module.__name__: module}):
        spec.loader.exec_module(module)
    return module


class ScopedRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository_module = load_repository_module()

    def make_model(self, *, include_site: bool = True) -> type[object]:
        names = ["tenant_id", "record_id", "code"]
        if include_site:
            names.insert(1, "site_id")
        columns = FakeColumns({name: FakeColumn(name) for name in names})
        key_columns = names[:3] if include_site else names[:2]
        primary_key = SimpleNamespace(columns=[columns[name] for name in key_columns])
        table = SimpleNamespace(name="svc_service_item", c=columns, primary_key=primary_key)

        class Model:
            __table__ = table

            def __init__(self, **values: object) -> None:
                self.__dict__.update(values)

        return Model

    def make_scope(self, site_id: str = "site-a") -> object:
        module = self.repository_module
        decision = module.AuthorizationDecision(
            principal_id="principal-1",
            tenant_id="tenant-trusted",
            permitted_site_ids=frozenset({"site-a", "site-b"}),
            purpose="care-service",
            authorization_ref="grant-123",
        )
        return module.ResolvedScope.from_authorization(decision, site_id)

    def test_same_code_across_tenants_and_sites_is_returned_only_in_resolved_scope(self) -> None:
        model = self.make_model()
        rows = [
            model(tenant_id="tenant-trusted", site_id="site-a", record_id="a1", code="CARE"),
            model(tenant_id="tenant-trusted", site_id="site-b", record_id="b1", code="CARE"),
            model(tenant_id="tenant-other", site_id="site-a", record_id="c1", code="CARE"),
        ]
        session = FakeSession(rows)
        repo = self.repository_module.ScopedRepository(session, model, self.make_scope())

        found = repo.list({"code": "CARE"})

        self.assertEqual([row.record_id for row in found], ["a1"])
        predicates = flatten_predicates(session.statements[0].predicates)
        self.assertTrue(any(p.column == "tenant_id" and p.value == "tenant-trusted" for p in predicates))
        self.assertTrue(any(p.column == "site_id" and p.value == "site-a" for p in predicates))

    def test_lookup_cannot_return_same_local_id_from_another_scope(self) -> None:
        model = self.make_model()
        session = FakeSession(
            [
                model(tenant_id="tenant-other", site_id="site-a", record_id="same", code="X"),
                model(tenant_id="tenant-trusted", site_id="site-b", record_id="same", code="X"),
            ]
        )
        repo = self.repository_module.ScopedRepository(session, model, self.make_scope())

        self.assertIsNone(repo.get_by_id("same"))
        self.assertEqual(len(session.statements), 1)
        self.assertEqual(len(flatten_predicates(session.statements[0].predicates)), 3)

    def test_client_supplied_scope_filters_are_rejected(self) -> None:
        model = self.make_model()
        session = FakeSession([])
        repo = self.repository_module.ScopedRepository(session, model, self.make_scope())

        for name in ("tenant_id", "site_id"):
            with self.subTest(name=name), self.assertRaises(self.repository_module.ScopeDenied):
                repo.list({name: "client-value"})
        self.assertEqual(session.statements, [])

    def test_site_id_is_only_a_selector_checked_against_server_grant(self) -> None:
        module = self.repository_module
        decision = module.AuthorizationDecision(
            principal_id="principal-1",
            tenant_id="trusted-tenant",
            permitted_site_ids=frozenset({"authorized-site"}),
            purpose="care-service",
            authorization_ref="server-grant",
        )

        scope = module.ResolvedScope.from_authorization(decision, "authorized-site")
        self.assertEqual(scope.tenant_id, "trusted-tenant")
        self.assertEqual(scope.site_id, "authorized-site")
        with self.assertRaises(module.ScopeDenied):
            module.ResolvedScope.from_authorization(decision, "client-selected-site")
        with self.assertRaises(module.ScopeDenied):
            module.ResolvedScope.from_authorization(None, "authorized-site")

    def test_model_missing_a_required_scope_key_is_rejected(self) -> None:
        model = self.make_model(include_site=False)
        with self.assertRaises(self.repository_module.ScopeConfigurationError):
            self.repository_module.ScopedRepository(FakeSession([]), model, self.make_scope())


if __name__ == "__main__":
    unittest.main()
