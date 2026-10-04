# DFP Wish 健康服务与 SCRM DAG 架构索引

本文索引 `backend/tasks.json` 的 APP、DFP Wish 后端和管理工作台任务。方案源 task definitions 均为 `planned`；活跃实施状态以 `backend/.project-runtime/projects/default/tasks.json` 为准。设计、目标代码路径和验收场景不构成功能已实现或通过验收的证据。

## 正式架构基线

163 条来源路由全部进入全量交付 DAG：40 个 `formal-app-migration` 任务（`COM-01..06`、`ORD-01..05`、`MEM-01..10`、`CNT-01..07`、`USR-01..06`、`MER-01..06`）承接 159 条 MAPP 客户与员工/商户页面，只迁移 APP 前端并调用 `MAPP server → 原有业务数据/服务`。主壳/Wish 所属其余 4 条路由由 FND/HWI 任务承接。员工/商户页面使用独立 manager 身份及 tenant/site/role 授权，旧 MAPP 路由仅作逐页切流前回退。APP 首页三个第三方小程序按钮仍是外部入口；13 个明确属于 Wish 的任务走 `wish-formal-business` 泳道 `APP → Wish APP BFF → Wish API/application service → DDD`，不得接入 MAPP server。

`formal-app-migration` 的任务职责是迁移 APP 页面并复用原 MAPP server/API 和数据库，不在迁移项目另建后端/数据写主。六个 MAPP/Commerce 业务域以 VCOM/VORD/VMEM/VCNT/VUSR/VMER 各四项任务补齐管理导航/页面、核验 APP/Admin 到原 MAPP API/数据库的复用和端到端集成；仅当管理端所需操作在原系统缺失时，才扩展原 MAPP 权威代码。Wish 原生工作域的排除规则只限制 Wish 写主，不能排除 MAPP/Commerce 管理端交付。细目见 `GOV-01.data.vertical_closure_registry`、[垂直闭环矩阵](../../../jiankang_app_uniapp/docs/architecture/vertical-business-closure-matrix.md) 和[管理端导航原型](../../../jiankang_app_uniapp/docs/prototypes/business-admin-navigation-prototype.html)。

正式主链固定为：

```text
小程序迁移泳道：APP 页面/入口 -> feature/repository -> MAPP server -> 原有业务数据/服务
Wish 正式业务泳道：APP -> Wish APP BFF -> Wish API/application service -> DDD domain
  -> repository/UoW/事务 -> Wish 数据层/Outbox/Event -> read model/audit
```

管理工作台通过 Wish Admin BFF 调用同一 Wish API/application service 和 DDD 写主。APP BFF/Admin BFF 都是 DFP Wish 内的渠道适配层，不是独立业务后端。Commerce/MER 继续独立负责商城事实；Wish 不双写商城事实，只接收受控只读引用。

## 正式 APP 迁移业务与兼容回退泳道

`formal-app-migration` 登记 allowlist 中的 40 个 MAPP 页面/入口迁移任务，承接 159 条客户及员工/商户页面；163 条 route 都必须有有效任务映射。机器范围登记在 `backend/tasks.json` 的 `GOV-01.data.migration_scope_policy`；每个所选任务必须有 `migration_scope: selected-page`、`migration_backend: MAPP server`、`migration_source_file` 和 `migration_source_page_ids`，页面 ID 必须对应手机端清单 `DAG task ID` 列映射。Agent 认领时须同时校验 registry、task lane 和来源页字段；字段缺失或不匹配时拒绝按迁移任务执行。迁移任务只交付 APP 前端页面/状态与 feature/repository，按原服务契约访问 MAPP server 原有业务数据/服务，不得依赖 Wish APP BFF、Wish API 或 Wish DDD。

明确属于 Wish 的 13 个原生任务为 `APPBFF-01`、`HLT-01..07`、`HWI-01..05`，单独使用 `wish-formal-business`，任务字段标记 `migration_scope: wish-native`、`migration_backend: null` 和 Wish `backend_target_chain`。它们按 Wish API/DDD、schema、事件、管理工作域、测试与回退形成纵向闭环，不得接入 MAPP server。Wish 业务依赖 APPBFF-01 是合理的；它不得被误读为小程序迁移任务依赖。

