# DFP Wish 健康服务与 SCRM DAG 架构索引

本文索引 `backend/tasks.json` 的 APP、DFP Wish 后端和管理工作台任务。任务仍全部为 `planned`；设计、目标代码路径和验收场景均不构成功能已实现或通过验收的证据。

## 正式架构基线

指定小程序迁入 APP 只迁移前端页面/入口，独占 `formal-app-migration` 泳道；正式链路为 `APP 中的小程序迁移业务 → MAPP server → 原有业务数据/服务`。未迁移的小程序原客户端独立沿用 `小程序原客户端 → MAPP server`。APP 首页三个第三方小程序按钮只拉起其他第三方小程序，是外部入口，不属于本次迁移且不进入迁移任务。明确属于 Wish 的健康、SCRM、预约、履约和健康服务账功能进入单独的 `wish-formal-business` 泳道；它们不得与小程序迁移泳道混用。

正式主链固定为：

```text
小程序迁移泳道：APP 页面/入口 -> feature/repository -> MAPP server -> 原有业务数据/服务
Wish 正式业务泳道：APP -> Wish APP BFF -> Wish API/application service -> DDD domain
  -> repository/UoW/事务 -> Wish 数据层/Outbox/Event -> read model/audit
```

管理工作台通过 Wish Admin BFF 调用同一 Wish API/application service 和 DDD 写主。APP BFF/Admin BFF 都是 DFP Wish 内的渠道适配层，不是独立业务后端。Commerce/MER 继续独立负责商城事实；Wish 不双写商城事实，只接收受控只读引用。

## 正式 APP 迁移业务与兼容回退泳道

`formal-app-migration` 只登记确属小程序前端页面/入口迁移的任务。此类任务声明 `backend_target: MAPP server`，只交付 APP 前端调用适配和路由/页面；MAPP server 继续使用原有业务数据/服务。迁移任务不得依赖 Wish APP BFF、Wish API 或 Wish DDD。

明确属于 Wish 的新业务不属于小程序迁移泳道，单独使用 `wish-formal-business`：`APPBFF-01`、`HLT-*` 和相应 `HWI-*` 按 Wish API/DDD、schema、事件、管理工作域、测试与回退形成纵向闭环。Wish 业务依赖 APPBFF-01 是合理的；它不得被误读为迁移任务依赖。

`legacy-compatibility-fallback` 是独立的受控回退泳道，只包含历史 route 登记、短期 adapter 和安全回退。它不改变 MAPP server 作为小程序迁移页面后端目标的边界；MAPP server 不新增独立登录、长期 token 或与本次页面迁移无关的新业务 API。

`backend/tasks.json` 的 `data.migration_lane` 按任务边界标注：`COM-*`、`ORD-*`、`MEM-*`、`CNT-*`、`USR-*`、`MER-*` 为 `formal-app-migration`，且每项有 `backend_target: MAPP server`；`APPBFF-01`、`HLT-*` 和明确属于 Wish 的 `HWI-*` 为 `wish-formal-business`；`GOV-03`、`FND-05`、`FND-08` 为 `legacy-compatibility-fallback`；共享身份契约/实现及安全门禁 `GOV-02`、`GOV-05`、`FND-01`、`API-02`、`API-03`、`IDN-01`、`SEC-*`、`TST-05`、`TST-06` 为 `cross-cutting-security-gate`。未跨越这些业务边界的通用平台任务可不填写该字段。

小程序前端迁移任务可以直接依赖 `IDN-01` 获取 APP session 边界契约，但不得依赖 `APPBFF-01`、Wish API 或 Wish DDD；Wish BFF/DDD 依赖仅适用于任务本身明确属于 Wish 的业务。桥接实现/适配任务 `FND-01`、`API-02`、`APPBFF-01`、`FND-08` 和安全验收 `TST-05`、`SEC-04` 按各自职责依赖 `IDN-01`；`TST-05`、`SEC-04` 对 Wish 业务链的安全验收依赖 `APPBFF-01`。`IDN-01` 是设计前置，不反向依赖下游实现。

