"""Wish service-card contract and append-only balance-ledger operations.

The ledger stores Wish service entitlements only. Commerce orders, refunds,
member points, and balances are external facts and are rejected as ledger
sources. Monetary and quantity balances are recomputed from signed entries.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import sqlite3
from typing import Final


CARD_TYPES: Final = frozenset({"STORED_VALUE", "DISCOUNT", "SESSION", "PACKAGE"})
LEDGER_ENTRY_TYPES: Final = frozenset(
    {"ISSUANCE", "CONSUMPTION", "REFUND_REVERSAL", "MANUAL_ADJUSTMENT"}
)
ALLOWED_SOURCE_TYPES: Final = frozenset(
    {"SERVICE_CARD_ISSUANCE", "SERVICE_CONSUMPTION", "SERVICE_REFUND", "MANUAL_ADJUSTMENT", "REVERSAL"}
)
CENT: Final = Decimal("0.01")
MILLIUNIT: Final = Decimal("0.001")


class CardLedgerError(ValueError):
    """A card ledger operation would violate its scoped financial contract."""


class IdempotencyConflict(CardLedgerError):
    """An idempotency key was reused with a different operation payload."""


class InsufficientCardBalance(CardLedgerError):
    """The requested debit would make a card dimension negative."""


class ReversalConflict(CardLedgerError):
    """A ledger entry already has a different reversal or is itself a reversal."""


def _active_card_currency(
    connection: sqlite3.Connection, tenant_id: str, site_id: str, card_id: str
) -> tuple[str, str]:
    row = connection.execute(
        "SELECT card_type, status, currency_code FROM fin_service_card "
        "WHERE tenant_id = ? AND site_id = ? AND card_id = ?",
        (tenant_id, site_id, card_id),
    ).fetchone()
    if row is None:
        raise CardLedgerError("card does not exist in the requested tenant/site")
    card_type, status, currency_code = row
    if card_type not in CARD_TYPES:
        raise CardLedgerError("unclassified legacy card is not eligible for ledger writes")
    if status != "ACTIVE":
        raise CardLedgerError("service card is not active")
    return str(card_type), str(currency_code)


@dataclass(frozen=True)
class ServiceCard:
    tenant_id: str
    site_id: str
    card_id: str
    customer_id: str
    card_type: str
    status: str
    currency_code: str
    rule_version: str | None = None

    def __post_init__(self) -> None:
        if self.card_type not in CARD_TYPES:
            raise ValueError(f"unsupported service-card type: {self.card_type}")
        if len(self.currency_code) != 3:
            raise ValueError("currency_code must be a three-character ISO code")


@dataclass(frozen=True)
class CardBalance:
    amount: Decimal
    units: Decimal
    unit_code: str | None
    currency_code: str


@dataclass(frozen=True)
class LedgerEntry:
    tenant_id: str
    site_id: str
    ledger_entry_id: str
    card_id: str
    entry_type: str
    delta_amount: Decimal
    currency_code: str
    idempotency_key_hash: str
    source_type: str
    source_id: str
    occurred_at: str
    created_at: str
    delta_units: Decimal = Decimal("0")
    unit_code: str | None = None
    benefit_code: str | None = None
    reversal_of: str | None = None


def _decimal(value: Decimal | int | str, quantum: Decimal) -> Decimal:
    try:
        original = Decimal(str(value))
        amount = original.quantize(quantum)
    except (InvalidOperation, ValueError) as exc:
        raise CardLedgerError("ledger amounts must be finite decimal values") from exc
    if not amount.is_finite() or amount != original:
        raise CardLedgerError("ledger amounts must be finite decimal values")
    precision = 18
    scale = abs(quantum.as_tuple().exponent)
    if abs(amount) >= Decimal(10) ** (precision - scale):
        raise CardLedgerError("ledger amount exceeds the DECIMAL(18,scale) range")
    return amount


def _validate_source(source_type: str) -> None:
    if source_type not in ALLOWED_SOURCE_TYPES or source_type.upper().startswith(("MER_", "COMMERCE_")):
        raise CardLedgerError("only Wish service-card/service/refund sources may enter this ledger")


def _validate_scope(tenant_id: str, site_id: str, card_id: str, currency_code: str) -> None:
    if not tenant_id or not site_id or not card_id:
        raise CardLedgerError("tenant, site, and card identifiers are required")
    if len(currency_code) != 3 or not currency_code.isalpha() or currency_code != currency_code.upper():
        raise CardLedgerError("currency_code must be a three-letter uppercase code")


def recompute_balance(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    site_id: str,
    card_id: str,
    benefit_code: str | None = None,
) -> CardBalance:
    """Recompute both value and quantity balances from immutable entries."""
    query = (
        "SELECT delta_amount, currency_code, delta_units, unit_code "
        "FROM fin_service_card_ledger "
        "WHERE tenant_id = ? AND site_id = ? AND card_id = ?"
    )
    params: tuple[object, ...] = (tenant_id, site_id, card_id)
    if benefit_code is not None:
        query += " AND benefit_code = ?"
        params += (benefit_code,)
    amount = Decimal("0.00")
    units = Decimal("0.000")
    currency: str | None = None
    unit_code: str | None = None
    for delta_amount, currency_code, delta_units, row_unit in connection.execute(query, params):
        if currency is not None and currency != currency_code:
            raise CardLedgerError("a card ledger cannot mix currencies")
        currency = currency_code
        amount += _decimal(delta_amount, CENT)
        units += _decimal(delta_units, MILLIUNIT)
        if row_unit is not None:
            if unit_code is not None and unit_code != row_unit:
                raise CardLedgerError("a benefit balance cannot mix unit codes")
            unit_code = row_unit
    return CardBalance(amount, units, unit_code, currency or "XXX")


def _existing_idempotent(
    connection: sqlite3.Connection, tenant_id: str, site_id: str, key_hash: str
) -> tuple[object, ...] | None:
    return connection.execute(
        "SELECT ledger_entry_id, card_id, entry_type, delta_amount, currency_code, "
        "delta_units, unit_code, benefit_code, source_type, source_id, reversal_of "
        "FROM fin_service_card_ledger "
        "WHERE tenant_id = ? AND site_id = ? AND idempotency_key_hash = ?",
        (tenant_id, site_id, key_hash),
    ).fetchone()


def _assert_matching_replay(existing: tuple[object, ...], expected: tuple[object, ...]) -> str:
    normalized = list(existing[1:])
    normalized[2] = str(_decimal(normalized[2], CENT))
    normalized[4] = str(_decimal(normalized[4], MILLIUNIT))
    if tuple(normalized) != expected:
        raise IdempotencyConflict("idempotency key is already bound to another ledger operation")
    return str(existing[0])


def record_consumption(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    site_id: str,
    card_id: str,
    ledger_entry_id: str,
    idempotency_key_hash: str,
    source_id: str,
    currency_code: str,
    occurred_at: str,
    created_at: str,
    delta_amount: Decimal | int | str = Decimal("0"),
    delta_units: Decimal | int | str = Decimal("0"),
    unit_code: str | None = None,
    benefit_code: str | None = None,
) -> str:
    """Append a scoped debit; a repeated identical key returns the first ID."""
    amount = _decimal(delta_amount, CENT)
    units = _decimal(delta_units, MILLIUNIT)
    _validate_scope(tenant_id, site_id, card_id, currency_code)
    if amount > 0 or units > 0 or (amount == 0 and units == 0 and benefit_code is None):
        raise CardLedgerError("consumption must debit at least one balance dimension")
    if units != 0 and not unit_code:
        raise CardLedgerError("unit-based consumption requires unit_code")
    if units != 0 and not benefit_code:
        raise CardLedgerError("unit-based consumption must be scoped to one card benefit")
    if len(idempotency_key_hash) < 32:
        raise CardLedgerError("idempotency key must be stored as a non-reversible hash")
    _validate_source("SERVICE_CONSUMPTION")
    expected = (
        card_id,
        "CONSUMPTION",
        str(amount),
        currency_code,
        str(units),
        unit_code,
        benefit_code,
        "SERVICE_CONSUMPTION",
        source_id,
        None,
    )
    with connection:
        replay = _existing_idempotent(connection, tenant_id, site_id, idempotency_key_hash)
        if replay is not None:
            return _assert_matching_replay(replay, expected)
        card_type, card_currency = _active_card_currency(connection, tenant_id, site_id, card_id)
        if card_currency != currency_code:
            raise CardLedgerError("consumption currency does not match the issued card")
        if card_type == "STORED_VALUE" and units != 0:
            raise CardLedgerError("stored-value cards cannot consume service-unit benefits")
        if card_type == "DISCOUNT" and amount != 0:
            raise CardLedgerError("discount cards record the discount benefit separately from stored value")
        if card_type in {"SESSION", "PACKAGE"} and amount != 0 and units != 0:
            raise CardLedgerError("mixed value and unit consumption requires separate benefit entries")
        balance = recompute_balance(
            connection,
            tenant_id=tenant_id,
            site_id=site_id,
            card_id=card_id,
            benefit_code=benefit_code,
        )
        if balance.amount + amount < 0 or balance.units + units < 0:
            raise InsufficientCardBalance("consumption exceeds the scoped card balance")
        connection.execute(
            "INSERT INTO fin_service_card_ledger ("
            "tenant_id, site_id, ledger_entry_id, card_id, entry_type, delta_amount, "
            "currency_code, source_type, source_id, reversal_of, idempotency_key_hash, "
            "delta_units, unit_code, benefit_code, occurred_at, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)",
            (
                tenant_id,
                site_id,
                ledger_entry_id,
                card_id,
                "CONSUMPTION",
                str(amount),
                currency_code,
                "SERVICE_CONSUMPTION",
                source_id,
                idempotency_key_hash,
                str(units),
                unit_code,
                benefit_code,
                occurred_at,
                created_at,
            ),
        )
    return ledger_entry_id


def record_issuance(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    site_id: str,
    card_id: str,
    ledger_entry_id: str,
    idempotency_key_hash: str,
    source_id: str,
    currency_code: str,
    occurred_at: str,
    created_at: str,
    delta_amount: Decimal | int | str = Decimal("0"),
    delta_units: Decimal | int | str = Decimal("0"),
    unit_code: str | None = None,
    benefit_code: str | None = None,
) -> str:
    """Append an initial Wish card grant; ``source_id`` is a Wish grant ID."""
    amount = _decimal(delta_amount, CENT)
    units = _decimal(delta_units, MILLIUNIT)
    _validate_scope(tenant_id, site_id, card_id, currency_code)
    if amount < 0 or units < 0 or (amount == 0 and units == 0 and benefit_code is None):
        raise CardLedgerError("issuance must grant a positive balance or a named benefit")
    if units != 0 and not unit_code:
        raise CardLedgerError("unit-based issuance requires unit_code")
    if units != 0 and not benefit_code:
        raise CardLedgerError("unit-based issuance must be scoped to one card benefit")
    if len(idempotency_key_hash) < 32:
        raise CardLedgerError("idempotency key must be stored as a non-reversible hash")
    _validate_source("SERVICE_CARD_ISSUANCE")
    expected = (
        card_id,
        "ISSUANCE",
        str(amount),
        currency_code,
        str(units),
        unit_code,
        benefit_code,
        "SERVICE_CARD_ISSUANCE",
        source_id,
        None,
    )
    with connection:
        replay = _existing_idempotent(connection, tenant_id, site_id, idempotency_key_hash)
        if replay is not None:
            return _assert_matching_replay(replay, expected)
        card_type, card_currency = _active_card_currency(connection, tenant_id, site_id, card_id)
        if card_currency != currency_code:
            raise CardLedgerError("issuance currency does not match the card")
        if card_type == "STORED_VALUE" and units != 0:
            raise CardLedgerError("stored-value cards cannot grant service-unit benefits")
        if card_type == "DISCOUNT" and amount != 0:
            raise CardLedgerError("discount-card benefits do not create a stored-value balance")
        connection.execute(
            "INSERT INTO fin_service_card_ledger ("
            "tenant_id, site_id, ledger_entry_id, card_id, entry_type, delta_amount, "
            "currency_code, source_type, source_id, reversal_of, idempotency_key_hash, "
            "delta_units, unit_code, benefit_code, occurred_at, created_at"
            ") VALUES (?, ?, ?, ?, 'ISSUANCE', ?, ?, 'SERVICE_CARD_ISSUANCE', ?, NULL, ?, ?, ?, ?, ?, ?)",
            (
                tenant_id, site_id, ledger_entry_id, card_id, str(amount), currency_code,
                source_id, idempotency_key_hash, str(units), unit_code, benefit_code,
                occurred_at, created_at,
            ),
        )
    return ledger_entry_id


def reverse_entry(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    site_id: str,
    original_entry_id: str,
    reversal_entry_id: str,
    refund_id: str,
    idempotency_key_hash: str,
    occurred_at: str,
    created_at: str,
) -> str:
    """Append one refund reversal; never edit or delete the original entry."""
    if len(idempotency_key_hash) < 32:
        raise CardLedgerError("idempotency key must be stored as a non-reversible hash")
    with connection:
        original = connection.execute(
            "SELECT card_id, entry_type, delta_amount, currency_code, delta_units, "
            "unit_code, benefit_code, reversal_of FROM fin_service_card_ledger "
            "WHERE tenant_id = ? AND site_id = ? AND ledger_entry_id = ?",
            (tenant_id, site_id, original_entry_id),
        ).fetchone()
        if original is None:
            raise CardLedgerError("original ledger entry is not present in this tenant/site")
        card_id, entry_type, delta_amount, currency, delta_units, unit_code, benefit_code, was_reversal = original
        _validate_scope(tenant_id, site_id, str(card_id), str(currency))
        if was_reversal is not None or entry_type == "REFUND_REVERSAL":
            raise ReversalConflict("a reversal cannot itself be reversed")
        existing_reversal = connection.execute(
            "SELECT ledger_entry_id, source_id, idempotency_key_hash FROM fin_service_card_ledger "
            "WHERE tenant_id = ? AND site_id = ? AND reversal_of = ?",
            (tenant_id, site_id, original_entry_id),
        ).fetchone()
        if existing_reversal is not None:
            if existing_reversal[1:] != (refund_id, idempotency_key_hash):
                raise ReversalConflict("original ledger entry already has another refund reversal")
            return str(existing_reversal[0])
        idem_replay = _existing_idempotent(connection, tenant_id, site_id, idempotency_key_hash)
        expected = (
            card_id,
            "REFUND_REVERSAL",
            str(-_decimal(delta_amount, CENT)),
            currency,
            str(-_decimal(delta_units, MILLIUNIT)),
            unit_code,
            benefit_code,
            "SERVICE_REFUND",
            refund_id,
            original_entry_id,
        )
        if idem_replay is not None:
            return _assert_matching_replay(idem_replay, expected)
        _validate_source("SERVICE_REFUND")
        connection.execute(
            "INSERT INTO fin_service_card_ledger ("
            "tenant_id, site_id, ledger_entry_id, card_id, entry_type, delta_amount, "
            "currency_code, source_type, source_id, reversal_of, idempotency_key_hash, "
            "delta_units, unit_code, benefit_code, occurred_at, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tenant_id,
                site_id,
                reversal_entry_id,
                card_id,
                "REFUND_REVERSAL",
                str(-_decimal(delta_amount, CENT)),
                currency,
                "SERVICE_REFUND",
                refund_id,
                original_entry_id,
                idempotency_key_hash,
                str(-_decimal(delta_units, MILLIUNIT)),
                unit_code,
                benefit_code,
                occurred_at,
                created_at,
            ),
        )
    return reversal_entry_id


# Test-only SQLite guard DDL. Production migration uses MySQL/MariaDB triggers.
SQLITE_APPEND_ONLY_GUARDS: Final = (
    "CREATE TRIGGER db05_ledger_source_guard BEFORE INSERT ON fin_service_card_ledger "
    "WHEN UPPER(NEW.source_type) LIKE 'MER_%' OR UPPER(NEW.source_type) LIKE 'COMMERCE_%' "
    "BEGIN SELECT RAISE(ABORT, 'Commerce facts cannot enter the Wish service ledger'); END",
    "CREATE TRIGGER db05_ledger_no_update BEFORE UPDATE ON fin_service_card_ledger "
    "BEGIN SELECT RAISE(ABORT, 'fin_service_card_ledger is append-only'); END",
    "CREATE TRIGGER db05_ledger_no_delete BEFORE DELETE ON fin_service_card_ledger "
    "BEGIN SELECT RAISE(ABORT, 'fin_service_card_ledger is append-only'); END",
)
