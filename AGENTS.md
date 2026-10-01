# LangGraph DAG 架构与任务拆解约束

本项目只负责任务图、依赖、状态和机器验收证据，不承载手机端、管理端或 Wish 业务实现。当前任务图是总体方案的正确子集；任务设计不等于功能已实现。

## 技术架构硬约束：DAG 必须遵守统一身份与 Wish 主链

所有任务、路径、依赖、测试和回退设计都必须遵守以下架构，不得通过新增任务绕开：

- 小程序现状是微信登录/授权并可进行手机号核验；APP 客户入口是手机号 + 短信验证码。小程序业务并入 APP 后，客户只在 APP 登录一次。
- `IDN-01` 统一定义 APP customer session 到历史页面/短期兼容 adapter 的 migration session bridge：短期、一次性、opaque、限定 audience/route/origin、服务端原子兑换。bridge 不是独立登录、长期 token 或通用业务授权。
- 旧小程序后端不独立登录、不重新询问密码/验证码、不签发长期 token、不承载正式新业务；旧 token 仅服务端兑换并立即失效。APP logout 撤销派生 bridge。
- Wish API/application/DDD 统一解析 principal、tenant/site、subject、relationship、purpose、consent 和 field scope；客户端自报范围不是授权事实。重放、过期、越权、站点不匹配和桥接失败必须 fail closed、审计并回 APP 原生页/明确错误。
- 每个纵向模块任务必须串起 APP 入口、APP BFF、Wish API/DDD、schema/repository/UoW/事务、Outbox/事件、read model/audit、管理工作域、测试和回退；管理端只能通过 Wish Admin BFF 进入同一 Wish 写主。
- 管理员登录、认证、session、token 和凭据不在本轮；不得新增或调整 AUTH 任务。所有任务状态保持 `planned`，无任务级 owner、commit、evidence、verified_at 不得标记完成。

以上是目标设计/未实现约束；DAG 任务不是生产实现证据。

## 正式 APP 迁移业务泳道与兼容边界

小程序业务并入 APP 后，已经迁入 APP 的客户能力就是正式 APP 业务，不是“兼容页”或临时页面。正式迁移业务进入独立的 `formal-app-migration` 泳道：客户 APP 页面/状态 -> feature/repository -> APP BFF -> Wish API/application service -> DDD domain -> repository/UoW/事务 -> Wish 数据层/Outbox/Event -> read model/audit；对应管理工作域通过 Wish Admin BFF 进入同一 Wish 写主。Commerce 事实仍由 Commerce/MER 唯一写入，Wish 只接收受控只读引用。

任务图中的正式迁移泳道覆盖客户 APP 的健康服务、预约、履约、SCRM、服务账，以及后续并入 APP 的商城、订单/支付/售后、会员/营销/钱包、内容/发现和用户服务任务（对应 `HLT-*`、`COM-*`、`ORD-*`、`MEM-*`、`CNT-*`、`USR-*`、`MER-*`、`HWI-*` 等现有任务族）。每个纵向模块必须同时具备 APP 入口、APP BFF、Wish API/application service、DDD/schema/repository/UoW/事务、Outbox/事件、read model/audit、管理工作域、自动化测试和回退；任何页面迁移不得以历史后端或兼容 adapter 代替正式业务链。

`legacy-compatibility-fallback` 是独立的受控回退泳道，仅允许 `GOV-03` 路由登记、`FND-05` 平台适配、`FND-08` 历史小程序 adapter 及其安全验收使用。历史页面、旧小程序后端和原小程序管理端配置/兼容运营端只能作为迁移来源、短期 adapter 或受控回退，不是正式业务后端、登录入口或写主；不得在该泳道新增业务能力、独立登录、长期 token 或新业务 API。正式 APP 业务故障时只能回 APP 原生安全页或审核过的历史外链，不得把正式写主切回 legacy。

`IDN-01` 是共享的 `customer-session-bridge` 设计前置，不是正式业务泳道的替代品；`APPBFF-01` 是正式 APP 主链的唯一渠道适配任务；`TST-05` 与 `SEC-04` 是共享安全门禁。桥接与安全任务必须显式依赖并验证正式主链边界，但不改变纵向模块的 APP、BFF、Wish、数据、事件、管理和回退闭环。

## 架构拆解原则

产品架构同时使用四个维度：

正式 APP 迁移业务是独立的业务泳道：小程序中决定迁入 APP 的能力，迁入后按正式 APP 功能建设和验收；历史小程序相关对象只属于迁移来源/短期兼容回退泳道。两条泳道不得混淆，兼容 adapter 不得成为正式业务后端或写主。正式主链固定为 `APP -> APP BFF -> Wish API/application service -> DDD -> Wish 数据层`，随后进入 Outbox/Event、read model/audit；管理端通过 Wish Admin BFF 调用同一 Wish 主链。