横向集成必须晚于参与模块的纵向闭环，包含身份授权、tenant/site 与客户关系、消息/通知、Commerce 受控只读引用、预约—履约—服务账、发布和恢复验收。`IDN-01` 是共享客户会话桥接契约，不替代模块闭环；`APPBFF-01` 是明确属于 Wish 的业务渠道适配任务；`TST-05`、`SEC-04` 是共享安全门禁。

## 客户统一登录与会话桥接设计

小程序现状是微信登录/授权并可进行手机号核验；迁移后的客户入口是 APP 手机号 + 短信验证码，客户只在 APP 登录一次。历史小程序身份只能由服务端在该迁移契约内核验/映射；如需处理旧 token，只允许服务端一次性交换并立即使旧 token 失效，不要求客户重新登录小程序。`IDN-01` 是客户侧共享设计前置，定义从 APP session 进入历史迁移页面或短期兼容 adapter 时的一次性身份续接；它本身不代表 APP 页面、Wish 业务 API 或 DDD 已实现。

```text
APP 已登录 session
  → APP migration-session adapter
  → Wish APP BFF 请求 bridge
  → Wish API/application service 验证 APP session 并签发 opaque、短 TTL、单次 bridge
  → allowlist 内的 legacy adapter 原子兑换 bridge，获得仅限该路由的临时身份上下文
  → Wish DDD 统一解析 principal / tenant-site / subject / relationship / purpose / consent
```

- Bridge 绑定 audience、allowlist route/origin、nonce/jti、subject、tenant/site、relationship、purpose、consent 版本与有效期；只允许一次兑换。兑换仅向可信 adapter 提供该路由的临时身份上下文，不返回可复用凭据。它只续接迁移期身份，不作为长期凭据、独立登录或新业务授权。不得把 bridge 放进 URL、普通日志或客户端可复用存储。
- 如迁移涉及既有小程序 token，旧 token 只在服务端进行一次性交换并立即失效；不得发回客户端、兑换为可复用 token，或继续接受旧 token。无法确认原子失效时 fail closed。
- Wish API/application/DDD 只为明确属于 Wish 的业务解析身份上下文与授权。客户端提交的 principal、tenant/site、subject、relationship、purpose 和 consent 不可信；兑换及敏感操作时复核关系、同意、用途和有效期。
- Wish APP BFF 只适配 Wish 业务路由/DTO 并调用 Wish application service，不直连数据库。明确属于 Wish 的健康、预约、履约、SCRM 和服务账请求仍走 APP → Wish APP BFF → Wish API/DDD；正式迁移页面按原服务契约调用 MAPP server。
- MAPP server 按原服务契约继续承载正式迁移页面调用的既有业务和未迁移小程序业务；它不独立登录、不签发长期 token，也不被替换为 Wish 新业务 API。失败时 bridge/兼容入口 fail closed：APP session 有效则回 APP 原生安全页，失效则回 APP 登录入口，不转到独立 legacy 登录。
- APP 退出时撤销该客户尚未兑换的 bridge。退出、bridge 撤销/过期、重放、错误 audience/route、主体/站点/关系/用途/同意越权及 bridge 服务故障都产生脱敏最小化审计；日志不含 bridge、健康正文或完整敏感标识。

设计节点 `IDN-01` 依赖 `GOV-02`、`GOV-03`、`GOV-05` 和 `API-01`。APP session adapter、Wish bridge API/DDD、APP BFF、legacy adapter 和安全集成测试分别由 `FND-01`、`API-02`、`APPBFF-01`、`FND-08`、`TST-05` 拥有并显式依赖该设计；全部正式 APP 客户业务任务也直接依赖该共享契约。`API-03` 负责运行时统一 scope/拒绝策略；`TST-05`、`SEC-04` 直接依赖 `APPBFF-01` 并验证正式主链与 legacy 边界。`IDN-01` 只定义客户 APP session 到历史页面/短期 adapter 的短期、一次性、opaque migration session bridge，不是独立登录、长期 token 或通用业务授权。此客户认证设计不涉及管理端认证，不新增或调整管理员 `AUTH` 任务。

