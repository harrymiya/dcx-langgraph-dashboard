"""DB-04 appointment context, required-role assignments, holds, and lock history.

The canonical ``svc_appointment`` and ``svc_resource_lock`` tables remain the
only booking and slot-lock write masters. This revision adds scoped snapshots
around those facts; it does not create parallel reservation or lock tables.
The five-minute bucket key is the DB-02 unique key on
``svc_resource_lock(tenant_id, site_id, resource_id, slot_start_utc)``.

DDL targets MySQL/MariaDB and must be reviewed against the deployed version
before use. Tests pass fake operations and never execute these statements.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


revision = "db04_health_appointment_resources"
down_revision = "db03_tenant_site_constraints"
branch_labels = None
depends_on = None

LOCK_SLOT_UNIQUE_KEY = (
    "tenant_id",
    "site_id",
    "resource_id",
    "slot_start_utc",
)
APPOINTMENT_IDEMPOTENCY_KEY = ("tenant_id", "idempotency_key")
LOCK_EXPIRY_INDEX = "ix_db04_resource_lock_expiry"

REQUIRED_BASE_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "plat_site": ("tenant_id", "site_id"),
    "crm_customer": ("tenant_id", "customer_id"),
    "plat_staff_identity": ("tenant_id", "staff_id"),
    "svc_service_version": ("tenant_id", "site_id", "service_version_id"),
    "svc_resource": ("tenant_id", "site_id", "resource_id"),
    "svc_appointment": (
        "tenant_id",
        "site_id",
        "appointment_id",
        "customer_id",
        "subject_customer_id",
        "service_version_id",
        "idempotency_key",
        "status",
        "version_no",
        "starts_at",
        "ends_at",
        "hold_until",
        "requested_at",
        "confirmed_at",
        "created_at",
        "updated_at",
    ),
    "svc_resource_lock": (
        "tenant_id",
        "site_id",
        "lock_id",
        "resource_id",
        "slot_start_utc",
        "appointment_id",
        "idempotency_key_hash",
        "status",
        "lock_version",
        "locked_at",
        "expires_at",
        "updated_at",
    ),
}

REQUIRED_PRIMARY_KEYS: Mapping[str, tuple[str, ...]] = {
    "plat_site": ("tenant_id", "site_id"),
    "crm_customer": ("tenant_id", "customer_id"),
    "plat_staff_identity": ("tenant_id", "staff_id"),
    "svc_service_version": ("tenant_id", "site_id", "service_version_id"),
    "svc_resource": ("tenant_id", "site_id", "resource_id"),
    "svc_appointment": ("tenant_id", "site_id", "appointment_id"),
    "svc_resource_lock": ("tenant_id", "site_id", "lock_id"),
}

TABLE_DDL: Mapping[str, str] = {
    "svc_location": r"""
