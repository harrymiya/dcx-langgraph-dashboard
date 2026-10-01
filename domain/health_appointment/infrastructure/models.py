"""Framework-neutral appointment snapshots for the DB-04 target schema.

These are persistence-facing value objects, not a claim that the production
schema or booking API is deployed. Authorization scope comes from the existing
DB-03 server-resolved scope boundary; callers must not populate it from a DTO.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Mapping


LOCK_BUCKET_MINUTES = 5
SNAPSHOT_VERSION = 1
RESOURCE_KINDS = frozenset({"ROOM", "AREA", "DEVICE", "STAFF", "OTHER"})
ASSIGNMENT_SOURCES = frozenset({"MANUAL", "AUTO"})


class InvalidAppointmentSnapshot(ValueError):
    """An appointment snapshot is incomplete or internally inconsistent."""


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidAppointmentSnapshot(f"{name} is required")
    return value


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidAppointmentSnapshot(f"{name} must be a timezone-aware timestamp")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class RoleRequirementSnapshot:
    """Immutable service-version snapshot of one required staff role."""

    role_code: str
    required_count: int
    service_rule_version: int
    min_qualification_level: str | None = None
    qualification_snapshot: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required(self.role_code, "role_code")
        if self.required_count < 1:
            raise InvalidAppointmentSnapshot("required_count must be positive")
        if self.service_rule_version < 1:
            raise InvalidAppointmentSnapshot("service_rule_version must be positive")
        try:
            json.dumps(self.qualification_snapshot, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise InvalidAppointmentSnapshot("qualification_snapshot must be JSON serializable") from exc


@dataclass(frozen=True)
class ResourceAssignmentSnapshot:
    """One concrete resource assignment; STAFF rows also name the staff ID."""

    resource_id: str
    resource_kind: str
    assignment_source: str
    staff_id: str | None = None
    role_code: str | None = None

    def __post_init__(self) -> None:
        _required(self.resource_id, "resource_id")
        if self.resource_kind not in RESOURCE_KINDS:
            raise InvalidAppointmentSnapshot("unsupported resource_kind")
        if self.assignment_source not in ASSIGNMENT_SOURCES:
            raise InvalidAppointmentSnapshot("assignment_source must be MANUAL or AUTO")
        if self.resource_kind == "STAFF":
            _required(self.staff_id or "", "staff_id")
            _required(self.role_code or "", "role_code")
        elif self.staff_id is not None or self.role_code is not None:
            raise InvalidAppointmentSnapshot("only STAFF assignments may set staff_id or role_code")


@dataclass(frozen=True)
class AppointmentSnapshot:
    """Values frozen when a hold is created, including resource and role facts."""

    appointment_id: str
    tenant_id: str
    site_id: str
    customer_id: str
    subject_customer_id: str
    service_version_id: str
    location_id: str
    location_version: int
    starts_at: datetime
    ends_at: datetime
    idempotency_key: str
    resources: tuple[ResourceAssignmentSnapshot, ...]
    required_roles: tuple[RoleRequirementSnapshot, ...] = ()
    capacity_policy_version: int | None = None
    snapshot_version: int = SNAPSHOT_VERSION
    row_version: int = 1

    def __post_init__(self) -> None:
        for name in (
            "appointment_id",
            "tenant_id",
            "site_id",
            "customer_id",
            "subject_customer_id",
            "service_version_id",
            "location_id",
            "idempotency_key",
        ):
            _required(getattr(self, name), name)
        start = _utc(self.starts_at, "starts_at")
        end = _utc(self.ends_at, "ends_at")
        if end <= start:
            raise InvalidAppointmentSnapshot("ends_at must be after starts_at")
        object.__setattr__(self, "starts_at", start)
        object.__setattr__(self, "ends_at", end)
        object.__setattr__(self, "resources", tuple(self.resources))
        object.__setattr__(self, "required_roles", tuple(self.required_roles))
        if self.location_version < 1 or self.snapshot_version < 1 or self.row_version < 1:
            raise InvalidAppointmentSnapshot("snapshot and row versions must be positive")
        if self.capacity_policy_version is not None and self.capacity_policy_version < 1:
            raise InvalidAppointmentSnapshot("capacity_policy_version must be positive")
        if not self.resources:
            raise InvalidAppointmentSnapshot("at least one room, area, device, or staff resource is required")

        resource_ids = [assignment.resource_id for assignment in self.resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise InvalidAppointmentSnapshot("a resource may appear only once in an appointment snapshot")
        role_codes = [role.role_code for role in self.required_roles]
        if len(role_codes) != len(set(role_codes)):
            raise InvalidAppointmentSnapshot("required role codes must be unique")
        required = {role.role_code: role.required_count for role in self.required_roles}
        assigned: dict[str, int] = {code: 0 for code in required}
        for assignment in self.resources:
            if assignment.resource_kind == "STAFF":
                if assignment.role_code not in required:
                    raise InvalidAppointmentSnapshot("assigned staff role has no matching requirement snapshot")
                assigned[assignment.role_code] += 1
        if assigned != required:
            raise InvalidAppointmentSnapshot("assigned staff count must match every required role")

    @property
    def resource_ids(self) -> tuple[str, ...]:
        """Stable resource order used by the lock writer."""
        return tuple(sorted(assignment.resource_id for assignment in self.resources))

    def buckets(self) -> tuple[datetime, ...]:
        """UTC starts of all overlapping fixed five-minute buckets."""
        start = self.starts_at.replace(
            minute=(self.starts_at.minute // LOCK_BUCKET_MINUTES) * LOCK_BUCKET_MINUTES,
            second=0,
            microsecond=0,
        )
        step = timedelta(minutes=LOCK_BUCKET_MINUTES)
        buckets: list[datetime] = []
        current = start
        while current < self.ends_at:
            buckets.append(current)
            current += step
        return tuple(buckets)

    def request_hash(self) -> str:
        payload = {
            "tenant_id": self.tenant_id,
            "site_id": self.site_id,
            "customer_id": self.customer_id,
            "subject_customer_id": self.subject_customer_id,
            "service_version_id": self.service_version_id,
            "location_id": self.location_id,
            "location_version": self.location_version,
            "starts_at": self.starts_at.isoformat(timespec="milliseconds"),
            "ends_at": self.ends_at.isoformat(timespec="milliseconds"),
            "resources": [
                {
                    "resource_id": row.resource_id,
                    "resource_kind": row.resource_kind,
                    "assignment_source": row.assignment_source,
                    "staff_id": row.staff_id,
                    "role_code": row.role_code,
                }
                for row in sorted(self.resources, key=lambda item: item.resource_id)
            ],
            "required_roles": [
                {
                    "role_code": row.role_code,
                    "required_count": row.required_count,
                    "service_rule_version": row.service_rule_version,
                    "min_qualification_level": row.min_qualification_level,
                    "qualification_snapshot": row.qualification_snapshot,
                }
                for row in sorted(self.required_roles, key=lambda item: item.role_code)
            ],
            "capacity_policy_version": self.capacity_policy_version,
            "snapshot_version": self.snapshot_version,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def database_timestamp(value: datetime) -> str:
    """Format a UTC timestamp for DATETIME(3) / SQLite fixture columns."""
    normalized = _utc(value, "timestamp")
    return normalized.strftime("%Y-%m-%d %H:%M:%S.") + f"{normalized.microsecond // 1000:03d}"