`legacy-compatibility-fallback` 是独立的受控回退泳道，只包含历史 route 登记、短期 adapter 和安全回退。它不改变 MAPP server 作为小程序迁移页面后端目标的边界；MAPP server 不新增独立登录、长期 token 或与本次页面迁移无关的新业务 API。

`backend/tasks.json` 的 `data.migration_lane` 按任务边界标注。精确 allowlist、排除规则和 Wish 链定义在 `GOV-01.data.migration_scope_policy`；40 项迁移任务各自记录清单文件、route_inventory_page_ids 和 migration_source_page_ids，13 项 Wish 原生任务记录 Wish 后端链且 `migration_backend` 为空。`GOV-03`、`FND-05`、`FND-08` 为 `legacy-compatibility-fallback`；共享身份契约/实现及安全门禁 `GOV-02`、`GOV-05`、`FND-01`、`API-02`、`API-03`、`IDN-01`、`SEC-*`、`TST-05`、`TST-06` 为 `cross-cutting-security-gate`。未跨越这些业务边界的通用平台任务可不填写该字段。

小程序前端迁移任务可以直接依赖 `IDN-01` 获取 APP session 边界契约，但不得依赖 `APPBFF-01`、Wish API 或 Wish DDD；Wish BFF/DDD 依赖仅适用于任务本身明确属于 Wish 的业务。桥接实现/适配任务 `FND-01`、`API-02`、`APPBFF-01`、`FND-08` 和安全验收 `TST-05`、`SEC-04` 按各自职责依赖 `IDN-01`；`TST-05`、`SEC-04` 对 Wish 业务链的安全验收依赖 `APPBFF-01`。`IDN-01` 是设计前置，不反向依赖下游实现。

横向集成必须晚于参与模块的纵向闭环，包含身份授权、tenant/site 与客户关系、消息/通知、Commerce 受控只读引用、预约—履约—服务账、发布和恢复验收。`IDN-01` 是共享客户会话桥接契约，不替代模块闭环；`APPBFF-01` 是明确属于 Wish 的业务渠道适配任务；`TST-05`、`SEC-04` 是共享安全门禁。

## 客户统一登录与会话桥接设计

### 身份来源与唯一客户登录

小程序的微信登录/授权，以及按历史配置进行的可选手机号核验或短信验证，只是历史身份来源，不构成迁移后的客户登录入口。客户唯一登录入口是 APP 手机号 + 短信验证码；客户只在 APP 登录一次。进入兼容页、历史 route 或短期 adapter 时复用已验证的 APP session，不显示第二次登录/授权，也不再要求输入密码、短信码或重新登录小程序。管理员身份体系与客户 session 分离。

### Bridge 签发、兑换与旧 token 处理

仅当尚未迁移的历史 route 确实需要身份续接时，Wish 服务端在验证仍有效的 APP session 和服务端身份映射后，签发 opaque、短 TTL、单次兑换的 bridge。票据本身不携带可由客户端解读的授权声明，不是登录凭证、长期 token 或新业务授权。其最大有效时长由服务端限制，不能因读取、失败重试或兑换而延长；本设计不指定生产 TTL、issuer 字符串或 origin 配置值。

每张 bridge 必须绑定并在兑换时逐项核验：

- 由 GOV-03 登记及安全策略明确允许的 `route` 与 `origin`；两者成对匹配，客户端不能用 query、跳转目标或自报来源扩大 allowlist。
- 唯一 `audience`，且只面向该历史 route 的受信任 adapter；不得跨 Wish、Commerce 或其他 audience 使用。
- 与当前 APP session / route challenge 关联的 `nonce`，以及唯一 `jti`。服务端原子地消费 `jti` 后才返回该 route 的临时身份上下文；并发兑换、再次兑换及重放一律拒绝。
- 经服务端验证的 `subject`、`tenant_id`、`site_id`、`relationship`、`purpose`、`consent`（含适用的版本/状态）和有效期。缺失、冲突、撤销或过期的绑定均拒绝。

