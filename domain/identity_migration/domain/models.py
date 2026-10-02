"""Immutable identity and lifecycle values for the migration bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class VerifiedAppSession:
    """A session returned by the trusted APP session validator, never request JSON."""

    session_id: str
    subject_id: str
    expires_at: float
    active: bool = True


@dataclass(frozen=True)
class TrustedAdapter:
    """Adapter identity injected by authenticated server middleware."""

    adapter_id: str
    audience: str
    allowed_route_origins: frozenset[tuple[str, str]] = frozenset()

    def __post_init__(self) -> None:
        normalized = frozenset(
            (route, origin.rstrip("/"))
            for route, origin in self.allowed_route_origins
        )
        object.__setattr__(self, "allowed_route_origins", normalized)


@dataclass(frozen=True)
class ResolvedIdentityScope:
    """Current authorization facts resolved from server-side identity sources."""

    principal_id: str
    tenant_id: str
    site_id: str
    subject_id: str
    relationship_id: str
    relationship_type: str
    relationship_status: str
    purpose_code: str
    consent_id: str
    consent_version: str
    consent_status: str
    field_scope: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        required = (
            "principal_id",
            "tenant_id",
            "site_id",
            "subject_id",
            "relationship_id",
            "relationship_type",
            "relationship_status",
            "purpose_code",
            "consent_id",
            "consent_version",
            "consent_status",
        )
        if any(not isinstance(getattr(self, name), str) or not getattr(self, name) for name in required):
            raise ValueError("resolved identity scope must contain every server-owned binding")
        object.__setattr__(self, "field_scope", frozenset(self.field_scope))

    def same_binding(self, other: "ResolvedIdentityScope") -> bool:
        """Compare every identity and authorization binding, including consent version."""

        return (
            self.principal_id,
            self.tenant_id,
            self.site_id,
            self.subject_id,
            self.relationship_id,
            self.relationship_type,
            self.relationship_status,
            self.purpose_code,
            self.consent_id,
            self.consent_version,
            self.consent_status,
            self.field_scope,
        ) == (
            other.principal_id,
            other.tenant_id,
            other.site_id,
            other.subject_id,
            other.relationship_id,
            other.relationship_type,
            other.relationship_status,
            other.purpose_code,
            other.consent_id,
            other.consent_version,
            other.consent_status,
            other.field_scope,
        )


TicketState = Literal["issued", "redeemed", "revoked", "expired"]


@dataclass(frozen=True)
class TicketRecord:
    """Private server-side ticket state. The opaque ticket itself is never stored."""

    ticket_digest: str
    session_digest: str
    audience: str
    route: str
    origin: str
    nonce_digest: str
    jti_digest: str
    scope: ResolvedIdentityScope
    issued_at: float
    expires_at: float
    state: TicketState = "issued"


@dataclass(frozen=True)
class AuditRecord:
    """Allowlisted, pseudonymous audit facts; no raw credentials or rejected values."""

    request_id: str
    correlation_id: str
    occurred_at: float
    event_type: str
    decision: Literal["accepted", "rejected"]
    reason: str
    service: str = "wish.identity_migration"
    actor_ref: str | None = None
    object_ref: str | None = None
    tenant_ref: str | None = None
    site_ref: str | None = None
    purpose_code: str | None = None
    policy_version: str = "migration-bridge-v1"
    affected_count: int | None = None
