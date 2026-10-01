# Canonical DB model artifacts (DB-02)

`canonical-models.json` is the machine-readable target model used by the ERD and field dictionary. It contains all 60 target entities from `data-architecture-design.md` §4/§11 across `plat`, `crm`, `hlth`, `svc`, `fin`, `msg`, `mkt`, `evt`, `aud`, and `rpt`. The schema version and entity count are declared in JSON and checked by the Node test.

This is a **target design, not an implemented schema**. The model uses synthetic examples only. It contains no production records, has not connected to a database, and no real DDL or migration has been generated or executed. Health writes remain disabled until the health data owner and lawful purpose are confirmed. No production database connection is part of this artifact.

## Ownership and isolation

Each entity has exactly one `write_master` drawn from `plat`, `Wish`, or `Commerce/MER`. `plat` owns tenant/site directories and staff identity references. Wish owns CRM, service, service-finance, messaging, event consumption, audit, and rebuildable reporting projections. Health entities are only candidate Wish models behind an explicit owner gate. Commerce/MER remains the sole writer for mall orders, refunds, products, and inventory. Wish's `mkt_order_ref` is a minimized, read-only reference; `mkt_product_benefit_map` is a separate Wish-owned mapping and never writes MER facts.

Every business fact carries immutable `tenant_id` and `site_id`; directory and identity-anchor exceptions are marked by `entity_kind`. Cross-domain foreign keys include scope and default to `RESTRICT`. Unknown legacy ownership stays quarantined; the model never invents a tenant or site. UUID identifiers are independent of phone numbers and external IDs.

Sensitive identifiers and health payloads use KMS envelope encryption. Deterministic lookup uses a separate keyed HMAC. Money uses `DECIMAL(18,2)` with an explicit ISO-4217 `currency_code`; currency is never inferred. Effective intervals are half-open `[effective_from, effective_to)`. Ledger, state history, consent evidence, and audit rows are append-only and corrected through linked compensating records.

## Booking, snapshots, and mapping

Resource occupancy uses five-minute UTC buckets with unique key `(tenant_id, site_id, resource_id, slot_start_utc)`. A reservation inserts every required resource bucket in stable order inside one transaction; any conflict rolls back the full set. Appointments pin service, eligibility, capacity, pricing, and cancellation rule versions. Work orders pin the SOP version. Messages and projections pin their consent/policy/template or definition versions and source watermarks.

Logical names from §§12/13 that refer to an existing fact are listed under `logical_name_mappings`; they extend the existing entity after owner/DBA review and retain its one writer. These mappings do not declare parallel physical tables. The synthetic legacy CSV is candidate mapping metadata only; validate source ownership, lawful purpose, consent, site, field mapping, and retention before any migration. Never copy an MER order into Wish.

## Artifacts and checks

- `canonical-models.json`: 60 entities, scoped keys, foreign keys, write master, sensitivity, amounts, effective times, retention, relationships, and policies.
- `../../../docs/data/canonical-erd.md`: complete relationship diagram and ownership/invariant summary.
- `../../../docs/data/canonical-dictionary.md`: field and lifecycle dictionary for all 60 modeled entities.
- `../../../docs/data/canonical-models.test.mjs`: Node built-in tests; run with `node --test docs/data/canonical-models.test.mjs` from the repository root.

Rollback means stop the canonical rollout and disable the new write route. Keep legacy schemas/adapters until approved migration and recovery gates pass. Reconcile any already-written facts with linked reversal/cancellation/suppression records; do not delete ledger facts or blindly dual-write. DB-02 performs no cutover and no DDL.
