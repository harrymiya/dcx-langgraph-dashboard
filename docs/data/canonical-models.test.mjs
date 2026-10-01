import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const model = JSON.parse(readFileSync(new URL('../../domain/shared/db/models/canonical-models.json', import.meta.url), 'utf8'));
const erd = readFileSync(new URL('./canonical-erd.md', import.meta.url), 'utf8');
const dictionary = readFileSync(new URL('./canonical-dictionary.md', import.meta.url), 'utf8');
const readme = readFileSync(new URL('../../domain/shared/db/models/README.md', import.meta.url), 'utf8');
const legacyCsv = readFileSync(new URL('./wish-legacy-to-canonical-map.csv', import.meta.url), 'utf8');
const entities = model.entities;
const byName = new Map(entities.map((entity) => [entity.name, entity]));

function entity(name) {
  const value = byName.get(name);
  assert.ok(value, `missing model entity: ${name}`);
  return value;
}

test('canonical model JSON declares all 60 baseline entities and required prefixes', () => {
  assert.equal(model.design_status, 'target_design_not_implemented');
  assert.equal(model.data_mode, 'synthetic_only');
  assert.equal(model.ddl_executed, false);
  assert.equal(model.entity_count, 60);
  assert.equal(entities.length, 60);
  assert.equal(new Set(entities.map(({ name }) => name)).size, entities.length);
  const requiredPrefixes = ['plat', 'crm', 'hlth', 'svc', 'fin', 'msg', 'mkt', 'evt', 'aud', 'rpt'];
  assert.deepEqual(model.prefixes, requiredPrefixes);
  assert.deepEqual([...new Set(entities.map(({ prefix }) => prefix))].sort(), [...requiredPrefixes].sort());
  for (const entity of entities) {
    assert.equal(entity.name.split('_', 1)[0], entity.prefix, `${entity.name} prefix mismatch`);
  }
});

test('business facts require tenant/site and scoped restrictive foreign keys', () => {
  for (const value of entities.filter(({ entity_kind }) => entity_kind === 'business_fact')) {
    assert.equal(value.tenant_site_required, true, `${value.name} must require tenant/site`);
    assert.ok(value.pk.includes('tenant_id') && value.pk.includes('site_id'), `${value.name} PK must include tenant/site`);
    assert.ok(value.fks.some((fk) => fk.columns.includes('tenant_id') && fk.columns.includes('site_id')), `${value.name} needs a same-scope FK`);
    for (const fk of value.fks) {
      const parent = byName.get(fk.ref_entity);
      assert.ok(parent, `${value.name} has dangling FK ${fk.ref_entity}`);
      assert.equal(fk.on_delete, 'RESTRICT', `${value.name} FK to ${fk.ref_entity} must restrict delete`);
      assert.equal(fk.columns.length, fk.ref_columns.length, `${value.name} FK column arity mismatch`);
      if (parent.tenant_site_required) {
        assert.ok(fk.columns.includes('tenant_id') && fk.columns.includes('site_id'), `${value.name} -> ${parent.name} must preserve tenant/site`);
        assert.ok(fk.ref_columns.includes('tenant_id') && fk.ref_columns.includes('site_id'), `${value.name} -> ${parent.name} must reference scoped keys`);
      }
      assert.ok(model.relations.some((relation) => relation.from === fk.ref_entity && relation.to === value.name), `${value.name} FK to ${parent.name} must appear in ERD relations`);
    }
  }
  for (const relation of model.relations) {
    assert.ok(byName.has(relation.from), `dangling relation source ${relation.from}`);
    assert.ok(byName.has(relation.to), `dangling relation target ${relation.to}`);
  }
});

test('every entity has exactly one legal write master', () => {
  const allowed = new Set(model.write_masters.allowed);
  assert.deepEqual([...allowed].sort(), ['Commerce/MER', 'Wish', 'plat'].sort());
  assert.equal(model.write_masters.per_entity, 'exactly_one');
  for (const value of entities) {
    assert.equal(typeof value.write_master, 'string', `${value.name} must declare one writer`);
    assert.ok(allowed.has(value.write_master), `${value.name} has illegal writer ${value.write_master}`);
  }
});

test('health models require consent, encrypt sensitive data, and stay write-disabled', () => {
  const consent = entity('crm_consent_record');
  assert.ok(consent.pii.encrypted_fields.includes('evidence_ref_ciphertext'));
  const record = entity('hlth_health_record');
  const source = entity('hlth_source_link');
  const revision = entity('hlth_record_revision');
  for (const value of [record, revision, source]) {
    assert.equal(value.owner_status, 'health_owner_confirmation_required');
    assert.equal(value.write_enabled, false);
    assert.ok(value.pii.encrypted_fields.length > 0, `${value.name} must encrypt health-linked data`);
  }
  for (const value of [record, source]) {
    assert.ok(value.fks.some((fk) => fk.ref_entity === 'crm_consent_record' && fk.columns.includes('tenant_id') && fk.columns.includes('site_id') && fk.columns.includes('consent_id')), `${value.name} must reference same-scope consent`);
  }
  assert.ok(revision.fks.some((fk) => fk.ref_entity === 'hlth_health_record'), 'revision must inherit consent from its health record');
  assert.ok(record.fks.some((fk) => fk.ref_entity === 'crm_consent_record'));
  assert.match(model.policies.health_consent, /active CRM consent/i);
});

