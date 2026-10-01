"""SCRM model contracts backed by Wish's canonical CRM/service entities.

``crm_customer_followup_task`` from the architecture is a logical alias for
the existing ``svc_followup_task`` canonical entity. This module deliberately
does not define a second task table or a parallel write model.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final


FOLLOWUP_TASK_TABLE: Final = "svc_followup_task"
FOLLOWUP_RESULT_TABLE: Final = "svc_followup_result"
FOLLOWUP_STATUSES: Final = frozenset(
    {"OPEN", "IN_PROGRESS", "COMPLETED", "RESCHEDULED", "ESCALATED", "CANCELLED"}
)
CONTACT_PURPOSES: Final = frozenset({"SERVICE_FOLLOWUP", "CUSTOMER_SUPPORT"})


@dataclass(frozen=True)
class CustomerStaffRelation:
    tenant_id: str
    site_id: str
    relation_id: str
    customer_id: str
    staff_id: str
    responsibility_type: str
    status: str
    valid_from: datetime
    valid_to: datetime | None = None
    row_version: int = 1


@dataclass(frozen=True)
class CustomerServiceRelation:
    tenant_id: str
    site_id: str
    relation_id: str
    customer_id: str
    service_id: str
    service_version_id: str
    status: str
    source_type: str
    first_experienced_at: datetime | None = None
    last_experienced_at: datetime | None = None


@dataclass(frozen=True)
class FollowupPlan:
    tenant_id: str
    site_id: str
    plan_id: str
    service_version_id: str
    config_version: int
    day_offset: int
    channel_code: str
    required_outcome_code: str | None
    status: str
    effective_from: datetime
    effective_to: datetime | None = None


@dataclass(frozen=True)
class FollowupTask:
    """Application view of canonical ``svc_followup_task`` rows."""

    tenant_id: str
    site_id: str
    followup_id: str
    customer_id: str
    task_type: str
    status: str
    due_at: datetime
    plan_id: str | None = None
    plan_version: int | None = None
    plan_day_offset: int | None = None
    staff_id: str | None = None

    def __post_init__(self) -> None:
        if self.status not in FOLLOWUP_STATUSES:
            raise ValueError(f"unsupported follow-up status: {self.status}")
        if (self.plan_id is None) != (self.plan_version is None):
            raise ValueError("plan_id and plan_version must be supplied together")


@dataclass(frozen=True)
class CustomerContactLog:
    tenant_id: str
    site_id: str
    contact_log_id: str
    customer_id: str
    staff_id: str
    purpose: str
    channel: str
    result_code: str
    occurred_at: datetime
    followup_id: str | None = None
    external_ref_hash: str | None = None

    def __post_init__(self) -> None:
        if self.purpose not in CONTACT_PURPOSES:
            raise ValueError("contact log purpose must be service/support, never implicit marketing")
        if self.external_ref_hash is not None and len(self.external_ref_hash) < 32:
            raise ValueError("external references must be stored as a non-reversible hash")