CREATE TABLE svc_location (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  location_id CHAR(36) NOT NULL,
  parent_location_id CHAR(36) NULL,
  location_code VARCHAR(64) NOT NULL,
  location_type VARCHAR(32) NOT NULL,
  status VARCHAR(16) NOT NULL,
  location_version INT NOT NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, location_id),
  UNIQUE KEY uq_d04_location_code (tenant_id, site_id, location_code),
  CONSTRAINT fk_d04_location_site FOREIGN KEY (tenant_id, site_id)
    REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_d04_location_parent FOREIGN KEY
    (tenant_id, site_id, parent_location_id)
    REFERENCES svc_location (tenant_id, site_id, location_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""",
    "svc_appointment_context": r"""
CREATE TABLE svc_appointment_context (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  appointment_id CHAR(36) NOT NULL,
  location_id CHAR(36) NOT NULL,
  location_version INT NOT NULL,
  capacity_policy_version INT NULL,
  snapshot_version INT NOT NULL,
  row_version INT NOT NULL,
  request_hash CHAR(64) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, appointment_id),
  KEY ix_d04_context_location (tenant_id, site_id, location_id),
  CONSTRAINT fk_d04_context_appointment FOREIGN KEY
    (tenant_id, site_id, appointment_id)
    REFERENCES svc_appointment (tenant_id, site_id, appointment_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_d04_context_location FOREIGN KEY
    (tenant_id, site_id, location_id)
    REFERENCES svc_location (tenant_id, site_id, location_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""",
    "svc_appointment_resource_requirement": r"""
CREATE TABLE svc_appointment_resource_requirement (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  appointment_id CHAR(36) NOT NULL,
  role_code VARCHAR(64) NOT NULL,
  required_count INT NOT NULL,
  min_qualification_level VARCHAR(32) NULL,
  qualification_snapshot JSON NOT NULL,
  service_rule_version INT NOT NULL,
  status VARCHAR(16) NOT NULL,
  row_version INT NOT NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, appointment_id, role_code),
  KEY ix_d04_requirement_status (tenant_id, site_id, status, appointment_id),
  CONSTRAINT fk_d04_requirement_appointment FOREIGN KEY
    (tenant_id, site_id, appointment_id)
    REFERENCES svc_appointment (tenant_id, site_id, appointment_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""",
    "svc_appointment_resource_assignment": r"""
CREATE TABLE svc_appointment_resource_assignment (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  assignment_id CHAR(36) NOT NULL,
  appointment_id CHAR(36) NOT NULL,
  resource_id CHAR(36) NOT NULL,
  resource_kind VARCHAR(16) NOT NULL,
  role_code VARCHAR(64) NULL,
  staff_id CHAR(36) NULL,
  assignment_source VARCHAR(16) NOT NULL,
  starts_at DATETIME(3) NOT NULL,
  ends_at DATETIME(3) NOT NULL,
  status VARCHAR(16) NOT NULL,
  row_version INT NOT NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, assignment_id),
  UNIQUE KEY uq_d04_assignment_resource (tenant_id, site_id, appointment_id, resource_id),
  KEY ix_d04_assignment_staff (tenant_id, site_id, staff_id, status, starts_at),
  CONSTRAINT fk_d04_assignment_appointment FOREIGN KEY
    (tenant_id, site_id, appointment_id)
    REFERENCES svc_appointment (tenant_id, site_id, appointment_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_d04_assignment_resource FOREIGN KEY
    (tenant_id, site_id, resource_id)
    REFERENCES svc_resource (tenant_id, site_id, resource_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_d04_assignment_staff FOREIGN KEY (tenant_id, staff_id)
    REFERENCES plat_staff_identity (tenant_id, staff_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_d04_assignment_role FOREIGN KEY
    (tenant_id, site_id, appointment_id, role_code)
    REFERENCES svc_appointment_resource_requirement
      (tenant_id, site_id, appointment_id, role_code)
    ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""",
    "svc_appointment_hold": r"""
CREATE TABLE svc_appointment_hold (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  hold_id CHAR(36) NOT NULL,
  appointment_id CHAR(36) NOT NULL,
  idempotency_key VARCHAR(96) NOT NULL,
  status VARCHAR(16) NOT NULL,
  expires_at DATETIME(3) NOT NULL,
  released_at DATETIME(3) NULL,
  row_version INT NOT NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, hold_id),
  UNIQUE KEY uq_d04_hold_appointment (tenant_id, site_id, appointment_id),
  UNIQUE KEY uq_d04_hold_idempotency (tenant_id, site_id, idempotency_key),
  KEY ix_d04_hold_expiry (tenant_id, site_id, status, expires_at),
  CONSTRAINT fk_d04_hold_appointment FOREIGN KEY
    (tenant_id, site_id, appointment_id)
    REFERENCES svc_appointment (tenant_id, site_id, appointment_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""",
    "svc_resource_lock_history": r"""
CREATE TABLE svc_resource_lock_history (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  history_id CHAR(36) NOT NULL,
  lock_id CHAR(36) NOT NULL,
  resource_id CHAR(36) NOT NULL,
  appointment_id CHAR(36) NOT NULL,
  lock_version INT NOT NULL,
  from_status VARCHAR(16) NOT NULL,
  to_status VARCHAR(16) NOT NULL,
  reason_code VARCHAR(48) NOT NULL,
  actor_id CHAR(36) NOT NULL,
  occurred_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, history_id),
  UNIQUE KEY uq_d04_lock_history_version
    (tenant_id, site_id, lock_id, lock_version),
  KEY ix_d04_lock_history_appointment (tenant_id, site_id, appointment_id, occurred_at),
  CONSTRAINT fk_d04_lock_history_lock FOREIGN KEY (tenant_id, site_id, lock_id)
    REFERENCES svc_resource_lock (tenant_id, site_id, lock_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_d04_lock_history_resource FOREIGN KEY
    (tenant_id, site_id, resource_id)
    REFERENCES svc_resource (tenant_id, site_id, resource_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_d04_lock_history_appointment FOREIGN KEY
    (tenant_id, site_id, appointment_id)
    REFERENCES svc_appointment (tenant_id, site_id, appointment_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""",
}

_TABLE_DROP_ORDER = tuple(reversed(tuple(TABLE_DDL)))
_LOCK_EXPIRY_INDEX_DDL = (
    "CREATE INDEX ix_db04_resource_lock_expiry ON svc_resource_lock "
    "(tenant_id, site_id, status, expires_at)"
)
_LOCK_EXPIRY_INDEX_DROP = (
    "DROP INDEX ix_db04_resource_lock_expiry ON svc_resource_lock"
)
_LOCK_EXPIRY_COLUMNS = ("tenant_id", "site_id", "status", "expires_at")


class MigrationPreconditionError(RuntimeError):
    """The canonical DB-02/DB-03 schema is incomplete or unsafe to change."""


def _key_sets(inspector: Any, table: str) -> tuple[set[tuple[str, ...]], set[tuple[str, ...]]]:
    unique: set[tuple[str, ...]] = set()
    indexes: set[tuple[str, ...]] = set()
    for item in inspector.get_unique_constraints(table) or ():
        unique.add(tuple(item.get("column_names") or ()))
    for item in inspector.get_indexes(table) or ():
        columns = tuple(item.get("column_names") or ())
        indexes.add(columns)
        if item.get("unique"):
            unique.add(columns)
    pk = tuple((inspector.get_pk_constraint(table) or {}).get("constrained_columns") or ())
    if pk:
        unique.add(pk)
    return unique, indexes


def _has_expiry_index(inspector: Any) -> bool:
    _, indexes = _key_sets(inspector, "svc_resource_lock")
    return any(columns[: len(_LOCK_EXPIRY_COLUMNS)] == _LOCK_EXPIRY_COLUMNS for columns in indexes)


def _preflight(inspector: Any) -> bool:
    """Validate all prerequisites before the first migration statement.

    Returns whether this revision must add its expiry index. Existing matching
    indexes remain owned by their existing migration and are never dropped here.
    """
    available = set(inspector.get_table_names())
    missing = sorted(set(REQUIRED_BASE_COLUMNS) - available)
    if missing:
        raise MigrationPreconditionError(
            "DB-02/DB-03 canonical tables are missing: " + ", ".join(missing)
        )

    for table, required_columns in REQUIRED_BASE_COLUMNS.items():
        actual = {column["name"] for column in inspector.get_columns(table) or ()}
        missing_columns = sorted(set(required_columns) - actual)
        if missing_columns:
            raise MigrationPreconditionError(
                f"{table} is missing canonical columns: {', '.join(missing_columns)}"
            )
        actual_pk = tuple(
            (inspector.get_pk_constraint(table) or {}).get("constrained_columns") or ()
        )
        if actual_pk != REQUIRED_PRIMARY_KEYS[table]:
            raise MigrationPreconditionError(f"{table} primary key does not match DB-02")

    lock_unique, lock_indexes = _key_sets(inspector, "svc_resource_lock")
    if LOCK_SLOT_UNIQUE_KEY not in lock_unique:
        raise MigrationPreconditionError(
            "svc_resource_lock is missing the canonical tenant/site/resource/slot unique key"
        )
    appointment_unique, _ = _key_sets(inspector, "svc_appointment")
    if APPOINTMENT_IDEMPOTENCY_KEY not in appointment_unique:
        raise MigrationPreconditionError(
            "svc_appointment is missing the DB-02 tenant-wide idempotency key"
        )

    collisions = sorted(set(TABLE_DDL) & available)
    if collisions:
        raise MigrationPreconditionError(
            "DB-04 target names already exist; reconcile them before migration: "
            + ", ".join(collisions)
        )

    indexes = list(inspector.get_indexes("svc_resource_lock") or ())
    for index in indexes:
        if index.get("name") == LOCK_EXPIRY_INDEX and tuple(index.get("column_names") or ()) != _LOCK_EXPIRY_COLUMNS:
            raise MigrationPreconditionError("svc_resource_lock has a conflicting DB-04 index name")
    return not any(
        tuple(index.get("column_names") or ())[: len(_LOCK_EXPIRY_COLUMNS)] == _LOCK_EXPIRY_COLUMNS
        for index in indexes
    )


def _execute(operations: Any, statement: str) -> Any:
    execute = getattr(operations, "execute", None)
    if not callable(execute):
        raise TypeError("migration operations must provide execute(sql)")
    return execute(statement)


def _apply_upgrade(operations: Any, add_expiry_index: bool) -> None:
    created_tables: list[str] = []
    index_created = False
    try:
        for table, statement in TABLE_DDL.items():
            _execute(operations, statement)
            created_tables.append(table)
        if add_expiry_index:
            _execute(operations, _LOCK_EXPIRY_INDEX_DDL)
            index_created = True
    except Exception:
        rollback_errors: list[Exception] = []
        if index_created:
            try:
                _execute(operations, _LOCK_EXPIRY_INDEX_DROP)
            except Exception as exc:  # preserve original error; report failed compensation
                rollback_errors.append(exc)
        for table in reversed(created_tables):
            try:
                _execute(operations, f"DROP TABLE {table}")
            except Exception as exc:
                rollback_errors.append(exc)
        if rollback_errors:
            raise RuntimeError(
                f"DB-04 DDL failed and {len(rollback_errors)} compensation step(s) failed"
            )
        raise


def upgrade(*, operations: Any | None = None, inspector: Any | None = None) -> None:
    if operations is None:
        from alembic import op as operations
    if inspector is None:
        import sqlalchemy as sa

        inspector = sa.inspect(operations.get_bind())
    add_expiry_index = _preflight(inspector)
    _apply_upgrade(operations, add_expiry_index)


def _first_row(result: Any) -> Any | None:
    first = getattr(result, "first", None)
    if callable(first):
        return first()
    fetchone = getattr(result, "fetchone", None)
    if callable(fetchone):
        return fetchone()
    return next(iter(result), None)


def _query_bind(bind: Any, sql: str) -> Any:
    try:
        import sqlalchemy as sa
    except ImportError:
        statement = sql
    else:
        statement = sa.text(sql)
    return bind.execute(statement)


def _preflight_downgrade(operations: Any, inspector: Any) -> bool:
    available = set(inspector.get_table_names())
    missing = sorted(set(TABLE_DDL) - available)
    if missing:
        raise MigrationPreconditionError(
            "DB-04 tables are incomplete; refusing a partial downgrade: " + ", ".join(missing)
        )

    bind = operations.get_bind() if callable(getattr(operations, "get_bind", None)) else operations
    for table in TABLE_DDL:
        columns = {column["name"] for column in inspector.get_columns(table) or ()}
        if not columns:
            raise MigrationPreconditionError(f"cannot verify DB-04 table {table}")
        result = _query_bind(bind, f"SELECT 1 FROM {table} LIMIT 1")
        if _first_row(result) is not None:
            raise MigrationPreconditionError(
                f"{table} contains appointment snapshot data; preserve existing bookings"
            )

    indexes = list(inspector.get_indexes("svc_resource_lock") or ())
    owned = next((item for item in indexes if item.get("name") == LOCK_EXPIRY_INDEX), None)
    if owned is not None and tuple(owned.get("column_names") or ()) != _LOCK_EXPIRY_COLUMNS:
        raise MigrationPreconditionError("svc_resource_lock has a conflicting DB-04 index name")
    return owned is not None


def downgrade(*, operations: Any | None = None, inspector: Any | None = None) -> None:
    if operations is None:
        from alembic import op as operations
    if inspector is None:
        import sqlalchemy as sa

        inspector = sa.inspect(operations.get_bind())

    # Full preflight prevents a partial downgrade and refuses to erase any
    # appointment context, assignment, hold, or lock history that is in use.
    drop_expiry_index = _preflight_downgrade(operations, inspector)
    if drop_expiry_index:
        _execute(operations, _LOCK_EXPIRY_INDEX_DROP)
    for table in _TABLE_DROP_ORDER:
        _execute(operations, f"DROP TABLE {table}")
