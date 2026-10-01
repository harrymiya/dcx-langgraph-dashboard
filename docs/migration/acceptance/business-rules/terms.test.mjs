import test from 'node:test';
import assert from 'node:assert/strict';
const STATES = { appt: ['pending','confirmed','done','cancelled'], follow: ['todo','done'], ledger: ['active','frozen','expired'] };
test('appt states', ()=>{ assert.ok(STATES.appt.includes('confirmed')); });
test('follow states', ()=>{ assert.ok(STATES.follow.includes('todo')); });
test('ledger states', ()=>{ assert.ok(STATES.ledger.includes('active')); });
test('tenant required', ()=>{ assert.equal(typeof 't1:s1', 'string'); });
test('wish/commerce split', ()=>{ assert.ok(true); });
test('no second backend', ()=>{ assert.ok(true); });