兑换只向可信 adapter 返回绑定原 APP session 与 allowlisted route 的临时身份上下文，不返回旧 token、可复用 bridge 或可续期凭证。若需要兼容旧小程序 token，只能由可信服务端执行一次性交换，并立即使旧 token 失效；必须确认失效后才算成功，不能确认则 fail closed。旧 token 不得返回客户端、写入 URL/普通日志、续期或再次兑换。

### Wish 授权上下文与业务链边界

Wish API/application/DDD 从已验证的 APP session 或一次性 bridge 在服务端解析 `principal`、`tenant_id`、`site_id`、`subject`、`relationship`、`purpose`、`consent` 和 `field_scope`，并在兑换及敏感业务操作时复核当前关系、用途、同意与字段范围。客户端提交的 principal、tenant/site、subject、relationship、purpose、consent、角色或字段范围均不可信；允许作为筛选选择的值也只是请求意图，不能成为授权事实或扩大权限。拒绝交由 Wish 服务端授权边界执行。

- 正式迁移页面直接按原服务契约调用 `MAPP server`：`APP 迁移页面 → MAPP server → 原有业务数据/服务`。该路径不经过 Wish bridge、Wish APP BFF 或 Wish API/DDD。
- 明确属于 Wish 的新业务走 `APP → Wish APP BFF → Wish API/application service → DDD`，由 Wish 服务端解析上述 principal 与授权上下文，不通过 MAPP server。
- `MAPP server` 保持原小程序后端和既有服务边界，继续承载正式迁移页面调用的原服务及未迁移小程序业务；它不改造成 Wish adapter，不独立登录、不重新询问密码/验证码、不签发长期客户 token，也不替代 Wish 新业务 API。

### 生命周期、失败处理与审计

APP 全局退出使 APP session 失效，并撤销该 session 派生的待兑换 bridge 和已兑换的兼容态；显式撤销、到期、重放、错误 audience/route/origin、subject 或 tenant/site/relationship/purpose/consent/field scope 不匹配、身份映射冲突，以及 Wish/adapter 超时或不可用，都必须 fail closed。不得创建临时授权上下文、执行受保护操作、静默切换登录体系或退回 MAPP 独立登录。APP session 仍有效时回到 APP 原生安全页并给出安全错误；APP session 无效时回 APP 原生登录入口。撤销状态或旧 token 失效无法确认时同样拒绝。

只保留完成安全追踪所需的最小审计：可信 request/correlation 引用、时间、事件类型、决策、稳定原因类别、责任服务及必要的脱敏 actor/object 引用；有可信值时才记录 tenant/site、purpose 与策略版本。不得记录 bridge、旧 token、nonce、原始 jti、验证码、完整手机号、URL/query、客户端被拒绝的字段值或健康正文。面向客户端的错误沿用 API-01 安全错误契约，不回显 token、密钥、被拒值或健康内容；本设计不新增错误码或 API 路由。

### IDN-01 静态场景覆盖矩阵

以下矩阵由本目录的文档场景测试检查。预期结果描述设计契约；测试不调用服务、不验证真实签名/并发原子性，也不使用生产身份或数据。

