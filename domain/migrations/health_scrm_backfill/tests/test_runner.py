"""Synthetic DB-06 contract tests; no database driver or live connection."""

from __future__ import annotations

import unittest

from domain.alembic.versions import db06_health_scrm_backfill as revision
from domain.migrations.health_scrm_backfill.runner import (
    ApprovalEvidence,
    BackfillBatch,
    Checkpoint,
    CheckpointConflict,
    ComparisonReport,
    GateRejected,
    HealthScrmBackfillRunner,
    InventorySnapshot,
    Phase,
    Scope,
)


class MemoryCheckpointStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, Scope], Checkpoint] = {}

    def load(self, contract_version: str, scope: Scope) -> Checkpoint | None:
        return self.values.get((contract_version, scope))

    def save(self, checkpoint: Checkpoint, *, expected_revision: int) -> None:
        key = (checkpoint.contract_version, checkpoint.scope)
        current = self.values.get(key)
        actual = current.revision if current else 0
        if actual != expected_revision:
            raise CheckpointConflict("synthetic checkpoint compare-and-swap conflict")
        if checkpoint.revision != expected_revision + 1:
            raise CheckpointConflict("synthetic checkpoint revision did not advance by one")
        self.values[key] = checkpoint


class SyntheticPort:
    """A deterministic fake that records only synthetic aggregate state."""

    def __init__(self) -> None:
        self.scope = Scope("tenant-demo", "site-demo-a")
        self.schema_fingerprint = "a" * 64
        self.source_watermark = "synthetic-watermark-17"
        self.counts = {"customer": 3, "appointment": 2, "service_card_ledger": 2}
        self.amounts = {"service_card_ledger|CNY": "100.00"}
        self.inventory_reads = 0
        self.batch_results: dict[str, BackfillBatch] = {}
        self.batch_calls: list[str] = []
        self.applied_batch_keys: list[str] = []
        self.interrupt_after_first_batch_effect = False
        self.comparison_calls = 0
        self.amount_difference = False
        self.count_difference = False
        self.quarantine_first_batch = False
        self.orphan_fk_count = 0
        self.scope_violation_count = 0
        self.new_route_active = False
        self.legacy_read_only = False
        self.canary_calls: list[str] = []
        self.rollback_calls: list[str] = []
        self.appointments = ["synthetic-appointment-in-flight"]
        self.ledger_entries = ["synthetic-ledger-entry-append-only"]

    def read_only_inventory(self, scope: Scope) -> InventorySnapshot:
        self.inventory_reads += 1
        return InventorySnapshot(
            scope,
            self.schema_fingerprint,
            self.source_watermark,
            self.counts,
            self.amounts,
        )

    def backfill_shadow_batch(
        self,
        scope: Scope,
        *,
        source_fingerprint: str,
        after_cursor: str | None,
        limit: int,
        idempotency_key: str,
    ) -> BackfillBatch:
        self.batch_calls.append(idempotency_key)
        if idempotency_key in self.batch_results:
            return self.batch_results[idempotency_key]
        if after_cursor is None:
            quarantined = 1 if self.quarantine_first_batch else 0
            result = BackfillBatch("opaque-cursor-2", 2, 2 - quarantined, quarantined, True)
        else:
            result = BackfillBatch(None, 2, 2, 0, False)
        self.batch_results[idempotency_key] = result
        self.applied_batch_keys.append(idempotency_key)
        if self.interrupt_after_first_batch_effect and len(self.applied_batch_keys) == 1:
            self.interrupt_after_first_batch_effect = False
            raise RuntimeError("synthetic interruption after idempotent shadow effect")
        return result

    def compare_legacy_and_shadow(
        self, scope: Scope, *, source_fingerprint: str
    ) -> ComparisonReport:
        self.comparison_calls += 1
        shadow_counts = dict(self.counts)
        if self.count_difference:
            shadow_counts["appointment"] += 1
        shadow_amounts = dict(self.amounts)
        if self.amount_difference:
            shadow_amounts["service_card_ledger|CNY"] = "99.99"
        return ComparisonReport(
            scope=scope,
            schema_fingerprint=self.schema_fingerprint,
            source_watermark=self.source_watermark,
            legacy_counts=self.counts,
            shadow_counts=shadow_counts,
            legacy_amounts=self.amounts,
            shadow_amounts=shadow_amounts,
            orphan_fk_count=self.orphan_fk_count,
            site_scope_violation_count=self.scope_violation_count,
        )

    def activate_tenant_site_canary(
        self, scope: Scope, *, idempotency_key: str, evidence: ApprovalEvidence
    ) -> None:
        if idempotency_key not in self.canary_calls:
            self.canary_calls.append(idempotency_key)
            self.new_route_active = True
            self.legacy_read_only = True

    def restore_legacy_read_only_route(self, scope: Scope, *, idempotency_key: str) -> None:
        if idempotency_key not in self.rollback_calls:
            self.rollback_calls.append(idempotency_key)
            self.new_route_active = False
            self.legacy_read_only = True


