"""DB-06 staged migration orchestration contract.

This module has no database driver and executes no SQL. Deployments must
provide an approved ``MigrationPort`` and durable compare-and-swap
``CheckpointStore`` implementation. The in-memory test fixtures are the only
implementations in this repository.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import re
from typing import Mapping, Protocol

from domain.alembic.versions.db06_health_scrm_backfill import CONTRACT_VERSION


_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_AMOUNT_KEY = re.compile(r"^[a-z][a-z0-9_]*\|[A-Z]{3}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Phase(str, Enum):
    INVENTORY_COMPLETE = "inventory_complete"
    SHADOW_BACKFILL = "shadow_backfill"
    SHADOW_COMPLETE = "shadow_complete"
    DUAL_READ_VERIFIED = "dual_read_verified"
    CANARY_ACTIVE = "canary_active"
    ROLLED_BACK = "rolled_back"


class GateRejected(RuntimeError):
    """A data or approval gate failed; only safe metadata is included."""

    def __init__(self, issues: tuple[str, ...] | list[str]) -> None:
        self.issues = tuple(issues)
        super().__init__(", ".join(self.issues))


class CheckpointConflict(RuntimeError):
    """The durable checkpoint changed concurrently or uses another version."""


@dataclass(frozen=True, order=True)
class Scope:
    tenant_id: str
    site_id: str

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.site_id.strip():
            raise ValueError("tenant_id and site_id are required for every business scope")


def _normalise_counts(values: Mapping[str, int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, value in values.items():
        if not _KEY.fullmatch(key):
            raise ValueError("count keys must be stable logical dataset identifiers")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("counts must be non-negative integers")
        result[key] = value
    return dict(sorted(result.items()))


def _decimal_text(value: str | Decimal) -> str:
    if isinstance(value, float):
        raise ValueError("amount totals must not use binary floating-point values")
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("amount totals must be finite decimal values") from error
    if not amount.is_finite():
        raise ValueError("amount totals must be finite decimal values")
    if amount == 0:
        return "0"
    sign, digits, exponent = amount.as_tuple()
    significant_digits = list(digits)
    while significant_digits and significant_digits[-1] == 0:
        significant_digits.pop()
        exponent += 1
    return f"{sign}:{''.join(str(digit) for digit in significant_digits)}:{exponent}"


def _normalise_amounts(values: Mapping[str, str | Decimal]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in values.items():
        if not _AMOUNT_KEY.fullmatch(key):
            raise ValueError("amount keys must be logical_dataset|ISO_currency")
        result[key] = _decimal_text(value)
    return dict(sorted(result.items()))


def _snapshot_digest(
    scope: Scope,
    schema_fingerprint: str,
    source_watermark: str,
    row_counts: Mapping[str, int],
    amount_totals: Mapping[str, str | Decimal],
) -> str:
    if not _SHA256.fullmatch(schema_fingerprint):
        raise ValueError("schema_fingerprint must be a lowercase SHA-256 digest")
    if not source_watermark or len(source_watermark) > 256:
        raise ValueError("source_watermark must be a bounded, non-empty opaque value")
    payload = {
        "contract_version": CONTRACT_VERSION,
        "tenant_id": scope.tenant_id,
        "site_id": scope.site_id,
        "schema_fingerprint": schema_fingerprint,
        "source_watermark": source_watermark,
        "row_counts": _normalise_counts(row_counts),
        "amount_totals": _normalise_amounts(amount_totals),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class InventorySnapshot:
    """Read-only inventory summary; contains no row values or health payloads."""

    scope: Scope
    schema_fingerprint: str
    source_watermark: str
    row_counts: Mapping[str, int]
    amount_totals: Mapping[str, str | Decimal]

    def fingerprint(self) -> str:
        return _snapshot_digest(
            self.scope,
            self.schema_fingerprint,
            self.source_watermark,
            self.row_counts,
            self.amount_totals,
        )


@dataclass(frozen=True)
class BackfillBatch:
    """One idempotent shadow batch result with an opaque resume cursor."""

    next_cursor: str | None
    processed_rows: int
    copied_rows: int
    quarantined_rows: int
    has_more: bool

    def __post_init__(self) -> None:
        counts = (self.processed_rows, self.copied_rows, self.quarantined_rows)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
            raise ValueError("batch counters must be non-negative integers")
        if self.copied_rows + self.quarantined_rows > self.processed_rows:
            raise ValueError("copied and quarantined rows cannot exceed processed rows")
        if self.next_cursor is not None and (not self.next_cursor or len(self.next_cursor) > 256):
            raise ValueError("resume cursor must be a bounded opaque value")
        if self.has_more and (self.processed_rows == 0 or self.next_cursor is None):
            raise ValueError("a continuing batch must advance with a cursor")


@dataclass(frozen=True)
class ComparisonReport:
    """Aggregate-only dual-read comparison; never contains row-level values."""

    scope: Scope
    schema_fingerprint: str
    source_watermark: str
    legacy_counts: Mapping[str, int]
    shadow_counts: Mapping[str, int]
    legacy_amounts: Mapping[str, str | Decimal]
    shadow_amounts: Mapping[str, str | Decimal]
    orphan_fk_count: int
    site_scope_violation_count: int


@dataclass(frozen=True)
class ApprovalEvidence:
    """Required reviewed evidence references before tenant/site canary routing."""

    mapping_and_owner_review: str
    tenant_site_scope_review: str
    health_owner_approval: str
    backup_restore_exercise: str
    parity_signoff: str
    rollback_rehearsal: str

    def validate(self) -> None:
        if any(not value.strip() for value in self.__dict__.values()):
            raise GateRejected(("missing_canary_approval_evidence",))


@dataclass(frozen=True)
class Checkpoint:
    """Versioned per-tenant/site progress, stored with compare-and-swap."""

    contract_version: str
    scope: Scope
    source_fingerprint: str
    phase: Phase
    revision: int
    cursor: str | None = None
    batch_count: int = 0
    processed_rows: int = 0
    copied_rows: int = 0
    quarantined_rows: int = 0


class CheckpointStore(Protocol):
    def load(self, contract_version: str, scope: Scope) -> Checkpoint | None: ...

    def save(self, checkpoint: Checkpoint, *, expected_revision: int) -> None: ...


class MigrationPort(Protocol):
    """Semantic adapter contract; implementations are intentionally absent."""

    def read_only_inventory(self, scope: Scope) -> InventorySnapshot: ...

    def backfill_shadow_batch(
        self,
        scope: Scope,
        *,
        source_fingerprint: str,
        after_cursor: str | None,
        limit: int,
        idempotency_key: str,
    ) -> BackfillBatch: ...

    def compare_legacy_and_shadow(
        self, scope: Scope, *, source_fingerprint: str
    ) -> ComparisonReport: ...

    def activate_tenant_site_canary(
        self, scope: Scope, *, idempotency_key: str, evidence: ApprovalEvidence
    ) -> None: ...

    def restore_legacy_read_only_route(
        self, scope: Scope, *, idempotency_key: str
    ) -> None: ...


class HealthScrmBackfillRunner:
    """Advance one explicitly scoped migration through guarded stages.

    ``backfill_shadow_batch`` may be retried after an interruption. Ports must
    deduplicate the supplied idempotency key because a process can stop after
    the shadow effect but before the checkpoint's compare-and-swap succeeds.
    """

    def __init__(self, port: MigrationPort, checkpoints: CheckpointStore) -> None:
        self._port = port
        self._checkpoints = checkpoints

    def inventory(self, scope: Scope) -> Checkpoint:
        snapshot = self._port.read_only_inventory(scope)
        if snapshot.scope != scope:
            raise GateRejected(("inventory_scope_mismatch",))
        fingerprint = snapshot.fingerprint()
        current = self._load(scope)
        if current is not None:
            if current.source_fingerprint != fingerprint:
                raise GateRejected(("source_snapshot_changed_restart_with_reviewed_version",))
            return current
        checkpoint = Checkpoint(
            contract_version=CONTRACT_VERSION,
            scope=scope,
            source_fingerprint=fingerprint,
            phase=Phase.INVENTORY_COMPLETE,
            revision=1,
        )
        self._checkpoints.save(checkpoint, expected_revision=0)
        return checkpoint

    def backfill_shadow_batch(self, scope: Scope, *, limit: int = 500) -> Checkpoint:
        if limit <= 0:
            raise ValueError("batch limit must be positive")
        checkpoint = self._require(scope)
        if checkpoint.phase in (
            Phase.SHADOW_COMPLETE,
            Phase.DUAL_READ_VERIFIED,
            Phase.CANARY_ACTIVE,
            Phase.ROLLED_BACK,
        ):
            return checkpoint
        if checkpoint.phase not in (Phase.INVENTORY_COMPLETE, Phase.SHADOW_BACKFILL):
            raise GateRejected(("shadow_backfill_phase_invalid",))

        idempotency_key = self._operation_key("shadow", checkpoint, checkpoint.cursor)
        batch = self._port.backfill_shadow_batch(
            scope,
            source_fingerprint=checkpoint.source_fingerprint,
            after_cursor=checkpoint.cursor,
            limit=limit,
            idempotency_key=idempotency_key,
        )
        if batch.has_more and batch.next_cursor == checkpoint.cursor:
            raise GateRejected(("shadow_cursor_did_not_advance",))

        phase = Phase.SHADOW_BACKFILL if batch.has_more else Phase.SHADOW_COMPLETE
        updated = replace(
            checkpoint,
            phase=phase,
            revision=checkpoint.revision + 1,
            cursor=batch.next_cursor,
            batch_count=checkpoint.batch_count + 1,
            processed_rows=checkpoint.processed_rows + batch.processed_rows,
            copied_rows=checkpoint.copied_rows + batch.copied_rows,
            quarantined_rows=checkpoint.quarantined_rows + batch.quarantined_rows,
        )
        self._checkpoints.save(updated, expected_revision=checkpoint.revision)
        return updated

    def compare_dual_read(self, scope: Scope) -> Checkpoint:
        checkpoint = self._require(scope)
        if checkpoint.phase in (Phase.DUAL_READ_VERIFIED, Phase.CANARY_ACTIVE, Phase.ROLLED_BACK):
            return checkpoint
        if checkpoint.phase != Phase.SHADOW_COMPLETE:
            raise GateRejected(("dual_read_requires_complete_shadow",))

        report = self._port.compare_legacy_and_shadow(
            scope, source_fingerprint=checkpoint.source_fingerprint
        )
        issues = self._comparison_issues(scope, checkpoint, report)
        if issues:
            raise GateRejected(issues)
        updated = replace(
            checkpoint,
            phase=Phase.DUAL_READ_VERIFIED,
            revision=checkpoint.revision + 1,
        )
        self._checkpoints.save(updated, expected_revision=checkpoint.revision)
        return updated

    def activate_canary(self, scope: Scope, evidence: ApprovalEvidence) -> Checkpoint:
        checkpoint = self._require(scope)
        if checkpoint.phase in (Phase.CANARY_ACTIVE, Phase.ROLLED_BACK):
            return checkpoint
        if checkpoint.phase != Phase.DUAL_READ_VERIFIED:
            raise GateRejected(("canary_requires_verified_dual_read",))
        evidence.validate()
        if checkpoint.quarantined_rows:
            raise GateRejected(("unresolved_quarantine_blocks_canary",))

        idempotency_key = self._operation_key("canary", checkpoint, None)
        self._port.activate_tenant_site_canary(
            scope, idempotency_key=idempotency_key, evidence=evidence
        )
        updated = replace(
            checkpoint,
            phase=Phase.CANARY_ACTIVE,
            revision=checkpoint.revision + 1,
        )
        self._checkpoints.save(updated, expected_revision=checkpoint.revision)
        return updated

    def rollback_to_legacy_read_only(self, scope: Scope) -> Checkpoint:
        checkpoint = self._require(scope)
        if checkpoint.phase == Phase.ROLLED_BACK:
            return checkpoint
        if checkpoint.phase != Phase.CANARY_ACTIVE:
            raise GateRejected(("rollback_requires_active_tenant_site_canary",))

        idempotency_key = self._operation_key("rollback", checkpoint, None)
        self._port.restore_legacy_read_only_route(scope, idempotency_key=idempotency_key)
        updated = replace(
            checkpoint,
            phase=Phase.ROLLED_BACK,
            revision=checkpoint.revision + 1,
        )
        self._checkpoints.save(updated, expected_revision=checkpoint.revision)
        return updated

    def _load(self, scope: Scope) -> Checkpoint | None:
        checkpoint = self._checkpoints.load(CONTRACT_VERSION, scope)
        if checkpoint is not None and checkpoint.contract_version != CONTRACT_VERSION:
            raise CheckpointConflict("checkpoint contract version differs; use a reviewed new version")
        if checkpoint is not None and checkpoint.scope != scope:
            raise CheckpointConflict("checkpoint scope differs from requested tenant/site")
        return checkpoint

    def _require(self, scope: Scope) -> Checkpoint:
        checkpoint = self._load(scope)
        if checkpoint is None:
            raise GateRejected(("read_only_inventory_required",))
        return checkpoint

    @staticmethod
    def _operation_key(operation: str, checkpoint: Checkpoint, cursor: str | None) -> str:
        value = "|".join(
            (
                checkpoint.contract_version,
                operation,
                checkpoint.scope.tenant_id,
                checkpoint.scope.site_id,
                checkpoint.source_fingerprint,
                cursor or "<start>",
            )
        )
        return "db06:" + hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _comparison_issues(
        scope: Scope, checkpoint: Checkpoint, report: ComparisonReport
    ) -> tuple[str, ...]:
        issues: list[str] = []
        if report.scope != scope:
            issues.append("comparison_scope_mismatch")
        try:
            source_fingerprint = _snapshot_digest(
                scope,
                report.schema_fingerprint,
                report.source_watermark,
                report.legacy_counts,
                report.legacy_amounts,
            )
        except ValueError:
            issues.append("comparison_inventory_summary_invalid")
            source_fingerprint = ""
        if source_fingerprint != checkpoint.source_fingerprint:
            issues.append("source_inventory_changed_since_checkpoint")

        try:
            legacy_counts = _normalise_counts(report.legacy_counts)
            shadow_counts = _normalise_counts(report.shadow_counts)
            if legacy_counts != shadow_counts:
                issues.append("row_count_difference")
            legacy_amounts = _normalise_amounts(report.legacy_amounts)
            shadow_amounts = _normalise_amounts(report.shadow_amounts)
            if legacy_amounts != shadow_amounts:
                issues.append("amount_or_currency_difference")
        except ValueError:
            issues.append("comparison_metrics_invalid")

        for name, value in (
            ("orphan_fk_count", report.orphan_fk_count),
            ("site_scope_violation_count", report.site_scope_violation_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                issues.append("comparison_metrics_invalid")
            elif value:
                issues.append(name)
        return tuple(dict.fromkeys(issues))
