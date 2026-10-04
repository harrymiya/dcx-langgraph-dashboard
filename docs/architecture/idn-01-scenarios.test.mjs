import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const architecture = readFileSync(new URL('./dag-admin-architecture.md', import.meta.url), 'utf8');
const start = architecture.indexOf('## 客户统一登录与会话桥接设计');
const end = architecture.indexOf('\n## 任务统计与来源', start);
assert.notEqual(start, -1, 'IDN-01 design section must exist');
assert.notEqual(end, -1, 'IDN-01 section must have a following section boundary');
const section = architecture.slice(start, end);

test('历史身份来源与 APP 唯一客户登录', () => {
  assert.match(section, /微信登录\/授权.*可选手机号核验.*只.*历史身份来源/s);
  assert.match(section, /客户唯一登录入口是 APP 手机号 \+ 短信验证码/);
  assert.match(section, /兼容页、历史 route 或短期 adapter 时复用已验证的 APP session/);
  assert.match(section, /不显示第二次登录\/授权/);
});

test('bridge 必须 opaque、短期、单次且绑定完整 allowlist 与身份上下文', () => {
  for (const phrase of [
    'opaque、短 TTL、单次兑换',
    '`route` 与 `origin`',
    '唯一 `audience`',
    '`nonce`',
    '`jti`',
    '`subject`',
    '`tenant_id`',
    '`site_id`',
    '`relationship`',
    '`purpose`',
    '`consent`',
    '原子地消费 `jti`',
  ]) assert.ok(section.includes(phrase), `missing bridge binding: ${phrase}`);
});

test('旧 token 仅服务端一次性交换并立即失效', () => {
  assert.match(section, /可信服务端执行一次性交换，并立即使旧 token 失效/);
  assert.match(section, /不能确认则 fail closed/);
  assert.match(section, /旧 token 不得返回客户端/);
});

test('Wish 授权上下文由服务端解析，客户端字段不可信', () => {
  assert.match(section, /Wish API\/application\/DDD 从已验证的 APP session 或一次性 bridge 在服务端解析/);
  assert.match(section, /客户端提交的 principal、tenant\/site、subject、relationship、purpose、consent、角色或字段范围均不可信/);
  assert.match(section, /field_scope/);
});

test('MAPP migration 与 Wish 新业务保持独立调用链', () => {
  assert.match(section, /APP 迁移页面 → MAPP server → 原有业务数据\/服务/);
  assert.match(section, /APP → Wish APP BFF → Wish API\/application service → DDD/);
  assert.match(section, /MAPP server` 保持原小程序后端和既有服务边界/);
  assert.match(section, /不独立登录.*不签发长期客户 token/);
});

test('生命周期失败均 fail closed、最小审计并安全回 APP 原生页', () => {
  for (const phrase of ['APP 全局退出', '显式撤销', '到期', '重放', '超时或不可用', 'fail closed', '最小审计', 'APP 原生安全页']) {
    assert.ok(section.includes(phrase), `missing failure/return contract: ${phrase}`);
  }
  assert.match(section, /不得记录 bridge、旧 token、nonce、原始 jti/);
});

test('管理员组织 SSO 属于最终交付且与客户 bridge 独立', () => {
  assert.match(section, /管理端生产组织 SSO、认证 session 生命周期、登出\/撤销与配置属于最终交付/);
  assert.match(section, /WADM-17/);
  assert.match(section, /管理员身份体系与客户 session 分离/);
});

test('设计报告声明只做静态文档验收，不接真实服务或生产数据', () => {
  assert.match(section, /不调用服务、不验证真实签名\/并发原子性，也不使用生产身份或数据/);
  assert.match(section, /真实服务、生产身份数据与外部写入保持关闭/);
});

const scenarios = [
  ['IDN-S01', /有效兑换/, /原子消费一次/],
  ['IDN-S02', /重复兑换 \/ 重放/, /拒绝/],
  ['IDN-S03', /过期/, /拒绝/],
  ['IDN-S04', /撤销/, /拒绝并 fail closed/],
  ['IDN-S05', /APP 退出/, /撤销待用票据和派生兼容态/],
  ['IDN-S06', /audience 错误/, /拒绝/],
  ['IDN-S07', /route \/ origin 错误/, /拒绝/],
  ['IDN-S08', /授权 scope 不匹配/, /拒绝/],
  ['IDN-S09', /超时 \/ 依赖失败/, /不建立上下文/],
  ['IDN-S10', /旧 token 重用/, /再次使用拒绝/],
  ['IDN-S11', /无泄漏/, /无 bridge/],
  ['IDN-S12', /业务边界/, /前者直连 MAPP 原契约/],
  ['IDN-S13', /登录连续性/, /APP 手机号 \+ 短信验证码是唯一客户登录/],
];

test('所有 IDN-01 场景覆盖项均出现在矩阵且有预期结果', () => {
  for (const [id, description, outcome] of scenarios) {
    const row = section.split('\n').find((line) => line.startsWith(`| ${id} `));
    assert.ok(row, `missing scenario ${id}`);
    assert.match(row, description, `scenario ${id} description changed`);
    assert.match(row, outcome, `scenario ${id} expected outcome changed`);
  }
});
