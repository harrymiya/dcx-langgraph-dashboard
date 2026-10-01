from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select


class ScopeDenied(PermissionError):
    """The caller has no server-resolved authorization for the requested scope."""


class ScopeConfigurationError(ValueError):
    """A model or repository cannot prove that it is scoped by tenant and site."""


@dataclass(frozen=True)
class AuthorizationDecision:
    """Output of the server-side authorization boundary, never a request DTO.

    The producer must have resolved principal, tenant, site, subject,
    relationship, purpose, consent, and field scope. The permitted site set is
    the resulting grant; a site ID supplied by a client is only a selector.
    """

    principal_id: str
    tenant_id: str
    permitted_site_ids: frozenset[str]
    purpose: str
    authorization_ref: str
    allowed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "permitted_site_ids", frozenset(self.permitted_site_ids))
        if not self.principal_id or not self.tenant_id or not self.purpose or not self.authorization_ref:
            raise ScopeDenied("authorization decision is incomplete")


@dataclass(frozen=True, init=False)
class ResolvedScope:
    """Immutable repository scope issued from a trusted authorization decision."""

    tenant_id: str
    site_id: str
    principal_id: str
    purpose: str
    authorization_ref: str

    @classmethod
    def from_authorization(
        cls,
        decision: AuthorizationDecision,
        requested_site_id: str,
    ) -> ResolvedScope:
        if not isinstance(decision, AuthorizationDecision) or not decision.allowed:
            raise ScopeDenied("a server-side authorization decision is required")
        if not requested_site_id or requested_site_id not in decision.permitted_site_ids:
            raise ScopeDenied("the requested site is outside the authorized site grant")

        scope = object.__new__(cls)
        object.__setattr__(scope, "tenant_id", decision.tenant_id)
        object.__setattr__(scope, "site_id", requested_site_id)
        object.__setattr__(scope, "principal_id", decision.principal_id)
        object.__setattr__(scope, "purpose", decision.purpose)
        object.__setattr__(scope, "authorization_ref", decision.authorization_ref)
        return scope


class ScopedRepository:
    """Minimal SQLAlchemy repository that always applies tenant and site scope.

    This base intentionally accepts only mapped business-fact models whose
    primary key and non-null columns include tenant_id and site_id. Tenant-only
    identity anchors require a separate object-level authorization path.
    """

    def __init__(self, session: Any, model: type[Any], scope: ResolvedScope) -> None:
        if not isinstance(scope, ResolvedScope):
            raise ScopeDenied("repository access requires a ResolvedScope")
        table = getattr(model, "__table__", None)
        if table is None or not hasattr(table, "c"):
            raise ScopeConfigurationError("repository model must be a mapped SQLAlchemy entity")
        for name in ("tenant_id", "site_id"):
            column = table.c.get(name)
            if column is None:
                raise ScopeConfigurationError(f"{table.name} is missing required scope column {name}")
            if column.nullable:
                raise ScopeConfigurationError(f"{table.name}.{name} must be NOT NULL")
            if column not in table.primary_key.columns:
                raise ScopeConfigurationError(f"{table.name}.{name} must be part of the scoped primary key")

        local_keys = [
            column
            for column in table.primary_key.columns
            if column.name not in {"tenant_id", "site_id"}
        ]
        if len(local_keys) != 1:
            raise ScopeConfigurationError(
                f"{table.name} must have one local identifier in addition to tenant/site"
            )

        self._session = session
        self._model = model
        self._table = table
        self._scope = scope
        self._local_key = local_keys[0]

    def _scope_predicate(self) -> Any:
        return (
            (self._table.c.tenant_id == self._scope.tenant_id)
            & (self._table.c.site_id == self._scope.site_id)
        )

    def _filters(self, filters: Mapping[str, Any] | None) -> list[Any]:
        predicates: list[Any] = []
        for name, value in (filters or {}).items():
            if name in {"tenant_id", "site_id"}:
                raise ScopeDenied("tenant_id and site_id come only from the resolved authorization scope")
            column = self._table.c.get(name)
            if column is None:
                raise ScopeConfigurationError(f"{self._table.name} has no filterable column {name}")
            predicates.append(column == value)
        return predicates

    def list(self, filters: Mapping[str, Any] | None = None) -> list[Any]:
        """Return rows matching optional local filters inside this exact scope."""
        statement = select(self._model).where(self._scope_predicate(), *self._filters(filters))
        return list(self._session.execute(statement).scalars().all())

    def get_by_id(self, record_id: str) -> Any | None:
        """Resolve one local ID without accepting tenant/site from the caller."""
        statement = select(self._model).where(
            self._scope_predicate(),
            self._local_key == record_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def add(self, values: Mapping[str, Any]) -> Any:
        """Create a fact with scope copied from the trusted server decision."""
        payload = dict(values)
        for name, trusted_value in (
            ("tenant_id", self._scope.tenant_id),
            ("site_id", self._scope.site_id),
        ):
            supplied = payload.get(name)
            if supplied is not None and supplied != trusted_value:
                raise ScopeDenied(f"supplied {name} does not match the authorized scope")
            payload[name] = trusted_value

        entity = self._model(**payload)
        self._session.add(entity)
        return entity
