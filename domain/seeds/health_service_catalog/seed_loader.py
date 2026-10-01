"""Import DB-07 seed JSON into an in-memory SQLite verification fixture only.

This module is not a migration and intentionally refuses file-backed SQLite
connections. It exists to exercise deterministic seed, scope, publication-gate,
snapshot, and rollback behavior without opening any application database.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping


SEED_DIR = Path(__file__).parent
TENANT_SITE_SEED = SEED_DIR.parent / "tenant_site" / "seed.json"
HEALTH_CATALOG_SEED = SEED_DIR / "seed.json"

SERVICE_NAMES = (
    "3R AI生命力健康评估",
    "VISTRI 三合一智能体测",
    "红外线热能理疗（光舱）",
    "微高压富氧调理（氧舱）",
    "水感律动理疗（水疗床）",
    "3R情绪减压/睡眠养护/疲劳缓解",
    "3R舒缓解压疗愈",
    "3R专项康复疗愈",
    "AI智能健身训练",
)

_ROLLBACK_ORDER = (
    "svc_service_version",
    "svc_service_item",
    "plat_site",
    "plat_tenant",
)


class SyntheticFixtureRequired(RuntimeError):
    """Raised when a caller tries to use a persistent or non-SQLite database."""


class SeedConflict(RuntimeError):
    """Raised if an existing natural key has content different from this seed."""


class SeedRollbackBlocked(RuntimeError):
    """Raised when a DB-07 row is referenced by retained fixture facts."""


class PublicationBlocked(ValueError):
    """Raised until required facts and explicit approval exist for publication."""


class BookingBlocked(ValueError):
    """Raised when a service version is not approved, published, and active."""


class SiteScopeDenied(PermissionError):
    """Raised if a caller tries to select a site outside its resolved scope."""


def _assert_memory_sqlite(connection: sqlite3.Connection) -> None:
    if not isinstance(connection, sqlite3.Connection):
        raise SyntheticFixtureRequired("DB-07 accepts only sqlite3.Connection fixtures")
    databases = connection.execute("PRAGMA database_list").fetchall()
    main = next((row for row in databases if row[1] == "main"), None)
    if main is None or main[2] != "" or any(row[1] not in {"main", "temp"} for row in databases):
        raise SyntheticFixtureRequired("DB-07 refuses file-backed or attached databases")


def open_synthetic_fixture() -> sqlite3.Connection:
    """Create the isolated in-memory SQLite fixture used by DB-07 tests."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    create_synthetic_schema(connection)
    return connection


