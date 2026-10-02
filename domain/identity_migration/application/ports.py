"""Ports to trusted APP identity, adapter authentication, storage, and audit."""

from __future__ import annotations

from typing import Protocol

from ..domain.models import AuditRecord, ResolvedIdentityScope, TicketRecord, VerifiedAppSession


class AppSessionValidator(Protocol):
    def validate(self, credential: str) -> VerifiedAppSession | None: ...


class IdentityScopeResolver(Protocol):
    def resolve(self, session: VerifiedAppSession) -> ResolvedIdentityScope | None: ...


class MigrationBridgeStore(Protocol):
    def insert_ticket(self, record: TicketRecord, audit: AuditRecord) -> bool: ...

    def get_ticket(self, ticket_digest: str) -> TicketRecord | None: ...

    def consume_ticket(self, ticket_digest: str, now: float, audit: AuditRecord) -> bool: ...

    def revoke_ticket(self, ticket_digest: str, now: float, audit: AuditRecord) -> bool: ...

    def revoke_session_tickets(
        self, session_digest: str, now: float, audit: AuditRecord
    ) -> int: ...

    def expire_ticket(self, ticket_digest: str, now: float, audit: AuditRecord) -> bool: ...

    def exchange_legacy_once(
        self,
        token_digest: str,
        accepted_audit: AuditRecord,
        rejected_audit: AuditRecord,
    ) -> ResolvedIdentityScope | None: ...

    def append_audit(self, audit: AuditRecord) -> None: ...
