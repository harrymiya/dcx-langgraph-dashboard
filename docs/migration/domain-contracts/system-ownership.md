# GOV-02：Commerce / Wish 责任契约 v1

本契约冻结设计边界，任务状态保持 `planned`；自动化验收只证明文档、DAG 和合成场景一致，不证明手机端、MAPP、Wish、认证或账务已实现。GOV-02 单写本目录。版本变更须重新运行本目录专项检查及总体覆盖检查；未签署版本可撤回并暂停依赖该版本的开发，不修改现有登录、network client 或账本。

## 来源与优先级

以当前 worktree 的 [AGENTS.md](../../../AGENTS.md)、[backend/tasks.json](../../../backend/tasks.json) 的 GOV-02、GOV-01 范围登记为约束，承接上游：

| 来源（相对 `/home/agent/code/jiankang_app_uniapp`） | 对应章节 |
| --- | --- |
| `docs/ruixin-health-app-scrm-complete-design.md` | §1.1 客户登录、§6 权威域、§7 双站与双账隔离、§8 迁移 |
| `docs/architecture/health-scrm-cross-project-architecture.md` | §2 系统与身份边界、§3 纵向模块、§6 Wish Admin 生产组织 SSO、§7 分层与写主 |
| `docs/migration/mapp-page-migration-inventory.md` | 来源基线及 MP001–MP163 逐项映射 |

`contract-policy.json` 是本目录验收用的机器契约，引用 GOV-02 的全部 `source_item_ids`，不另建需求 registry、任务 allowlist、API schema 或路由中心。来源 SHA-256 与执行命令保存在 `verification-results.json`。GOV-01 仍为 `planned`；其已有来源台账可用，但独立 MAPP checkout 的 Git 对象未经本任务验证，不能把声明的 release SHA 当作代码验证结果。

## 调用边界

| 泳道/入口 | 固定调用链 | 禁止行为 |
| --- | --- | --- |
| `formal-app-migration` | APP 页面/状态 → feature/repository → MAPP server → 原有业务数据/服务 | 仅迁移前端；不依赖 Wish APP BFF/API/DDD，不强制经过 bridge |
| 迁移期间的 MAPP route 回退 | 切流前：原小程序客户端 → MAPP server → 原有业务数据/服务 | 只作逐页验收前回退；163 条路由均有 DAG 页面任务 |
| `wish-formal-business` | APP → Wish APP BFF → Wish API/application service → DDD → repository/UoW/事务 → Wish DB/Outbox/Event → read model/audit | 不接 MAPP server；APP/BFF 不直连 DB、ORM 或写事件总线 |
| Wish 管理工作域 | 组织 SSO → union_id/operator 权限映射 → Wish Admin BFF → 同一 Wish API/application service/DDD 与写主 | 不复制领域状态机、不建立第二套服务账；生产禁用 seed/mock 与自助提权 |
| `legacy-compatibility-fallback` | APP session → Wish 服务端一次性 bridge → allowlisted 历史 route/短期 adapter | bridge 只续接身份，不授权新业务，不成为正式迁移页入口 |
| 首页三个第三方小程序按钮 | APP 外部入口 → 对应第三方小程序 | 不创建迁移任务，不连接本图 MAPP server |

迁移认领必须读取 GOV-01 唯一 allowlist（40 项），并校验 163 条路由全部映射到有效任务和任务的 lane、`migration_scope: selected-page`、`migration_backend: MAPP server`、来源文件及 MP 页面 ID；与清单不匹配即拒绝认领。13 个 Wish 原生任务使用 `wish-native`、空 `migration_backend` 和 Wish 后端链。数量不是全量方案覆盖证明，覆盖仍由 GOV-01 registry 双向校验。

## 唯一事实写主与拒绝责任

