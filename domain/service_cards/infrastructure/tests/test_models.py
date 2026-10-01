from __future__ import annotations

from decimal import Decimal
import sqlite3
import unittest

from domain.service_cards.infrastructure.models import (
    CardLedgerError,
    IdempotencyConflict,
    InsufficientCardBalance,
    ReversalConflict,
    SQLITE_APPEND_ONLY_GUARDS,
    record_consumption,
    record_issuance,
    recompute_balance,
    reverse_entry,
)


def make_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE plat_site (
          tenant_id TEXT NOT NULL, site_id TEXT NOT NULL,
          PRIMARY KEY (tenant_id, site_id)
        );
        CREATE TABLE crm_customer (
          tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL,
          PRIMARY KEY (tenant_id, customer_id)
        );
        CREATE TABLE svc_appointment (
          tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, appointment_id TEXT NOT NULL,
          PRIMARY KEY (tenant_id, site_id, appointment_id),
          FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT
        );
        CREATE TABLE fin_service_card (
          tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, card_id TEXT NOT NULL,
          customer_id TEXT NOT NULL, balance_cache_amount TEXT NOT NULL DEFAULT '0',
          card_type TEXT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE', currency_code TEXT NOT NULL DEFAULT 'USD',
          PRIMARY KEY (tenant_id, site_id, card_id),
          FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT,
          FOREIGN KEY (tenant_id, customer_id) REFERENCES crm_customer (tenant_id, customer_id) ON DELETE RESTRICT
        );
        CREATE TABLE fin_service_card_ledger (
          tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, ledger_entry_id TEXT NOT NULL,
          card_id TEXT NOT NULL, entry_type TEXT NOT NULL,
          delta_amount TEXT NOT NULL DEFAULT '0.00', currency_code TEXT NOT NULL,
          source_type TEXT NOT NULL, source_id TEXT NOT NULL, reversal_of TEXT NULL,
          idempotency_key_hash TEXT NOT NULL, delta_units TEXT NOT NULL DEFAULT '0.000',
          unit_code TEXT NULL, benefit_code TEXT NULL, aggregate_version INTEGER NOT NULL DEFAULT 1,
          occurred_at TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY (tenant_id, site_id, ledger_entry_id),
          UNIQUE (tenant_id, site_id, idempotency_key_hash),
          UNIQUE (tenant_id, site_id, source_type, source_id, entry_type),
          UNIQUE (tenant_id, site_id, reversal_of),
          FOREIGN KEY (tenant_id, site_id, card_id) REFERENCES fin_service_card (tenant_id, site_id, card_id) ON DELETE RESTRICT,
          FOREIGN KEY (tenant_id, site_id, reversal_of) REFERENCES fin_service_card_ledger (tenant_id, site_id, ledger_entry_id) ON DELETE RESTRICT
        );
        CREATE TABLE svc_service_note (
          tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, service_note_id TEXT NOT NULL,
          appointment_id TEXT NOT NULL,
          PRIMARY KEY (tenant_id, site_id, service_note_id),
          FOREIGN KEY (tenant_id, site_id, appointment_id) REFERENCES svc_appointment (tenant_id, site_id, appointment_id) ON DELETE RESTRICT
        );
        INSERT INTO plat_site VALUES ('tenant-a', 'site-a'), ('tenant-a', 'site-b');
        INSERT INTO crm_customer VALUES ('tenant-a', 'customer-a');
        INSERT INTO fin_service_card (tenant_id, site_id, card_id, customer_id, balance_cache_amount, card_type)
          VALUES ('tenant-a', 'site-a', 'card-a', 'customer-a', '999999.99', 'STORED_VALUE');
        INSERT INTO svc_appointment VALUES ('tenant-a', 'site-a', 'appointment-a');
        """
    )
    for statement in SQLITE_APPEND_ONLY_GUARDS:
        connection.execute(statement)
    return connection


def insert_ledger(
    connection: sqlite3.Connection,
    *,
    entry_id: str,
    entry_type: str,
    amount: str,
    units: str = "0.000",
    unit_code: str | None = None,
    benefit_code: str | None = None,
    source_type: str = "SERVICE_CARD_ISSUANCE",
    source_id: str | None = None,
    idem: str | None = None,
    reversal_of: str | None = None,
) -> None:
    connection.execute(
        "INSERT INTO fin_service_card_ledger (tenant_id, site_id, ledger_entry_id, card_id, "
        "entry_type, delta_amount, currency_code, source_type, source_id, reversal_of, "
        "idempotency_key_hash, delta_units, unit_code, benefit_code, occurred_at, created_at) "
        "VALUES ('tenant-a','site-a',?,'card-a',?,?,'USD',?,?,?,?,?,?,?,?,?)",
        (
            entry_id, entry_type, amount, source_type, source_id or entry_id, reversal_of,
            idem or f"hash-{entry_id}-" + "x" * 40, units, unit_code, benefit_code,
            "2026-10-02T10:00:00Z", "2026-10-02T10:00:00Z",
        ),
    )


class ServiceCardLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = make_connection()

    def tearDown(self) -> None:
        self.connection.close()

    def test_balance_is_recomputed_from_entries_not_cache(self) -> None:
        insert_ledger(
            self.connection,
            entry_id="issue-a",
            entry_type="ISSUANCE",
            amount="100.00",
            units="10.000",
            unit_code="SESSION",
            benefit_code="massage",
        )
        insert_ledger(
            self.connection,
            entry_id="issue-b",
            entry_type="ISSUANCE",
            amount="5.50",
            source_id="issue-b-source",
        )
        balance = recompute_balance(
            self.connection,
            tenant_id="tenant-a",
            site_id="site-a",
            card_id="card-a",
            benefit_code="massage",
        )
        self.assertEqual(Decimal("100.00"), balance.amount)
        self.assertEqual(Decimal("10.000"), balance.units)
        self.assertEqual("SESSION", balance.unit_code)
        self.assertEqual("USD", balance.currency_code)

    def test_four_card_types_and_unit_balance_are_supported(self) -> None:
        from domain.service_cards.infrastructure.models import ServiceCard

        for card_type in ("STORED_VALUE", "DISCOUNT", "SESSION", "PACKAGE"):
            self.assertEqual(card_type, ServiceCard(
                "tenant-a", "site-a", f"card-{card_type}", "customer-a", card_type,
                "ACTIVE", "USD",
            ).card_type)
        self.connection.execute(
            "UPDATE fin_service_card SET card_type = 'SESSION' WHERE card_id = 'card-a'"
        )
        grant = dict(
            tenant_id="tenant-a", site_id="site-a", card_id="card-a",
            ledger_entry_id="session-grant", idempotency_key_hash="idem-" + "f" * 48,
            source_id="wish-grant-1", currency_code="USD",
            occurred_at="2026-10-02T09:00:00Z", created_at="2026-10-02T09:00:00Z",
            delta_units="8", unit_code="SESSION", benefit_code="therapy",
        )
        self.assertEqual("session-grant", record_issuance(self.connection, **grant))
        self.assertEqual("session-grant", record_issuance(self.connection, **grant))
        usage = dict(
            tenant_id="tenant-a", site_id="site-a", card_id="card-a",
            ledger_entry_id="session-use", idempotency_key_hash="idem-" + "g" * 48,
            source_id="service-consumption-1", currency_code="USD",
            occurred_at="2026-10-02T10:00:00Z", created_at="2026-10-02T10:00:00Z",
            delta_units="-1", unit_code="SESSION", benefit_code="therapy",
        )
        record_consumption(self.connection, **usage)
        balance = recompute_balance(
            self.connection, tenant_id="tenant-a", site_id="site-a", card_id="card-a", benefit_code="therapy"
        )
        self.assertEqual(Decimal("7.000"), balance.units)

    def test_consumption_is_idempotent_and_cannot_overdraw(self) -> None:
        insert_ledger(self.connection, entry_id="issue", entry_type="ISSUANCE", amount="100.00")
        kwargs = dict(
            tenant_id="tenant-a", site_id="site-a", card_id="card-a",
            ledger_entry_id="use-1", idempotency_key_hash="idem-" + "a" * 48,
            source_id="appointment-a", currency_code="USD",
            occurred_at="2026-10-02T11:00:00Z", created_at="2026-10-02T11:00:00Z",
            delta_amount="-20.00",
        )
        self.assertEqual("use-1", record_consumption(self.connection, **kwargs))
        self.assertEqual("use-1", record_consumption(self.connection, **kwargs))
        count = self.connection.execute(
            "SELECT COUNT(*) FROM fin_service_card_ledger WHERE entry_type = 'CONSUMPTION'"
        ).fetchone()[0]
        self.assertEqual(1, count)
        balance = recompute_balance(
            self.connection, tenant_id="tenant-a", site_id="site-a", card_id="card-a"
        )
        self.assertEqual(Decimal("80.00"), balance.amount)

        with self.assertRaises(InsufficientCardBalance):
            record_consumption(
                self.connection,
                **{**kwargs, "ledger_entry_id": "use-too-much", "idempotency_key_hash": "idem-" + "b" * 48, "delta_amount": "-81.00"},
            )
        with self.assertRaises(IdempotencyConflict):
            record_consumption(self.connection, **{**kwargs, "source_id": "another-source"})

    def test_refund_appends_one_opposite_entry_and_preserves_consumption(self) -> None:
        insert_ledger(self.connection, entry_id="issue", entry_type="ISSUANCE", amount="40.00")
        consumption_id = record_consumption(
            self.connection,
            tenant_id="tenant-a", site_id="site-a", card_id="card-a",
            ledger_entry_id="use-1", idempotency_key_hash="idem-" + "c" * 48,
            source_id="appointment-a", currency_code="USD",
            occurred_at="2026-10-02T11:00:00Z", created_at="2026-10-02T11:00:00Z",
            delta_amount="-12.50",
        )
        kwargs = dict(
            tenant_id="tenant-a", site_id="site-a", original_entry_id=consumption_id,
            reversal_entry_id="refund-1", refund_id="wish-refund-1",
            idempotency_key_hash="idem-" + "d" * 48,
            occurred_at="2026-10-02T12:00:00Z", created_at="2026-10-02T12:00:00Z",
        )
        self.assertEqual("refund-1", reverse_entry(self.connection, **kwargs))
        self.assertEqual("refund-1", reverse_entry(self.connection, **kwargs))
        balance = recompute_balance(
            self.connection, tenant_id="tenant-a", site_id="site-a", card_id="card-a"
        )
        self.assertEqual(Decimal("40.00"), balance.amount)
        self.assertIsNone(self.connection.execute(
            "SELECT reversal_of FROM fin_service_card_ledger WHERE ledger_entry_id = 'use-1'"
        ).fetchone()[0])
        self.assertEqual(3, self.connection.execute(
            "SELECT COUNT(*) FROM fin_service_card_ledger WHERE card_id = 'card-a'"
        ).fetchone()[0])  # issue + consumption + reversal
        with self.assertRaises(ReversalConflict):
            reverse_entry(self.connection, **{**kwargs, "refund_id": "wish-refund-2", "idempotency_key_hash": "idem-" + "e" * 48})

    def test_cross_site_card_and_service_note_foreign_keys_are_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO fin_service_card_ledger (tenant_id, site_id, ledger_entry_id, card_id, "
                "entry_type, delta_amount, currency_code, source_type, source_id, idempotency_key_hash, occurred_at, created_at) "
                "VALUES ('tenant-a','site-b','bad-ledger','card-a','CONSUMPTION','-1','USD','SERVICE_CONSUMPTION','a','hash-bad-" + "z" * 32 + "','now','now')"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO svc_service_note (tenant_id, site_id, service_note_id, appointment_id) "
                "VALUES ('tenant-a','site-b','bad-note','appointment-a')"
            )

    def test_ledger_rows_cannot_be_updated_or_deleted(self) -> None:
        insert_ledger(self.connection, entry_id="issue", entry_type="ISSUANCE", amount="10.00")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE fin_service_card_ledger SET delta_amount = '500.00' WHERE ledger_entry_id = 'issue'"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("DELETE FROM fin_service_card_ledger WHERE ledger_entry_id = 'issue'")
        self.assertEqual(Decimal("10.00"), recompute_balance(
            self.connection, tenant_id="tenant-a", site_id="site-a", card_id="card-a"
        ).amount)

    def test_commerce_sources_are_not_accepted_as_wish_ledger_facts(self) -> None:
        with self.assertRaises(CardLedgerError):
            from domain.service_cards.infrastructure.models import _validate_source

            _validate_source("MER_ORDER")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO fin_service_card_ledger (tenant_id, site_id, ledger_entry_id, card_id, "
                "entry_type, delta_amount, currency_code, source_type, source_id, idempotency_key_hash, occurred_at, created_at) "
                "VALUES ('tenant-a','site-a','commerce-row','card-a','ISSUANCE','12.00','USD','MER_ORDER','order-1','hash-commerce-" + "z" * 32 + "','now','now')"
            )


if __name__ == "__main__":
    unittest.main()