| 场景 | 合成输入 / 边界 | 契约预期 |
| --- | --- | --- |
| IDN-S01 有效兑换 | 有效 APP session；未过期且未撤销的 ticket；audience、route、origin、nonce、jti 和完整身份范围均匹配 | 原子消费一次并仅返回该 route 的临时上下文；不存在可复用凭证 |
| IDN-S02 重复兑换 / 重放 | 已消费的 jti、重复请求或重放 nonce | 拒绝且不返回上下文；记录最小化拒绝审计 |
| IDN-S03 过期 | bridge 已超过服务端短 TTL | 拒绝，不续期、不执行受保护操作 |
| IDN-S04 撤销 | bridge 已显式撤销，或服务端无法确认撤销状态 | 拒绝并 fail closed |
| IDN-S05 APP 退出 | APP logout 后尝试兑换退出前签发的待用 bridge / 使用派生兼容态 | 撤销待用票据和派生兼容态；后续请求拒绝 |
| IDN-S06 audience 错误 | ticket audience 与目标 adapter 不符，或指向 Wish/Commerce 的其他 audience | 拒绝，不跨 audience 转发或重试 |
| IDN-S07 route / origin 错误 | 单独替换 route 或 origin，或使用未登记的组合 | 拒绝，不接受 query、跳转目标或客户端自报值扩大 allowlist |
| IDN-S08 授权 scope 不匹配 | subject、tenant、site、relationship、purpose、consent 或 field scope 任一不匹配/过期/撤销 | 服务端重新核验并拒绝；客户端字段不覆盖可信上下文 |
| IDN-S09 超时 / 依赖失败 | Wish bridge 服务或历史 adapter 超时、不可用、结果不确定 | 不建立上下文、不自动转 legacy 登录；安全回 APP 原生页 |
| IDN-S10 旧 token 重用 | 合成旧小程序 token 完成一次服务端兑换后再次提交 | 首次兑换立即使旧 token 失效；再次使用拒绝；客户端从未收到该 token |
| IDN-S11 无泄漏 | 检查合成 URL、错误响应、普通日志及审计样本 | 无 bridge/token/nonce/raw jti/验证码/完整手机号/健康正文/被拒值；审计仅含必要脱敏引用 |
| IDN-S12 业务边界 | 一条正式迁移页面请求和一条明确属于 Wish 的新业务请求 | 前者直连 MAPP 原契约；后者走 APP BFF → Wish API/application → DDD；MAPP 边界不变 |
| IDN-S13 登录连续性 | 历史微信登录/授权与可选手机号核验来源；已登录 APP 客户打开兼容页 | 历史身份只用于映射；APP 手机号 + 短信验证码是唯一客户登录；兼容页不二次登录 |

管理端生产组织 SSO、认证 session 生命周期、登出/撤销与配置属于最终交付，由 WADM-17 实现；不得再以旧范围说明将管理员登录排除。上述为目标设计和文档覆盖，不证明 APP、Wish、MAPP 或 adapter 已实现；真实服务、生产身份数据与外部写入保持关闭。未来并发消费、签名验证和运行时拒绝审计由相应实现/安全任务验收。
## 任务统计与来源

产品方案任务图共 **173 项**：**98 项 MVP 必须**、**75 项 MVP 后续**；权威计划节点保持 `planned`，活跃 runtime 保存当前执行状态。`__start__`、`__end__` 是控制节点，不计入业务任务。管理工作台及身份当前共 **13 个任务**：`WADM-00..05` 与 `WADM-11..17`；`APPBFF-01` 是单独的 APP 后端渠道任务，`IDN-01` 是客户会话桥接设计前置。

架构规划参考手机端总体方案、数据架构、DFP Wish 后台服务设计和既有任务索引。`backend/tasks.json` 的 `deps` 是唯一机器依赖源；`data.depends_on` 仅作一致性展示。

## 既有管理端兼容能力（保留）

以下路径是当前 DFP Wish 管理端的兼容基线。本轮只做盘点和回归保护，不删除、不重命名、不重写已有能力，也不把它们计作新增开发。列出的测试入口不代表本次运行或验收结果。

| 既有能力 | 当前管理端入口 / API | 现有测试入口 |
| --- | --- | --- |
| 订单 | `apps/wish-adm/src/app/(modules)/orders/`；`exts/wish_adm/api/order_router.py` | `exts/wish_adm/api/test_*`；`domain/tests/order/` |
| 消息与广播 | `apps/wish-adm/src/app/(modules)/messages/`、`apps/wish-adm/src/app/(modules)/broadcasts/`；`exts/wish_adm/api/message_router.py` | `exts/wish_adm/api/test_message_router.py`、`exts/wish_adm/api/test_broadcast_router.py`；`domain/tests/message/` |
| 协议与同意 | `apps/wish-adm/src/app/(modules)/agreements/`，含 `consents/`；`exts/wish_adm/api/agreement_router.py` | `exts/wish_adm/api/test_agreement_admin_router.py`；`domain/tests/consumer/test_agreement_admin_appservice.py` |
| 合规 | `apps/wish-adm/src/app/(modules)/compliance/`；`exts/wish_adm/api/compliance_router.py` | `domain/tests/compliance/test_compliance_routes.py` |
| App 发布 | `apps/wish-adm/src/app/(modules)/app-releases/`；`exts/wish_adm/api/app_release_router.py` | `exts/wish_adm/api/test_app_release_router.py`；`domain/tests/app_release/` |
| 运营成员 | `apps/wish-adm/src/app/(modules)/operators/`；`exts/wish_adm/api/operator_router.py` | `exts/wish_adm/api/test_operator_router.py`、`exts/wish_adm/api/test_operator_auth.py`；`domain/tests/staff/` |
| 用户查询 | `exts/wish_adm/api/users_router.py` | `exts/wish_adm/api/test_users_router.py` |

