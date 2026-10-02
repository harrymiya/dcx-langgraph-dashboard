"""SQLite implementation of API-02 storage ports for isolated verification.

The default connection is in-memory. Production deployment must inject a store
with equivalent transaction/CAS guarantees and approved secret handling.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
import json
import sqlite3
from threading import RLock
from typing import Iterator

from ..domain.models import AuditRecord, ResolvedIdentityScope, TicketRecord


class SQLiteMigrationBridgeStore:
    """Atomic ticket/legacy-token fixture store using SQLite transactions."""

    def __init__(self, connection: sqlite3.Connection | None = None):
        self._connection = connection or sqlite3.connect(":memory:", check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        statements = (
            """CREATE TABLE IF NOT EXISTS migration_tickets (
                ticket_digest TEXT PRIMARY KEY,
                session_digest TEXT NOT NULL,
                audience TEXT NOT NULL,
                route TEXT NOT NULL,
                origin TEXT NOT NULL,
                nonce_digest TEXT NOT NULL UNIQUE,
                jti_digest TEXT NOT NULL UNIQUE,
                scope_json TEXT NOT NULL,
                issued_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('issued','redeemed','revoked','expired'))
            )""",
            "CREATE INDEX IF NOT EXISTS migration_tickets_by_session ON migration_tickets(session_digest, state)",
            """CREATE TABLE IF NOT EXISTS legacy_credentials (
                token_digest TEXT PRIMARY KEY,
                scope_json TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('active','consumed'))
            )""",
            """CREATE TABLE IF NOT EXISTS migration_audit (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                occurred_at REAL NOT NULL,
                event_type TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                service TEXT NOT NULL,
                actor_ref TEXT,
                object_ref TEXT,
                tenant_ref TEXT,
                site_ref TEXT,
                purpose_code TEXT,
                policy_version TEXT NOT NULL,
                affected_count INTEGER
            )""",
        )
        with self._lock:
            for statement in statements:
                self._connection.execute(statement)
            self._connection.commit()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def insert_ticket(self, record: TicketRecord, audit: AuditRecord) -> bool:
        try:
            with self._transaction() as connection:
                connection.execute(
                    """INSERT INTO migration_tickets
                    (ticket_digest,session_digest,audience,route,origin,nonce_digest,jti_digest,
                     scope_json,issued_at,expires_at,state)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        record.ticket_digest,
                        record.session_digest,
                        record.audience,
                        record.route,
                        record.origin,
                        record.nonce_digest,
                        record.jti_digest,
                        _scope_json(record.scope),
                        record.issued_at,
                        record.expires_at,
                        record.state,
                    ),
                )
                _insert_audit(connection, audit)
            return True
        except sqlite3.IntegrityError:
            return False

    def get_ticket(self, ticket_digest: str) -> TicketRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM migration_tickets WHERE ticket_digest=?", (ticket_digest,)
            ).fetchone()
        if row is None:
            return None
        return TicketRecord(
            ticket_digest=row["ticket_digest"],
            session_digest=row["session_digest"],
            audience=row["audience"],
            route=row["route"],
            origin=row["origin"],
            nonce_digest=row["nonce_digest"],
            jti_digest=row["jti_digest"],
            scope=_scope_from_json(row["scope_json"]),
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            state=row["state"],
        )

    def consume_ticket(self, ticket_digest: str, now: float, audit: AuditRecord) -> bool:
        with self._transaction() as connection:
            connection.execute(
                """UPDATE migration_tickets SET state='expired'
                WHERE ticket_digest=? AND state='issued' AND expires_at<=?""",
                (ticket_digest, now),
            )
            cursor = connection.execute(
                """UPDATE migration_tickets SET state='redeemed'
                WHERE ticket_digest=? AND state='issued' AND expires_at>?""",
                (ticket_digest, now),
            )
            if cursor.rowcount == 1:
                _insert_audit(connection, audit)
                return True
            return False

    def revoke_ticket(self, ticket_digest: str, now: float, audit: AuditRecord) -> bool:
        with self._transaction() as connection:
            connection.execute(
                """UPDATE migration_tickets SET state='expired'
                WHERE ticket_digest=? AND state='issued' AND expires_at<=?""",
                (ticket_digest, now),
            )
            cursor = connection.execute(
                """UPDATE migration_tickets SET state='revoked'
                WHERE ticket_digest=? AND state='issued' AND expires_at>?""",
                (ticket_digest, now),
            )
            if cursor.rowcount == 1:
                _insert_audit(connection, audit)
                return True
            return False

    def expire_ticket(self, ticket_digest: str, now: float, audit: AuditRecord) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE migration_tickets SET state='expired'
                WHERE ticket_digest=? AND state='issued' AND expires_at<=?""",
                (ticket_digest, now),
            )
            _insert_audit(connection, audit)
            return cursor.rowcount == 1

    def revoke_session_tickets(
        self, session_digest: str, now: float, audit: AuditRecord
    ) -> int:
        with self._transaction() as connection:
            connection.execute(
                """UPDATE migration_tickets SET state='expired'
                WHERE session_digest=? AND state='issued' AND expires_at<=?""",
                (session_digest, now),
            )
            cursor = connection.execute(
                """UPDATE migration_tickets SET state='revoked'
                WHERE session_digest=? AND state='issued' AND expires_at>?""",
                (session_digest, now),
            )
            count = cursor.rowcount
            _insert_audit(connection, replace(audit, affected_count=count))
            return count

    def exchange_legacy_once(
        self,
        token_digest: str,
        accepted_audit: AuditRecord,
        rejected_audit: AuditRecord,
    ) -> ResolvedIdentityScope | None:
        """Atomically invalidate an existing synthetic legacy credential."""

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT scope_json FROM legacy_credentials WHERE token_digest=? AND state='active'",
                (token_digest,),
            ).fetchone()
            if row is None:
                _insert_audit(connection, rejected_audit)
                return None
            cursor = connection.execute(
                """UPDATE legacy_credentials SET state='consumed'
                WHERE token_digest=? AND state='active'""",
                (token_digest,),
            )
            if cursor.rowcount != 1:
                _insert_audit(connection, rejected_audit)
                return None
            _insert_audit(connection, accepted_audit)
            return _scope_from_json(row["scope_json"])

    def append_audit(self, audit: AuditRecord) -> None:
        with self._transaction() as connection:
            _insert_audit(connection, audit)

    def load_synthetic_legacy_credential(
        self, token_digest: str, scope: ResolvedIdentityScope
    ) -> None:
        """Seed only an in-memory synthetic credential for unit tests."""

        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO legacy_credentials(token_digest,scope_json,state) VALUES (?,?, 'active')",
                (token_digest, _scope_json(scope)),
            )

    def synthetic_legacy_state(self, token_digest: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT state FROM legacy_credentials WHERE token_digest=?", (token_digest,)
            ).fetchone()
        return row["state"] if row else None

    def ticket_state(self, ticket_digest: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT state FROM migration_tickets WHERE ticket_digest=?", (ticket_digest,)
            ).fetchone()
        return row["state"] if row else None

    def audit_json(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM migration_audit ORDER BY audit_id"
            ).fetchall()
        return [
            {
                key: row[key]
                for key in (
                    "request_id", "correlation_id", "occurred_at", "event_type", "decision",
                    "reason", "service", "actor_ref", "object_ref", "tenant_ref", "site_ref",
                    "purpose_code", "policy_version", "affected_count",
                )
            }
            for row in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _scope_json(scope: ResolvedIdentityScope) -> str:
    value = asdict(scope)
    value["field_scope"] = sorted(scope.field_scope)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _scope_from_json(value: str) -> ResolvedIdentityScope:
    raw = json.loads(value)
    raw["field_scope"] = frozenset(raw["field_scope"])
    return ResolvedIdentityScope(**raw)


def _insert_audit(connection: sqlite3.Connection, audit: AuditRecord) -> None:
    connection.execute(
        """INSERT INTO migration_audit
        (request_id,correlation_id,occurred_at,event_type,decision,reason,service,actor_ref,
         object_ref,tenant_ref,site_ref,purpose_code,policy_version,affected_count)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            audit.request_id,
            audit.correlation_id,
            audit.occurred_at,
            audit.event_type,
            audit.decision,
            audit.reason,
            audit.service,
            audit.actor_ref,
            audit.object_ref,
            audit.tenant_ref,
            audit.site_ref,
            audit.purpose_code,
            audit.policy_version,
            audit.affected_count,
        ),
    )
