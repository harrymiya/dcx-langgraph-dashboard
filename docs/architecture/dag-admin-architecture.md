# DFP Wish 管理端健康服务与 SCRM 架构任务索引

本文是 `backend/tasks.json` 中管理端新增任务的索引与范围基线。任务仍全部为 `planned`；这里的设计、已有代码路径和验收场景都不构成功能已实现或通过验收的证据。

## 来源与范围

- 手机端与角色总体方案：`/home/agent/code/jiankang_app_uniapp/docs/ruixin-health-app-scrm-complete-design.md`，重点参考角色入口、前台 PC Web 六个一级导航、SCRM、权威域与权限边界。
- 数据架构：`/home/agent/code/jiankang_app_uniapp/docs/data-architecture-design.md`，重点参考第 12–13 节服务目录、资源容量、客户服务、服务账、事件和数据隔离模型。
- Wish 后台服务设计：`/home/agent/code/jiankang_app_uniapp/docs/dfp-wish-backend-service-design.md`，重点参考 BFF/API、RBAC+ABAC、事务/事件、目录预约和客户运营 API 设计。
- 当前任务索引：`/home/agent/code/jiankang_app_uniapp/docs/migration/dag/task-index.md`；既有 `API-*`、`DB-*`、`SCR-*`、`OPS-*` 是下面新增管理端任务的领域 API、schema 与运营支撑前置，不由新任务复制其权威写入职责。

本轮新增 **12 个任务**。任务图共 **141 项**，其中 **95 项 MVP必须**、**46 项 MVP后续**。六个前台管理工作域均属于健康服务与 SCRM MVP。业务归属以 Wish 为健康服务/SCRM 权威域，Commerce/MER 继续独立维护商城事实和商城账。

## 既有管理端兼容能力（保留）

以下路径是当前 DFP Wish 管理端的兼容基线。本轮将其标记为“既有兼容能力”，仅供盘点和回归保护；不删除、不重命名、不重写其能力描述，也不将它们计作本轮新开发。列出的测试文件是现有测试入口，不代表本次运行或验收结果。

| 既有能力 | 当前管理端入口 / API | 现有测试入口 |
| --- | --- | --- |
| 订单 | `apps/wish-adm/src/app/(modules)/orders/`；`exts/wish_adm/api/order_router.py` | `exts/wish_adm/api/test_*`；`domain/tests/order/` |
| 消息与广播 | `apps/wish-adm/src/app/(modules)/messages/`、`apps/wish-adm/src/app/(modules)/broadcasts/`；`exts/wish_adm/api/message_router.py` | `exts/wish_adm/api/test_message_router.py`、`exts/wish_adm/api/test_broadcast_router.py`；`domain/tests/message/` |
| 协议与同意 | `apps/wish-adm/src/app/(modules)/agreements/`，含 `consents/`；`exts/wish_adm/api/agreement_router.py` | `exts/wish_adm/api/test_agreement_admin_router.py`；`domain/tests/consumer/test_agreement_admin_appservice.py` |
| 合规 | `apps/wish-adm/src/app/(modules)/compliance/`；`exts/wish_adm/api/compliance_router.py` | `domain/tests/compliance/test_compliance_routes.py` |
| App 发布 | `apps/wish-adm/src/app/(modules)/app-releases/`；`exts/wish_adm/api/app_release_router.py` | `exts/wish_adm/api/test_app_release_router.py`；`domain/tests/app_release/` |
| 运营成员 | `apps/wish-adm/src/app/(modules)/operators/`；`exts/wish_adm/api/operator_router.py` | `exts/wish_adm/api/test_operator_router.py`、`exts/wish_adm/api/test_operator_auth.py`；`domain/tests/staff/` |
| 用户查询 | `exts/wish_adm/api/users_router.py` | `exts/wish_adm/api/test_users_router.py` |

既有兼容能力不进入新增模块的文件 claim。新增用户档案工作域针对 Wish SCRM 客户主档，不替换既有用户查询 API 或协议/同意管理入口。

## 六个前台工作域

管理端一级导航只增加总体方案指定的六项。每项任务的 `target_paths_or_modules` 与 `file_claims` 在 `backend/tasks.json` 中给出了独占路径；这里列出主页面和 API/domain 落点。

