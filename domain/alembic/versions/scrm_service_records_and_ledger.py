"""DB-05: SCRM follow-up, service notes, and Wish service-card ledger schema.

This revision extends DB-02 canonical tables instead of creating aliases such
as ``fin_card`` or ``crm_customer_followup_task`` as second write masters.
Migration SQL targets MySQL/MariaDB. Tests inject fake operations/inspectors;
this module never connects to a database on import.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


revision = "db05_scrm_service_records_and_ledger"
down_revision = "db04_health_appointment_resources"
branch_labels = None
depends_on = None


class MigrationPreconditionError(RuntimeError):
    """The canonical schema or retained business data is unsafe to migrate."""


BASE_REQUIRED_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "plat_site": ("tenant_id", "site_id"),
    "crm_customer": ("tenant_id", "customer_id"),
    "plat_staff_identity": ("tenant_id", "staff_id"),
    "svc_service_item": ("tenant_id", "site_id", "service_id"),
    "svc_service_version": ("tenant_id", "site_id", "service_version_id", "service_id"),
    "svc_appointment": ("tenant_id", "site_id", "appointment_id", "customer_id", "service_version_id"),
    "svc_work_order": ("tenant_id", "site_id", "work_order_id", "appointment_id", "service_version_id"),
    "svc_followup_task": ("tenant_id", "site_id", "followup_id", "customer_id", "appointment_id", "staff_id"),
    "fin_service_card": ("tenant_id", "site_id", "card_id", "customer_id", "card_number_hmac", "status", "valid_to"),
    "fin_service_card_ledger": (
        "tenant_id", "site_id", "ledger_entry_id", "card_id", "entry_type",
        "delta_amount", "currency_code", "source_type", "source_id",
        "reversal_of", "idempotency_key_hash", "occurred_at", "created_at",
    ),
}

BASE_REQUIRED_PRIMARY_KEYS: Mapping[str, tuple[str, ...]] = {
    "plat_site": ("tenant_id", "site_id"),
    "crm_customer": ("tenant_id", "customer_id"),
    "plat_staff_identity": ("tenant_id", "staff_id"),
    "svc_service_item": ("tenant_id", "site_id", "service_id"),
    "svc_service_version": ("tenant_id", "site_id", "service_version_id"),
    "svc_appointment": ("tenant_id", "site_id", "appointment_id"),
    "svc_work_order": ("tenant_id", "site_id", "work_order_id"),
    "svc_followup_task": ("tenant_id", "site_id", "followup_id"),
    "fin_service_card": ("tenant_id", "site_id", "card_id"),
    "fin_service_card_ledger": ("tenant_id", "site_id", "ledger_entry_id"),
}

# These columns are nullable/zero-default during the expand phase so existing
# canonical rows are not silently classified as one of the four card types.
ADDED_COLUMNS: Mapping[str, tuple[tuple[str, str], ...]] = {
    "fin_service_card": (
        ("card_type", "VARCHAR(24) NULL"),
        ("card_rule_version", "VARCHAR(64) NULL"),
        ("source_type", "VARCHAR(32) NULL"),
        ("source_ref_hash", "CHAR(64) NULL"),
    ),
    "fin_service_card_ledger": (
        ("delta_units", "DECIMAL(18,3) NOT NULL DEFAULT 0"),
        ("unit_code", "VARCHAR(32) NULL"),
        ("benefit_code", "VARCHAR(64) NULL"),
        ("aggregate_version", "BIGINT NOT NULL DEFAULT 1"),
    ),
    "svc_followup_task": (
        ("plan_id", "CHAR(36) NULL"),
        ("plan_version", "INT NULL"),
        ("plan_day_offset", "INT NULL"),
    ),
}

NEW_TABLE_DDL: Mapping[str, str] = {
    "crm_customer_staff_relation": r"""