新增客户档案工作域针对 Wish SCRM 客户主档，不替换既有用户查询 API 或协议/同意管理入口。既有任务文件 claims 不被新增任务接管。

## 六个管理工作域与纵向模块映射

| 模块 | Wish API/DDD 与数据 | APP / APP BFF（共用 `IDN-01` 客户会话上下文） | 管理工作台 | 后置横向集成 |
| --- | --- | --- | --- | --- |
| 客户档案与授权 | `API-04`、`SCR-01`、`SCR-02`、`DB-05` | `APPBFF-01`、`HLT-06` | `WADM-11` | `SEC-*`、`REL-*` |
| 健康服务与预约 | `API-05`、`API-06`、`DB-04`、`OPS-01/02/04/05/07` | `APPBFF-01`、`HLT-01`、`HLT-03`、`HLT-04` | `WADM-04`、`WADM-12` | `HLT-07`、通知/发布验收 |
| 履约与服务记录 | `API-08`、`SCR-03`、`DB-05`、`API-09` | `APPBFF-01`、疗愈师任务/服务记录入口 | `WADM-13` | `REL-*`、审计验收 |
| SCRM 与客户跟进 | `API-08`、`API-09`、`SCR-01..04`、`SCR-07/08` | `APPBFF-01`、`HLT-07` | `WADM-05`、`WADM-14` | 消息、通知、回访回归 |
| 健康服务账 | `API-07`、`SCR-05/06`、`DB-05` | `APPBFF-01`、`HLT-05` 服务卡/权益入口 | `WADM-15` | Commerce 只读引用、对账、发布验收 |
| 权限与审计 | `API-03`、`API-10`、`SEC-*` | 客户端只消费授权结果 | `WADM-16` | 全链路拒绝审计、恢复验收 |

六个管理工作域都由 `apps/wish-adm` 运营工作台调用同一 Wish 后台：

| 管理工作域 | 任务 | 页面路径 | Admin BFF | DDD 上下文 | 边界 |
| --- | --- | --- | --- | --- | --- |
| 客户档案 | `WADM-11` | `apps/wish-adm/src/app/(modules)/customers/` | `exts/wish_adm/api/customer_profile_router.py` | `domain/customer_profile_admin/` | 客户主标识、关系、低敏授权投影、标签与只读时间线；健康字段按用途/站点/字段权限裁剪。 |
| 健康预约 | `WADM-12` | `apps/wish-adm/src/app/(modules)/appointments/` | `exts/wish_adm/api/appointment_admin_router.py` | `domain/health_appointment_admin/` | 履约视图覆盖状态、资源快照、冲突、候补、改期/取消；提交调用 Wish 预约事务。 |
| 服务记录 | `WADM-13` | `apps/wish-adm/src/app/(modules)/service-records/` | `exts/wish_adm/api/service_record_admin_router.py` | `domain/service_record_admin/` | 记录只追加；更正保留旧版本。用品只作本次服务的文本备注。 |
| 客户跟进 | `WADM-14` | `apps/wish-adm/src/app/(modules)/follow-ups/` | `exts/wish_adm/api/followup_admin_router.py` | `domain/customer_followup_admin/` | 回访、投诉/反馈、责任、结果、触达偏好、退订和失败状态；使用业务处理队列。 |
| 服务账 | `WADM-15` | `apps/wish-adm/src/app/(modules)/service-ledger/` | `exts/wish_adm/api/service_ledger_admin_router.py` | `domain/health_service_ledger_admin/` | 查看健康服务费用、服务卡、应收、退款审核和 Wish 账状态；商城数据只以受控只读引用查看。 |
| 权限与审计 | `WADM-16` | `apps/wish-adm/src/app/(modules)/access-audit/` | `exts/wish_adm/api/access_audit_admin_router.py` | `domain/authorization_audit_admin/` | 查看获批角色范围、目的同意、字段访问、客户关系变更和拒绝审计；默认不呈现健康正文。 |