def create_synthetic_schema(connection: sqlite3.Connection) -> None:
    """Create minimal fixture tables; this does not execute application DDL."""
    _assert_memory_sqlite(connection)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS plat_tenant (
            tenant_id TEXT PRIMARY KEY,
            tenant_code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plat_site (
            tenant_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            site_code TEXT NOT NULL,
            name TEXT NOT NULL,
            timezone TEXT,
            status TEXT NOT NULL,
            PRIMARY KEY (tenant_id, site_id),
            UNIQUE (tenant_id, site_code),
            FOREIGN KEY (tenant_id) REFERENCES plat_tenant (tenant_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS svc_service_item (
            tenant_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            service_id TEXT NOT NULL,
            service_code TEXT NOT NULL,
            name TEXT NOT NULL,
            service_type TEXT,
            status TEXT NOT NULL,
            PRIMARY KEY (tenant_id, site_id, service_id),
            UNIQUE (tenant_id, site_id, service_code),
            FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS svc_service_version (
            tenant_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            service_version_id TEXT NOT NULL,
            service_id TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            status TEXT NOT NULL,
            approval_status TEXT NOT NULL,
            publication_status TEXT NOT NULL,
            description TEXT,
            duration_minutes INTEGER,
            price_amount TEXT,
            currency_code TEXT,
            eligibility_rule_version TEXT,
            qualification_requirements_json TEXT,
            service_location_ids_json TEXT,
            capacity_policy_version TEXT,
            preparation TEXT,
            onsite_rules_version TEXT,
            cancellation_policy_version TEXT,
            effective_from TEXT,
            effective_to TEXT,
            approved_at TEXT,
            published_at TEXT,
            PRIMARY KEY (tenant_id, site_id, service_version_id),
            UNIQUE (tenant_id, site_id, service_id, version_no),
            FOREIGN KEY (tenant_id, site_id, service_id)
                REFERENCES svc_service_item (tenant_id, site_id, service_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS svc_appointment (
            tenant_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            appointment_id TEXT NOT NULL,
            service_version_id TEXT NOT NULL,
            status TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            PRIMARY KEY (tenant_id, site_id, appointment_id),
            FOREIGN KEY (tenant_id, site_id, service_version_id)
                REFERENCES svc_service_version (tenant_id, site_id, service_version_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS db07_seed_manifest (
            seed_id TEXT NOT NULL,
            table_name TEXT NOT NULL,
            key_json TEXT NOT NULL,
            PRIMARY KEY (seed_id, table_name, key_json)
        );
        CREATE TABLE IF NOT EXISTS db07_scope_fixture (
            tenant_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('customer', 'resource', 'ledger')),
            fixture_key TEXT NOT NULL,
            PRIMARY KEY (tenant_id, site_id, kind, fixture_key),
            FOREIGN KEY (tenant_id, site_id) REFERENCES plat_site (tenant_id, site_id) ON DELETE RESTRICT
        );
        """
    )


def _read_payload(payload: Mapping[str, Any] | str | Path | None, default_path: Path) -> dict[str, Any]:
    if payload is None:
        source: Any = json.loads(default_path.read_text(encoding="utf-8"))
    elif isinstance(payload, (str, Path)):
        source = json.loads(Path(payload).read_text(encoding="utf-8"))
    else:
        source = dict(payload)
    if not isinstance(source, dict):
        raise ValueError(f"seed payload must be a JSON object: {default_path}")
    return source


def _validate_payloads(tenant_seed: Mapping[str, Any], catalog_seed: Mapping[str, Any]) -> None:
    tenant = tenant_seed.get("tenant", {})
    sites = tenant_seed.get("sites", [])
    site_codes = {site.get("site_code") for site in sites}
    services = catalog_seed.get("services", [])
    names = tuple(service.get("name") for service in services)
    if not tenant_seed.get("seed_id") or not catalog_seed.get("seed_id"):
        raise ValueError("both DB-07 seed payloads must declare seed_id")
    if tenant.get("tenant_code") != "tenant-demo" or site_codes != {"site-a", "site-b"}:
        raise ValueError("DB-07 seed must contain tenant-demo with exactly site-a and site-b")
    if catalog_seed.get("tenant_code") != "tenant-demo" or catalog_seed.get("site_code") != "site-a":
        raise ValueError("the nine-service catalog belongs only to tenant-demo/site-a")
    if names != SERVICE_NAMES:
        raise ValueError("Phoenix Valley service names/order must match the approved source text exactly")
    if any(len(service.get("versions", [])) != 1 for service in services):
        raise ValueError("initial DB-07 seed must contain one immutable draft version per service")
    for service in services:
        version = service["versions"][0]
        if version.get("approval_status") != "pending" or version.get("publication_status") != "unpublished":
            raise ValueError("initial seeded service versions must remain unapproved and unpublished")


def _json_or_none(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _ensure_row(
    connection: sqlite3.Connection,
    *,
    seed_id: str,
    table: str,
    row: Mapping[str, Any],
    key_columns: tuple[str, ...],
) -> None:
    where = " AND ".join(f"{column} = ?" for column in key_columns)
    key_values = tuple(row[column] for column in key_columns)
    existing = connection.execute(f"SELECT * FROM {table} WHERE {where}", key_values).fetchone()
    if existing is not None:
        mismatches = [column for column, value in row.items() if existing[column] != value]
        if mismatches:
            raise SeedConflict(f"{table} key {key_values!r} differs in fields: {', '.join(mismatches)}")
        return

    columns = tuple(row)
    placeholders = ", ".join("?" for _ in columns)
    try:
        connection.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(row[column] for column in columns),
        )
    except sqlite3.IntegrityError as exc:
        raise SeedConflict(f"conflicting natural key for {table} row {key_values!r}: {exc}") from exc
    key_json = json.dumps({column: row[column] for column in key_columns}, sort_keys=True, separators=(",", ":"))
    connection.execute(
        "INSERT OR IGNORE INTO db07_seed_manifest (seed_id, table_name, key_json) VALUES (?, ?, ?)",
        (seed_id, table, key_json),
    )


def apply_seed(
    connection: sqlite3.Connection,
    *,
    tenant_seed: Mapping[str, Any] | str | Path | None = None,
    catalog_seed: Mapping[str, Any] | str | Path | None = None,
) -> None:
    """Idempotently add the two sites and nine draft service versions."""
    _assert_memory_sqlite(connection)
    tenant_data = _read_payload(tenant_seed, TENANT_SITE_SEED)
    catalog_data = _read_payload(catalog_seed, HEALTH_CATALOG_SEED)
    _validate_payloads(tenant_data, catalog_data)
    tenant_seed_id = tenant_data["seed_id"]
    catalog_seed_id = catalog_data["seed_id"]
    tenant = tenant_data["tenant"]
    sites_by_code = {site["site_code"]: site for site in tenant_data["sites"]}
    site = sites_by_code[catalog_data["site_code"]]

    connection.execute("SAVEPOINT db07_apply_seed")
    try:
        _ensure_row(
            connection,
            seed_id=tenant_seed_id,
            table="plat_tenant",
            row={
                "tenant_id": tenant["tenant_id"],
                "tenant_code": tenant["tenant_code"],
                "name": tenant["name"],
                "status": tenant["status"],
            },
            key_columns=("tenant_id",),
        )
        for site_data in tenant_data["sites"]:
            _ensure_row(
                connection,
                seed_id=tenant_seed_id,
                table="plat_site",
                row={
                    "tenant_id": tenant["tenant_id"],
                    "site_id": site_data["site_id"],
                    "site_code": site_data["site_code"],
                    "name": site_data["name"],
                    "timezone": site_data.get("timezone"),
                    "status": site_data["status"],
                },
                key_columns=("tenant_id", "site_id"),
            )

        for service in catalog_data["services"]:
            _ensure_row(
                connection,
                seed_id=catalog_seed_id,
                table="svc_service_item",
                row={
                    "tenant_id": tenant["tenant_id"],
                    "site_id": site["site_id"],
                    "service_id": service["service_id"],
                    "service_code": service["service_code"],
                    "name": service["name"],
                    "service_type": service.get("service_type"),
                    "status": service["status"],
                },
                key_columns=("tenant_id", "site_id", "service_id"),
            )
            for version in service["versions"]:
                _ensure_row(
                    connection,
                    seed_id=catalog_seed_id,
                    table="svc_service_version",
                    row={
                        "tenant_id": tenant["tenant_id"],
                        "site_id": site["site_id"],
                        "service_version_id": version["service_version_id"],
                        "service_id": service["service_id"],
                        "version_no": version["version_no"],
                        "status": version["status"],
                        "approval_status": version["approval_status"],
                        "publication_status": version["publication_status"],
                        "description": version.get("description"),
                        "duration_minutes": version.get("duration_minutes"),
                        "price_amount": version.get("price_amount"),
                        "currency_code": version.get("currency_code"),
                        "eligibility_rule_version": version.get("eligibility_rule_version"),
                        "qualification_requirements_json": _json_or_none(version.get("qualification_requirements")),
                        "service_location_ids_json": _json_or_none(version.get("service_location_ids")),
                        "capacity_policy_version": version.get("capacity_policy_version"),
                        "preparation": version.get("preparation"),
                        "onsite_rules_version": version.get("onsite_rules_version"),
                        "cancellation_policy_version": version.get("cancellation_policy_version"),
                        "effective_from": version.get("effective_from"),
                        "effective_to": version.get("effective_to"),
                        "approved_at": version.get("approved_at"),
                        "published_at": version.get("published_at"),
                    },
                    key_columns=("tenant_id", "site_id", "service_version_id"),
                )
        connection.execute("RELEASE SAVEPOINT db07_apply_seed")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT db07_apply_seed")
        connection.execute("RELEASE SAVEPOINT db07_apply_seed")
        raise


_PUBLICATION_REQUIRED_FIELDS = (
    "duration_minutes",
    "price_amount",
    "currency_code",
    "eligibility_rule_version",
    "qualification_requirements_json",
    "service_location_ids_json",
    "capacity_policy_version",
    "preparation",
    "onsite_rules_version",
    "cancellation_policy_version",
    "effective_from",
)


def publication_blockers(version: Mapping[str, Any]) -> tuple[str, ...]:
    """List missing approval/configuration inputs; no values are inferred here."""
    blockers: list[str] = []
    if version.get("approval_status") != "approved":
        blockers.append("approval_status")
    blockers.extend(field for field in _PUBLICATION_REQUIRED_FIELDS if version.get(field) is None)
    return tuple(blockers)


def require_publishable(version: Mapping[str, Any]) -> None:
    blockers = publication_blockers(version)
    if blockers:
        raise PublicationBlocked("service version is not publishable; pending: " + ", ".join(blockers))


def require_bookable(service: Mapping[str, Any], version: Mapping[str, Any]) -> None:
    if service.get("status") != "active":
        raise BookingBlocked("service item is not active")
    if version.get("status") != "published":
        raise BookingBlocked("service version is not published")
    if version.get("approval_status") != "approved":
        raise BookingBlocked("service version has no explicit approval")
    if version.get("publication_status") != "published":
        raise BookingBlocked("service version publication is not active")
    require_publishable(version)


def read_scoped_fixture(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    authorized_site_id: str,
    kind: str,
    requested_site_id: str | None = None,
) -> list[sqlite3.Row]:
    """Read only a test fixture within the server-resolved tenant/site scope."""
    _assert_memory_sqlite(connection)
    if kind not in {"customer", "resource", "ledger"}:
        raise ValueError(f"unsupported isolation fixture kind: {kind}")
    if requested_site_id is not None and requested_site_id != authorized_site_id:
        raise SiteScopeDenied("requested site is outside the resolved authorization scope")
    return connection.execute(
        "SELECT * FROM db07_scope_fixture WHERE tenant_id = ? AND site_id = ? AND kind = ? ORDER BY fixture_key",
        (tenant_id, authorized_site_id, kind),
    ).fetchall()


def _manifest_rows(connection: sqlite3.Connection, seed_ids: tuple[str, ...]) -> list[sqlite3.Row]:
    if not seed_ids:
        return []
    placeholders = ", ".join("?" for _ in seed_ids)
    return connection.execute(
        f"SELECT seed_id, table_name, key_json FROM db07_seed_manifest WHERE seed_id IN ({placeholders})",
        seed_ids,
    ).fetchall()


def rollback_seed(
    connection: sqlite3.Connection,
    *,
    tenant_seed_id: str = "db07-tenant-site-v1",
    catalog_seed_id: str = "db07-health-catalog-v1",
) -> None:
    """Remove only DB-07-created, unreferenced rows from the in-memory fixture."""
    _assert_memory_sqlite(connection)
    seed_ids = (tenant_seed_id, catalog_seed_id)
    rows = _manifest_rows(connection, seed_ids)
    owned: dict[str, set[str]] = {table: set() for table in _ROLLBACK_ORDER}
    for row in rows:
        owned[row["table_name"]].add(row["key_json"])
    if not rows:
        return

    decoded = {
        table: [json.loads(key) for key in keys]
        for table, keys in owned.items()
    }
    connection.execute("SAVEPOINT db07_rollback_seed")
    try:
        version_keys = decoded["svc_service_version"]
        for key in version_keys:
            references = connection.execute(
                "SELECT 1 FROM svc_appointment WHERE tenant_id = ? AND site_id = ? AND service_version_id = ? LIMIT 1",
                (key["tenant_id"], key["site_id"], key["service_version_id"]),
            ).fetchone()
            if references:
                raise SeedRollbackBlocked(
                    f"service version {key['service_version_id']} is referenced by an appointment snapshot"
                )

        owned_sites = {(key["tenant_id"], key["site_id"]) for key in decoded["plat_site"]}
        for tenant_id, site_id in owned_sites:
            if connection.execute(
                "SELECT 1 FROM svc_appointment WHERE tenant_id = ? AND site_id = ? LIMIT 1",
                (tenant_id, site_id),
            ).fetchone():
                raise SeedRollbackBlocked(f"site {site_id} has retained appointment history")
            if connection.execute(
                "SELECT 1 FROM db07_scope_fixture WHERE tenant_id = ? AND site_id = ? LIMIT 1",
                (tenant_id, site_id),
            ).fetchone():
                raise SeedRollbackBlocked(f"site {site_id} has retained isolation fixture rows")

        for key in decoded["svc_service_item"]:
            versions = connection.execute(
                "SELECT service_version_id FROM svc_service_version WHERE tenant_id = ? AND site_id = ? AND service_id = ?",
                (key["tenant_id"], key["site_id"], key["service_id"]),
            ).fetchall()
            if any((key["tenant_id"], key["site_id"], version["service_version_id"]) not in {
                (version_key["tenant_id"], version_key["site_id"], version_key["service_version_id"])
                for version_key in decoded["svc_service_version"]
            } for version in versions):
                raise SeedRollbackBlocked(f"service {key['service_id']} has non-seed version rows")

        for table in _ROLLBACK_ORDER:
            for key in decoded[table]:
                where = " AND ".join(f"{column} = ?" for column in key)
                connection.execute(f"DELETE FROM {table} WHERE {where}", tuple(key.values()))
        connection.execute(
            f"DELETE FROM db07_seed_manifest WHERE seed_id IN ({', '.join('?' for _ in seed_ids)})",
            seed_ids,
        )
        connection.execute("RELEASE SAVEPOINT db07_rollback_seed")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT db07_rollback_seed")
        connection.execute("RELEASE SAVEPOINT db07_rollback_seed")
        raise
