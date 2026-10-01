"""DB-04 transaction tests using only stdlib SQLite and synthetic rows."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from domain.health_appointment.infrastructure.models import (
    AppointmentSnapshot,
    InvalidAppointmentSnapshot,
    ResourceAssignmentSnapshot,
    RoleRequirementSnapshot,
)
from domain.health_appointment.infrastructure.repositories import (
    AppointmentRepository,
    IdempotencyConflict,
    ResourceConflict,
    ScopeMismatch,
)


SQLITE_FIXTURE_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE plat_site (
  tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, PRIMARY KEY (tenant_id, site_id)
);
CREATE TABLE crm_customer (
  tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL, PRIMARY KEY (tenant_id, customer_id)
);
CREATE TABLE plat_staff_identity (
  tenant_id TEXT NOT NULL, staff_id TEXT NOT NULL, PRIMARY KEY (tenant_id, staff_id)
);
CREATE TABLE svc_service_version (
  tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, service_version_id TEXT NOT NULL,
  PRIMARY KEY (tenant_id, site_id, service_version_id),
  FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT
);
CREATE TABLE svc_resource (
  tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, resource_id TEXT NOT NULL,
  PRIMARY KEY (tenant_id, site_id, resource_id),
  FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT
);
CREATE TABLE svc_location (
  tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, location_id TEXT NOT NULL,
  PRIMARY KEY (tenant_id, site_id, location_id),
  FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT
);
CREATE TABLE svc_appointment (
  tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, appointment_id TEXT NOT NULL,
  customer_id TEXT NOT NULL, subject_customer_id TEXT NOT NULL, service_version_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL, status TEXT NOT NULL, version_no INTEGER NOT NULL,
  starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, hold_until TEXT,
  requested_at TEXT NOT NULL, confirmed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, site_id, appointment_id), UNIQUE (tenant_id, idempotency_key),
  FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, customer_id) REFERENCES crm_customer (tenant_id, customer_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, subject_customer_id) REFERENCES crm_customer (tenant_id, customer_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, site_id, service_version_id)
    REFERENCES svc_service_version (tenant_id, site_id, service_version_id) ON DELETE RESTRICT
);
CREATE TABLE svc_appointment_context (
  tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, appointment_id TEXT NOT NULL, location_id TEXT NOT NULL,
  location_version INTEGER NOT NULL, capacity_policy_version INTEGER, snapshot_version INTEGER NOT NULL,
  row_version INTEGER NOT NULL, request_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, site_id, appointment_id),
  FOREIGN KEY (tenant_id, site_id, appointment_id)
    REFERENCES svc_appointment (tenant_id, site_id, appointment_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, site_id, location_id)
    REFERENCES svc_location (tenant_id, site_id, location_id) ON DELETE RESTRICT
);
CREATE TABLE svc_appointment_resource_requirement (
  tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, appointment_id TEXT NOT NULL, role_code TEXT NOT NULL,
  required_count INTEGER NOT NULL, min_qualification_level TEXT, qualification_snapshot TEXT NOT NULL,
  service_rule_version INTEGER NOT NULL, status TEXT NOT NULL, row_version INTEGER NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, site_id, appointment_id, role_code),
  FOREIGN KEY (tenant_id, site_id, appointment_id)
    REFERENCES svc_appointment (tenant_id, site_id, appointment_id) ON DELETE RESTRICT
);
CREATE TABLE svc_appointment_resource_assignment (
  tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, assignment_id TEXT NOT NULL, appointment_id TEXT NOT NULL,
  resource_id TEXT NOT NULL, resource_kind TEXT NOT NULL, role_code TEXT, staff_id TEXT,
  assignment_source TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
  status TEXT NOT NULL, row_version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, site_id, assignment_id),
  UNIQUE (tenant_id, site_id, appointment_id, resource_id),
  FOREIGN KEY (tenant_id, site_id, appointment_id)
    REFERENCES svc_appointment (tenant_id, site_id, appointment_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, site_id, resource_id)
    REFERENCES svc_resource (tenant_id, site_id, resource_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, staff_id) REFERENCES plat_staff_identity (tenant_id, staff_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, site_id, appointment_id, role_code)
    REFERENCES svc_appointment_resource_requirement (tenant_id, site_id, appointment_id, role_code)
    ON DELETE RESTRICT
);
CREATE TABLE svc_appointment_hold (
  tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, hold_id TEXT NOT NULL, appointment_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL, status TEXT NOT NULL, expires_at TEXT NOT NULL, released_at TEXT,
  row_version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, site_id, hold_id), UNIQUE (tenant_id, site_id, appointment_id),
  UNIQUE (tenant_id, site_id, idempotency_key),
  FOREIGN KEY (tenant_id, site_id, appointment_id)
    REFERENCES svc_appointment (tenant_id, site_id, appointment_id) ON DELETE RESTRICT
);
CREATE TABLE svc_resource_lock (
  tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, lock_id TEXT NOT NULL, resource_id TEXT NOT NULL,
  slot_start_utc TEXT NOT NULL, appointment_id TEXT NOT NULL, idempotency_key_hash TEXT NOT NULL,
  status TEXT NOT NULL, lock_version INTEGER NOT NULL, locked_at TEXT NOT NULL,
  expires_at TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, site_id, lock_id),
  UNIQUE (tenant_id, site_id, resource_id, slot_start_utc),
  FOREIGN KEY (tenant_id, site_id, resource_id)
    REFERENCES svc_resource (tenant_id, site_id, resource_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, site_id, appointment_id)
    REFERENCES svc_appointment (tenant_id, site_id, appointment_id) ON DELETE RESTRICT
);
CREATE TABLE svc_resource_lock_history (
  tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, history_id TEXT NOT NULL, lock_id TEXT NOT NULL,
  resource_id TEXT NOT NULL, appointment_id TEXT NOT NULL, lock_version INTEGER NOT NULL,
  from_status TEXT NOT NULL, to_status TEXT NOT NULL, reason_code TEXT NOT NULL,
  actor_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, site_id, history_id), UNIQUE (tenant_id, site_id, lock_id, lock_version),
  FOREIGN KEY (tenant_id, site_id, lock_id)
    REFERENCES svc_resource_lock (tenant_id, site_id, lock_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, site_id, resource_id)
    REFERENCES svc_resource (tenant_id, site_id, resource_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, site_id, appointment_id)
    REFERENCES svc_appointment (tenant_id, site_id, appointment_id) ON DELETE RESTRICT
);
"""