1. **领域**：客户档案与授权、健康记录、服务目录与预约、履约/SOP/服务记录、SCRM/回访/触达、健康服务账分别定义边界、聚合和唯一写主；Commerce/MER 独立负责商城事实。
2. **分层**：客户 APP 页面/状态 → feature/repository → DFP Wish APP BFF；管理端工作台页面 → DFP Wish Admin BFF；两条渠道均进入同一 Wish API/application service → DDD domain → repository/UoW/事务 → Wish DB/Outbox/Event → read model/audit。BFF 是 DFP Wish 内的渠道适配层，不是独立业务后端。
3. **纵向闭环**：每个独立模块必须把 APP 手机端入口、管理端工作域、对应 BFF、Wish API/DDD、schema/repository/事务、事件/通知、读模型/审计、测试和回退串成一条可独立验收的链。
4. **横向集成**：客户 APP 会话身份源和一次性迁移桥接由 `IDN-01` 作为共享基础契约先行定义，这不是跨域业务集成。只有纵向模块闭环后，才安排身份授权联调、tenant/site、客户关系、消息、Commerce 引用、预约—履约—服务账和发布验收等跨域集成。

客户小程序业务并入 APP 手机端。小程序/MAPP 只作为历史迁移来源或短期兼容 adapter；可以保留历史路由、深链、外链的登记与安全回退，不得把它描述成正式业务后端，也不得在其中新增业务能力。新健康/SCRM/预约/履约/服务账业务统一经过 Wish APP BFF/Admin BFF、Wish API/application service 与 DDD 数据层。管理端只是同一套 Wish 后台的运营工作台。Commerce/MER 继续独立维护商城事实，Wish 只通过受控只读引用与之协作。

禁止把任务按“手机端一批、管理端一批、后台一批”拆成无法独立验收的横向孤岛。一个模块可以包含多个 DAG 节点，但节点必须通过依赖把纵向链串起来；跨模块任务只能依赖相关模块闭环完成。

## 纵向闭环与横向集成门禁

每个正式 APP 迁移模块都必须形成可独立验收的纵向闭环：APP 页面/状态、feature/repository、`APPBFF-01`、Wish API/application service、DDD 聚合与授权、schema/repository/UoW/事务、Outbox/事件、read model/audit、对应 Admin BFF/管理工作域、测试和回退缺一不可。`IDN-01` 提供客户会话桥接契约，但不替代任何模块的业务入口或数据闭环。

只有参与模块的纵向闭环全部具备后，才允许安排横向集成：身份授权联调、tenant/site 与客户关系、消息/通知、Commerce 受控只读引用、预约—履约—服务账、发布和恢复验收。`TST-05`、`SEC-04` 必须覆盖拒绝审计与 fail-closed 回退；横向集成任务不得反向成为正式业务写主。

## 客户统一登录与迁移会话桥接

客户只在 APP 登录一次。`IDN-01` 定义 APP session 到历史页面/短期兼容 adapter 的身份续接契约；进入兼容入口时由 Wish 服务端验证 APP session 并签发短时、单次兑换、绑定 allowlist route/origin、audience、nonce、subject、tenant/site、relationship、purpose 和 consent 的 opaque migration bridge。Bridge 仅续接迁移期身份，不是独立登录或长期 token。

Wish API/application/DDD 是唯一 principal 解析与授权上下文来源，统一核验 principal、tenant/site、subject、relationship、purpose、consent 和有效期；不得信任客户端自报字段。APP BFF 只适配 bridge 并调用 Wish application service。旧小程序后端不得独立登录、签发长期 token 或承载正式业务 API；新健康/SCRM/预约/履约/服务账请求都留在 Wish 链路。APP 退出时撤销尚未兑换的 bridge；退出、撤销、过期、重放、越权和 bridge 故障均 fail closed、记录最小化审计并安全回到 APP 原生页或 APP 登录入口。

`IDN-01` 是客户侧共享设计前置，不替代任何模块的 APP 页面、BFF、API/DDD、数据、事件、测试和回退闭环。受影响实现任务及 `TST-05` 必须显式依赖该契约；管理员认证仍完全排除，不新增或调整 `AUTH` 任务。

## 纵向模块任务映射

| 模块 | Wish API/DDD 与数据 | APP/BFF（共用 `IDN-01` 客户会话上下文） | 管理工作台 | 后置横向集成 |
| --- | --- | --- | --- | --- |
| 客户档案与授权 | `API-04`、`SCR-01`、`SCR-02`、`DB-05` | `APPBFF-01`、`HLT-06`、资料/授权入口 | `WADM-11` | `SEC-*`、`REL-*` |
| 健康服务与预约 | `API-05`、`API-06`、`DB-04`、`OPS-01/02/04/05/07` | `APPBFF-01`、`HLT-01`、`HLT-03`、`HLT-04` | `WADM-04`、`WADM-12` | `HLT-07`、通知/发布验收 |
| 履约与服务记录 | `API-08`、`SCR-03`、`DB-05`、`API-09` | `APPBFF-01`、疗愈师任务/服务记录入口 | `WADM-13` | `REL-*`、审计验收 |
| SCRM 与客户跟进 | `API-08`、`API-09`、`SCR-01..04`、`SCR-07/08` | `APPBFF-01`、`HLT-07` | `WADM-05`、`WADM-14` | 消息、通知、回访回归 |
| 健康服务账 | `API-07`、`SCR-05/06`、`DB-05` | `APPBFF-01`、`HLT-05` 服务卡/权益入口 | `WADM-15` | Commerce 只读引用、对账、发布验收 |
| 权限与审计 | `API-03`、`API-10`、`SEC-*` | 客户端只消费授权结果 | `WADM-16` | 全链路拒绝审计、恢复验收 |