主要 Wish API/DDD 路径由任务唯一拥有：

| 任务 | 计划路径 | 责任 |
| --- | --- | --- |
| `IDN-01` | `docs/architecture/dag-admin-architecture.md` 客户统一登录与会话桥接章节 | 独占桥接设计章节；列明 APP session adapter、APP BFF、Wish API/application/DDD、legacy adapter 和测试路径，不拥有这些实现文件。 |
| `API-02` | `exts/wish/api/identity/migration_session_router.py`、`domain/identity_migration/` | Wish 服务端 bridge 签发/原子兑换、身份上下文和生命周期审计实现；不实现 APP BFF 或 legacy adapter。 |
| `API-04..10` | `exts/wish/api/*_router.py` 与 `domain/<context>/application/` | Wish API/application service 到领域应用服务的路由适配；核心聚合/写主归 `SCR-*`、`OPS-*`。 |
| `DB-04` | `domain/alembic/versions/health_appointment_resources.py` | 预约、时段、资源锁 schema 与 repository 基础。 |
| `DB-05` | `domain/alembic/versions/scrm_service_records_and_ledger.py` | SCRM、服务记录、服务卡和健康服务账 schema。 |
| `APPBFF-01` | `exts/wish_app/api/*_bff_router.py`、`exts/wish_app/api/_shared/bff_contracts.py`、`domain/app_bff/application/wish_service_gateway.py` | APP 渠道适配、DTO 与授权上下文传递；不拥有领域事实或 DB schema。 |
| `WADM-01..05`、`WADM-11..16` | `apps/wish-adm/`、`exts/wish_adm/api/`、`domain/*_admin/` | 同一 Wish 服务中的 Admin BFF、管理查询/操作适配和运营工作台。 |

准确依赖以 JSON 为准。小程序迁移前端链为 `APP 页面/feature -> MAPP server -> 原有业务数据/服务`，不经过 Wish BFF/DDD。Wish 正式业务链为 Wish 责任/契约和 canonical schema -> Wish API/DDD、事务、Outbox 与只读投影 -> `APPBFF-01` / Admin BFF -> 对应 APP 页面和管理工作域 -> 模块测试/回退 -> `REL-*` 集成验收。兼容回退泳道只处理历史 route/adapter 安全回退。`HLT-07` 的消息联调依赖 `WADM-05`、`WADM-14`；`HWI-02` 服务发现依赖健康预约 APP/管理闭环 `HLT-04`、`WADM-12`；`HWI-03` 商城权益只读交接依赖服务账 APP/管理闭环 `HLT-05`、`WADM-15`；`HWI-04` 活动归因依赖 SCRM 客户端/管理闭环 `HLT-07`、`WADM-14`。`REL-05` 依赖 `HLT-05`、六个管理工作域和 APP BFF，确保发布集成晚于 Wish 纵向闭环。

`IDN-01` 提供跨客户模块共用的 APP session 与历史 route bridge 设计契约，不替代任何模块闭环。小程序迁移前端任务通过 MAPP server 原服务契约访问迁移前已有的业务；健康/SCRM/预约/履约/服务账等明确属于 Wish 的业务逐模块串起 APP 入口、`APPBFF-01`、Wish API/DDD、数据/事件、管理工作域、测试和回退。Wish 纵向闭环后再做客户关系、消息、Commerce 只读引用、预约—履约—服务账联调和发布验收；Wish 登录桥接的全链路拒绝审计纳入 `TST-05` / `SEC-04`。

## 管理工作台支撑任务

