"""Scoped, transactional appointment persistence for the DB-04 target model.

The repository accepts the DB-03 resolved scope object (tenant/site/principal)
and a SQLite connection for isolated tests or a SQLAlchemy Connection/Session in
an application. It never takes tenant_id or site_id from a request argument.
All booking writes, five-minute resource buckets, holds, and lock-history rows
share one transaction boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Any, Iterator, Mapping, Protocol
from uuid import uuid4

from .models import (
    AppointmentSnapshot,
    LOCK_BUCKET_MINUTES,
    ResourceAssignmentSnapshot,
    database_timestamp,
)


class ResolvedScopeLike(Protocol):
    tenant_id: str
    site_id: str
    principal_id: str


class AppointmentRepositoryError(RuntimeError):
    """Base class for safe appointment write failures."""


class ScopeMismatch(AppointmentRepositoryError):
    """A snapshot does not match the server-resolved repository scope."""


class ResourceConflict(AppointmentRepositoryError):
    """At least one requested resource bucket is occupied."""


class IdempotencyConflict(AppointmentRepositoryError):
    """An idempotency key was reused with a different request snapshot."""


class OptimisticConcurrencyError(AppointmentRepositoryError):
    """The supplied appointment version is stale or a conditional write lost."""


class HoldExpired(AppointmentRepositoryError):
    """The hold cannot be confirmed because its expiry has passed."""


@dataclass(frozen=True)
class BookingResult:
    appointment_id: str
    status: str
    version: int
    idempotent_replay: bool = False


def _row_mapping(row: Any) -> Mapping[str, Any] | None:
    if row is None:
        return None
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping
    if isinstance(row, Mapping):
        return row
    if isinstance(row, sqlite3.Row):
        return {key: row[key] for key in row.keys()}
    return row


def _integrity_error(error: Exception) -> bool:
    current: Any = error
    while current is not None:
        if isinstance(current, sqlite3.IntegrityError):
            return True
        if type(current).__name__ == "IntegrityError":
            return True
        current = getattr(current, "orig", None)
    return False


def _resource_lock_integrity_error(error: Exception) -> bool:
    current: Any = error
    while current is not None:
        message = str(current).lower()
        if "svc_resource_lock" in message or "uq_svc_lock_slot" in message:
            return True
        current = getattr(current, "orig", None)
    return False


class AppointmentRepository:
    """Persistence boundary for one immutable tenant/site authorization scope."""

    def __init__(
        self,
        connection: Any,
        scope: ResolvedScopeLike,
        *,
        id_factory: Any = None,
    ) -> None:
        tenant_id = getattr(scope, "tenant_id", None)
        site_id = getattr(scope, "site_id", None)
        principal_id = getattr(scope, "principal_id", None)
        if not tenant_id or not site_id or not principal_id:
            raise ScopeMismatch("a server-resolved tenant/site/principal scope is required")
        self._connection = connection
        self._tenant_id = tenant_id
        self._site_id = site_id
        self._actor_id = principal_id
        self._id_factory = id_factory or (lambda: str(uuid4()))

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Own a write transaction; SQLite uses IMMEDIATE to serialize writers."""
        connection = self._connection
        if isinstance(connection, sqlite3.Connection):
            if connection.in_transaction:
                savepoint = f"db04_{uuid4().hex}"
                connection.execute(f"SAVEPOINT {savepoint}")
                try:
                    yield
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception:
                    connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    raise
                return
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            return

        begin = getattr(connection, "begin", None)
        if not callable(begin):
            raise TypeError("connection must be sqlite3 or provide SQLAlchemy begin()/execute()")
        with begin():
            yield

    def _execute(self, sql: str, params: Mapping[str, Any] | None = None) -> Any:
        values = dict(params or {})
        if isinstance(self._connection, sqlite3.Connection):
            return self._connection.execute(sql, values)
        try:
            from sqlalchemy import text
        except ImportError:
            # Allows light fake connections in unit tests without installing SQLAlchemy.
            statement = sql
        else:
            statement = text(sql)
        return self._connection.execute(statement, values)

    def _assert_scope(self, snapshot: AppointmentSnapshot) -> None:
        if snapshot.tenant_id != self._tenant_id or snapshot.site_id != self._site_id:
            raise ScopeMismatch("appointment snapshot is outside the resolved tenant/site scope")

    def _one(self, sql: str, params: Mapping[str, Any]) -> Mapping[str, Any] | None:
        result = self._execute(sql, params)
        return _row_mapping(result.fetchone())

    @staticmethod
    def _affected(result: Any) -> int:
        count = getattr(result, "rowcount", None)
        return int(count) if count is not None else -1

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        current = value or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("timestamps passed to the appointment repository must be timezone-aware")
        return current.astimezone(timezone.utc)

    def _lookup_idempotency(self, snapshot: AppointmentSnapshot) -> BookingResult | None:
        params = {
            "tenant_id": self._tenant_id,
            "site_id": self._site_id,
            "idempotency_key": snapshot.idempotency_key,
        }
        existing = self._one(
            "SELECT appointment_id, status, version_no FROM svc_appointment "
            "WHERE tenant_id = :tenant_id AND site_id = :site_id "
            "AND idempotency_key = :idempotency_key",
            params,
        )
        if existing is None:
            return None
        context = self._one(
            "SELECT request_hash FROM svc_appointment_context "
            "WHERE tenant_id = :tenant_id AND site_id = :site_id "
            "AND appointment_id = :appointment_id",
            {**params, "appointment_id": existing["appointment_id"]},
        )
        if context is None or context["request_hash"] != snapshot.request_hash():
            raise IdempotencyConflict("idempotency key already represents a different booking request")
        return BookingResult(
            appointment_id=str(existing["appointment_id"]),
            status=str(existing["status"]),
            version=int(existing["version_no"]),
            idempotent_replay=True,
        )

    def create_hold(
        self,
        snapshot: AppointmentSnapshot,
        *,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> BookingResult:
        """Create the appointment snapshot, hold, assignments, and all locks atomically."""
        self._assert_scope(snapshot)
        current = self._now(now)
        expiry = self._now(expires_at)
        if expiry <= current:
            raise ValueError("hold expiry must be in the future")
        request_hash = snapshot.request_hash()
        timestamp = database_timestamp(current)
        expiry_value = database_timestamp(expiry)

        # Expiry is a whole-appointment transition: release an old hold and all
        # of its buckets before any one bucket can be recycled by a new request.
        # The scheduled worker calls the same operation; this scoped pass closes
        # the race when a new hold arrives before that worker runs.
        self.release_expired_holds(now=current, limit=10000)

        try:
            with self._transaction():
                replay = self._lookup_idempotency(snapshot)
                if replay is not None:
                    return replay
                appointment_params = {
                    "tenant_id": self._tenant_id,
                    "site_id": self._site_id,
                    "appointment_id": snapshot.appointment_id,
                    "customer_id": snapshot.customer_id,
                    "subject_customer_id": snapshot.subject_customer_id,
                    "service_version_id": snapshot.service_version_id,
                    "idempotency_key": snapshot.idempotency_key,
                    "status": "HELD",
                    "version_no": snapshot.row_version,
                    "starts_at": database_timestamp(snapshot.starts_at),
                    "ends_at": database_timestamp(snapshot.ends_at),
                    "hold_until": expiry_value,
                    "requested_at": timestamp,
                    "confirmed_at": None,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                self._execute(
                    "INSERT INTO svc_appointment "
                    "(tenant_id, site_id, appointment_id, customer_id, subject_customer_id, "
                    "service_version_id, idempotency_key, status, version_no, starts_at, ends_at, "
                    "hold_until, requested_at, confirmed_at, created_at, updated_at) VALUES "
                    "(:tenant_id, :site_id, :appointment_id, :customer_id, :subject_customer_id, "
                    ":service_version_id, :idempotency_key, :status, :version_no, :starts_at, :ends_at, "
                    ":hold_until, :requested_at, :confirmed_at, :created_at, :updated_at)",
                    appointment_params,
                )
                self._execute(
                    "INSERT INTO svc_appointment_context "
                    "(tenant_id, site_id, appointment_id, location_id, location_version, "
                    "capacity_policy_version, snapshot_version, row_version, request_hash, created_at, updated_at) "
                    "VALUES (:tenant_id, :site_id, :appointment_id, :location_id, :location_version, "
                    ":capacity_policy_version, :snapshot_version, :row_version, :request_hash, :created_at, :updated_at)",
                    {
                        "tenant_id": self._tenant_id,
                        "site_id": self._site_id,
                        "appointment_id": snapshot.appointment_id,
                        "location_id": snapshot.location_id,
                        "location_version": snapshot.location_version,
                        "capacity_policy_version": snapshot.capacity_policy_version,
                        "snapshot_version": snapshot.snapshot_version,
                        "row_version": 1,
                        "request_hash": request_hash,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )
                for requirement in snapshot.required_roles:
                    self._execute(
                        "INSERT INTO svc_appointment_resource_requirement "
                        "(tenant_id, site_id, appointment_id, role_code, required_count, "
                        "min_qualification_level, qualification_snapshot, service_rule_version, "
                        "status, row_version, created_at) VALUES (:tenant_id, :site_id, :appointment_id, "
                        ":role_code, :required_count, :min_qualification_level, :qualification_snapshot, "
                        ":service_rule_version, 'REQUIRED', 1, :created_at)",
                        {
                            "tenant_id": self._tenant_id,
                            "site_id": self._site_id,
                            "appointment_id": snapshot.appointment_id,
                            "role_code": requirement.role_code,
                            "required_count": requirement.required_count,
                            "min_qualification_level": requirement.min_qualification_level,
                            "qualification_snapshot": json.dumps(
                                requirement.qualification_snapshot,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            "service_rule_version": requirement.service_rule_version,
                            "created_at": timestamp,
                        },
                    )
                for assignment in snapshot.resources:
                    self._insert_assignment(snapshot, assignment, timestamp)

                hold_id = self._id_factory()
                self._execute(
                    "INSERT INTO svc_appointment_hold "
                    "(tenant_id, site_id, hold_id, appointment_id, idempotency_key, status, expires_at, "
                    "released_at, row_version, created_at, updated_at) VALUES "
                    "(:tenant_id, :site_id, :hold_id, :appointment_id, :idempotency_key, 'HELD', "
                    ":expires_at, NULL, 1, :created_at, :updated_at)",
                    {
                        "tenant_id": self._tenant_id,
                        "site_id": self._site_id,
                        "hold_id": hold_id,
                        "appointment_id": snapshot.appointment_id,
                        "idempotency_key": snapshot.idempotency_key,
                        "expires_at": expiry_value,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )

                for resource_id in snapshot.resource_ids:
                    for bucket in snapshot.buckets():
                        self._claim_bucket(
                            appointment_id=snapshot.appointment_id,
                            resource_id=resource_id,
                            bucket=bucket,
                            idempotency_hash=request_hash,
                            expires_at=expiry_value,
                            now=timestamp,
                        )
        except Exception as exc:
            if _integrity_error(exc):
                # A concurrent identical idempotent request may have committed
                # after our initial lookup. Resolve it after transaction rollback.
                try:
                    with self._transaction():
                        replay = self._lookup_idempotency(snapshot)
                except IdempotencyConflict:
                    raise
                if replay is not None:
                    return BookingResult(
                        replay.appointment_id,
                        replay.status,
                        replay.version,
                        idempotent_replay=True,
                    )
                if _resource_lock_integrity_error(exc):
                    raise ResourceConflict("a requested resource bucket is already occupied") from exc
                raise AppointmentRepositoryError("database rejected the scoped appointment write") from exc
            raise
        return BookingResult(snapshot.appointment_id, "HELD", snapshot.row_version)

    def _insert_assignment(
        self,
        snapshot: AppointmentSnapshot,
        assignment: ResourceAssignmentSnapshot,
        timestamp: str,
    ) -> None:
        self._execute(
            "INSERT INTO svc_appointment_resource_assignment "
            "(tenant_id, site_id, assignment_id, appointment_id, resource_id, resource_kind, "
            "role_code, staff_id, assignment_source, starts_at, ends_at, status, row_version, "
            "created_at, updated_at) VALUES (:tenant_id, :site_id, :assignment_id, :appointment_id, "
            ":resource_id, :resource_kind, :role_code, :staff_id, :assignment_source, :starts_at, "
            ":ends_at, 'LOCKED', 1, :created_at, :updated_at)",
            {
                "tenant_id": self._tenant_id,
                "site_id": self._site_id,
                "assignment_id": self._id_factory(),
                "appointment_id": snapshot.appointment_id,
                "resource_id": assignment.resource_id,
                "resource_kind": assignment.resource_kind,
                "role_code": assignment.role_code,
                "staff_id": assignment.staff_id,
                "assignment_source": assignment.assignment_source,
                "starts_at": database_timestamp(snapshot.starts_at),
                "ends_at": database_timestamp(snapshot.ends_at),
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )

    def _claim_bucket(
        self,
        *,
        appointment_id: str,
        resource_id: str,
        bucket: datetime,
        idempotency_hash: str,
        expires_at: str,
        now: str,
    ) -> None:
        params = {
            "tenant_id": self._tenant_id,
            "site_id": self._site_id,
            "resource_id": resource_id,
            "slot_start_utc": database_timestamp(bucket),
        }
        lock = self._one(
            "SELECT lock_id, appointment_id, status, lock_version, expires_at "
            "FROM svc_resource_lock WHERE tenant_id = :tenant_id AND site_id = :site_id "
            "AND resource_id = :resource_id AND slot_start_utc = :slot_start_utc",
            params,
        )
        if lock is None:
            lock_id = self._id_factory()
            self._execute(
                "INSERT INTO svc_resource_lock "
                "(tenant_id, site_id, lock_id, resource_id, slot_start_utc, appointment_id, "
                "idempotency_key_hash, status, lock_version, locked_at, expires_at, updated_at) "
                "VALUES (:tenant_id, :site_id, :lock_id, :resource_id, :slot_start_utc, "
                ":appointment_id, :idempotency_key_hash, 'LOCKED', 1, :locked_at, :expires_at, :updated_at)",
                {
                    **params,
                    "lock_id": lock_id,
                    "appointment_id": appointment_id,
                    "idempotency_key_hash": idempotency_hash,
                    "locked_at": now,
                    "expires_at": expires_at,
                    "updated_at": now,
                },
            )
            self._write_lock_history(
                lock_id=lock_id,
                resource_id=resource_id,
                appointment_id=appointment_id,
                lock_version=1,
                from_status="ABSENT",
                to_status="LOCKED",
                reason="HOLD_CREATED",
                occurred_at=now,
            )
            return

        status = str(lock["status"])
        lock_version = int(lock["lock_version"])
        old_appointment = str(lock["appointment_id"])
        expired_locked = (
            status == "LOCKED"
            and lock.get("expires_at") is not None
            and str(lock["expires_at"]) <= now
        )
        if status not in {"RELEASED", "EXPIRED"} and not expired_locked:
            raise ResourceConflict("a requested resource bucket is already occupied")

        if expired_locked:
            old_hold = self._one(
                "SELECT status FROM svc_appointment_hold WHERE tenant_id = :tenant_id "
                "AND site_id = :site_id AND appointment_id = :appointment_id",
                {"tenant_id": self._tenant_id, "site_id": self._site_id, "appointment_id": old_appointment},
            )
            if old_hold is not None and str(old_hold["status"]) == "HELD":
                raise ResourceConflict("the previous appointment hold must expire as a whole before lock reuse")
            self._write_lock_history(
                lock_id=str(lock["lock_id"]),
                resource_id=resource_id,
                appointment_id=old_appointment,
                lock_version=lock_version + 1,
                from_status="LOCKED",
                to_status="EXPIRED",
                reason="HOLD_EXPIRED",
                occurred_at=now,
            )
            expired = self._execute(
                "UPDATE svc_resource_lock SET status = 'EXPIRED', expires_at = NULL, "
                "lock_version = lock_version + 1, updated_at = :updated_at "
                "WHERE tenant_id = :tenant_id AND site_id = :site_id AND lock_id = :lock_id "
                "AND status = 'LOCKED' AND lock_version = :lock_version",
                {
                    **params,
                    "lock_id": lock["lock_id"],
                    "lock_version": lock_version,
                    "updated_at": now,
                },
            )
            self._require_one(expired, "expired resource lock changed concurrently")
            status = "EXPIRED"
            lock_version += 1

        next_version = lock_version + 1
        self._write_lock_history(
            lock_id=str(lock["lock_id"]),
            resource_id=resource_id,
            appointment_id=appointment_id,
            lock_version=next_version,
            from_status=status,
            to_status="LOCKED",
            reason="RESOURCE_RECLAIMED",
            occurred_at=now,
        )
        updated = self._execute(
            "UPDATE svc_resource_lock SET appointment_id = :appointment_id, "
            "idempotency_key_hash = :idempotency_key_hash, status = 'LOCKED', "
            "lock_version = :next_version, locked_at = :locked_at, expires_at = :expires_at, "
            "updated_at = :updated_at WHERE tenant_id = :tenant_id AND site_id = :site_id "
            "AND lock_id = :lock_id AND status = :old_status AND lock_version = :old_version",
            {
                **params,
                "appointment_id": appointment_id,
                "idempotency_key_hash": idempotency_hash,
                "next_version": next_version,
                "locked_at": now,
                "expires_at": expires_at,
                "updated_at": now,
                "lock_id": lock["lock_id"],
                "old_status": status,
                "old_version": lock_version,
            },
        )
        self._require_one(updated, "resource lock changed concurrently")

    def _write_lock_history(
        self,
        *,
        lock_id: str,
        resource_id: str,
        appointment_id: str,
        lock_version: int,
        from_status: str,
        to_status: str,
        reason: str,
        occurred_at: str,
    ) -> None:
        self._execute(
            "INSERT INTO svc_resource_lock_history "
            "(tenant_id, site_id, history_id, lock_id, resource_id, appointment_id, lock_version, "
            "from_status, to_status, reason_code, actor_id, occurred_at) VALUES "
            "(:tenant_id, :site_id, :history_id, :lock_id, :resource_id, :appointment_id, :lock_version, "
            ":from_status, :to_status, :reason_code, :actor_id, :occurred_at)",
            {
                "tenant_id": self._tenant_id,
                "site_id": self._site_id,
                "history_id": self._id_factory(),
                "lock_id": lock_id,
                "resource_id": resource_id,
                "appointment_id": appointment_id,
                "lock_version": lock_version,
                "from_status": from_status,
                "to_status": to_status,
                "reason_code": reason,
                "actor_id": self._actor_id,
                "occurred_at": occurred_at,
            },
        )

    @staticmethod
    def _require_one(result: Any, message: str) -> None:
        count = AppointmentRepository._affected(result)
        if count != 1:
            raise OptimisticConcurrencyError(message)

    def confirm(
        self,
        appointment_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> BookingResult:
        """Confirm appointment, hold, assignments, and all bucket locks atomically."""
        current = self._now(now)
        timestamp = database_timestamp(current)
        params = {
            "tenant_id": self._tenant_id,
            "site_id": self._site_id,
            "appointment_id": appointment_id,
        }
        with self._transaction():
            appointment = self._one(
                "SELECT status, version_no, starts_at, ends_at, idempotency_key, hold_until "
                "FROM svc_appointment WHERE tenant_id = :tenant_id AND site_id = :site_id "
                "AND appointment_id = :appointment_id",
                params,
            )
            if appointment is None:
                raise AppointmentRepositoryError("appointment was not found in this scope")
            if str(appointment["idempotency_key"]) != idempotency_key:
                raise IdempotencyConflict("confirmation key does not match the booking idempotency key")
            if str(appointment["status"]) == "CONFIRMED":
                return BookingResult(appointment_id, "CONFIRMED", int(appointment["version_no"]), True)
            if int(appointment["version_no"]) != expected_version:
                raise OptimisticConcurrencyError("appointment version does not match expected_version")
            if str(appointment["status"]) != "HELD" or str(appointment["hold_until"]) <= timestamp:
                raise HoldExpired("appointment hold is no longer confirmable")

            hold = self._one(
                "SELECT hold_id, status, expires_at, row_version FROM svc_appointment_hold "
                "WHERE tenant_id = :tenant_id AND site_id = :site_id AND appointment_id = :appointment_id",
                params,
            )
            if hold is None or str(hold["status"]) != "HELD" or str(hold["expires_at"]) <= timestamp:
                raise HoldExpired("appointment hold is no longer confirmable")

            starts_at = self._parse_db_time(appointment["starts_at"])
            ends_at = self._parse_db_time(appointment["ends_at"])
            bucket_count = len(self._buckets(starts_at, ends_at))
            assignment_result = self._execute(
                "SELECT COUNT(*) AS assignment_count FROM svc_appointment_resource_assignment "
                "WHERE tenant_id = :tenant_id AND site_id = :site_id AND appointment_id = :appointment_id",
                params,
            )
            assignment_count = int(_row_mapping(assignment_result.fetchone())["assignment_count"])
            expected_locks = assignment_count * bucket_count
            lock_rows = self._all(
                "SELECT lock_id, resource_id, status, lock_version, expires_at FROM svc_resource_lock "
                "WHERE tenant_id = :tenant_id AND site_id = :site_id AND appointment_id = :appointment_id "
                "ORDER BY resource_id, slot_start_utc",
                params,
            )
            if len(lock_rows) != expected_locks or not lock_rows:
                raise ResourceConflict("appointment does not own its complete resource bucket set")
            if any(
                str(row["status"]) != "LOCKED"
                or row["expires_at"] is None
                or str(row["expires_at"]) <= timestamp
                for row in lock_rows
            ):
                raise HoldExpired("one or more resource locks expired before confirmation")

            updated_appointment = self._execute(
                "UPDATE svc_appointment SET status = 'CONFIRMED', version_no = version_no + 1, "
                "confirmed_at = :confirmed_at, updated_at = :updated_at WHERE tenant_id = :tenant_id "
                "AND site_id = :site_id AND appointment_id = :appointment_id AND status = 'HELD' "
                "AND version_no = :expected_version AND hold_until > :now",
                {
                    **params,
                    "expected_version": expected_version,
                    "confirmed_at": timestamp,
                    "updated_at": timestamp,
                    "now": timestamp,
                },
            )
            self._require_one(updated_appointment, "appointment changed before confirmation")
            updated_hold = self._execute(
                "UPDATE svc_appointment_hold SET status = 'CONFIRMED', row_version = row_version + 1, "
                "updated_at = :updated_at WHERE tenant_id = :tenant_id AND site_id = :site_id "
                "AND hold_id = :hold_id AND status = 'HELD' AND row_version = :row_version AND expires_at > :now",
                {
                    **params,
                    "hold_id": hold["hold_id"],
                    "row_version": hold["row_version"],
                    "updated_at": timestamp,
                    "now": timestamp,
                },
            )
            self._require_one(updated_hold, "hold changed before confirmation")
            updated_context = self._execute(
                "UPDATE svc_appointment_context SET row_version = row_version + 1, updated_at = :updated_at "
                "WHERE tenant_id = :tenant_id AND site_id = :site_id AND appointment_id = :appointment_id",
                {**params, "updated_at": timestamp},
            )
            self._require_one(updated_context, "appointment context is missing")
            self._execute(
                "UPDATE svc_appointment_resource_assignment SET status = 'CONFIRMED', "
                "row_version = row_version + 1, updated_at = :updated_at WHERE tenant_id = :tenant_id "
                "AND site_id = :site_id AND appointment_id = :appointment_id AND status = 'LOCKED'",
                {**params, "updated_at": timestamp},
            )
            for lock in lock_rows:
                new_version = int(lock["lock_version"]) + 1
                self._write_lock_history(
                    lock_id=str(lock["lock_id"]),
                    resource_id=str(lock["resource_id"]),
                    appointment_id=appointment_id,
                    lock_version=new_version,
                    from_status="LOCKED",
                    to_status="CONFIRMED",
                    reason="APPOINTMENT_CONFIRMED",
                    occurred_at=timestamp,
                )
                updated_lock = self._execute(
                    "UPDATE svc_resource_lock SET status = 'CONFIRMED', lock_version = :new_version, "
                    "updated_at = :updated_at WHERE tenant_id = :tenant_id AND site_id = :site_id "
                    "AND lock_id = :lock_id AND appointment_id = :appointment_id AND status = 'LOCKED' "
                    "AND lock_version = :old_version AND expires_at > :now",
                    {
                        **params,
                        "lock_id": lock["lock_id"],
                        "old_version": lock["lock_version"],
                        "new_version": new_version,
                        "updated_at": timestamp,
                        "now": timestamp,
                    },
                )
                self._require_one(updated_lock, "resource lock changed before confirmation")

        return BookingResult(appointment_id, "CONFIRMED", expected_version + 1)

    def release_expired_holds(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        """Expire due holds and release every associated resource bucket atomically."""
        if limit < 1:
            raise ValueError("limit must be positive")
        current = self._now(now)
        timestamp = database_timestamp(current)
        scope = {"tenant_id": self._tenant_id, "site_id": self._site_id}
        released = 0
        with self._transaction():
            due = self._all(
                "SELECT hold_id, appointment_id, row_version FROM svc_appointment_hold "
                "WHERE tenant_id = :tenant_id AND site_id = :site_id AND status = 'HELD' "
                "AND expires_at <= :now ORDER BY expires_at, hold_id LIMIT :limit",
                {**scope, "now": timestamp, "limit": limit},
            )
            for hold in due:
                appointment_id = str(hold["appointment_id"])
                appointment = self._one(
                    "SELECT version_no, starts_at, ends_at, status FROM svc_appointment "
                    "WHERE tenant_id = :tenant_id AND site_id = :site_id AND appointment_id = :appointment_id",
                    {**scope, "appointment_id": appointment_id},
                )
                if appointment is None or str(appointment["status"]) != "HELD":
                    raise OptimisticConcurrencyError("held appointment and hold state are inconsistent")
                updated_hold = self._execute(
                    "UPDATE svc_appointment_hold SET status = 'EXPIRED', released_at = :released_at, "
                    "row_version = row_version + 1, updated_at = :updated_at WHERE tenant_id = :tenant_id "
                    "AND site_id = :site_id AND hold_id = :hold_id AND status = 'HELD' "
                    "AND row_version = :row_version AND expires_at <= :now",
                    {
                        **scope,
                        "hold_id": hold["hold_id"],
                        "row_version": hold["row_version"],
                        "released_at": timestamp,
                        "updated_at": timestamp,
                        "now": timestamp,
                    },
                )
                self._require_one(updated_hold, "hold changed during expiry release")
                updated_appointment = self._execute(
                    "UPDATE svc_appointment SET status = 'EXPIRED', version_no = version_no + 1, "
                    "updated_at = :updated_at WHERE tenant_id = :tenant_id AND site_id = :site_id "
                    "AND appointment_id = :appointment_id AND status = 'HELD' AND version_no = :version_no",
                    {
                        **scope,
                        "appointment_id": appointment_id,
                        "version_no": appointment["version_no"],
                        "updated_at": timestamp,
                    },
                )
                self._require_one(updated_appointment, "appointment changed during expiry release")

                starts_at = self._parse_db_time(appointment["starts_at"])
                ends_at = self._parse_db_time(appointment["ends_at"])
                assignment_result = self._execute(
                    "SELECT COUNT(*) AS assignment_count FROM svc_appointment_resource_assignment "
                    "WHERE tenant_id = :tenant_id AND site_id = :site_id AND appointment_id = :appointment_id",
                    {**scope, "appointment_id": appointment_id},
                )
                assignment_count = int(_row_mapping(assignment_result.fetchone())["assignment_count"])
                expected_locks = assignment_count * len(self._buckets(starts_at, ends_at))
                lock_rows = self._all(
                    "SELECT lock_id, resource_id, status, lock_version FROM svc_resource_lock "
                    "WHERE tenant_id = :tenant_id AND site_id = :site_id AND appointment_id = :appointment_id "
                    "ORDER BY resource_id, slot_start_utc",
                    {**scope, "appointment_id": appointment_id},
                )
                if len(lock_rows) != expected_locks or not lock_rows:
                    raise ResourceConflict("expired hold does not own a complete resource bucket set")
                self._require_one(
                    self._execute(
                        "UPDATE svc_appointment_context SET row_version = row_version + 1, updated_at = :updated_at "
                        "WHERE tenant_id = :tenant_id AND site_id = :site_id AND appointment_id = :appointment_id",
                        {**scope, "appointment_id": appointment_id, "updated_at": timestamp},
                    ),
                    "appointment context is missing during hold expiry",
                )
                self._execute(
                    "UPDATE svc_appointment_resource_assignment SET status = 'EXPIRED', "
                    "row_version = row_version + 1, updated_at = :updated_at WHERE tenant_id = :tenant_id "
                    "AND site_id = :site_id AND appointment_id = :appointment_id AND status = 'LOCKED'",
                    {**scope, "appointment_id": appointment_id, "updated_at": timestamp},
                )
                for lock in lock_rows:
                    if str(lock["status"]) != "LOCKED":
                        raise ResourceConflict("expired hold contains a non-locked resource bucket")
                    next_version = int(lock["lock_version"]) + 1
                    self._write_lock_history(
                        lock_id=str(lock["lock_id"]),
                        resource_id=str(lock["resource_id"]),
                        appointment_id=appointment_id,
                        lock_version=next_version,
                        from_status="LOCKED",
                        to_status="EXPIRED",
                        reason="HOLD_EXPIRED",
                        occurred_at=timestamp,
                    )
                    self._require_one(
                        self._execute(
                            "UPDATE svc_resource_lock SET status = 'EXPIRED', expires_at = NULL, "
                            "lock_version = :new_version, updated_at = :updated_at WHERE tenant_id = :tenant_id "
                            "AND site_id = :site_id AND lock_id = :lock_id AND appointment_id = :appointment_id "
                            "AND status = 'LOCKED' AND lock_version = :old_version",
                            {
                                **scope,
                                "lock_id": lock["lock_id"],
                                "appointment_id": appointment_id,
                                "old_version": lock["lock_version"],
                                "new_version": next_version,
                                "updated_at": timestamp,
                            },
                        ),
                        "resource lock changed during hold expiry",
                    )
                released += 1
        return released

    def _all(self, sql: str, params: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        result = self._execute(sql, params)
        return [mapped for row in result.fetchall() if (mapped := _row_mapping(row)) is not None]

    @staticmethod
    def _parse_db_time(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _buckets(start: datetime, end: datetime) -> tuple[datetime, ...]:
        delta = (end - start).total_seconds()
        if delta <= 0:
            return ()
        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        bucket = start.replace(
            minute=(start.minute // LOCK_BUCKET_MINUTES) * LOCK_BUCKET_MINUTES,
            second=0,
            microsecond=0,
        )
        step = timedelta(minutes=LOCK_BUCKET_MINUTES)
        values = []
        while bucket < end:
            values.append(bucket)
            bucket += step
        return tuple(values)