def approved_evidence() -> ApprovalEvidence:
    return ApprovalEvidence(
        mapping_and_owner_review="review-map-001",
        tenant_site_scope_review="review-scope-001",
        health_owner_approval="review-health-owner-001",
        backup_restore_exercise="restore-run-001",
        parity_signoff="parity-review-001",
        rollback_rehearsal="rollback-run-001",
    )


class HealthScrmBackfillRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.port = SyntheticPort()
        self.checkpoints = MemoryCheckpointStore()
        self.runner = HealthScrmBackfillRunner(self.port, self.checkpoints)
        self.scope = self.port.scope

    def _reach_shadow_complete(self) -> Checkpoint:
        self.runner.inventory(self.scope)
        checkpoint = self.runner.backfill_shadow_batch(self.scope, limit=2)
        self.assertEqual(checkpoint.phase, Phase.SHADOW_BACKFILL)
        return self.runner.backfill_shadow_batch(self.scope, limit=2)

    def _reach_dual_read(self) -> Checkpoint:
        checkpoint = self._reach_shadow_complete()
        self.assertEqual(checkpoint.phase, Phase.SHADOW_COMPLETE)
        return self.runner.compare_dual_read(self.scope)

    def test_revision_is_a_schema_neutral_contract_marker(self) -> None:
        self.assertEqual(revision.revision, "db06_health_scrm_backfill")
        self.assertEqual(revision.down_revision, "db05_scrm_service_records_and_ledger")
        self.assertIsNone(revision.upgrade())
        self.assertIsNone(revision.downgrade())

    def test_interruption_retries_the_same_batch_key_and_resumes_from_checkpoint(self) -> None:
        self.port.interrupt_after_first_batch_effect = True
        inventory = self.runner.inventory(self.scope)

        with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
            self.runner.backfill_shadow_batch(self.scope, limit=2)

        unchanged = self.checkpoints.load(inventory.contract_version, self.scope)
        self.assertEqual(unchanged, inventory)
        resumed = self.runner.backfill_shadow_batch(self.scope, limit=2)
        self.assertEqual(resumed.phase, Phase.SHADOW_BACKFILL)
        self.assertEqual(self.port.batch_calls[0], self.port.batch_calls[1])
        self.assertEqual(len(self.port.applied_batch_keys), 1)

        completed = self.runner.backfill_shadow_batch(self.scope, limit=2)
        self.assertEqual(completed.phase, Phase.SHADOW_COMPLETE)
        self.assertEqual(completed.batch_count, 2)
        self.assertEqual(completed.copied_rows, 4)

    def test_repeated_execution_is_idempotent_across_phases(self) -> None:
        inventory = self.runner.inventory(self.scope)
        self.assertEqual(self.runner.inventory(self.scope), inventory)
        self.runner.backfill_shadow_batch(self.scope, limit=2)
        complete = self.runner.backfill_shadow_batch(self.scope, limit=2)
        self.assertEqual(self.runner.backfill_shadow_batch(self.scope), complete)

        dual_read = self.runner.compare_dual_read(self.scope)
        self.assertEqual(self.runner.compare_dual_read(self.scope), dual_read)
        active = self.runner.activate_canary(self.scope, approved_evidence())
        self.assertEqual(self.runner.activate_canary(self.scope, approved_evidence()), active)
        self.assertEqual(len(self.port.applied_batch_keys), 2)
        self.assertEqual(self.port.comparison_calls, 1)
        self.assertEqual(len(self.port.canary_calls), 1)

    def test_rollback_restores_legacy_read_only_and_preserves_appointments_and_ledger(self) -> None:
        self._reach_dual_read()
        self.runner.activate_canary(self.scope, approved_evidence())
        appointments_before = list(self.port.appointments)
        ledger_before = list(self.port.ledger_entries)
        checkpoint_before = self.checkpoints.load(revision.CONTRACT_VERSION, self.scope)

        rolled_back = self.runner.rollback_to_legacy_read_only(self.scope)
        self.assertEqual(rolled_back.phase, Phase.ROLLED_BACK)
        self.assertEqual(rolled_back.cursor, checkpoint_before.cursor)
        self.assertFalse(self.port.new_route_active)
        self.assertTrue(self.port.legacy_read_only)
        self.assertEqual(self.port.appointments, appointments_before)
        self.assertEqual(self.port.ledger_entries, ledger_before)
        self.assertEqual(self.runner.rollback_to_legacy_read_only(self.scope), rolled_back)
        self.assertEqual(len(self.port.rollback_calls), 1)

    def test_orphan_foreign_key_and_amount_differences_block_cutover(self) -> None:
        self._reach_shadow_complete()
        self.port.orphan_fk_count = 1
        self.port.amount_difference = True
        with self.assertRaises(GateRejected) as raised:
            self.runner.compare_dual_read(self.scope)
        self.assertIn("orphan_fk_count", raised.exception.issues)
        self.assertIn("amount_or_currency_difference", raised.exception.issues)
        self.assertEqual(
            self.checkpoints.load(revision.CONTRACT_VERSION, self.scope).phase,
            Phase.SHADOW_COMPLETE,
        )
        with self.assertRaisesRegex(GateRejected, "canary_requires_verified_dual_read"):
            self.runner.activate_canary(self.scope, approved_evidence())
        self.assertEqual(self.port.canary_calls, [])

    def test_row_count_and_tenant_site_scope_differences_block_dual_read(self) -> None:
        self._reach_shadow_complete()
        self.port.count_difference = True
        self.port.scope_violation_count = 1
        with self.assertRaises(GateRejected) as raised:
            self.runner.compare_dual_read(self.scope)
        self.assertIn("row_count_difference", raised.exception.issues)
        self.assertIn("site_scope_violation_count", raised.exception.issues)

    def test_unresolved_quarantine_blocks_tenant_site_canary(self) -> None:
        self.port.quarantine_first_batch = True
        self._reach_dual_read()
        with self.assertRaisesRegex(GateRejected, "unresolved_quarantine_blocks_canary"):
            self.runner.activate_canary(self.scope, approved_evidence())
        self.assertEqual(self.port.canary_calls, [])

    def test_amount_fingerprint_preserves_precision_beyond_decimal_context(self) -> None:
        base = self.port.read_only_inventory(self.scope)
        precise = InventorySnapshot(
            scope=base.scope,
            schema_fingerprint=base.schema_fingerprint,
            source_watermark=base.source_watermark,
            row_counts=base.row_counts,
            amount_totals={
                "service_card_ledger|CNY": "1234567890123456789012345678901234"
            },
        )
        changed = InventorySnapshot(
            scope=base.scope,
            schema_fingerprint=base.schema_fingerprint,
            source_watermark=base.source_watermark,
            row_counts=base.row_counts,
            amount_totals={
                "service_card_ledger|CNY": "1234567890123456789012345678901235"
            },
        )
        self.assertNotEqual(precise.fingerprint(), changed.fingerprint())

    def test_source_inventory_drift_prevents_checkpoint_resume(self) -> None:
        self.runner.inventory(self.scope)
        self.port.counts["customer"] = 4
        with self.assertRaisesRegex(GateRejected, "source_snapshot_changed"):
            self.runner.inventory(self.scope)


if __name__ == "__main__":
    unittest.main()