| 一级工作域 | 任务 | 页面路径 | Wish 管理 API | DDD 上下文 | 边界 |
| --- | --- | --- | --- | --- | --- |
| 客户档案 | `WADM-11` | `apps/wish-adm/src/app/(modules)/customers/` | `exts/wish_adm/api/customer_profile_router.py` | `domain/customer_profile_admin/` | 客户主标识、身份映射、关系、低敏授权投影、标签与只读时间线；健康字段按用途、站点和字段范围裁剪。 |
| 健康预约 | `WADM-12` | `apps/wish-adm/src/app/(modules)/appointments/` | `exts/wish_adm/api/appointment_admin_router.py` | `domain/health_appointment_admin/` | 履约视图，覆盖预约状态、资源快照、冲突、候补、改期/取消；提交调用现有预约事务。 |
| 服务记录 | `WADM-13` | `apps/wish-adm/src/app/(modules)/service-records/` | `exts/wish_adm/api/service_record_admin_router.py` | `domain/service_record_admin/` | 记录只追加；更正保留旧版本。用品只作本次服务的文本备注。 |
| 客户跟进 | `WADM-14` | `apps/wish-adm/src/app/(modules)/follow-ups/` | `exts/wish_adm/api/followup_admin_router.py` | `domain/customer_followup_admin/` | 回访、投诉/反馈、责任、结果、触达偏好、退订和失败状态；使用业务处理队列。 |
| 服务账 | `WADM-15` | `apps/wish-adm/src/app/(modules)/service-ledger/` | `exts/wish_adm/api/service_ledger_admin_router.py` | `domain/health_service_ledger_admin/` | 查看健康服务费用、服务卡、应收、退款审核和 Wish 账状态；商城数据只以受控只读引用查看。 |
| 权限与审计 | `WADM-16` | `apps/wish-adm/src/app/(modules)/access-audit/` | `exts/wish_adm/api/access_audit_admin_router.py` | `domain/authorization_audit_admin/` | 查看获批角色范围、目的同意、字段访问、客户关系变更和拒绝审计；默认不呈现健康正文。 |

## 管理端纵向支撑任务

| 任务 | 交付内容 | 唯一写入范围 / 主要依赖 |
| --- | --- | --- |
| `WADM-00` | 本索引、兼容能力登记、模块边界与排除项 | 唯一写入 `docs/architecture/dag-admin-architecture.md`；依赖 `GOV-05`、`GOV-06`。 |
| `WADM-01` | 六个工作域的 BFF/API envelope、分页、幂等、错误、范围和字段投影契约 | shared contract 文件；依赖 `API-01`、`API-03`。不定义登录/session API。 |
| `WADM-02` | 管理端 DDD 应用适配边界和六个业务上下文写主归属 | 独占 `domain/admin_console/`；六个具体业务上下文由 `WADM-11..16` 分别拥有。 |
| `WADM-03` | 现有 canonical 事实之上的管理查询索引/可重建投影 | 独占管理投影模型和单个增量 migration；依赖 `DB-03/04/05`、`API-09`，不复制 canonical 事实表。 |
| `WADM-04` | 目录版本、站点设置、可约资源与容量配置管理适配 | 目录/可约性专属组件、API 和 domain；依赖 `API-05/10`、`OPS-01/02/04/07`。 |
| `WADM-05` | SCRM 服务任务队列、事件消费及通知结果适配 | 独占 `domain/scrm_task_queue/` 和其 API；复用 `API-09` Outbox/Inbox、`OPS-08` 队列范围。 |

任务依赖的主链为：治理与现有通用契约 → `WADM-00` 范围 → `WADM-01/02/03` 共用纵向基础 → `WADM-04/05` 预约资源及 SCRM 队列支撑 → 六个业务工作域。准确 DAG 以 JSON `deps` 为准。

## 授权、数据与事件规则

- 每次读写都由服务端根据授权主体解析 tenant/site；请求中的 `site_id` 不能覆盖授权范围。管理端复用现有 `API-03` 角色/站点策略，不新增管理员身份认证任务。
- 客户、健康数据、预约、服务记录、服务账和审计采用最小字段投影。家属/代理关系本身不构成健康字段授权；跨站访问要有具体对象、站点、用途和有效期授权。
- Wish 是健康服务、SCRM 和健康服务账唯一权威写端；Commerce/MER 是商城订单和商城账唯一权威写端。禁止双写、账本合并或将商城购买推导成健康预约/参与事实。
- Outbox/Inbox 事件固定源 tenant/site 并支持幂等重放。事件只含业务引用、低敏状态和版本，不带手机号、健康正文、媒体地址。通知发送前复核用途同意、偏好、频控和退订；发送失败可追踪、退避并进入可处理状态。
- 预约可用性、房间/设备/服务角色约束、容量、冲突、候补、改期和取消属于健康服务履约主线；它们不建立员工日历，也不维护员工班次、休假或调班。

## 本轮明确排除

- 管理员登录、验证码、认证、session、token 或凭据问题；不新增或调整 AUTH 任务。
- 员工排班管理、班次、休假、调班、员工日历和人员资源维护界面。
- 物料/耗材库存、低库存、仓库、采购、盘点或仓库成本。服务记录可写本次用品文本。
- 绩效、提成、薪酬、员工结算；日常运营 KPI/日报；日常收银工作台；商户经营管理。

## 校验口径

任务图校验应确认全部任务状态为 `planned`，ID 唯一，`deps` 无未知 ID 且无环，MVP 统计由 `data.scope == "MVP必须"` 计算，后续统计由 `data.scope == "MVP后续"` 计算。新增任务均必须有唯一 `file_claims`、可执行 `targeted_tests` 和任务级 `rollback_or_fallback`；新增数据不填写 owner、commit、evidence 或 verified_at。