| 事实/责任 | 唯一权威方 | 其他系统可做什么 / 拒绝方 |
| --- | --- | --- |
| APP 客户认证凭证、APP session | 经确认的客户身份源；APP 是唯一客户登录入口 | Wish 不保存密码/验证码；FND-01 的 APP session 边界拒绝第二次登录流程 |
| 租户、组织、员工主体、平台角色 | 平台/IAM 既有控制面 | Wish 只保存受验证引用与业务授权；Wish Admin production SSO 通过 Feishu OAuth/IAM 和当前 union_id → operator contract 服务端核验 active 状态、角色及 tenant/site scope |
| 客户主档、身份映射、关系、purpose consent、SCRM | Wish CRM/consent/SCRM | Wish application/DDD 拒绝未经验证映射、同号自动合并和未经授权的读取/写入 |
| 健康数据/报告 | 经业务和隐私 owner 确认的健康域，由 Wish 按授权引用/服务 | owner 未确认前不导入；Commerce、营销、普通日志不复制健康正文 |
| 健康目录、预约/资源锁、履约/SOP、服务记录 | Wish 服务域 | Wish application/DDD 拒绝越权；记录更正追加，不能用商城购买推导预约或参与事实 |
| 商品、价格、购物车、商城订单、会员资产、支付退款、商城账 | Commerce/MER，经既有 MAPP 服务契约访问 | Commerce/MER 服务端拒绝 Wish 代写、跨 audience、双写；Wish 仅消费获批最小引用 |
| 服务费用、服务卡、应收、退款审核、健康服务账 | Wish 健康服务账领域 | Wish application/DDD 拒绝 Commerce 代写、覆盖/删除分录、错误 tenant/site；资金结果仍以 provider 验证结果为准 |
| 消息意图、退订与业务通知状态 | Wish 消息域；渠道仅是投递回执方 | 渠道回执不改变预约/授权/账务事实；发送前重验目的与同意 |
| Outbox、Inbox、读模型、审计 | 源域同事务 Outbox；消费者 Inbox；只读投影与追加审计 | 事件消费者去重且固定原 tenant/site；投影不得回写事实，业务接口不得改删审计 |

Commerce 既有库存事实的归属不引入库存/仓库、商户经营、收银、绩效、员工排班等新任务。管理端既有订单、消息/广播、协议/同意、合规、App 发布、运营成员、用户查询保留回归边界。

Wish adapter 调用 application；application 使用 domain 和 repository/UoW ports；infrastructure 实现 ports。domain 不依赖 HTTP、UI、ORM 或外部 SDK。源域写主事实、历史/审计引用和 Outbox 同事务提交，消费者按事件 ID/版本去重；不能用跨库事务、共享表、读模型或渠道回调实现双写。

## 契约单写与交接

| 内容 | 唯一写入任务 / 交接边界 |
| --- | --- |
| 本责任矩阵及身份/账本边界 | GOV-02；本目录不提供可部署服务 |
| 客户 APP session 与历史 bridge 详细设计 | IDN-01；GOV-02 只冻结不变量，具体身份源、TTL、issuer、audience 字符串及兑换协议待其契约确认 |
| APP session、bridge 实现、历史 adapter | FND-01、API-02、FND-08 各自已声明路径；不在本任务实现 |
| Wish APP BFF contract/router/gateway | APPBFF-01 |
| Wish Admin BFF 基础契约 | WADM-01；具体工作域由 WADM-* 已声明路径拥有 |
| 版本化 Wish API / 共享事件 envelope | API-01 / DB-07（按 tasks.json 的 claims） |
| schema / repository / UoW | 对应 DB-* 唯一声明任务；GOV-02 不创建 schema |
| 中心导航注册 | FND-03；页面任务只提交 route fragment；本任务不注册任何路由 |
| tenant/site、关系、目的与字段授权 | GOV-05 规则；API-03 运行时授权；TST-05、SEC-04 共享安全验收 |

纵向 Wish 模块须串起 APP、APPBFF-01、Wish API/DDD、schema/repository/UoW、Outbox、read model/audit、对应管理工作域、测试与回退。跨域协作在参与模块闭环之后；例如 HWI-03 等待 HLT-05 与 WADM-15，不能用本契约或只读交接代替服务账闭环。`deps` 仍是唯一依赖源，本任务不修改任务、状态、AUTH、API、schema、中心路由或业务代码。
