# DFP Wish 健康服务与 SCRM DAG 架构索引

本文索引 `backend/tasks.json` 的 APP、DFP Wish 后端和管理工作台任务。任务仍全部为 `planned`；设计、目标代码路径和验收场景均不构成功能已实现或通过验收的证据。

## 正式架构基线

客户小程序业务并入 APP 手机端。小程序/MAPP 只保留为历史迁移来源或短期兼容 adapter；历史路由、深链与外链可以登记并做安全回退，但不在其后端新增业务能力。新的健康、SCRM、预约、履约和健康服务账功能统一进入 DFP Wish。

```text
客户 APP 页面/状态 → feature/repository → DFP Wish APP BFF ─┐
                                                            ├→ Wish API/application service
管理工作台页面       → DFP Wish Admin BFF ──────────────────┘
    → DDD domain → repository/UoW/事务 → Wish DB/Outbox/Event → read model/audit
```

APP BFF 和 Admin BFF 是 DFP Wish 内的渠道适配层。管理端是同一套 Wish 后台的运营工作台，不是另一套业务后端。Commerce/MER 独立负责商城订单和商城账；Wish 不双写商城事实，跨域只传经授权的只读引用。

`APPBFF-01` 是统一 APP BFF 方案任务，独占 `exts/wish_app/api/` 的健康档案、目录、预约、履约、SCRM、服务账 router、共享 BFF contract 和 Wish application-service gateway。它依赖相应 `API-*`、`SCR-*`、`OPS-*` 领域前置。各 `HLT-*` 客户端任务通过该 BFF 访问 Wish API，不直连数据库或旧小程序后端。

## 任务统计与来源

任务图共 **142 项**：**96 项 MVP 必须**、**46 项 MVP 后续**；当前任务状态均为 `planned`。`__start__`、`__end__` 是控制节点，不计入业务任务。管理工作台本轮增加的 **12 个任务**是 `WADM-00..05` 与 `WADM-11..16`；`APPBFF-01` 是单独的 APP 后端渠道任务。

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

| 模块 | Wish API/DDD 与数据 | APP / APP BFF | 管理工作台 | 后置横向集成 |
| --- | --- | --- | --- | --- |
| 客户档案与授权 | `API-04`、`SCR-01`、`SCR-02`、`DB-05` | `APPBFF-01`、`HLT-06` | `WADM-11` | `SEC-*`、`REL-*` |
| 健康服务与预约 | `API-05`、`API-06`、`DB-04`、`OPS-01/02/04/05/07` | `APPBFF-01`、`HLT-01`、`HLT-03`、`HLT-04` | `WADM-04`、`WADM-12` | `HLT-07`、通知/发布验收 |
| 履约与服务记录 | `API-08`、`SCR-03`、`DB-05`、`API-09` | `APPBFF-01`、疗愈师任务/服务记录入口 | `WADM-13` | `REL-*`、审计验收 |
| SCRM 与客户跟进 | `API-08`、`API-09`、`SCR-01..04`、`SCR-07/08` | `APPBFF-01`、`HLT-07` | `WADM-05`、`WADM-14` | 消息、通知、回访回归 |
| 健康服务账 | `API-07`、`SCR-05/06`、`DB-05` | `APPBFF-01`、服务卡/账状态入口 | `WADM-15` | Commerce 只读引用、对账、发布验收 |
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
| `API-04..10` | `exts/wish/api/*_router.py` 与 `domain/<context>/application/` | Wish API/application service 到领域应用服务的路由适配；核心聚合/写主归 `SCR-*`、`OPS-*`。 |
| `DB-04` | `domain/alembic/versions/health_appointment_resources.py` | 预约、时段、资源锁 schema 与 repository 基础。 |
| `DB-05` | `domain/alembic/versions/scrm_service_records_and_ledger.py` | SCRM、服务记录、服务卡和健康服务账 schema。 |
| `APPBFF-01` | `exts/wish_app/api/*_bff_router.py`、`exts/wish_app/api/_shared/bff_contracts.py`、`domain/app_bff/application/wish_service_gateway.py` | APP 渠道适配、DTO 与授权上下文传递；不拥有领域事实或 DB schema。 |
| `WADM-01..05`、`WADM-11..16` | `apps/wish-adm/`、`exts/wish_adm/api/`、`domain/*_admin/` | 同一 Wish 服务中的 Admin BFF、管理查询/操作适配和运营工作台。 |

准确依赖以 JSON 为准。纵向主链为：Wish 责任/契约和 canonical schema → Wish API/DDD、事务、Outbox 与只读投影 → `APPBFF-01` / Admin BFF → 对应 APP 页面和管理工作域 → 模块测试/回退 → `REL-*` 集成验收。`REL-05` 依赖六个管理工作域和 APP BFF，确保发布集成晚于纵向模块闭环。

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
- 客户、健康数据、预约、服务记录、服务账和审计采用最小字段投影。家属/代理关系本身不构成健康字段授权；跨站访问要有具体对象、站点、用途和有效期授权。
- Wish 是健康服务、SCRM 和健康服务账唯一权威写端；Commerce/MER 是商城订单和商城账唯一权威写端。禁止双写、账本合并或将商城购买推导成健康预约/参与事实。
- Outbox/Inbox 事件固定源 tenant/site 并支持幂等重放。事件只含业务引用、低敏状态和版本，不带手机号、健康正文、媒体地址。通知发送前复核用途同意、偏好、频控和退订；发送失败可追踪、退避并进入可处理状态。
- 预约可用性、房间/设备/服务角色约束、容量、冲突、候补、改期和取消属于健康服务履约主线；它们不建立员工日历，也不维护员工班次、休假或调班。
- 历史 route/外链 fallback 由 APP 路由 allowlist 和短期 adapter 控制；fallback 不改变业务写主，也不把 legacy MAPP 后端提升为正式业务 API。

## 本轮明确排除

- 管理员登录、验证码、认证、session、token 或凭据问题；不新增或调整 AUTH 任务。
- 员工排班管理、班次、休假、调班、员工日历和人员资源维护界面。
- 物料/耗材库存、低库存、仓库、采购、盘点或仓库成本。服务记录可写本次用品文本。
- 绩效、提成、薪酬、员工结算；日常运营 KPI/日报；日常收银工作台；商户经营管理。
- 将小程序/MAPP 作为新业务端、正式业务后端或额外管理平台。

## 校验口径

任务图校验应确认全部 **142** 个任务状态为 `planned`，ID 唯一，`deps` 全部存在且无环，`data.depends_on` 与 `deps` 一致；MVP 统计由 `data.scope == "MVP必须"` 计算，后续统计由 `data.scope == "MVP后续"` 计算。新增任务必须有唯一 `file_claims`、可执行 `targeted_tests` 和任务级 `rollback_or_fallback`；新增数据不填写 owner、commit、evidence 或 verified_at。
