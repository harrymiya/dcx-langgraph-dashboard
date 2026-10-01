# LangGraph DAG 架构与任务拆解约束

本项目只负责任务图、依赖、状态和机器验收证据，不承载手机端、管理端或 Wish 业务实现。当前任务图是总体方案的正确子集；任务设计不等于功能已实现。

## 技术架构硬约束：区分 MAPP 迁移链与 Wish 正式业务链

所有任务、路径、依赖、测试和回退设计都必须遵守以下架构，不得通过新增任务绕开：

- 小程序现状是微信登录/授权并可按配置进行手机号核验或短信验证；APP 客户入口是手机号 + 短信验证码。指定小程序业务迁入 APP 只迁移前端页面/入口，客户只在 APP 登录一次。
- `formal-app-migration` 独占迁入 APP 的小程序前端页面/入口，正式链路固定为 `APP 中的小程序迁移业务 → MAPP server → 原有业务数据/服务`。MAPP server 保持原小程序后端和服务边界；未迁移小程序原客户端独立沿用 `小程序原客户端 → MAPP server`。
- APP 首页三个第三方小程序按钮只拉起其他第三方小程序，是独立外部入口，与本次迁移无关；不得放入迁移泳道或迁移任务，也不得把它们连接到本图的 MAPP server。
- `IDN-01` 定义客户 APP session 与历史页面/短期兼容 adapter 的身份续接边界：bridge 短期、一次性、opaque、限定 audience/route/origin、服务端原子兑换。正式迁入页面直接按原服务契约调用 MAPP server，不经过 Wish bridge；bridge 不是独立登录、长期 token 或通用业务授权。
- MAPP server 不独立登录、不重新询问密码/验证码、不签发长期 token；既有 MAPP 业务后端继续承载正式迁入前端所调用的原有业务和未迁移小程序业务。旧 token 仅服务端兑换并立即失效。APP logout 撤销派生 bridge。
- 只有明确属于 Wish 的正式业务由 Wish API/application/DDD 解析 principal、tenant/site、subject、relationship、purpose、consent 和 field scope；客户端自报范围不是授权事实。Wish 路径中的重放、过期、撤销、越权、站点不匹配和桥接失败必须 fail closed、留下脱敏最小审计，并安全回 APP 原生页/明确错误。
- 每个明确属于 Wish 的纵向模块任务必须串起 APP 入口、Wish APP BFF、Wish API/DDD、schema/repository/UoW/事务、Outbox/事件、read model/audit、管理工作域、测试和回退；管理端只能通过 Wish Admin BFF 进入同一 Wish 写主。小程序前端迁移任务不接入 Wish BFF/DDD，除非该任务本身明确是 Wish 业务。
- 管理员登录、认证、session、token 和凭据不在本轮；不得新增或调整 AUTH 任务。所有任务状态保持 `planned`，无任务级 owner、commit、evidence、verified_at 不得标记完成。

以上是目标设计/未实现约束；DAG 任务不是生产实现证据。

## 正式 APP 迁移业务泳道与兼容边界

小程序业务并入 APP 后，已迁入 APP 的前端页面/入口属于正式 APP 业务，不是兼容页或临时页面。正式迁移业务进入独占 `formal-app-migration` 泳道：`APP 页面/状态 → feature/repository → MAPP server → 原有业务数据/服务`；迁移只覆盖前端，既有 MAPP server 保持原业务后端边界。未迁移小程序原客户端单独沿用 `小程序原客户端 → MAPP server`，不与 APP 迁移泳道合并。明确属于 Wish 的其他业务另走 `wish-formal-business` 泳道：`APP → Wish APP BFF → Wish API/application service → DDD → Wish 写主/Outbox/Event/read model/audit`；管理端通过 Wish Admin BFF 进入同一 Wish 写主。

任务图中的 `formal-app-migration` 泳道只覆盖确属小程序前端页面/入口迁移的任务（当前为 `COM-*`、`ORD-*`、`MEM-*`、`CNT-*`、`USR-*`、`MER-*`）。每项任务必须声明 `backend_target: MAPP server`，并不得依赖 Wish APP BFF/DDD。`APPBFF-01`、`HLT-*` 和明确属于 Wish 的 `HWI-*` 进入独立 `wish-formal-business` 泳道，按各自 Wish 纵向闭环执行。APP 首页三个第三方小程序按钮不是迁移任务；入口交互盘点可由 UX 任务记录其外部入口属性。

`legacy-compatibility-fallback` 是独立的受控回退泳道，仅允许历史路由登记、旧 route adapter 和安全回退任务使用。它不改变正式迁移页面调用 MAPP server 原有服务的边界，也不建立第二套登录或业务写主。正式 APP 页面故障时按对应业务的既有服务回退策略处理，不得新增独立登录或长期 token。