test('financial ledger is append-only and every monetary amount names a currency', () => {
  for (const name of ['fin_service_card_ledger', 'fin_transaction_history', 'fin_commission_entry']) {
    const value = entity(name);
    assert.equal(value.append_only, true, `${name} must be append-only`);
    assert.equal(value.retention.update_allowed, false, `${name} updates must be prohibited`);
    assert.equal(value.retention.delete_allowed, false, `${name} deletes must be prohibited`);
  }
  const monetary = entities.flatMap((value) => value.amount_fields.map((amount) => ({ value, amount })));
  assert.ok(monetary.length > 0);
  for (const { value, amount } of monetary) {
    assert.equal(amount.type, 'DECIMAL(18,2)', `${value.name}.${amount.field} must use DECIMAL`);
    assert.equal(amount.currency_field, 'currency_code', `${value.name}.${amount.field} must name currency`);
  }
  assert.match(model.policies.money, /ISO currency_code/i);
});

test('booking uses five-minute resource buckets and pins published rule versions', () => {
  const lock = entity('svc_resource_lock');
  assert.equal(lock.lock_bucket.duration_minutes, 5);
  assert.deepEqual(lock.lock_bucket.unique_key, ['tenant_id', 'site_id', 'resource_id', 'slot_start_utc']);
  assert.equal(lock.lock_bucket.insert_all_buckets_atomically, true);
  const appointment = entity('svc_appointment');
  for (const field of ['service_version_id', 'capacity_rule_version', 'eligibility_rule_version', 'pricing_rule_version']) {
    assert.ok(appointment.rule_snapshot_fields.includes(field), `appointment must pin ${field}`);
  }
  assert.ok(entity('svc_work_order').rule_snapshot_fields.includes('sop_version_id'));
  assert.match(model.policies.rule_snapshots, /later rule edits do not rewrite existing facts/i);
});

test('MER order facts remain external and read-only in Wish', () => {
  const order = entity('mkt_order_ref');
  assert.equal(order.write_master, 'Commerce/MER');
  assert.equal(order.read_only_reference, true);
  assert.match(order.retention.policy, /no address, contact or line items/i);
  assert.match(model.policies.mer_read_only, /never writes MER facts/i);
  assert.match(readme, /read-only reference/i);
});

test('ERD, dictionary, and README state the design, security, booking, and rollout boundaries', () => {
  const allDocs = `${erd}\n${dictionary}\n${readme}`.toLowerCase();
  for (const keyword of ['目标设计', '未实现', '合成', 'ddl', '生产库', 'tenant_id', 'site_id', '唯一写主', '5 分钟', 'append-only', 'effective_from', 'decimal(18,2)', 'currency_code', 'kms', 'pii', 'commerce/mer']) {
    assert.ok(allDocs.includes(keyword.toLowerCase()), `missing required design keyword: ${keyword}`);
  }
  const dictionaryNames = new Set([...dictionary.matchAll(/^\| `([^`]+)` \|/gm)].map((match) => match[1]));
  assert.deepEqual(dictionaryNames, new Set(entities.map(({ name }) => name)));
  for (const value of entities) assert.ok(erd.includes(value.name), `ERD omits ${value.name}`);
  assert.match(readme, /no real ddl or migration has been generated or executed/i);
});

test('legacy CSV rows map to the canonical entity and encrypted/HMAC field', () => {
  const [headerLine, ...lines] = legacyCsv.trim().split(/\r?\n/);
  const headers = headerLine.split(',');
  const rows = lines.map((line) => Object.fromEntries(line.split(',').map((field, index) => [headers[index], field])));
  assert.equal(rows.length, 2);
  for (const row of rows) {
    assert.equal(row.evidence, 'unverified/synthetic');
    const alias = model.legacy_aliases.find((value) => value.legacy_table === row.legacy_table && value.legacy_field === row.legacy_field);
    assert.ok(alias, `missing machine mapping for ${row.legacy_table}.${row.legacy_field}`);
    assert.equal(alias.csv_entity, row.canonical_entity);
    assert.equal(alias.csv_field, row.canonical_field);
    assert.equal(alias.csv_write_master, row.write_master);
    const canonical = entity(alias.canonical_entity);
    assert.ok(canonical.pii.encrypted_fields.includes(alias.canonical_field), `${alias.canonical_entity}.${alias.canonical_field} should be encrypted`);
    assert.equal(canonical.write_master, row.write_master);
  }
});
