# DB-08 Health/SCRM quality and recovery gates

This document describes the read-only DB-08 checks for the DB-02 canonical
model, DB-03 tenant/site scope, DB-04 appointment locks, and DB-05 service-card
ledger. The checker uses only Python's standard library and the caller's
`sqlite3.Connection`; it does not create a connection, execute DDL, or modify
database rows. All examples and tests use synthetic in-memory SQLite data.

## Machine contract

`domain/data_quality/health_scrm_gates.py` exposes
`run_quality_gates(connection, ...)`, which returns a JSON-serializable object
with `contract_version`, overall `status`, summary counts, and individual
checks. Each check has `id`, `status` (`pass`, `fail`, or `skip`),
`issue_count`, and a short summary. Findings contain a machine code and
aggregate count; they never contain row values or sample records.

The gates cover:

- Canonical owner, PII classification, state field, primary/unique key, and
  retention policy, and single-writer metadata. Health owner confirmation must
  remain pending and health writes disabled until ownership is confirmed.
- Materialized schema columns, scope columns declared `NOT NULL`, encrypted or
  HMAC PII fields, primary/unique keys, and plaintext sensitive-column names.
- Non-empty tenant/site values on scoped business facts, duplicate key tuples,
  missing states and invalid catalogued appointment, lock, card, and ledger
  states, plus non-empty health-record retention deadlines.
- Canonical foreign-key orphans, partial composite references, SQLite FK
  violations, and tenant/site mismatches for site-scoped references. Customer
  identity anchors remain tenant-scoped as specified by the canonical model.
- UTC resource lock bucket alignment to the fixed five-minute grid and expiry
  ordering for a `LOCKED` hold.
- The append-only policy and SQLite `BEFORE UPDATE` / `BEFORE DELETE` abort
  guards on `fin_service_card_ledger`.
- Optional seed-to-backup and seed-to-restored comparisons. When all three
  connections are supplied, the gate compares schema hashes and per-table row
  counts/fingerprints. A mismatch reports table names and hashes only.

Tables absent from the supplied snapshot are reported as unmaterialized, not as
proof that the canonical schema has been deployed. A skipped recovery check
means its three snapshots were not supplied. A passing synthetic check is not
production rollout or recovery evidence; owner-approved RPO/RTO targets and an
authorized recovery exercise remain separate operational sign-offs.

## Health and PII export boundary

The checker does not select health payload columns for findings and never
serializes row values. The recovery fingerprint hashes canonicalized row bytes
inside the process and exports only a SHA-256 digest, row count, schema digest,
and table identifier. Reports set `health_payload_exported` and
`row_values_exported` to `false`. Fingerprints can still reveal equality
between snapshots, so handle the report with the same access controls as other
operational metadata. Direct identifiers and health正文 are not included.

## Targeted tests

Run the dependency-free synthetic suite from the repository root:

```sh
python3 -m unittest discover -s domain/data_quality/tests -p 'test_*.py' -v
```

The suite exercises passing recovery parity, redaction, owner/PII/state/scope
and reference anomalies, five-minute bucket alignment, ledger immutability
guards, duplicate business keys, and restore drift. The fixtures only use
`:memory:` SQLite databases and never open a production connection.