`IDN-01` 是共享客户会话与历史 route bridge 的设计前置；正式迁移页面仍直接访问 MAPP server 原服务契约。`APPBFF-01` 只服务明确属于 Wish 的正式业务，`TST-05` 与 `SEC-04` 是共享安全门禁。正式迁移前端任务可依赖 `IDN-01` 获取 APP session 边界，但不得依赖 `APPBFF-01`、Wish API 或 Wish DDD；这些依赖只适用于任务本身明确属于 Wish 的业务。`FND-01`、`API-02`、`APPBFF-01`、`FND-08` 和安全验收 `TST-05`、`SEC-04` 按各自职责依赖 `IDN-01`；`TST-05`、`SEC-04` 对 Wish 业务链的安全验收直接依赖 `APPBFF-01`。`IDN-01` 是设计前置，不反向依赖实现任务。

## 架构拆解原则

产品架构同时使用四个维度：

小程序前端迁移与 Wish 正式业务是两条独立泳道。迁移链固定为 `APP 中的小程序迁移业务 -> MAPP server -> 原有业务数据/服务`；明确属于 Wish 的其他正式业务才走 `APP -> Wish APP BFF -> Wish API/application service -> DDD -> Wish 数据层`。未迁移小程序原客户端继续独立调用 MAPP server。历史路由/adapter 只在相关来源或回退节点旁说明。APP 首页三个第三方小程序按钮是外部入口，不属于迁移泳道。

1. **领域**：客户档案与授权、健康记录、服务目录与预约、履约/SOP/服务记录、SCRM/回访/触达、健康服务账分别定义边界、聚合和唯一写主；Commerce/MER 独立负责商城事实。
2. **分层**：小程序迁移泳道的 APP 页面/状态 → feature/repository → MAPP server → 原有业务数据/服务；明确属于 Wish 的 APP 页面/状态 → DFP Wish APP BFF，管理端工作台页面 → DFP Wish Admin BFF；Wish 两条渠道均进入同一 Wish API/application service → DDD domain → repository/UoW/事务 → Wish DB/Outbox/Event → read model/audit。BFF 是 DFP Wish 内的渠道适配层，不是独立业务后端。
3. **纵向闭环**：每个明确属于 Wish 的独立模块必须把 APP 手机端入口、管理端工作域、对应 Wish BFF、Wish API/DDD、schema/repository/事务、事件/通知、读模型/审计、测试和回退串成一条可独立验收的链；小程序迁移模块只交付 APP 前端页面/入口并按原契约调用 MAPP server。
4. **横向集成**：客户 APP 会话身份源和一次性迁移桥接由 `IDN-01` 作为共享基础契约先行定义，这不是跨域业务集成。只有纵向模块闭环后，才安排身份授权联调、tenant/site、客户关系、消息、Commerce 引用、预约—履约—服务账和发布验收等跨域集成。

迁入 APP 的小程序能力只迁移前端页面/入口，继续调用 MAPP server 和原有业务数据/服务；MAPP server 不是仅供兼容的 adapter。未迁移的小程序原客户端使用独立路径调用 MAPP server。明确属于 Wish 的健康/SCRM/预约/履约/服务账业务统一经过 Wish APP BFF/Admin BFF、Wish API/application service 与 DDD 数据层。管理端只是同一套 Wish 后台的运营工作台。Commerce/MER 继续独立维护商城事实，Wish 只通过受控只读引用与之协作。

禁止把任务按“手机端一批、管理端一批、后台一批”拆成无法独立验收的横向孤岛。一个模块可以包含多个 DAG 节点，但节点必须通过依赖把纵向链串起来；跨模块任务只能依赖相关模块闭环完成。

## 纵向闭环与横向集成门禁

每个小程序前端迁移任务交付 APP 页面/状态和 feature/repository，并按 `MAPP server` 原服务契约读写原有业务；不得自动附加 Wish APP BFF/DDD。每个明确属于 Wish 的正式业务模块才形成 Wish 纵向闭环：APP 页面/状态、`APPBFF-01`、Wish API/application service、DDD 聚合与授权、schema/repository/UoW/事务、Outbox/事件、read model/audit、对应 Admin BFF/管理工作域、测试和回退。`IDN-01` 提供客户 session 与历史 route bridge 契约，不替代任何模块的业务入口或数据闭环。

只有参与模块的纵向闭环全部具备后，才允许安排横向集成：身份授权联调、tenant/site 与客户关系、消息/通知、Commerce 受控只读引用、预约—履约—服务账、发布和恢复验收。`TST-05`、`SEC-04` 必须覆盖拒绝审计与 fail-closed 回退；横向集成任务不得反向成为正式业务写主。

