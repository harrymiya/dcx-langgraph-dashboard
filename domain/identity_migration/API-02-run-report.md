# API-02 implementation report

Date: 2026-10-02

## Scope

Implemented only the API-02 router and `domain/identity_migration/` layers. The router is framework-neutral and uses the API-01 v1 success/error envelopes, stable error codes, request metadata, and required `Idempotency-Key` validation. No API-01 OpenAPI or error catalog files were changed; API-01 owns those versioned contracts.

The injected APP session validator and identity resolver are the only sources for principal, tenant, site, subject, relationship, purpose, consent/version, and field scope. Request bodies accept only the route challenge and opaque bridge inputs. Exact route/origin/audience grants and an authenticated server-side adapter context bound to allowed route/origin pairs are required. The TTL is server-configured, capped at 120 seconds, and cannot outlive the APP session.

Tickets, nonces, jti values, APP session references, and legacy credentials are stored as keyed digests. SQLite `BEGIN IMMEDIATE` transactions atomically insert tickets, consume a ticket once, revoke pending tickets, consume a legacy credential once, and append minimal pseudonymous audit records. Redemption revalidates the APP session and the current identity/consent/relationship scope. APP logout must call `on_app_logout` before invalidating its session. The legacy credential store and identity ports are synthetic/injectable fixtures; no external identity service is connected.

The router exposes only bridge issue, redeem, legacy exchange, ticket revoke, and session-ticket revoke operations. It does not issue long-lived MAPP credentials or proxy Wish business operations. Selected MAPP migration pages remain on their existing MAPP server contract.

## Verification

| Check | Command | Exit | Result |
| --- | --- | ---: | --- |
| API-02 targeted tests | `PYTHONDONTWRITEBYTECODE=1 python3 -S -m unittest discover -s domain/identity_migration/tests -v` | 0 | 19 passed; includes concurrent single-use redemption, expiry, explicit/logout revoke, scope changes, legacy token single-use, API-01 envelope/errors, and audit redaction. |
| Baseline coverage gate | `python3 scripts/validate_plan_coverage.py --source-root /home/agent/code/jiankang_app_uniapp` | 0 | 6 PASS; 143 planned, 97/46 split, 58 bidirectional registry links, 35 MAPP + 13 Wish lanes, inventory mapping. |
| Tracked diff whitespace check | `git diff --check` | 0 | Clean. |
| New API-02 artifact whitespace scan | Python standard-library scan of `.py` and `.md` files under the two API-02 target roots | 0 | 13 files scanned; no trailing whitespace or missing final newlines. |

All tests use Python's standard library and synthetic in-memory SQLite fixtures. No production identity data, external services, database writes, MAPP changes, administrator authentication changes, task-state updates, progress updates, or Git commit/push were made.

## Runtime integration boundary

The production host must provide the real APP session validator, server-side scope resolver, authenticated adapter context, and a store with the same transaction guarantees. The host must call the logout hook before APP session invalidation and redact `Authorization`, `ticket`, `nonce`, and `legacyCredential` from HTTP request logs. The one-time bridge contract rejects redemption replays even when an API idempotency key is present.