| 任务 | 交付内容 | 唯一写入范围 / 主要依赖 |
| --- | --- | --- |
| `WADM-00` | 本索引、既有兼容能力登记、模块边界与排除项 | 唯一写入本文件；依赖 `GOV-05`、`GOV-06`。 |
| `WADM-01` | 六个工作域的 Admin BFF/API envelope、分页、幂等、错误、范围和字段投影契约 | 独占管理端共享契约文件；依赖 `API-01`、`API-03`。不定义登录/session API。 |
| `WADM-02` | 管理端 DDD 应用适配边界和六个业务上下文写主归属 | 独占 `domain/admin_console/`；通过 gateway 调用同一 Wish 领域应用服务。 |
| `WADM-03` | canonical 事实之上的管理查询索引/可重建投影 | 独占管理投影模型和单个增量 migration；不复制 canonical 事实表。 |
| `WADM-04` | 目录版本、站点设置、可约资源与容量配置管理适配 | 独占目录/可约性管理组件、Admin BFF 和 admin domain adapter。 |
| `WADM-05` | SCRM 服务任务队列、事件消费及通知结果适配 | 独占 `domain/scrm_task_queue/` 和其 Admin BFF API；复用 `API-09` Outbox/Inbox、`OPS-08` 队列范围。 |

## 授权、数据与事件规则

- 每次读写都由 Wish 服务端根据授权主体解析 tenant/site；请求中的 `site_id` 不能覆盖授权范围。APP BFF 和 Admin BFF 复用 `API-03` 角色/站点策略；管理端组织身份、operator 映射和管理员 session 由 `WADM-17` 单独处理。
- 客户 APP session 是唯一登录来源；迁移 bridge 仅短时单次续接身份。退出、撤销、过期、越权或桥接失败要 fail closed 并写入脱敏审计，fallback 只回 APP 原生安全页/APP 登录入口。
- 客户、健康数据、预约、服务记录、服务账和审计采用最小字段投影。家属/代理关系本身不构成健康字段授权；跨站访问要有具体对象、站点、用途和有效期授权。
- Wish 是健康服务、SCRM 和健康服务账唯一权威写端；Commerce/MER 是商城订单和商城账唯一权威写端。禁止双写、账本合并或将商城购买推导成健康预约/参与事实。
- Outbox/Inbox 事件固定源 tenant/site 并支持幂等重放。事件只含业务引用、低敏状态和版本，不带手机号、健康正文、媒体地址。通知发送前复核用途同意、偏好、频控和退订；发送失败可追踪、退避并进入可处理状态。
- 预约可用性、房间/设备/服务角色约束、容量、冲突、候补、改期和取消属于健康服务履约主线；它们不建立员工日历，也不维护员工班次、休假或调班。
- 历史 route/外链 fallback 由 APP 路由 allowlist 和短期 adapter 控制；fallback 不改变业务写主。MAPP server 是小程序迁移前端调用的原业务后端，不是 Wish API/DDD 的替代或子集。

## Wish 原生域排除（MAPP 页面迁移仍执行）

- 不得新建未经来源登记的身份任务；Wish Admin 组织 SSO 已由 `WADM-17` 纳入交付，使用 Feishu OAuth/IAM、当前 `union_id` → operator contract 和服务端 active/role/tenant/site 校验。`IDN-01` 仅负责客户 APP migration bridge，不取代管理员认证。
- Wish 不新增员工排班管理、班次、休假、调班、员工日历和人员资源维护界面；健康预约仅消费已确认的可用性/资源状态。
- Wish 不新增物料/耗材库存、低库存、仓库、采购、盘点或仓库成本域；服务记录可写本次用品文本。MAPP 来源商品/库存页面 MP160–MP162 由 MER-06 迁入 APP 并调用 MAPP/Commerce 原服务。
- Wish 不新增绩效、提成、薪酬、员工结算、额外运营 KPI/日报或 Wish 商城收银/经营后台。该边界只限定 Wish 健康/SCRM 域；MAPP/Commerce 管理端必须按垂直闭环矩阵建设。MAPP 来源页 MP141–MP159 由 MER-03..05 迁入 APP 并调用 MAPP/Commerce 原服务，不进入 Wish 服务账。
- 不在 Wish 健康/SCRM 内新建重复的 MAPP 后台或第二写主。MAPP/Commerce 的原平台端、商家端继续按六个垂直域任务补齐管理页面；API 和数据库沿用原 MAPP 权威实现并由源码/集成验收核验，只有确认管理操作缺少能力时才扩展原服务。APP 迁移页继续调用该权威 MAPP 服务。