`APPBFF-01` 是 APP 渠道适配任务，具体拥有 `exts/wish_app/api/` 路由、共享 BFF contract 和 Wish application-service gateway；它不拥有 Wish 领域事实、schema 或 Admin BFF。客户模块共用 `IDN-01` 定义的会话上下文，不各自建立登录流程。Admin BFF 和运营工作域由 `WADM-*` 在同一 DFP Wish 服务内实现。映射是架构规划，不构成实现证据。若某模块的客户端、BFF、DDD、数据、事件或测试节点缺失，应新增或调整 `planned` 任务，不能用页面壳、合并提交或单个 BFF 测试替代闭环。

横向集成必须在参与模块的 APP 与管理工作域纵向闭环后发生：`HLT-07` 依赖 `WADM-05`、`WADM-14`；Commerce 服务发现 `HWI-02` 依赖 `HLT-04`、`WADM-12`；商城权益只读交接 `HWI-03` 依赖 `HLT-05`、`WADM-15`；活动归因 `HWI-04` 依赖 `HLT-07`、`WADM-14`。`REL-05` 等发布联调还必须等待 `HLT-05` 和六个管理工作域。

## 任务字段与状态

每个任务必须有唯一 `id`、目标、范围、`deps`、`delivery_wave`、`target_paths_or_modules`、`file_claims`、`targeted_tests` 和 `rollback_or_fallback`。涉及迁移边界的任务还必须声明 `migration_lane`：正式 APP 业务使用 `formal-app-migration`，历史来源/短期兼容使用 `legacy-compatibility-fallback`，共享身份与安全验收使用 `cross-cutting-security-gate`。`APPBFF-01` 及 `HLT-*`、`COM-*`、`ORD-*`、`MEM-*`、`CNT-*`、`USR-*`、`MER-*`、`HWI-*` 正式迁移业务任务标记为 `formal-app-migration`；`GOV-03`、`FND-05`、`FND-08` 标记为 `legacy-compatibility-fallback`；共享身份契约/实现与安全门禁（包括 `GOV-02`、`GOV-05`、`FND-01`、`API-02`、`API-03`、`IDN-01`、`SEC-*`、`TST-05`、`TST-06`）标记为 `cross-cutting-security-gate`。共享 API 契约、schema、导航和事件 envelope 必须指定唯一写入任务。`deps` 是 DAG 唯一依赖源；如保留 `data.depends_on` 展示字段，必须与 `deps` 完全一致，不得用 `ROOT` 等未知哨兵代替空依赖。

所有新增设计任务默认 `planned`。没有任务级 owner、领取记录、commit、自动化测试命令与退出码、制品路径和验收结果，不得标记 `in-progress` 或 `done`。`merge-status` 只能证明合并发生，不能证明业务任务完成。

依赖门禁必须满足：任务 ID 唯一、依赖全部存在、依赖无环、横向集成晚于参与模块纵向闭环。`__start__` 和 `__end__` 是控制节点，不计入业务任务数。

## 范围保护

- 管理员登录、认证、session、token、凭据和登录配置不属于本阶段，不新增或调整 AUTH 任务。
- 管理端订单、消息/广播、协议/同意、合规、App 发布、运营成员和用户查询是既有兼容能力，保留并做回归保护。
- 健康预约的目录、容量、房间/设备/服务角色可用性、资源冲突和候补属于主线履约约束；不因此建设员工排班、班次、请假、调班或员工日历。
- 员工排班管理、物料/库存/仓库、绩效/提成、日常运营 KPI、收银工作台和商户经营管理排除在本期任务图之外。
- 手机端总体方案是架构上位基线；客户小程序业务合入 APP。小程序/MAPP 仅作为历史迁移来源、短期兼容 adapter 和外链配置边界，不作为本阶段目标设计层或正式业务后端。

## 验收规则

设计阶段只做文档、任务和依赖校验，不实施业务代码。未来实施必须按纵向模块逐项领取和验收，使用隔离环境、合成数据和自动化测试；真实健康数据、支付、消息、生产发布和外部系统写入必须有独立授权与门禁。任务状态、机器结果和报告写回 `backend/tasks.json`，不以 Markdown 叙述替代机器证据。
