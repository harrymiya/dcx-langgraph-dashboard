"""DB-06 migration contract marker; this revision intentionally performs no DDL.

The resumable data workflow lives in ``domain.migrations.health_scrm_backfill``
and talks only to explicitly injected ports.  Applying this revision records
the reviewed contract version in Alembic metadata; it is not evidence that a
backfill, comparison, or route cutover has run.
"""

from __future__ import annotations


revision = "db06_health_scrm_backfill"
down_revision = "db05_scrm_service_records_and_ledger"
branch_labels = None
depends_on = None

CONTRACT_VERSION = "db06-health-scrm-backfill-v1"


def upgrade() -> None:
    """Keep this revision schema-neutral; DB-06 never executes DDL."""


def downgrade() -> None:
    """Keep schema and business data intact; routing rollback is a runbook step."""