## 任务统计与来源

任务图共 **143 项**：**97 项 MVP 必须**、**46 项 MVP 后续**；当前任务状态均为 `planned`。`__start__`、`__end__` 是控制节点，不计入业务任务。管理工作台本轮增加的 **12 个任务**是 `WADM-00..05` 与 `WADM-11..16`；`APPBFF-01` 是单独的 APP 后端渠道任务，`IDN-01` 是客户会话桥接设计前置。

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

- 每次读写都由 Wish 服务端根据授权主体解析 tenant/site；请求中的 `site_id` 不能覆盖授权范围。APP BFF 和 Admin BFF 复用 `API-03` 角色/站点策略，不新增管理员身份认证任务。
- 客户 APP session 是唯一登录来源；迁移 bridge 仅短时单次续接身份。退出、撤销、过期、越权或桥接失败要 fail closed 并写入脱敏审计，fallback 只回 APP 原生安全页/APP 登录入口。
- 客户、健康数据、预约、服务记录、服务账和审计采用最小字段投影。家属/代理关系本身不构成健康字段授权；跨站访问要有具体对象、站点、用途和有效期授权。
- Wish 是健康服务、SCRM 和健康服务账唯一权威写端；Commerce/MER 是商城订单和商城账唯一权威写端。禁止双写、账本合并或将商城购买推导成健康预约/参与事实。
- Outbox/Inbox 事件固定源 tenant/site 并支持幂等重放。事件只含业务引用、低敏状态和版本，不带手机号、健康正文、媒体地址。通知发送前复核用途同意、偏好、频控和退订；发送失败可追踪、退避并进入可处理状态。
- 预约可用性、房间/设备/服务角色约束、容量、冲突、候补、改期和取消属于健康服务履约主线；它们不建立员工日历，也不维护员工班次、休假或调班。
- 历史 route/外链 fallback 由 APP 路由 allowlist 和短期 adapter 控制；fallback 不改变业务写主。MAPP server 是小程序迁移前端调用的原业务后端，不是 Wish API/DDD 的替代或子集。

## 本轮明确排除

- 管理员登录、验证码、认证、session、token 或凭据问题；不新增或调整 AUTH 任务。`IDN-01` 仅设计客户 APP session bridge，不改变管理员认证范围。
- 员工排班管理、班次、休假、调班、员工日历和人员资源维护界面。
- 物料/耗材库存、低库存、仓库、采购、盘点或仓库成本。服务记录可写本次用品文本。
- 绩效、提成、薪酬、员工结算；日常运营 KPI/日报；日常收银工作台；商户经营管理。
- 新建第二套小程序业务后台或管理平台；MAPP server 按既有服务契约承载指定小程序迁移页面和未迁移小程序原客户端。

## 校验口径

任务图校验应确认全部 **143** 个任务状态为 `planned`，ID 唯一，`deps` 全部存在且无环，`data.depends_on` 与 `deps` 一致；MVP 统计由 `data.scope == "MVP必须"` 计算，后续统计由 `data.scope == "MVP后续"` 计算。迁移任务必须使用独占 `formal-app-migration`、声明 `backend_target: MAPP server`，且不依赖 Wish APP BFF/DDD；明确属于 Wish 的任务使用 `wish-formal-business`。其他迁移边界的 `data.migration_lane` 可为 `legacy-compatibility-fallback` 或 `cross-cutting-security-gate`。新增任务必须有唯一 `file_claims`、可执行 `targeted_tests` 和任务级 `rollback_or_fallback`；新增数据不填写 owner、commit、evidence 或 verified_at。
