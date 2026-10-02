"""Application use cases for issuing, redeeming, and revoking migration tickets."""

from __future__ import annotations

from typing import Callable
import hashlib
import hmac
import secrets
import time

from exts.wish.api.contracts.errors import ErrorCode, WishAPIError
from exts.wish.api.contracts.envelope import AuthorizationContext

from ..domain.models import (
    AuditRecord,
    ResolvedIdentityScope,
    TicketRecord,
    TrustedAdapter,
    VerifiedAppSession,
)
from ..domain.policy import InvalidBridgeBinding, RouteGrant, RouteGrantRegistry, validate_nonce
from .ports import AppSessionValidator, IdentityScopeResolver, MigrationBridgeStore


HARD_MAX_TTL_SECONDS = 120
MIN_HASH_KEY_BYTES = 32
SERVICE_NAME = "wish.identity_migration"


class MigrationBridgeApplicationService:
    """Enforce server-resolved scope and single-use lifecycle at the Wish boundary."""

    def __init__(
        self,
        *,
        sessions: AppSessionValidator,
        scopes: IdentityScopeResolver,
        store: MigrationBridgeStore,
        route_grants: RouteGrantRegistry,
        hash_key: bytes,
        ttl_seconds: int = 60,
        clock: Callable[[], float] = time.time,
        policy_version: str = "migration-bridge-v1",
    ) -> None:
        if not isinstance(hash_key, bytes) or len(hash_key) < MIN_HASH_KEY_BYTES:
            raise ValueError("hash_key must contain at least 32 bytes")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
            raise ValueError("ttl_seconds must be an integer")
        if not 1 <= ttl_seconds <= HARD_MAX_TTL_SECONDS:
            raise ValueError(f"ttl_seconds must be between 1 and {HARD_MAX_TTL_SECONDS}")
        self._sessions = sessions
        self._scopes = scopes
        self._store = store
        self._route_grants = route_grants
        self._hash_key = hash_key
        self._ttl = ttl_seconds
        self._clock = clock
        self._policy_version = policy_version

    def issue(
        self,
        *,
        app_session_credential: str,
        adapter: TrustedAdapter | None,
        audience: str,
        route: str,
        origin: str,
        nonce: str,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, object]:
        now = self._clock()
        grant = self._require_grant(adapter, audience, route, origin, now, request_id, correlation_id)
        self._validate_nonce_or_reject(nonce, now, request_id, correlation_id)
        session, scope = self._resolve_current_scope(
            app_session_credential, now, request_id, correlation_id
        )
        return self._issue_for_scope(
            session=session,
            scope=scope,
            grant=grant,
            nonce=nonce,
            now=now,
            request_id=request_id,
            correlation_id=correlation_id,
            event_type="bridge.issue",
        )

    def exchange_legacy_and_issue(
        self,
        *,
        app_session_credential: str,
        legacy_credential: str,
        adapter: TrustedAdapter | None,
        audience: str,
        route: str,
        origin: str,
        nonce: str,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, object]:
        """Consume a legacy credential server-side before issuing a bridge."""

        now = self._clock()
        grant = self._require_grant(adapter, audience, route, origin, now, request_id, correlation_id)
        self._validate_nonce_or_reject(nonce, now, request_id, correlation_id)
        session, current_scope = self._resolve_current_scope(
            app_session_credential, now, request_id, correlation_id
        )
        if not isinstance(legacy_credential, str) or not 1 <= len(legacy_credential) <= 4096:
            self._reject(
                "legacy.exchange",
                "invalid_legacy_credential",
                now,
                request_id,
                correlation_id,
                scope=current_scope,
            )
            raise _api_error(ErrorCode.AUTH_REQUIRED, "Migration could not be authorized.")

        token_digest = self._digest("legacy", legacy_credential)
        accepted_audit = self._audit(
            "legacy.exchange",
            "accepted",
            "legacy_credential_consumed",
            now,
            request_id,
            correlation_id,
            scope=current_scope,
            object_digest=token_digest,
        )
        rejected_audit = self._audit(
            "legacy.exchange",
            "rejected",
            "legacy_credential_unavailable",
            now,
            request_id,
            correlation_id,
            scope=current_scope,
            object_digest=token_digest,
        )
        try:
            legacy_scope = self._store.exchange_legacy_once(
                token_digest, accepted_audit, rejected_audit
            )
        except Exception as exc:
            raise _dependency_error() from exc
        if legacy_scope is None or not legacy_scope.same_binding(current_scope):
            if legacy_scope is not None:
                self._reject(
                    "legacy.exchange",
                    "legacy_scope_mismatch",
                    now,
                    request_id,
                    correlation_id,
                    scope=current_scope,
                    object_digest=token_digest,
                )
            raise _api_error(ErrorCode.SCOPE_DENIED, "Migration could not be authorized.")
        return self._issue_for_scope(
            session=session,
            scope=current_scope,
            grant=grant,
            nonce=nonce,
            now=now,
            request_id=request_id,
            correlation_id=correlation_id,
            event_type="bridge.issue_from_legacy",
        )

    def redeem(
        self,
        *,
        app_session_credential: str,
        ticket: str,
        adapter: TrustedAdapter | None,
        audience: str,
        route: str,
        origin: str,
        nonce: str,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, object]:
        now = self._clock()
        grant = self._require_grant(adapter, audience, route, origin, now, request_id, correlation_id)
        self._validate_nonce_or_reject(nonce, now, request_id, correlation_id)
        if not isinstance(ticket, str) or not 32 <= len(ticket) <= 128:
            self._reject("bridge.redeem", "ticket_unavailable", now, request_id, correlation_id)
            raise _api_error(ErrorCode.AUTH_REQUIRED, "Migration could not be authorized.")
        ticket_digest = self._digest("ticket", ticket)
        try:
            record = self._store.get_ticket(ticket_digest)
        except Exception as exc:
            raise _dependency_error() from exc
        if record is None:
            self._reject(
                "bridge.redeem", "ticket_unavailable", now, request_id, correlation_id,
                object_digest=ticket_digest,
            )
            raise _api_error(ErrorCode.AUTH_REQUIRED, "Migration could not be authorized.")
        if now >= record.expires_at:
            audit = self._audit(
                "bridge.redeem", "rejected", "ticket_expired", now, request_id, correlation_id,
                scope=record.scope, object_digest=ticket_digest,
            )
            try:
                self._store.expire_ticket(ticket_digest, now, audit)
            except Exception as exc:
                raise _dependency_error() from exc
            raise _api_error(ErrorCode.AUTH_REQUIRED, "Migration could not be authorized.")

        if record.state != "issued":
            self._reject(
                "bridge.redeem",
                "replay_or_revocation",
                now,
                request_id,
                correlation_id,
                object_digest=ticket_digest,
            )
            raise _api_error(ErrorCode.AUTH_REQUIRED, "Migration could not be authorized.")

        try:
            session, scope = self._resolve_current_scope(
                app_session_credential, now, request_id, correlation_id
            )
        except WishAPIError as error:
            if error.code in {
                ErrorCode.AUTH_REQUIRED,
                ErrorCode.SCOPE_DENIED,
                ErrorCode.RELATIONSHIP_INVALID,
                ErrorCode.CONSENT_REQUIRED,
            }:
                audit = self._audit(
                    "bridge.revoke",
                    "rejected",
                    "current_scope_unavailable",
                    now,
                    request_id,
                    correlation_id,
                    scope=record.scope,
                    object_digest=ticket_digest,
                )
                try:
                    self._store.revoke_ticket(ticket_digest, now, audit)
                except Exception as exc:
                    raise _dependency_error() from exc
            raise
        expected_session_digest = self._digest("session", session.session_id)
        expected_nonce_digest = self._digest("nonce", nonce)
        binding_ok = (
            record.state == "issued"
            and record.session_digest == expected_session_digest
            and record.audience == grant.audience == adapter.audience
            and record.route == grant.route
            and record.origin == grant.origin
            and record.nonce_digest == expected_nonce_digest
            and record.scope.same_binding(scope)
        )
        if not binding_ok:
            self._reject(
                "bridge.redeem",
                "binding_mismatch",
                now,
                request_id,
                correlation_id,
                scope=scope,
                object_digest=ticket_digest,
            )
            # Any changed binding makes this bridge stale. Revocation is a CAS;
            # a concurrent valid redeemer can still win at most once.
            try:
                audit = self._audit(
                    "bridge.revoke", "rejected", "binding_mismatch", now, request_id,
                    correlation_id, scope=scope, object_digest=ticket_digest,
                )
                self._store.revoke_ticket(ticket_digest, now, audit)
            except Exception as exc:
                raise _dependency_error() from exc
            raise _api_error(ErrorCode.SCOPE_DENIED, "Migration could not be authorized.")

        audit = self._audit(
            "bridge.redeem", "accepted", "ticket_consumed", now, request_id,
            correlation_id, scope=scope, object_digest=ticket_digest,
        )
        try:
            consumed = self._store.consume_ticket(ticket_digest, now, audit)
        except Exception as exc:
            raise _dependency_error() from exc
        if not consumed:
            self._reject(
                "bridge.redeem", "replay_or_revocation", now, request_id, correlation_id,
                scope=scope, object_digest=ticket_digest,
            )
            raise _api_error(ErrorCode.AUTH_REQUIRED, "Migration could not be authorized.")
        return self._temporary_context(scope, min(record.expires_at, session.expires_at))

    def revoke_ticket(
        self,
        *,
        app_session_credential: str,
        ticket: str,
        request_id: str,
        correlation_id: str,
    ) -> bool:
        now = self._clock()
        session, scope = self._resolve_current_scope(
            app_session_credential, now, request_id, correlation_id
        )
        if not isinstance(ticket, str) or not 32 <= len(ticket) <= 128:
            self._reject("bridge.revoke", "ticket_unavailable", now, request_id, correlation_id, scope=scope)
            raise _api_error(ErrorCode.AUTH_REQUIRED, "Migration could not be authorized.")
        ticket_digest = self._digest("ticket", ticket)
        try:
            record = self._store.get_ticket(ticket_digest)
            if record is None or record.session_digest != self._digest("session", session.session_id):
                self._reject(
                    "bridge.revoke", "ticket_unavailable", now, request_id,
                    correlation_id, scope=scope, object_digest=ticket_digest,
                )
                raise _api_error(ErrorCode.AUTH_REQUIRED, "Migration could not be authorized.")
            if record.state != "issued":
                self._reject(
                    "bridge.revoke", "ticket_not_pending", now, request_id,
                    correlation_id, scope=scope, object_digest=ticket_digest,
                )
                return False
            audit = self._audit(
                "bridge.revoke", "accepted", "explicit_revocation", now,
                request_id, correlation_id, scope=scope, object_digest=ticket_digest,
            )
            revoked = self._store.revoke_ticket(ticket_digest, now, audit)
        except WishAPIError:
            raise
        except Exception as exc:
            raise _dependency_error() from exc
        if not revoked:
            self._reject(
                "bridge.revoke", "ticket_not_pending", now, request_id,
                correlation_id, scope=scope, object_digest=ticket_digest,
            )
        return revoked

    def revoke_session_for_logout(
        self, session: VerifiedAppSession, *, request_id: str, correlation_id: str
    ) -> int:
        """Logout hook: call with the trusted session before APP invalidates it."""

        now = self._clock()
        audit = self._audit(
            "bridge.logout_revoke",
            "accepted",
            "app_logout",
            now,
            request_id,
            correlation_id,
            scope=None,
            actor_subject=session.subject_id,
        )
        try:
            return self._store.revoke_session_tickets(
                self._digest("session", session.session_id), now, audit
            )
        except Exception as exc:
            raise _dependency_error() from exc

    def record_boundary_rejection(
        self, *, reason: str, request_id: str, correlation_id: str
    ) -> None:
        """Record a fixed router rejection category without request values."""

        allowed = {
            "route_not_found",
            "method_not_allowed",
            "request_fields_invalid",
            "session_header_invalid",
            "api_metadata_invalid",
            "idempotency_key_missing",
        }
        if reason not in allowed:
            raise ValueError("boundary audit reason is not allowlisted")
        self._reject(
            "bridge.request",
            reason,
            self._clock(),
            request_id,
            correlation_id,
        )

    def revoke_pending_for_session_credential(
        self, *, app_session_credential: str, request_id: str, correlation_id: str
    ) -> int:
        """Authenticated logout adapter hook; call before invalidating the APP session."""

        now = self._clock()
        session, scope = self._resolve_current_scope(
            app_session_credential, now, request_id, correlation_id
        )
        audit = self._audit(
            "bridge.logout_revoke",
            "accepted",
            "app_logout",
            now,
            request_id,
            correlation_id,
            scope=scope,
        )
        try:
            return self._store.revoke_session_tickets(
                self._digest("session", session.session_id), now, audit
            )
        except Exception as exc:
            raise _dependency_error() from exc

    def _issue_for_scope(
        self,
        *,
        session: VerifiedAppSession,
        scope: ResolvedIdentityScope,
        grant: RouteGrant,
        nonce: str,
        now: float,
        request_id: str,
        correlation_id: str,
        event_type: str,
    ) -> dict[str, object]:
        expiry = min(now + self._ttl, session.expires_at)
        if expiry <= now:
            self._reject(event_type, "session_expired", now, request_id, correlation_id, scope=scope)
            raise _api_error(ErrorCode.AUTH_REQUIRED, "APP session is not valid.")
        ticket = secrets.token_urlsafe(32)
        ticket_digest = self._digest("ticket", ticket)
        jti_digest = self._digest("jti", secrets.token_urlsafe(24))
        record = TicketRecord(
            ticket_digest=ticket_digest,
            session_digest=self._digest("session", session.session_id),
            audience=grant.audience,
            route=grant.route,
            origin=grant.origin,
            nonce_digest=self._digest("nonce", nonce),
            jti_digest=jti_digest,
            scope=scope,
            issued_at=now,
            expires_at=expiry,
        )
        audit = self._audit(
            event_type,
            "accepted",
            "ticket_issued",
            now,
            request_id,
            correlation_id,
            scope=scope,
            object_digest=ticket_digest,
        )
        try:
            stored = self._store.insert_ticket(record, audit)
        except Exception as exc:
            raise _dependency_error() from exc
        if not stored:
            self._reject(
                event_type,
                "nonce_reused_or_ticket_conflict",
                now,
                request_id,
                correlation_id,
                scope=scope,
                object_digest=ticket_digest,
            )
            raise _api_error(ErrorCode.IDEMPOTENCY_CONFLICT, "Migration challenge is no longer available.")
        return {"ticket": ticket, "expiresAt": _utc_iso(expiry)}

    def _require_grant(
        self,
        adapter: TrustedAdapter | None,
        audience: str,
        route: str,
        origin: str,
        now: float,
        request_id: str,
        correlation_id: str,
    ) -> RouteGrant:
        try:
            if adapter is None or not adapter.adapter_id or adapter.audience != audience:
                raise InvalidBridgeBinding("adapter audience is not trusted")
            grant = self._route_grants.require(route, origin, audience)
            if (grant.route, grant.origin) not in adapter.allowed_route_origins:
                raise InvalidBridgeBinding("adapter is not authorized for this route")
            return grant
        except (InvalidBridgeBinding, AttributeError, TypeError):
            self._reject("bridge.binding", "route_not_allowlisted", now, request_id, correlation_id)
            raise _api_error(ErrorCode.TOKEN_AUDIENCE_INVALID, "Migration route is not authorized.")

    def _validate_nonce_or_reject(
        self, nonce: str, now: float, request_id: str, correlation_id: str
    ) -> None:
        try:
            validate_nonce(nonce)
        except InvalidBridgeBinding:
            self._reject("bridge.binding", "challenge_invalid", now, request_id, correlation_id)
            raise _api_error(ErrorCode.VALIDATION_FAILED, "Migration challenge is invalid.")

    def _resolve_current_scope(
        self,
        credential: str,
        now: float,
        request_id: str,
        correlation_id: str,
    ) -> tuple[VerifiedAppSession, ResolvedIdentityScope]:
        if not isinstance(credential, str) or not credential or len(credential) > 4096:
            self._reject("session.validate", "app_session_invalid", now, request_id, correlation_id)
            raise _api_error(ErrorCode.AUTH_REQUIRED, "APP session is not valid.")
        try:
            session = self._sessions.validate(credential)
        except Exception as exc:
            self._reject("session.validate", "session_dependency_unavailable", now, request_id, correlation_id)
            raise _dependency_error() from exc
        if session is None or not session.active or session.expires_at <= now:
            self._reject("session.validate", "app_session_invalid", now, request_id, correlation_id)
            raise _api_error(ErrorCode.AUTH_REQUIRED, "APP session is not valid.")
        try:
            scope = self._scopes.resolve(session)
        except Exception as exc:
            self._reject(
                "scope.resolve", "identity_dependency_unavailable", now, request_id,
                correlation_id, actor_subject=session.subject_id,
            )
            raise _dependency_error() from exc
        if scope is None or scope.subject_id != session.subject_id:
            self._reject(
                "scope.resolve", "identity_mapping_unavailable", now, request_id,
                correlation_id, actor_subject=session.subject_id,
            )
            raise _api_error(ErrorCode.SCOPE_DENIED, "Migration identity is not authorized.")
        try:
            AuthorizationContext(
                principal_id=scope.principal_id,
                tenant_id=scope.tenant_id,
                site_id=scope.site_id,
                subject_id=scope.subject_id,
                purpose_code=scope.purpose_code,
                relationship_id=scope.relationship_id,
                consent_ids=(scope.consent_id,),
                field_scope=scope.field_scope,
            )
        except (TypeError, ValueError):
            self._reject(
                "scope.resolve", "field_scope_invalid", now, request_id,
                correlation_id, scope=scope,
            )
            raise _api_error(ErrorCode.FIELD_SCOPE_DENIED, "Migration identity is not authorized.")
        if scope.relationship_status.lower() != "active":
            self._reject("scope.resolve", "relationship_inactive", now, request_id, correlation_id, scope=scope)
            raise _api_error(ErrorCode.RELATIONSHIP_INVALID, "Migration relationship is not active.")
        if scope.consent_status.lower() not in {"active", "granted"}:
            self._reject("scope.resolve", "consent_inactive", now, request_id, correlation_id, scope=scope)
            raise _api_error(ErrorCode.CONSENT_REQUIRED, "Current consent is required.")
        return session, scope

    def _audit(
        self,
        event_type: str,
        decision: str,
        reason: str,
        now: float,
        request_id: str,
        correlation_id: str,
        *,
        scope: ResolvedIdentityScope | None = None,
        actor_subject: str | None = None,
        object_digest: str | None = None,
    ) -> AuditRecord:
        subject = scope.subject_id if scope is not None else actor_subject
        return AuditRecord(
            request_id=request_id,
            correlation_id=correlation_id,
            occurred_at=now,
            event_type=event_type,
            decision=decision,  # type: ignore[arg-type]
            reason=reason,
            service=SERVICE_NAME,
            actor_ref=self._pseudonym("actor", subject) if subject else None,
            object_ref=self._pseudonym("object", object_digest) if object_digest else None,
            tenant_ref=self._pseudonym("tenant", scope.tenant_id) if scope else None,
            site_ref=self._pseudonym("site", scope.site_id) if scope else None,
            purpose_code=scope.purpose_code if scope else None,
            policy_version=self._policy_version,
        )

    def _reject(
        self,
        event_type: str,
        reason: str,
        now: float,
        request_id: str,
        correlation_id: str,
        *,
        scope: ResolvedIdentityScope | None = None,
        actor_subject: str | None = None,
        object_digest: str | None = None,
    ) -> None:
        audit = self._audit(
            event_type,
            "rejected",
            reason,
            now,
            request_id,
            correlation_id,
            scope=scope,
            actor_subject=actor_subject,
            object_digest=object_digest,
        )
        try:
            self._store.append_audit(audit)
        except Exception as exc:
            raise _dependency_error() from exc

    def _digest(self, purpose: str, value: str) -> str:
        return hmac.new(self._hash_key, f"{purpose}\0{value}".encode(), hashlib.sha256).hexdigest()

    def _pseudonym(self, purpose: str, value: str) -> str:
        return self._digest(f"audit:{purpose}", value)[:24]

    @staticmethod
    def _temporary_context(scope: ResolvedIdentityScope, expires_at: float) -> dict[str, object]:
        return {
            "principalId": scope.principal_id,
            "tenantId": scope.tenant_id,
            "siteId": scope.site_id,
            "subjectId": scope.subject_id,
            "relationship": {"id": scope.relationship_id, "type": scope.relationship_type},
            "purposeCode": scope.purpose_code,
            "consent": {
                "id": scope.consent_id,
                "version": scope.consent_version,
                "status": scope.consent_status,
            },
            "fieldScope": sorted(scope.field_scope),
            "expiresAt": _utc_iso(expires_at),
        }


def _api_error(code: ErrorCode, message: str) -> WishAPIError:
    return WishAPIError(code, message)


def _dependency_error() -> WishAPIError:
    return WishAPIError(
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        "Migration service is temporarily unavailable.",
        retryable=True,
    )


def _utc_iso(value: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