## 客户统一登录与迁移会话桥接

客户只在 APP 登录一次。`IDN-01` 定义 APP session 到历史页面/短期兼容 adapter 的身份续接契约；进入兼容入口时由 Wish 服务端验证 APP session 并签发短时、单次兑换、绑定 allowlist route/origin、audience、nonce、subject、tenant/site、relationship、purpose 和 consent 的 opaque migration bridge。Bridge 仅续接迁移期身份，不是独立登录或长期 token。

Wish API/application/DDD 只为明确属于 Wish 的业务解析 principal 与授权上下文，统一核验 principal、tenant/site、subject、relationship、purpose、consent 和有效期；不得信任客户端自报字段。Wish APP BFF 只适配 Wish 业务路由/DTO 并调用 Wish application service。MAPP server 按原服务契约继续承载正式迁移页面调用的既有业务和未迁移小程序业务；它不独立登录、不签发长期 token，也不被替换为 Wish 新业务 API。明确属于 Wish 的健康/SCRM/预约/履约/服务账请求仍留在 Wish 链路。APP 退出时撤销尚未兑换的 bridge；退出、撤销、过期、重放、越权和 bridge 故障均 fail closed、记录最小化审计并安全回到 APP 原生页或 APP 登录入口。

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

每个任务必须有唯一 `id`、目标、范围、`deps`、`delivery_wave`、`target_paths_or_modules`、`file_claims`、`targeted_tests` 和 `rollback_or_fallback`。小程序前端迁移任务必须声明 `migration_lane: formal-app-migration` 与 `backend_target: MAPP server`；明确属于 Wish 的业务标记 `wish-formal-business`，历史来源/短期兼容使用 `legacy-compatibility-fallback`，共享身份与安全验收使用 `cross-cutting-security-gate`。`COM-*`、`ORD-*`、`MEM-*`、`CNT-*`、`USR-*`、`MER-*` 属于 `formal-app-migration`；`APPBFF-01`、`HLT-*`、明确属于 Wish 的 `HWI-*` 属于 `wish-formal-business`；`GOV-03`、`FND-05`、`FND-08` 属于 `legacy-compatibility-fallback`；共享身份契约/实现与安全门禁（包括 `GOV-02`、`GOV-05`、`FND-01`、`API-02`、`API-03`、`IDN-01`、`SEC-*`、`TST-05`、`TST-06`）属于 `cross-cutting-security-gate`。`formal-app-migration` 任务不得依赖 Wish APP BFF/DDD，除非任务本身明确属于 Wish 业务。APP 首页三个第三方小程序按钮只作为外部入口说明，不新增到迁移任务。共享 API 契约、schema、导航和事件 envelope 必须指定唯一写入任务。`deps` 是 DAG 唯一依赖源；如保留 `data.depends_on` 展示字段，必须与 `deps` 完全一致，不得用 `ROOT` 等未知哨兵代替空依赖。

所有新增设计任务默认 `planned`。没有任务级 owner、领取记录、commit、自动化测试命令与退出码、制品路径和验收结果，不得标记 `in-progress` 或 `done`。`merge-status` 只能证明合并发生，不能证明业务任务完成。

依赖门禁必须满足：任务 ID 唯一、依赖全部存在、依赖无环、横向集成晚于参与模块纵向闭环。`__start__` 和 `__end__` 是控制节点，不计入业务任务数。

## 范围保护

- 管理员登录、认证、session、token、凭据和登录配置不属于本阶段，不新增或调整 AUTH 任务。
- 管理端订单、消息/广播、协议/同意、合规、App 发布、运营成员和用户查询是既有兼容能力，保留并做回归保护。
- 健康预约的目录、容量、房间/设备/服务角色可用性、资源冲突和候补属于主线履约约束；不因此建设员工排班、班次、请假、调班或员工日历。
- 员工排班管理、物料/库存/仓库、绩效/提成、日常运营 KPI、收银工作台和商户经营管理排除在本期任务图之外。
- 手机端总体方案是架构上位基线；指定小程序迁入 APP 只迁移前端页面/入口，正式后端目标为 MAPP server。未迁移小程序原客户端独立调用 MAPP server；APP 首页三个第三方小程序按钮是外部入口而非迁移任务。明确属于 Wish 的业务才接入 Wish APP BFF/API/DDD。

## 验收规则

设计阶段只做文档、任务和依赖校验，不实施业务代码。未来实施必须按纵向模块逐项领取和验收，使用隔离环境、合成数据和自动化测试；真实健康数据、支付、消息、生产发布和外部系统写入必须有独立授权与门禁。任务状态、机器结果和报告写回 `backend/tasks.json`，不以 Markdown 叙述替代机器证据。
