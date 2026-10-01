# GOV-03 历史路由兼容登记（legacy-route-registry）

> 单写声明：本目录 `features/navigation/legacy-route-registry` 由 **GOV-03 独占写入**。
> 页面任务只提交 route fragment，中心注册由 **FND-03** 单写 `pages/shell`。
> 通用 deep-link/security adapter 由 **FND-05** 单写 `features/platform/adapters`，
> 短期历史 route adapter 由 **FND-08** 独占 `features/legacy/mapp-compat-adapter/`。
> 本目录不拥有业务写主、不签发登录态、不接入 Wish BFF/DDD。

## 1. 登记内容

- `legacy-route-registry.json`：163 条旧路由的机器可读兼容登记表（来源事实）。
  - 每条记录：`mp_id`、`legacy_route`（旧路由）、`source_file`、`domain`、
    `legacy_entry`（原入口/深链）、`migration_target`、`shell_entry`（新主壳入口）、
    `carry_stage`、`auth_backend`（认证与后端归属）、`platform_deps`、
    `dag_task_id`、`compat_note`、`current_status`。
  - 兼容派生字段：`legacy_alias`（恒等于 `legacy_route`）、
    `query_passthrough=true`、`attribution_preserved=[scene,source,activity_id,content_id]`、
    `return_stack_preserved=true`、`capabilities{share,qrcode,webview,payment,staff_workbench,deep_link}`、
    `requires_login`、`login_recovery`、`feature_flag{default:legacy,switch_by:automated-route-check}`、
    `fallback`。
- 上游来源：`/home/agent/code/jiankang_app_uniapp/docs/migration/mapp-page-migration-inventory.md`
  （163 行 `| MPxxx |` 明细表，MAPP origin SHA `ce281ef0d9a6c05a43e87a4799b730c36112ff75`）。
  登记表是该清单的逐行投影，不增删路由；`dag_task_id` 为 `—（无本期任务）` 的行
  （员工/商户工作台与范围外记录）保留既有入口，不创建 APP 迁移任务。
- `formal-app-migration` 仅 35 个 allowlist 任务
  （`COM-01..06`、`ORD-01..05`、`MEM-01..10`、`CNT-01..07`、`USR-01..06`、`MER-01`）；
  未选中客户路由继续 `小程序原客户端 → MAPP server`。
  APP 首页三个第三方小程序按钮是外部入口，不在本登记表、不连 MAPP server。

## 2. 兼容规则（全局，见 JSON `global_rules`）

1. 正式迁移页：`APP 迁移页面 → MAPP server → 原有业务数据/服务`（按原服务契约）。
2. 未迁移小程序：`小程序原客户端 → MAPP server`（不变）。
3. Wish 原生业务另走 `APP → Wish APP BFF → Wish API/application service → DDD`，
   本登记不附加 Wish BFF/DDD。
4. query 参数原样往返；未知参数保留但不作为授权依据。
5. 分享/二维码/Deep Link 只携带 `scene/source/activity_id/content_id` 等公开归因引用；
   **token、健康资料、支付凭据永不进链接**；二维码仅为短时公开业务引用。
6. WebView 内容只走 host allowlist；禁止向远端注入原始身份 token。
7. 未登录深链：暂存 pending 链接（opaque、限定 allowlist route/origin），
   APP 一次登录（`IDN-01` 会话/bridge 边界）后恢复；正式迁移页仍直调 MAPP 原契约，
   不经过 Wish bridge。退出/撤销/过期/重放/越权一律 fail closed，
   留最小脱敏审计并安全回 APP 原生页或登录入口。
8. 非法链接（未知路由、非 allowlist origin/host、缺失/非法必填参数、
   链接中含 token 或健康数据、过期 scene/码）一律拒绝并给出明确错误，
   不得自动创建新业务路由。
9. feature flag 默认 `legacy`，仅自动化路由检查可切换；关闭时回退 legacy alias。
   正式页由 APP 中心路由承接；历史路由仅可走审计过的短期兼容 adapter 或安全外链。
10. 路由回退永不解释为后端写主切换；Wish/Commerce 权威写主不变。
11. 不新增/不调整 AUTH 任务（管理员登录/认证/session/token/凭据不在本轮）。

## 3. 验收代表路由（`verification_routes`，6 类）

| 角色 | MP | 旧路由 | 说明 |
| --- | --- | --- | --- |
| 首页 | MP002 | `/pages/index/index` | 访客可读，验证参数往返/无效拒绝/回退 |
| 预约·订单 | MP062 | `/pages/goods/order_list/index` | 登录后恢复、参数往返、无效拒绝、回退 |
| 支付 | MP065 | `/pages/goods/order_payment/index` | 金额服务端核对、链接无 token、登录恢复、幂等回退注记 |
| 分享 | MP052 | `/pages/goods/goods_details/index` | 分享归因往返、无 token/健康数据、无效拒绝、回退 |
| WebView | MP006 | `/pages/webview/webview` | host allowlist、无原始 token 注入、非法 host 拒绝、回退 |
| 员工入口 | MP143 | `/pages/admin/order/index` | 无本期任务，仅保留既有入口，不创建迁移任务 |

## 4. 校验与测试（全部限定本目录，不碰业务外文件）

```sh
node --test features/navigation/legacy-route-registry/gov-03-legacy-registry.test.mjs
node features/navigation/legacy-route-registry/validate.mjs
```

- `validate.mjs`：结构校验（163 条、唯一性、alias 恒等、必填字段、
  校验代表路由存在、fail-closed 规则文本存在）。
- `gov-03-legacy-registry.test.mjs`：`node:test` 专项验收，
  覆盖首页/预约订单/支付/分享/WebView/员工入口的参数往返、
  未登录恢复、无效链接拒绝和 legacy 回退。

## 5. 回退

恢复上一版 `legacy-route-registry.json`；
由 APP 中心路由处理已迁入页面，尚未迁入的历史路由仅可走
审核过的短期兼容 adapter 或安全外链，不把路由回退解释为后端写主切换。