@dataclass(frozen=True)
class TestScope:
    tenant_id: str = "tenant-1"
    site_id: str = "site-1"
    principal_id: str = "staff-operator"


def open_connection(path: str = ":memory:") -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(SQLITE_FIXTURE_SCHEMA)
    connection.execute("INSERT INTO plat_site VALUES ('tenant-1', 'site-1')")
    connection.executemany(
        "INSERT INTO crm_customer VALUES (?, ?)",
        [("tenant-1", "customer-1"), ("tenant-1", "subject-1")],
    )
    connection.execute("INSERT INTO plat_staff_identity VALUES ('tenant-1', 'staff-1')")
    connection.execute("INSERT INTO svc_service_version VALUES ('tenant-1', 'site-1', 'service-v1')")
    connection.executemany(
        "INSERT INTO svc_resource VALUES ('tenant-1', 'site-1', ?)",
        [("room-1",), ("staff-resource-1",), ("a-device",), ("z-room",)],
    )
    connection.execute("INSERT INTO svc_location VALUES ('tenant-1', 'site-1', 'location-1')")
    connection.commit()


def make_snapshot(
    appointment_id: str = "appointment-1",
    idempotency_key: str = "idem-1",
    *,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    resources: tuple[ResourceAssignmentSnapshot, ...] | None = None,
    required_roles: tuple[RoleRequirementSnapshot, ...] | None = None,
    tenant_id: str = "tenant-1",
    site_id: str = "site-1",
) -> AppointmentSnapshot:
    start = starts_at or datetime(2026, 10, 2, 10, 2, tzinfo=timezone.utc)
    end = ends_at or datetime(2026, 10, 2, 10, 12, tzinfo=timezone.utc)
    return AppointmentSnapshot(
        appointment_id=appointment_id,
        tenant_id=tenant_id,
        site_id=site_id,
        customer_id="customer-1",
        subject_customer_id="subject-1",
        service_version_id="service-v1",
        location_id="location-1",
        location_version=3,
        starts_at=start,
        ends_at=end,
        idempotency_key=idempotency_key,
        resources=(
            resources if resources is not None else (
                ResourceAssignmentSnapshot("room-1", "ROOM", "AUTO"),
                ResourceAssignmentSnapshot("staff-resource-1", "STAFF", "AUTO", "staff-1", "therapist"),
            )
        ),
        required_roles=(
            required_roles if required_roles is not None else (
                RoleRequirementSnapshot("therapist", 1, 7, "senior", {"skill": "therapy-v2"}),
            )
        ),
        capacity_policy_version=5,
    )


class AppointmentRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.connection = open_connection()
        initialize(self.connection)
        self.repository = AppointmentRepository(self.connection, TestScope())

    def tearDown(self):
        self.connection.close()

    def test_snapshot_requires_complete_role_staff_and_utc_time_data(self):
        with self.assertRaisesRegex(InvalidAppointmentSnapshot, "assigned staff count"):
            make_snapshot(resources=(ResourceAssignmentSnapshot("room-1", "ROOM", "AUTO"),))

        naive = datetime(2026, 10, 2, 10, 0)
        with self.assertRaisesRegex(InvalidAppointmentSnapshot, "timezone-aware"):
            make_snapshot(starts_at=naive)

    def test_hold_locks_sorted_five_minute_buckets_and_confirm_is_atomic(self):
        snapshot = make_snapshot()
        expiry = datetime(2026, 10, 2, 10, 30, tzinfo=timezone.utc)
        created = self.repository.create_hold(snapshot, expires_at=expiry, now=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc))

        locks = self.connection.execute(
            "SELECT resource_id, slot_start_utc, status FROM svc_resource_lock "
            "WHERE tenant_id = 'tenant-1' AND site_id = 'site-1' ORDER BY resource_id, slot_start_utc"
        ).fetchall()
        self.assertEqual("HELD", created.status)
        self.assertEqual(6, len(locks))
        self.assertEqual(
            ["2026-10-02 10:00:00.000", "2026-10-02 10:05:00.000", "2026-10-02 10:10:00.000"],
            [row["slot_start_utc"] for row in locks[:3]],
        )
        self.assertEqual({"LOCKED"}, {row["status"] for row in locks})

        confirmed = self.repository.confirm(
            snapshot.appointment_id,
            expected_version=1,
            idempotency_key=snapshot.idempotency_key,
            now=datetime(2026, 10, 2, 9, 1, tzinfo=timezone.utc),
        )
        appointment = self.connection.execute(
            "SELECT status, version_no FROM svc_appointment WHERE appointment_id = ?",
            (snapshot.appointment_id,),
        ).fetchone()
        hold = self.connection.execute(
            "SELECT status, row_version FROM svc_appointment_hold WHERE appointment_id = ?",
            (snapshot.appointment_id,),
        ).fetchone()
        self.assertEqual(("CONFIRMED", 2), tuple(appointment))
        self.assertEqual(("CONFIRMED", 2), tuple(hold))
        self.assertEqual("CONFIRMED", confirmed.status)
        self.assertEqual({"CONFIRMED"}, {
            row[0] for row in self.connection.execute(
                "SELECT status FROM svc_resource_lock WHERE appointment_id = ?", (snapshot.appointment_id,)
            )
        })
        self.assertEqual(12, self.connection.execute(
            "SELECT COUNT(*) FROM svc_resource_lock_history WHERE appointment_id = ?",
            (snapshot.appointment_id,),
        ).fetchone()[0])

    def test_same_idempotency_request_replays_and_changed_payload_is_rejected(self):
        snapshot = make_snapshot()
        now = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
        first = self.repository.create_hold(
            snapshot,
            expires_at=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
            now=now,
        )
        replay = self.repository.create_hold(
            snapshot,
            expires_at=datetime(2026, 10, 2, 10, 5, tzinfo=timezone.utc),
            now=now,
        )
        self.assertEqual(first.appointment_id, replay.appointment_id)
        self.assertTrue(replay.idempotent_replay)
        self.assertEqual(1, self.connection.execute("SELECT COUNT(*) FROM svc_appointment").fetchone()[0])

        changed = replace(snapshot, location_version=4)
        with self.assertRaises(IdempotencyConflict):
            self.repository.create_hold(
                changed,
                expires_at=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
                now=now,
            )

    def test_expired_hold_releases_every_bucket_and_allows_reuse(self):
        snapshot = make_snapshot(starts_at=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
                                 ends_at=datetime(2026, 10, 2, 10, 10, tzinfo=timezone.utc))
        self.repository.create_hold(
            snapshot,
            expires_at=datetime(2026, 10, 2, 10, 3, tzinfo=timezone.utc),
            now=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
        )
        expired_count = self.repository.release_expired_holds(now=datetime(2026, 10, 2, 10, 4, tzinfo=timezone.utc))

        self.assertEqual(1, expired_count)
        self.assertEqual("EXPIRED", self.connection.execute(
            "SELECT status FROM svc_appointment WHERE appointment_id = ?", (snapshot.appointment_id,)
        ).fetchone()[0])
        self.assertEqual("EXPIRED", self.connection.execute(
            "SELECT status FROM svc_appointment_hold WHERE appointment_id = ?", (snapshot.appointment_id,)
        ).fetchone()[0])
        self.assertEqual({"EXPIRED"}, {
            row[0] for row in self.connection.execute(
                "SELECT status FROM svc_resource_lock WHERE appointment_id = ?", (snapshot.appointment_id,)
            )
        })

        replacement = make_snapshot("appointment-2", "idem-2", starts_at=snapshot.starts_at, ends_at=snapshot.ends_at)
        created = self.repository.create_hold(
            replacement,
            expires_at=datetime(2026, 10, 2, 10, 30, tzinfo=timezone.utc),
            now=datetime(2026, 10, 2, 10, 4, tzinfo=timezone.utc),
        )
        self.assertEqual("HELD", created.status)
        self.assertEqual(4, self.connection.execute(
            "SELECT COUNT(*) FROM svc_resource_lock WHERE appointment_id = ? AND status = 'LOCKED'",
            (replacement.appointment_id,),
        ).fetchone()[0])

    def test_new_hold_expires_prior_due_hold_before_reclaiming_any_bucket(self):
        previous = make_snapshot(
            "appointment-old",
            "idem-old",
            starts_at=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 10, 2, 10, 5, tzinfo=timezone.utc),
        )
        self.repository.create_hold(
            previous,
            expires_at=datetime(2026, 10, 2, 10, 3, tzinfo=timezone.utc),
            now=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
        )
        replacement = make_snapshot(
            "appointment-new",
            "idem-new",
            starts_at=previous.starts_at,
            ends_at=previous.ends_at,
        )

        self.repository.create_hold(
            replacement,
            expires_at=datetime(2026, 10, 2, 10, 30, tzinfo=timezone.utc),
            now=datetime(2026, 10, 2, 10, 4, tzinfo=timezone.utc),
        )

        self.assertEqual("EXPIRED", self.connection.execute(
            "SELECT status FROM svc_appointment WHERE appointment_id = ?", (previous.appointment_id,)
        ).fetchone()[0])
        self.assertEqual(2, self.connection.execute(
            "SELECT COUNT(*) FROM svc_resource_lock WHERE appointment_id = ? AND status = 'LOCKED'",
            (replacement.appointment_id,),
        ).fetchone()[0])
        self.assertEqual(6, self.connection.execute(
            "SELECT COUNT(*) FROM svc_resource_lock_history WHERE resource_id IN ('room-1','staff-resource-1')",
        ).fetchone()[0])

    def test_late_resource_conflict_rolls_back_prior_appointment_and_bucket_writes(self):
        occupied_start = "2026-10-02 10:00:00.000"
        self.connection.execute(
            "INSERT INTO svc_appointment VALUES "
            "('tenant-1','site-1','occupied','customer-1','subject-1','service-v1','occupied-idem',"
            "'CONFIRMED',2,'2026-10-02 10:00:00.000','2026-10-02 10:05:00.000',NULL,"
            "'2026-10-02 09:00:00.000','2026-10-02 09:00:00.000','2026-10-02 09:00:00.000','2026-10-02 09:00:00.000')"
        )
        self.connection.execute(
            "INSERT INTO svc_resource_lock VALUES "
            "('tenant-1','site-1','occupied-lock','z-room',?,'occupied','hash','CONFIRMED',1,"
            "'2026-10-02 09:00:00.000',NULL,'2026-10-02 09:00:00.000')",
            (occupied_start,),
        )
        self.connection.commit()
        snapshot = make_snapshot(
            resources=(
                ResourceAssignmentSnapshot("a-device", "DEVICE", "AUTO"),
                ResourceAssignmentSnapshot("z-room", "ROOM", "AUTO"),
            ),
            required_roles=(),
        )

        with self.assertRaises(ResourceConflict):
            self.repository.create_hold(
                snapshot,
                expires_at=datetime(2026, 10, 2, 10, 30, tzinfo=timezone.utc),
                now=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(0, self.connection.execute(
            "SELECT COUNT(*) FROM svc_appointment WHERE appointment_id = ?", (snapshot.appointment_id,)
        ).fetchone()[0])
        self.assertEqual(0, self.connection.execute(
            "SELECT COUNT(*) FROM svc_appointment_context WHERE appointment_id = ?", (snapshot.appointment_id,)
        ).fetchone()[0])
        self.assertEqual(0, self.connection.execute(
            "SELECT COUNT(*) FROM svc_appointment_hold WHERE appointment_id = ?", (snapshot.appointment_id,)
        ).fetchone()[0])
        self.assertEqual(0, self.connection.execute(
            "SELECT COUNT(*) FROM svc_appointment_resource_assignment WHERE appointment_id = ?",
            (snapshot.appointment_id,),
        ).fetchone()[0])
        self.assertEqual(0, self.connection.execute(
            "SELECT COUNT(*) FROM svc_resource_lock WHERE resource_id = 'a-device'"
        ).fetchone()[0])
        self.assertEqual(1, self.connection.execute(
            "SELECT COUNT(*) FROM svc_resource_lock WHERE lock_id = 'occupied-lock'"
        ).fetchone()[0])

    def test_concurrent_requests_cannot_claim_the_same_tenant_site_resource_bucket(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "db04.sqlite")
            setup = open_connection(db_path)
            initialize(setup)
            setup.close()
            barrier = threading.Barrier(2)
            results: list[str] = []
            errors: list[BaseException] = []

            def worker(index: int) -> None:
                connection = open_connection(db_path)
                try:
                    repository = AppointmentRepository(connection, TestScope())
                    snapshot = make_snapshot(
                        f"parallel-{index}",
                        f"parallel-idem-{index}",
                        starts_at=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
                        ends_at=datetime(2026, 10, 2, 10, 5, tzinfo=timezone.utc),
                    )
                    barrier.wait(timeout=5)
                    try:
                        repository.create_hold(
                            snapshot,
                            expires_at=datetime(2026, 10, 2, 10, 30, tzinfo=timezone.utc),
                            now=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
                        )
                        results.append("created")
                    except ResourceConflict:
                        results.append("conflict")
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    connection.close()

            workers = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
            for thread in workers:
                thread.start()
            for thread in workers:
                thread.join(timeout=10)
            self.assertFalse(any(thread.is_alive() for thread in workers), "worker did not finish")
            self.assertEqual([], errors)
            self.assertCountEqual(["created", "conflict"], results)

            verify = open_connection(db_path)
            try:
                self.assertEqual(1, verify.execute("SELECT COUNT(*) FROM svc_appointment").fetchone()[0])
                self.assertEqual(2, verify.execute("SELECT COUNT(*) FROM svc_resource_lock").fetchone()[0])
            finally:
                verify.close()

    def test_snapshot_outside_resolved_scope_is_rejected_before_write(self):
        with self.assertRaises(ScopeMismatch):
            self.repository.create_hold(
                make_snapshot(tenant_id="tenant-2"),
                expires_at=datetime(2026, 10, 2, 10, 30, tzinfo=timezone.utc),
                now=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(0, self.connection.execute("SELECT COUNT(*) FROM svc_appointment").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
