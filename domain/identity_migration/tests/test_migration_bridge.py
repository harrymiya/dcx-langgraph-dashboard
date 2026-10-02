from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Lock
import hashlib
import hmac
import json
import unittest

from exts.wish.api.identity.migration_session_router import (
    ISSUE_PATH,
    LEGACY_EXCHANGE_PATH,
    REDEEM_PATH,
    REVOKE_TICKET_PATH,
    MigrationSessionRouter,
)
from domain.identity_migration.application.service import (
    HARD_MAX_TTL_SECONDS,
    MigrationBridgeApplicationService,
)
from domain.identity_migration.domain.models import (
    ResolvedIdentityScope,
    TrustedAdapter,
    VerifiedAppSession,
)
from domain.identity_migration.domain.policy import RouteGrant, RouteGrantRegistry
from domain.identity_migration.infrastructure.sqlite_store import SQLiteMigrationBridgeStore


HASH_KEY = b"api02-test-only-hmac-key-material-000000000000000000000000"
SESSION_SECRET = "synthetic-app-session-secret-not-for-production"
LEGACY_SECRET = "synthetic-legacy-token-never-return-this"
AUDIENCE = "legacy-customer-adapter"
ROUTE = "/legacy/customer/profile"
ORIGIN = "https://legacy.example.test"
NONCE = "challenge_nonce_0123456789"


def synthetic_scope(**changes: object) -> ResolvedIdentityScope:
    values: dict[str, object] = {
        "principal_id": "principal-synthetic-17",
        "tenant_id": "tenant-synthetic-north",
        "site_id": "site-synthetic-riverside",
        "subject_id": "customer-synthetic-42",
        "relationship_id": "relationship-synthetic-8",
        "relationship_type": "customer-owner",
        "relationship_status": "active",
        "purpose_code": "customer-service-continuity",
        "consent_id": "consent-synthetic-3",
        "consent_version": "v4",
        "consent_status": "granted",
        "field_scope": frozenset({"customer.displayName", "customer.maskedPhone"}),
    }
    values.update(changes)
    return ResolvedIdentityScope(**values)  # type: ignore[arg-type]


class MutableClock:
    def __init__(self, value: float = 2_000_000_000.0):
        self.value = value
        self.lock = Lock()

    def __call__(self) -> float:
        with self.lock:
            return self.value

    def advance(self, seconds: float) -> None:
        with self.lock:
            self.value += seconds


class FakeSessionValidator:
    def __init__(self, session: VerifiedAppSession):
        self.session = session
        self.raise_error = False

    def validate(self, credential: str) -> VerifiedAppSession | None:
        if self.raise_error:
            raise RuntimeError("synthetic idp secret detail")
        if credential != SESSION_SECRET:
            return None
        return self.session


class FakeScopeResolver:
    def __init__(self, scope: ResolvedIdentityScope):
        self.scope = scope
        self.raise_error = False
        self.calls = 0

    def resolve(self, session: VerifiedAppSession) -> ResolvedIdentityScope | None:
        self.calls += 1
        if self.raise_error:
            raise RuntimeError("synthetic identity backend detail")
        return self.scope


class MigrationBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.session = VerifiedAppSession(
            session_id="server-session-ref-1",
            subject_id="customer-synthetic-42",
            expires_at=self.clock.value + 3600,
        )
        self.sessions = FakeSessionValidator(self.session)
        self.scopes = FakeScopeResolver(synthetic_scope())
        self.store = SQLiteMigrationBridgeStore()
        self.request_count = 0
        self.request_lock = Lock()
        self.service = MigrationBridgeApplicationService(
            sessions=self.sessions,
            scopes=self.scopes,
            store=self.store,
            route_grants=RouteGrantRegistry([RouteGrant(ROUTE, ORIGIN, AUDIENCE)]),
            hash_key=HASH_KEY,
            ttl_seconds=60,
            clock=self.clock,
        )
        self.router = MigrationSessionRouter(self.service)
        self.adapter = TrustedAdapter(
            "synthetic-legacy-adapter",
            AUDIENCE,
            frozenset({(ROUTE, ORIGIN)}),
        )

    def tearDown(self) -> None:
        self.store.close()

    def issue(self, nonce: str = NONCE):
        return self.router.dispatch(
            method="POST",
            path=ISSUE_PATH,
            headers=self.headers(),
            body={"audience": AUDIENCE, "route": ROUTE, "origin": ORIGIN, "nonce": nonce},
            trusted_adapter=self.adapter,
        )

    def redeem(self, ticket: str, *, nonce: str = NONCE, **overrides: str):
        body = {
            "ticket": ticket,
            "audience": AUDIENCE,
            "route": ROUTE,
            "origin": ORIGIN,
            "nonce": nonce,
        }
        body.update(overrides)
        return self.router.dispatch(
            method="POST",
            path=REDEEM_PATH,
            headers=self.headers(),
            body=body,
            trusted_adapter=self.adapter,
        )

    def headers(self) -> dict[str, str]:
        with self.request_lock:
            self.request_count += 1
            idempotency_key = f"api02-idem-{self.request_count}"
        return {
            "Authorization": f"Bearer {SESSION_SECRET}",
            "X-Request-Id": "api02-test-request-1",
            "X-Correlation-Id": "api02-test-correlation-1",
            "Idempotency-Key": idempotency_key,
        }

    def ticket_digest(self, ticket: str) -> str:
        return hmac.new(HASH_KEY, f"ticket\0{ticket}".encode(), hashlib.sha256).hexdigest()

    def legacy_digest(self, token: str) -> str:
        return hmac.new(HASH_KEY, f"legacy\0{token}".encode(), hashlib.sha256).hexdigest()

    def test_valid_issue_returns_opaque_ticket_then_single_use_temporary_context(self) -> None:
        issued = self.issue()
        self.assertEqual(issued.status, 200)
        self.assertEqual(set(issued.body), {"data", "meta", "error"})
        data = issued.body["data"]
        self.assertEqual(set(data), {"ticket", "expiresAt"})
        ticket = data["ticket"]
        self.assertIsInstance(ticket, str)
        self.assertNotIn("customer-synthetic-42", ticket)
        self.assertNotIn("tenant-synthetic", ticket)
        self.assertEqual(issued.headers["Cache-Control"], "no-store")
        self.assertIsNone(issued.body["error"])

        redeemed = self.redeem(ticket)
        self.assertEqual(redeemed.status, 200)
        context = redeemed.body["data"]
        self.assertEqual(context["tenantId"], "tenant-synthetic-north")
        self.assertEqual(context["siteId"], "site-synthetic-riverside")
        self.assertEqual(context["subjectId"], "customer-synthetic-42")
        self.assertEqual(context["relationship"]["id"], "relationship-synthetic-8")
        self.assertEqual(context["purposeCode"], "customer-service-continuity")
        self.assertEqual(context["consent"]["version"], "v4")
        self.assertEqual(self.store.ticket_state(self.ticket_digest(ticket)), "redeemed")

        replay = self.redeem(ticket)
        self.assertEqual(replay.status, 401)
        self.assertIsNone(replay.body["data"])
        self.assertEqual(replay.body["error"]["code"], "AUTH_REQUIRED")

    def test_client_cannot_supply_server_resolved_claims(self) -> None:
        before = self.scopes.calls
        response = self.router.dispatch(
            method="POST",
            path=ISSUE_PATH,
            headers=self.headers(),
            body={
                "audience": AUDIENCE,
                "route": ROUTE,
                "origin": ORIGIN,
                "nonce": NONCE,
                "tenantId": "attacker-tenant",
                "subjectId": "attacker-subject",
                "purposeCode": "attacker-purpose",
                "consent": "attacker-consent",
            },
            trusted_adapter=self.adapter,
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(response.body["error"]["code"], "BAD_REQUEST")
        self.assertNotIn("attacker", json.dumps(response.body))
        self.assertEqual(self.scopes.calls, before)

    def test_mutating_routes_require_api01_idempotency_and_reject_bad_api_version(self) -> None:
        no_key = self.router.dispatch(
            method="POST",
            path=ISSUE_PATH,
            headers={"Authorization": f"Bearer {SESSION_SECRET}"},
            body={"audience": AUDIENCE, "route": ROUTE, "origin": ORIGIN, "nonce": NONCE},
            trusted_adapter=self.adapter,
        )
        self.assertEqual(no_key.status, 400)
        self.assertEqual(no_key.body["error"]["code"], "IDEMPOTENCY_KEY_REQUIRED")
        self.assertIsNone(no_key.body["meta"]["idempotencyKey"])

        bad_version = self.router.dispatch(
            method="POST",
            path=ISSUE_PATH,
            headers={
                "Authorization": f"Bearer {SESSION_SECRET}",
                "Idempotency-Key": "api02-idem-bad-version",
                "X-Wish-API-Version": "v9",
            },
            body={"audience": AUDIENCE, "route": ROUTE, "origin": ORIGIN, "nonce": NONCE},
            trusted_adapter=self.adapter,
        )
        self.assertEqual(bad_version.status, 400)
        self.assertEqual(bad_version.body["error"]["code"], "API_VERSION_MISMATCH")

    def test_wrong_audience_route_or_origin_fails_closed(self) -> None:
        ticket = self.issue().body["data"]["ticket"]
        cases = (
            {"audience": "commerce-adapter"},
            {"route": "/legacy/other"},
            {"origin": "https://other.example.test"},
        )
        for change in cases:
            with self.subTest(change=change):
                response = self.redeem(ticket, **change)
                self.assertIn(response.status, (401, 403))
                self.assertIsNone(response.body["data"])
                self.assertNotIn("ticket", json.dumps(response.body))

        unauthorized_adapter = TrustedAdapter(
            "synthetic-other-route-adapter",
            AUDIENCE,
            frozenset({("/legacy/other", ORIGIN)}),
        )
        rejected = self.router.dispatch(
            method="POST",
            path=ISSUE_PATH,
            headers=self.headers(),
            body={"audience": AUDIENCE, "route": ROUTE, "origin": ORIGIN, "nonce": "adapter_nonce_0123456789"},
            trusted_adapter=unauthorized_adapter,
        )
        self.assertEqual(rejected.status, 401)

    def test_nonce_is_bound_and_cannot_be_reused_for_another_issue(self) -> None:
        ticket = self.issue().body["data"]["ticket"]
        bad_nonce = self.redeem(ticket, nonce="another_nonce_0123456789")
        self.assertEqual(bad_nonce.status, 403)
        self.assertEqual(self.store.ticket_state(self.ticket_digest(ticket)), "revoked")

        duplicate = self.issue()
        self.assertEqual(duplicate.status, 409)
        self.assertEqual(duplicate.body["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_expired_ticket_is_marked_expired_and_never_extended(self) -> None:
        issued = self.issue()
        ticket = issued.body["data"]["ticket"]
        self.clock.advance(60.001)
        response = self.redeem(ticket)
        self.assertEqual(response.status, 401)
        self.assertEqual(self.store.ticket_state(self.ticket_digest(ticket)), "expired")
        self.assertEqual(response.body["error"]["code"], "AUTH_REQUIRED")

    def test_explicit_ticket_revocation_and_logout_revoke_pending_tickets(self) -> None:
        first = self.issue(nonce="logout_nonce_0123456789").body["data"]["ticket"]
        revoked = self.router.dispatch(
            method="POST",
            path=REVOKE_TICKET_PATH,
            headers=self.headers(),
            body={"ticket": first},
            trusted_adapter=self.adapter,
        )
        self.assertEqual(revoked.status, 200)
        self.assertTrue(revoked.body["data"]["revoked"])
        self.assertEqual(self.redeem(first, nonce="logout_nonce_0123456789").status, 401)

        second = self.issue(nonce="logout_nonce_1123456789").body["data"]["ticket"]
        count = self.router.on_app_logout(session=self.session, headers=self.headers())
        self.assertEqual(count, 1)
        self.assertEqual(self.store.ticket_state(self.ticket_digest(second)), "revoked")
        self.assertEqual(self.redeem(second, nonce="logout_nonce_1123456789").status, 401)

    def test_redeem_requires_the_same_validated_app_session(self) -> None:
        ticket = self.issue().body["data"]["ticket"]
        response = self.router.dispatch(
            method="POST",
            path=REDEEM_PATH,
            headers={
                "Authorization": "Bearer invalid-session",
                "Idempotency-Key": "api02-idem-invalid-session",
            },
            body={"ticket": ticket, "audience": AUDIENCE, "route": ROUTE, "origin": ORIGIN, "nonce": NONCE},
            trusted_adapter=self.adapter,
        )
        self.assertEqual(response.status, 401)
        self.assertIsNone(response.body["data"])

    def test_each_identity_scope_change_denies_redeem(self) -> None:
        changes = (
            {"tenant_id": "tenant-synthetic-south"},
            {"site_id": "site-synthetic-lakeside"},
            {"relationship_id": "relationship-synthetic-other"},
            {"relationship_type": "customer-proxy"},
            {"relationship_status": "revoked"},
            {"purpose_code": "different-purpose"},
            {"consent_id": "consent-synthetic-other"},
            {"consent_version": "v5"},
            {"consent_status": "withdrawn"},
            {"field_scope": frozenset({"customer.displayName"})},
        )
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                self.scopes.scope = synthetic_scope()
                nonce = f"scope_nonce_{index:02d}_0123456789"
                ticket = self.issue(nonce).body["data"]["ticket"]
                self.scopes.scope = synthetic_scope(**change)
                response = self.redeem(ticket, nonce=nonce)
                self.assertIn(response.status, (403,))
                self.assertIsNone(response.body["data"])
                self.assertEqual(self.store.ticket_state(self.ticket_digest(ticket)), "revoked")

    def test_subject_mapping_change_is_denied_without_using_client_subject(self) -> None:
        ticket = self.issue().body["data"]["ticket"]
        self.scopes.scope = synthetic_scope(subject_id="different-customer")
        response = self.redeem(ticket)
        self.assertEqual(response.status, 403)
        self.assertIsNone(response.body["data"])

    def test_legacy_token_is_consumed_once_and_never_returned(self) -> None:
        self.store.load_synthetic_legacy_credential(
            self.legacy_digest(LEGACY_SECRET), synthetic_scope()
        )
        body = {
            "legacyCredential": LEGACY_SECRET,
            "audience": AUDIENCE,
            "route": ROUTE,
            "origin": ORIGIN,
            "nonce": NONCE,
        }
        first = self.router.dispatch(
            method="POST",
            path=LEGACY_EXCHANGE_PATH,
            headers=self.headers(),
            body=body,
            trusted_adapter=self.adapter,
        )
        self.assertEqual(first.status, 200)
        ticket = first.body["data"]["ticket"]
        self.assertNotEqual(ticket, LEGACY_SECRET)
        self.assertNotIn(LEGACY_SECRET, json.dumps(first.body))
        self.assertEqual(
            self.store.synthetic_legacy_state(self.legacy_digest(LEGACY_SECRET)), "consumed"
        )

        second = self.router.dispatch(
            method="POST",
            path=LEGACY_EXCHANGE_PATH,
            headers=self.headers(),
            body={**body, "nonce": "legacy_nonce_0123456789"},
            trusted_adapter=self.adapter,
        )
        self.assertEqual(second.status, 403)
        self.assertNotIn(LEGACY_SECRET, json.dumps(second.body))

    def test_legacy_scope_mismatch_consumes_old_token_and_fails_closed(self) -> None:
        self.store.load_synthetic_legacy_credential(
            self.legacy_digest(LEGACY_SECRET),
            synthetic_scope(tenant_id="tenant-synthetic-other"),
        )
        response = self.router.dispatch(
            method="POST",
            path=LEGACY_EXCHANGE_PATH,
            headers=self.headers(),
            body={
                "legacyCredential": LEGACY_SECRET,
                "audience": AUDIENCE,
                "route": ROUTE,
                "origin": ORIGIN,
                "nonce": NONCE,
            },
            trusted_adapter=self.adapter,
        )
        self.assertEqual(response.status, 403)
        self.assertIsNone(response.body["data"])
        self.assertEqual(
            self.store.synthetic_legacy_state(self.legacy_digest(LEGACY_SECRET)), "consumed"
        )

    def test_concurrent_redemption_consumes_jti_once(self) -> None:
        ticket = self.issue().body["data"]["ticket"]
        with ThreadPoolExecutor(max_workers=12) as pool:
            responses = list(pool.map(lambda _: self.redeem(ticket), range(12)))
        self.assertEqual(sum(response.status == 200 for response in responses), 1)
        self.assertTrue(all(response.status in (200, 401, 403) for response in responses))
        self.assertEqual(self.store.ticket_state(self.ticket_digest(ticket)), "redeemed")

    def test_audit_is_minimal_and_redacts_all_credentials_challenges_and_raw_ids(self) -> None:
        ticket = self.issue().body["data"]["ticket"]
        self.redeem(ticket)
        audit = json.dumps(self.store.audit_json(), sort_keys=True)
        for secret in (SESSION_SECRET, LEGACY_SECRET, ticket, NONCE, "server-session-ref-1"):
            self.assertNotIn(secret, audit)
        events = self.store.audit_json()
        self.assertTrue(all("policy_version" in event for event in events))
        self.assertTrue(all(event["request_id"] == "api02-test-request-1" for event in events))
        self.assertTrue(all(event["tenant_ref"] != "tenant-synthetic-north" for event in events))
        self.assertTrue(all(event["site_ref"] != "site-synthetic-riverside" for event in events))

    def test_session_or_identity_dependency_failure_returns_safe_api01_error(self) -> None:
        self.sessions.raise_error = True
        failed_session = self.issue()
        self.assertEqual(failed_session.status, 503)
        self.assertEqual(failed_session.body["error"]["code"], "DEPENDENCY_UNAVAILABLE")
        self.assertNotIn("synthetic idp secret detail", json.dumps(failed_session.body))
        self.assertEqual(failed_session.body["error"]["retryable"], True)

        self.sessions.raise_error = False
        self.scopes.raise_error = True
        failed_scope = self.issue(nonce="dependency_nonce_0123456789")
        self.assertEqual(failed_scope.status, 503)
        self.assertNotIn("synthetic identity backend detail", json.dumps(failed_scope.body))

    def test_inactive_relationship_or_consent_is_rejected(self) -> None:
        self.scopes.scope = synthetic_scope(relationship_status="suspended")
        relationship = self.issue()
        self.assertEqual(relationship.status, 403)
        self.assertEqual(relationship.body["error"]["code"], "RELATIONSHIP_INVALID")

        self.scopes.scope = synthetic_scope(consent_status="withdrawn")
        consent = self.issue(nonce="consent_nonce_0123456789")
        self.assertEqual(consent.status, 403)
        self.assertEqual(consent.body["error"]["code"], "CONSENT_REQUIRED")

    def test_server_resolved_field_scope_must_fit_api01_allowlist(self) -> None:
        self.scopes.scope = synthetic_scope(field_scope=frozenset({"healthRecord.fullText"}))
        response = self.issue()
        self.assertEqual(response.status, 403)
        self.assertEqual(response.body["error"]["code"], "FIELD_SCOPE_DENIED")
        self.assertNotIn("healthRecord.fullText", json.dumps(response.body))

    def test_no_long_lived_token_or_business_proxy_route_exists(self) -> None:
        issue = self.issue()
        self.assertEqual(set(issue.body["data"]), {"ticket", "expiresAt"})
        unknown = self.router.dispatch(
            method="POST",
            path="/api/wish/v1/appointments",
            headers=self.headers(),
            body={},
            trusted_adapter=self.adapter,
        )
        self.assertEqual(unknown.status, 404)
        self.assertEqual(unknown.body["error"]["code"], "RESOURCE_NOT_FOUND")
        reasons = [event["reason"] for event in self.store.audit_json()]
        self.assertIn("route_not_found", reasons)

    def test_ttl_is_server_bounded_and_ticket_expires_no_later_than_session(self) -> None:
        with self.assertRaises(ValueError):
            MigrationBridgeApplicationService(
                sessions=self.sessions,
                scopes=self.scopes,
                store=self.store,
                route_grants=RouteGrantRegistry([RouteGrant(ROUTE, ORIGIN, AUDIENCE)]),
                hash_key=HASH_KEY,
                ttl_seconds=HARD_MAX_TTL_SECONDS + 1,
                clock=self.clock,
            )
        self.sessions.session = replace(self.session, expires_at=self.clock.value + 10)
        issued = self.issue(nonce="shortsession_nonce_0123456789")
        self.assertEqual(issued.status, 200)
        self.assertTrue(issued.body["data"]["expiresAt"].endswith("Z"))
        self.clock.advance(10.001)
        self.assertEqual(
            self.redeem(
                issued.body["data"]["ticket"], nonce="shortsession_nonce_0123456789"
            ).status,
            401,
        )


if __name__ == "__main__":
    unittest.main()