CREATE TABLE crm_customer_staff_relation (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  relation_id CHAR(36) NOT NULL,
  customer_id CHAR(36) NOT NULL,
  staff_id CHAR(36) NOT NULL,
  responsibility_type VARCHAR(32) NOT NULL,
  assignment_source VARCHAR(32) NOT NULL,
  scope_code VARCHAR(64) NOT NULL,
  purpose_code VARCHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  valid_from DATETIME(3) NOT NULL,
  valid_to DATETIME(3) NULL,
  row_version BIGINT NOT NULL DEFAULT 1,
  created_by CHAR(36) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, relation_id),
  UNIQUE KEY uq_db05_customer_staff_start (tenant_id, site_id, customer_id, staff_id, responsibility_type, valid_from),
  CONSTRAINT fk_db05_csr_site FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_csr_customer FOREIGN KEY (tenant_id, customer_id) REFERENCES crm_customer (tenant_id, customer_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_csr_staff FOREIGN KEY (tenant_id, staff_id) REFERENCES plat_staff_identity (tenant_id, staff_id) ON DELETE RESTRICT ON UPDATE RESTRICT
)""",
    "crm_customer_service_relation": r"""
CREATE TABLE crm_customer_service_relation (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  relation_id CHAR(36) NOT NULL,
  customer_id CHAR(36) NOT NULL,
  service_id CHAR(36) NOT NULL,
  service_version_id CHAR(36) NOT NULL,
  appointment_id CHAR(36) NULL,
  status VARCHAR(24) NOT NULL,
  source_type VARCHAR(32) NOT NULL,
  first_experienced_at DATETIME(3) NULL,
  last_experienced_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, relation_id),
  UNIQUE KEY uq_db05_customer_service_version (tenant_id, site_id, customer_id, service_version_id, status),
  CONSTRAINT fk_db05_cser_site FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_cser_customer FOREIGN KEY (tenant_id, customer_id) REFERENCES crm_customer (tenant_id, customer_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_cser_service FOREIGN KEY (tenant_id, site_id, service_id) REFERENCES svc_service_item (tenant_id, site_id, service_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_cser_version FOREIGN KEY (tenant_id, site_id, service_version_id) REFERENCES svc_service_version (tenant_id, site_id, service_version_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_cser_appointment FOREIGN KEY (tenant_id, site_id, appointment_id) REFERENCES svc_appointment (tenant_id, site_id, appointment_id) ON DELETE RESTRICT ON UPDATE RESTRICT
)""",
    "crm_customer_followup_plan": r"""
CREATE TABLE crm_customer_followup_plan (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  plan_id CHAR(36) NOT NULL,
  service_id CHAR(36) NOT NULL,
  service_version_id CHAR(36) NOT NULL,
  config_version INT NOT NULL,
  day_offset INT NOT NULL,
  channel_code VARCHAR(32) NOT NULL,
  required_outcome_code VARCHAR(32) NULL,
  status VARCHAR(24) NOT NULL,
  effective_from DATETIME(3) NOT NULL,
  effective_to DATETIME(3) NULL,
  created_by CHAR(36) NOT NULL,
  updated_by CHAR(36) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, plan_id),
  UNIQUE KEY uq_db05_followup_plan_node (tenant_id, site_id, service_version_id, config_version, day_offset),
  CONSTRAINT fk_db05_fup_plan_site FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_fup_plan_service FOREIGN KEY (tenant_id, site_id, service_id) REFERENCES svc_service_item (tenant_id, site_id, service_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_fup_plan_version FOREIGN KEY (tenant_id, site_id, service_version_id) REFERENCES svc_service_version (tenant_id, site_id, service_version_id) ON DELETE RESTRICT ON UPDATE RESTRICT
)""",
    "crm_customer_contact_log": r"""
CREATE TABLE crm_customer_contact_log (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  contact_log_id CHAR(36) NOT NULL,
  customer_id CHAR(36) NOT NULL,
  staff_id CHAR(36) NOT NULL,
  followup_id CHAR(36) NULL,
  purpose_code VARCHAR(32) NOT NULL,
  channel_code VARCHAR(32) NOT NULL,
  result_code VARCHAR(32) NOT NULL,
  external_ref_hash CHAR(64) NULL,
  consent_version VARCHAR(64) NULL,
  occurred_at DATETIME(3) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, contact_log_id),
  CONSTRAINT fk_db05_contact_site FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_contact_customer FOREIGN KEY (tenant_id, customer_id) REFERENCES crm_customer (tenant_id, customer_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_contact_staff FOREIGN KEY (tenant_id, staff_id) REFERENCES plat_staff_identity (tenant_id, staff_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_contact_followup FOREIGN KEY (tenant_id, site_id, followup_id) REFERENCES svc_followup_task (tenant_id, site_id, followup_id) ON DELETE RESTRICT ON UPDATE RESTRICT
)""",
    "svc_service_note": r"""
CREATE TABLE svc_service_note (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  service_note_id CHAR(36) NOT NULL,
  customer_id CHAR(36) NOT NULL,
  appointment_id CHAR(36) NOT NULL,
  work_order_id CHAR(36) NULL,
  service_version_id CHAR(36) NULL,
  author_staff_id CHAR(36) NOT NULL,
  note_ciphertext BLOB NOT NULL,
  note_hash CHAR(64) NOT NULL,
  idempotency_key_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  note_version INT NOT NULL DEFAULT 1,
  amends_note_id CHAR(36) NULL,
  occurred_at DATETIME(3) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, service_note_id),
  UNIQUE KEY uq_db05_service_note_idem (tenant_id, site_id, idempotency_key_hash),
  CONSTRAINT fk_db05_note_site FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_note_customer FOREIGN KEY (tenant_id, customer_id) REFERENCES crm_customer (tenant_id, customer_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_note_appointment FOREIGN KEY (tenant_id, site_id, appointment_id) REFERENCES svc_appointment (tenant_id, site_id, appointment_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_note_work_order FOREIGN KEY (tenant_id, site_id, work_order_id) REFERENCES svc_work_order (tenant_id, site_id, work_order_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_note_version FOREIGN KEY (tenant_id, site_id, service_version_id) REFERENCES svc_service_version (tenant_id, site_id, service_version_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_note_staff FOREIGN KEY (tenant_id, author_staff_id) REFERENCES plat_staff_identity (tenant_id, staff_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_note_amends FOREIGN KEY (tenant_id, site_id, amends_note_id) REFERENCES svc_service_note (tenant_id, site_id, service_note_id) ON DELETE RESTRICT ON UPDATE RESTRICT
)""",
    "svc_service_note_media": r"""
CREATE TABLE svc_service_note_media (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  media_id CHAR(36) NOT NULL,
  service_note_id CHAR(36) NOT NULL,
  object_ref_ciphertext BLOB NOT NULL,
  object_hash CHAR(64) NOT NULL,
  mime_type VARCHAR(128) NOT NULL,
  byte_size BIGINT NOT NULL,
  purpose_code VARCHAR(32) NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_by CHAR(36) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  expires_at DATETIME(3) NULL,
  PRIMARY KEY (tenant_id, site_id, media_id),
  UNIQUE KEY uq_db05_service_note_media_hash (tenant_id, site_id, object_hash),
  CONSTRAINT fk_db05_note_media_note FOREIGN KEY (tenant_id, site_id, service_note_id) REFERENCES svc_service_note (tenant_id, site_id, service_note_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_note_media_staff FOREIGN KEY (tenant_id, created_by) REFERENCES plat_staff_identity (tenant_id, staff_id) ON DELETE RESTRICT ON UPDATE RESTRICT
)""",
    "fin_service_card_rule": r"""
CREATE TABLE fin_service_card_rule (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  card_rule_id CHAR(36) NOT NULL,
  card_type VARCHAR(24) NOT NULL,
  service_version_id CHAR(36) NULL,
  config_version INT NOT NULL,
  discount_bps INT NULL,
  granted_units DECIMAL(18,3) NULL,
  unit_code VARCHAR(32) NULL,
  validity_days INT NULL,
  stacking_code VARCHAR(32) NOT NULL,
  refund_policy_code VARCHAR(32) NOT NULL,
  status VARCHAR(24) NOT NULL,
  effective_from DATETIME(3) NOT NULL,
  effective_to DATETIME(3) NULL,
  approved_by CHAR(36) NULL,
  approved_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, card_rule_id),
  UNIQUE KEY uq_db05_card_rule_version (tenant_id, site_id, card_type, config_version, service_version_id),
  CONSTRAINT fk_db05_card_rule_site FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_card_rule_service FOREIGN KEY (tenant_id, site_id, service_version_id) REFERENCES svc_service_version (tenant_id, site_id, service_version_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_db05_card_rule_type CHECK (card_type IN ('STORED_VALUE','DISCOUNT','SESSION','PACKAGE'))
)""",
    "fin_service_card_benefit": r"""
CREATE TABLE fin_service_card_benefit (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  benefit_id CHAR(36) NOT NULL,
  card_id CHAR(36) NOT NULL,
  service_version_id CHAR(36) NULL,
  benefit_code VARCHAR(64) NOT NULL,
  benefit_type VARCHAR(24) NOT NULL,
  granted_units DECIMAL(18,3) NULL,
  unit_code VARCHAR(32) NULL,
  discount_bps INT NULL,
  rule_version VARCHAR(64) NOT NULL,
  source_grant_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  valid_from DATETIME(3) NOT NULL,
  valid_to DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (tenant_id, site_id, benefit_id),
  UNIQUE KEY uq_db05_card_benefit_code (tenant_id, site_id, card_id, benefit_code),
  UNIQUE KEY uq_db05_card_benefit_ref (tenant_id, site_id, card_id, benefit_id),
  CONSTRAINT fk_db05_card_benefit_card FOREIGN KEY (tenant_id, site_id, card_id) REFERENCES fin_service_card (tenant_id, site_id, card_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_card_benefit_service FOREIGN KEY (tenant_id, site_id, service_version_id) REFERENCES svc_service_version (tenant_id, site_id, service_version_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_db05_card_benefit_type CHECK (benefit_type IN ('VALUE','DISCOUNT','SESSION','PACKAGE_ITEM'))
)""",
    "fin_service_card_consumption": r"""
CREATE TABLE fin_service_card_consumption (
  tenant_id CHAR(36) NOT NULL,
  site_id CHAR(36) NOT NULL,
  consumption_id CHAR(36) NOT NULL,
  card_id CHAR(36) NOT NULL,
  benefit_id CHAR(36) NULL,
  appointment_id CHAR(36) NOT NULL,
  service_version_id CHAR(36) NOT NULL,
  ledger_entry_id CHAR(36) NOT NULL,
  idempotency_key_hash CHAR(64) NOT NULL,
  delta_amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  currency_code CHAR(3) NOT NULL,
  delta_units DECIMAL(18,3) NOT NULL DEFAULT 0,
  unit_code VARCHAR(32) NULL,
  discount_bps INT NULL,
  rule_version VARCHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_by CHAR(36) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  reversed_at DATETIME(3) NULL,
  PRIMARY KEY (tenant_id, site_id, consumption_id),
  UNIQUE KEY uq_db05_card_consumption_idem (tenant_id, site_id, appointment_id, idempotency_key_hash),
  UNIQUE KEY uq_db05_card_consumption_ledger (tenant_id, site_id, ledger_entry_id),
  CONSTRAINT fk_db05_consumption_card FOREIGN KEY (tenant_id, site_id, card_id) REFERENCES fin_service_card (tenant_id, site_id, card_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_consumption_benefit FOREIGN KEY (tenant_id, site_id, card_id, benefit_id) REFERENCES fin_service_card_benefit (tenant_id, site_id, card_id, benefit_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_consumption_appointment FOREIGN KEY (tenant_id, site_id, appointment_id) REFERENCES svc_appointment (tenant_id, site_id, appointment_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_consumption_service FOREIGN KEY (tenant_id, site_id, service_version_id) REFERENCES svc_service_version (tenant_id, site_id, service_version_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_consumption_ledger FOREIGN KEY (tenant_id, site_id, ledger_entry_id) REFERENCES fin_service_card_ledger (tenant_id, site_id, ledger_entry_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_db05_consumption_staff FOREIGN KEY (tenant_id, created_by) REFERENCES plat_staff_identity (tenant_id, staff_id) ON DELETE RESTRICT ON UPDATE RESTRICT
)""",
}

TABLE_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX ix_db05_customer_staff_lookup ON crm_customer_staff_relation (tenant_id, site_id, customer_id, status, valid_to)",
    "CREATE INDEX ix_db05_staff_customer_lookup ON crm_customer_staff_relation (tenant_id, site_id, staff_id, status, valid_to)",
    "CREATE INDEX ix_db05_customer_service_lookup ON crm_customer_service_relation (tenant_id, site_id, customer_id, status, last_experienced_at)",
    "CREATE INDEX ix_db05_service_customer_lookup ON crm_customer_service_relation (tenant_id, site_id, service_id, customer_id, status)",
    "CREATE INDEX ix_db05_followup_plan_active ON crm_customer_followup_plan (tenant_id, site_id, service_version_id, status, effective_from, effective_to)",
    "CREATE INDEX ix_db05_contact_customer_time ON crm_customer_contact_log (tenant_id, site_id, customer_id, occurred_at)",
    "CREATE INDEX ix_db05_contact_task_time ON crm_customer_contact_log (tenant_id, site_id, followup_id, occurred_at)",
    "CREATE INDEX ix_db05_service_note_customer_time ON svc_service_note (tenant_id, site_id, customer_id, occurred_at)",
    "CREATE INDEX ix_db05_service_note_appointment ON svc_service_note (tenant_id, site_id, appointment_id, author_staff_id)",
    "CREATE INDEX ix_db05_note_media_status ON svc_service_note_media (tenant_id, site_id, service_note_id, status, created_at)",
    "CREATE INDEX ix_db05_card_rule_active ON fin_service_card_rule (tenant_id, site_id, card_type, status, effective_from, effective_to)",
    "CREATE INDEX ix_db05_card_benefit_status ON fin_service_card_benefit (tenant_id, site_id, card_id, status, valid_to)",
    "CREATE INDEX ix_db05_card_consumption_history ON fin_service_card_consumption (tenant_id, site_id, card_id, status, created_at)",
)

BASE_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX ix_db05_card_type_status ON fin_service_card (tenant_id, site_id, card_type, status, valid_to)",
    "CREATE UNIQUE INDEX uq_db05_card_source_ref ON fin_service_card (tenant_id, site_id, source_type, source_ref_hash)",
    "CREATE INDEX ix_db05_card_ledger_balance ON fin_service_card_ledger (tenant_id, site_id, card_id, benefit_code, occurred_at)",
    "CREATE UNIQUE INDEX uq_db05_card_ledger_reversal ON fin_service_card_ledger (tenant_id, site_id, reversal_of)",
    "CREATE INDEX ix_db05_followup_plan_task ON svc_followup_task (tenant_id, site_id, plan_id, plan_version, plan_day_offset)",
)

TRIGGER_DDL: tuple[str, ...] = (
    "CREATE TRIGGER trg_db05_ledger_source_guard BEFORE INSERT ON fin_service_card_ledger FOR EACH ROW BEGIN IF UPPER(NEW.source_type) LIKE 'MER_%' OR UPPER(NEW.source_type) LIKE 'COMMERCE_%' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Commerce facts cannot enter the Wish service ledger'; END IF; END",
    "CREATE TRIGGER trg_db05_ledger_no_update BEFORE UPDATE ON fin_service_card_ledger FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'fin_service_card_ledger is append-only'",
    "CREATE TRIGGER trg_db05_ledger_no_delete BEFORE DELETE ON fin_service_card_ledger FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'fin_service_card_ledger is append-only'",
)

NEW_TABLE_DROP_ORDER: tuple[str, ...] = (
    "fin_service_card_consumption",
    "fin_service_card_benefit",
    "fin_service_card_rule",
    "svc_service_note_media",
    "svc_service_note",
    "crm_customer_contact_log",
    "crm_customer_followup_plan",
    "crm_customer_service_relation",
    "crm_customer_staff_relation",
)

ADDED_FOREIGN_KEYS: tuple[tuple[str, str], ...] = (
    ("svc_followup_task", "fk_db05_followup_plan"),
    ("fin_service_card_ledger", "fk_db05_ledger_reversal"),
)


def _execute(bind: Any, sql: str) -> Any:
    try:
        import sqlalchemy as sa
    except ImportError:
        return bind.execute(sql)
    return bind.execute(sa.text(sql))


def _first_row(result: Any) -> Any | None:
    first = getattr(result, "first", None)
    if callable(first):
        return first()
    fetchone = getattr(result, "fetchone", None)
    if callable(fetchone):
        return fetchone()
    return next(iter(result), None)


def _columns(inspector: Any, table: str) -> set[str]:
    return {column["name"] for column in (inspector.get_columns(table) or ())}


def _pk(inspector: Any, table: str) -> tuple[str, ...]:
    return tuple((inspector.get_pk_constraint(table) or {}).get("constrained_columns") or ())


def _preflight(bind: Any, inspector: Any) -> None:
    tables = set(inspector.get_table_names())
    missing = sorted(set(BASE_REQUIRED_COLUMNS) - tables)
    if missing:
        raise MigrationPreconditionError(
            "DB-02/DB-03 canonical prerequisite tables are missing: " + ", ".join(missing)
        )
    for table, required in BASE_REQUIRED_COLUMNS.items():
        actual = _columns(inspector, table)
        absent = sorted(set(required) - actual)
        if absent:
            raise MigrationPreconditionError(f"{table} is missing canonical columns: {', '.join(absent)}")
        if _pk(inspector, table) != BASE_REQUIRED_PRIMARY_KEYS[table]:
            raise MigrationPreconditionError(f"{table} primary key differs from DB-02 canonical model")

    collisions = sorted(set(NEW_TABLE_DDL) & tables)
    if collisions:
        raise MigrationPreconditionError(
            "same-name SCRM extension tables need explicit canonical reconciliation before DB-05: "
            + ", ".join(collisions)
        )
    for table, additions in ADDED_COLUMNS.items():
        actual = _columns(inspector, table)
        present = sorted({name for name, _ in additions} & actual)
        if present:
            raise MigrationPreconditionError(
                f"{table} already contains DB-05 extension columns; reconcile before rollout: "
                + ", ".join(present)
            )

    for ddl in BASE_INDEX_DDL:
        index_name, table = _index_name_and_table(ddl)
        indexes = list(inspector.get_indexes(table) or ())
        unique_constraints = list(inspector.get_unique_constraints(table) or ())
        if any(item.get("name") == index_name for item in indexes + unique_constraints):
            raise MigrationPreconditionError(f"reserved DB-05 index name already exists: {index_name}")
    for table, foreign_key_name in ADDED_FOREIGN_KEYS:
        if any(
            item.get("name") == foreign_key_name
            for item in (inspector.get_foreign_keys(table) or ())
        ):
            raise MigrationPreconditionError(f"reserved DB-05 foreign-key name already exists: {foreign_key_name}")
    get_checks = getattr(inspector, "get_check_constraints", None)
    if callable(get_checks) and any(
        item.get("name") == "ck_db05_card_type"
        for item in (get_checks("fin_service_card") or ())
    ):
        raise MigrationPreconditionError("reserved DB-05 card-type check name already exists")

    # Existing reversal references must already resolve in the same tenant/site,
    # and each original entry may be reversed at most once.
    orphan = _first_row(_execute(bind, """
SELECT 1 FROM fin_service_card_ledger AS child
LEFT JOIN fin_service_card_ledger AS parent
  ON parent.tenant_id = child.tenant_id
 AND parent.site_id = child.site_id
 AND parent.ledger_entry_id = child.reversal_of
WHERE child.reversal_of IS NOT NULL AND parent.ledger_entry_id IS NULL
LIMIT 1"""))
    if orphan is not None:
        raise MigrationPreconditionError("existing card ledger has an orphan or cross-scope reversal reference")
    duplicate_reversal = _first_row(_execute(bind, """
SELECT 1 FROM fin_service_card_ledger
WHERE reversal_of IS NOT NULL
GROUP BY tenant_id, site_id, reversal_of
HAVING COUNT(*) > 1
LIMIT 1"""))
    if duplicate_reversal is not None:
        raise MigrationPreconditionError("existing card ledger reverses one entry more than once")

    collision = _first_row(_execute(
        bind,
        "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS "
        "WHERE TRIGGER_SCHEMA = DATABASE() AND TRIGGER_NAME IN "
        "('trg_db05_ledger_source_guard','trg_db05_ledger_no_update','trg_db05_ledger_no_delete') LIMIT 1",
    ))
    if collision is not None:
        raise MigrationPreconditionError("a reserved DB-05 append-only trigger name is already in use")
    commerce_fact = _first_row(_execute(bind, """
SELECT 1 FROM fin_service_card_ledger
WHERE UPPER(source_type) LIKE 'MER_%' OR UPPER(source_type) LIKE 'COMMERCE_%'
LIMIT 1"""))
    if commerce_fact is not None:
        raise MigrationPreconditionError("existing Wish card ledger contains Commerce-owned entries")


def _apply_upgrade(operations: Any) -> None:
    for table, additions in ADDED_COLUMNS.items():
        for name, sql_type in additions:
            operations.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
    operations.execute(
        "ALTER TABLE fin_service_card ADD CONSTRAINT ck_db05_card_type "
        "CHECK (card_type IS NULL OR card_type IN ('STORED_VALUE','DISCOUNT','SESSION','PACKAGE'))"
    )

    for table, ddl in NEW_TABLE_DDL.items():
        operations.execute(ddl)
    for ddl in TABLE_INDEX_DDL:
        operations.execute(ddl)
    for ddl in BASE_INDEX_DDL:
        operations.execute(ddl)
    operations.execute(
        "ALTER TABLE svc_followup_task ADD CONSTRAINT fk_db05_followup_plan "
        "FOREIGN KEY (tenant_id, site_id, plan_id) "
        "REFERENCES crm_customer_followup_plan (tenant_id, site_id, plan_id) "
        "ON DELETE RESTRICT ON UPDATE RESTRICT"
    )
    operations.execute(
        "ALTER TABLE fin_service_card_ledger ADD CONSTRAINT fk_db05_ledger_reversal "
        "FOREIGN KEY (tenant_id, site_id, reversal_of) "
        "REFERENCES fin_service_card_ledger (tenant_id, site_id, ledger_entry_id) "
        "ON DELETE RESTRICT ON UPDATE RESTRICT"
    )
    for ddl in TRIGGER_DDL:
        operations.execute(ddl)


def upgrade(*, operations: Any | None = None, inspector: Any | None = None) -> None:
    if operations is None:
        from alembic import op as operations
    bind = operations.get_bind()
    if inspector is None:
        import sqlalchemy as sa

        inspector = sa.inspect(bind)
    _preflight(bind, inspector)
    _apply_upgrade(operations)


def _ensure_empty(bind: Any, table: str, *, where: str | None = None) -> None:
    suffix = f" WHERE {where}" if where else ""
    if _first_row(_execute(bind, f"SELECT 1 FROM {table}{suffix} LIMIT 1")) is not None:
        raise MigrationPreconditionError(
            f"{table} contains business data; DB-05 downgrade would discard it"
        )


def _preflight_downgrade(bind: Any, inspector: Any) -> None:
    tables = set(inspector.get_table_names())
    missing = sorted(set(NEW_TABLE_DDL) - tables)
    if missing:
        raise MigrationPreconditionError(
            "DB-05 schema is partial; reconcile before downgrade: " + ", ".join(missing)
        )
    for table in NEW_TABLE_DROP_ORDER:
        _ensure_empty(bind, table)
    # The existing canonical ledger is never dropped. Refuse rollback if it has
    # any rows, since removing its guards/FK could make historical entries mutable.
    _ensure_empty(bind, "fin_service_card_ledger")
    _ensure_empty(bind, "fin_service_card", where="card_type IS NOT NULL OR card_rule_version IS NOT NULL OR source_ref_hash IS NOT NULL")
    _ensure_empty(bind, "svc_followup_task", where="plan_id IS NOT NULL OR plan_version IS NOT NULL OR plan_day_offset IS NOT NULL")


def _apply_downgrade(operations: Any) -> None:
    operations.execute("DROP TRIGGER IF EXISTS trg_db05_ledger_source_guard")
    operations.execute("DROP TRIGGER IF EXISTS trg_db05_ledger_no_delete")
    operations.execute("DROP TRIGGER IF EXISTS trg_db05_ledger_no_update")
    operations.execute("ALTER TABLE fin_service_card_ledger DROP FOREIGN KEY fk_db05_ledger_reversal")
    operations.execute("ALTER TABLE svc_followup_task DROP FOREIGN KEY fk_db05_followup_plan")
    operations.execute("ALTER TABLE fin_service_card DROP CHECK ck_db05_card_type")
    for table in NEW_TABLE_DROP_ORDER:
        operations.execute(f"DROP TABLE {table}")
    for index in reversed(BASE_INDEX_DDL):
        name, table = _index_name_and_table(index)
        operations.execute(f"DROP INDEX {name} ON {table}")
    for table, additions in reversed(tuple(ADDED_COLUMNS.items())):
        for name, _ in reversed(additions):
            operations.execute(f"ALTER TABLE {table} DROP COLUMN {name}")


def _index_name_and_table(ddl: str) -> tuple[str, str]:
    # All identifiers here are constant migration-owned names.
    tokens = ddl.split()
    unique_index = tokens[1].upper() == "UNIQUE"
    name = tokens[3]
    table = tokens[tokens.index("ON") + 1]
    return name, table


def downgrade(*, operations: Any | None = None, inspector: Any | None = None) -> None:
    if operations is None:
        from alembic import op as operations
    bind = operations.get_bind()
    if inspector is None:
        import sqlalchemy as sa

        inspector = sa.inspect(bind)
    _preflight_downgrade(bind, inspector)
    _apply_downgrade(operations)
