# DEV-05 encrypted backup and isolated restore runbook

Status: target design and synthetic verification only. This workspace has no
production backup adapter, object-store integration, key service, or production
database connection. No real backup or restore was run. RPO and RTO are **owner
confirmation pending**; record approved values and their approver before an
authorized operational rehearsal.

## Security and manifest contract

The backup platform must encrypt the database snapshot with its approved
envelope-encryption/KMS integration before storage or transfer. Keep data keys,
KMS credentials, signing/HMAC material, database credentials, and recovery
credentials in the external secret manager or KMS. Supply only a non-secret key
reference and key version in the manifest. Do not implement encryption with
home-grown Python code or store keys beside the artifact. The Python test helper
does not encrypt bytes; its fixture is labeled opaque synthetic ciphertext and
only tests the metadata contract and hashes.

Each manifest records:

- A unique backup ID, UTC creation time, isolated source environment, source
  watermark, and schema fingerprint.
- Encrypted artifact format marker, byte count, and SHA-256 digest computed
  over ciphertext.
- Encryption algorithm label, external key reference, key version, and an
  explicit `key_material_included: false` marker.
- Retention policy reference and expiry, legal-hold state, access policy
  reference, and least-privilege role allowlist.
- SHA-256 over canonical manifest JSON and an HMAC-SHA-256 authentication tag.
  The HMAC key is injected from the external secret manager at verification
  time and never serialized. In production, use the approved signing/KMS
  mechanism for this integrity field.

Store the artifact and manifest under separate access-controlled objects. Do
not put database URLs, object-store credentials, secret values, raw row values,
health payloads, direct identifiers, encryption material, or exception text in
the manifest, logs, or test report. Logs use stable finding codes and aggregate
counts only. Treat fingerprints and operational metadata as restricted
information because they reveal equality between snapshots.

## Access and retention

Apply least privilege at both the backup service and storage layers. Separate
the `backup-writer`, `restore-operator`, and `security-auditor` duties; require
time-bounded approval for restore access, record access in tamper-evident audit
logs, and deny public or broad user access. Restore operators must not receive
production application credentials by default. Use a separately approved,
isolated recovery identity and never copy production credentials into a test
environment.

The storage lifecycle must enforce the owner-approved retention schedule,
including legal holds and auditable expiry deletion. The retention duration,
legal/accounting obligations, and evidence archive schedule remain owner
decisions; this runbook invents no duration. Preserve appointment, payment,
service-card ledger, and audit history according to their owners' approved
retention rules. Ledger/audit facts remain append-only; correct them with
compensating records, never by editing a restored ledger row.

## Authorized isolated restore sequence

1. Obtain named data/service owners' approval, an incident or exercise record,
   and signed RPO/RTO targets. Select a backup by opaque ID and confirm its
   retention/legal-hold eligibility.
2. Verify manifest completeness, its external HMAC/signature, ciphertext byte
   count and digest, schema version, source watermark, key reference/version,
   and artifact access audit. Stop on any mismatch.
3. Provision a disposable recovery target in a separate account/network with
   no route to production. Inject only time-bounded recovery secrets at runtime.
   Disable outbound callbacks, payments, messages, webhooks, scheduled jobs,
   and application writes before opening the restored database.
4. Decrypt into that isolated target using the external KMS/backup platform.
   Never restore over the source or reuse its storage path. The source stays
   read-only and available for comparison. If a restore or check fails, discard
   only the isolated candidate after retaining approved aggregate evidence;
   repair this runbook/configuration and rehearse again from a fresh candidate.
5. Compare seed/source, backup, and restored schema fingerprints, per-table
   counts, and hashes. Use the reviewed recovery adapter to pass the isolated
   connection objects to `domain.data_quality.health_scrm_gates.run_quality_gates`
   with `seed_db`, `backup_db`, and `restored_db` supplied. No production
   adapter or invocation command is included in this synthetic-only delivery.
   The DB-08 dependency-free regression suite is:

   ```sh
   python3 -m unittest discover -s domain/data_quality/tests -p 'test_*.py' -v
   ```

6. Confirm tenant/site references and continuity through catalog item/version,
   appointment, payment, service-card ledger, and audit-event references. Check
   tenant/site composite foreign keys, append-only ledger update/delete guards,
   and parity with the selected source watermark. Reports contain counts,
   hashes, table identifiers, and finding codes only; health正文 and row values
   are never exported.
7. Record actual observed RPO/RTO against the owner-approved targets, the
   artifact/manifest digest, isolated target identifier, gate outcomes, and
   cleanup evidence. Keep all real writes, production routing, and external
   callbacks disabled unless a separate authorization explicitly opens them.

The checked-in helper `dev05_restore.py` is a synthetic contract harness. Its
`restore_isolated` accepts only a caller-owned `sqlite3.Connection` and writes
to a fresh `:memory:` database; it has no path, URI, network, or production
adapter. `verify_snapshot_chain` reports schema/table digests and the required
reference chain without exposing row values. This harness does not decrypt,
encrypt, access a secret manager, or establish operational recovery evidence.
The DB-08 unittest command above also uses only synthetic in-memory fixtures; it
does not inspect a restored environment by itself.

## Synthetic targeted tests

From the dashboard repository root:

```sh
python3 -m unittest discover -s ops/backup-restore/runbooks/tests -p 'test_*.py' -v
```

These tests use only in-memory SQLite databases and an opaque byte-string
fixture. They cover manifest completeness and tamper detection, secret
non-disclosure, isolated restore parity, tenant/site and business-reference
continuity, ledger append-only guards, drift detection, and source preservation
after a rejected restore. A green synthetic suite does not prove production
backup encryption, retention enforcement, access configuration, or a real
recovery exercise.