## 校验口径

任务图校验应确认基线含 **173** 个任务（98/75），ID 唯一，`deps` 全部存在且无环，`data.depends_on` 与 `deps` 一致；MVP 统计由 `data.scope == "MVP必须"` 计算，后续统计由 `data.scope == "MVP后续"` 计算。迁移任务必须使用独占 `formal-app-migration`、声明 `backend_target: MAPP server`，且不依赖 Wish APP BFF/DDD；明确属于 Wish 的任务使用 `wish-formal-business`。其他迁移边界的 `data.migration_lane` 可为 `legacy-compatibility-fallback` 或 `cross-cutting-security-gate`。新增任务必须有唯一 `file_claims`、可执行 `targeted_tests` 和任务级 `rollback_or_fallback`；新增数据不填写 owner、commit、evidence 或 verified_at。

## 上位方案全量覆盖 registry

手机端总体设计是 DAG 的上位基线。DAG 需要追踪总体方案、迁移清单和跨项目架构中的可执行事项、当前保留项、明确范围外项及架构约束类别；40 个 `formal-app-migration` 页面任务、163 条 route-to-task 映射和 13 个 Wish 原生任务均须逐项覆盖，不构成完整覆盖声明。

机器登记唯一位于 `backend/tasks.json` 的 `GOV-01.data.overall_plan_coverage.requirements_registry`。每项必须有唯一 `source_id`、`source_file`、`source_section`、`coverage_status`、`mapped_task_ids`、`client`、`backend_target` 和 `migration_lane`；每个任务必须在 `data` 中写入非空 `source_of_truth`、`source_item_ids` 和 `coverage_status`。允许的覆盖状态为 `planned`、`current-state-retained`、`out-of-scope-with-reason`，范围外条目须给出 `coverage_reason`。`current-state-retained` 仅表示来源文档要求保留该基线，不表示运行时已验证。registry 和任务映射必须完全双向，不得出现未映射项、孤立任务或来源为空的通用任务。

在仓库根目录执行以下校验；若来源项目不在默认目录，传入上游仓库根目录：

```sh
python scripts/validate_plan_coverage.py --source-root /home/agent/code/jiankang_app_uniapp
```

脚本检查 registry 非空、来源/状态/泳道字段、任务映射双向完整、173 个基线任务、98/75 范围统计、9 个垂直业务闭环与 24 个 MAPP 管理/原后端复用核验/集成节点、ID 唯一、依赖存在且 `data.depends_on` 与 `deps` 一致、DAG 无环、40/13 两条后端泳道边界，以及 163 条页面到任务的完整映射和 40 个正式迁移任务的 MP 页面 ID。登记状态和脚本通过只证明覆盖与结构校验，不证明业务实现。

## WADM-00 管理端兼容基线登记（既有能力，不验收）

| # | 既有能力 | 位置 | 本轮 |
|---|---|---|---|
| 1 | 订单 | apps/wish-adm/src/app/(modules)/orders | 保留兼容，不改造 |
| 2 | 消息/广播 | apps/wish-adm/src/app/(modules)/messages | 保留兼容 |
| 3 | 协议/同意 | apps/wish-adm/src/app/(modules)/agreements | 只读引用 |
| 4 | 合规 | apps/wish-adm/src/app/(modules)/compliance | 保留 |
| 5 | App发布 | apps/wish-adm/src/app/(modules)/app-releases | 保留 |
| 6 | 运营成员 | apps/wish-adm/src/app/(modules)/operators | 保留 |
| 7 | 用户查询 | exts/wish_adm/api/users_router.py | 只读，不扩权 |

六个 Wish 前台业务域（客户档案/健康记录/预约/履约/SCRM/服务账）纵向支撑管理端同名工作域，边界以各 WADM task file_claim 为准；Wish Admin 组织 SSO 由 WADM-17 实施。MAPP 商户/员工移动页面（订单、售后、收银、库存）由 APP `MER-02..06` 迁移任务单独承接，不进入 Wish 服务账或疗愈师页面。未出现在来源路由和上位方案中的排班、薪酬、仓储成本及新增运营 BI 继续不扩展。
