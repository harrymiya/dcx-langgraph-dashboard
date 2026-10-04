# OpenCode loop、DAG 与原型专项诊断

首轮检查时间：2026-10-04 03:51（Asia/Shanghai）

> 当前基线说明：本文前半部分保留首轮审计时的 144 项 DAG、35 条 formal migration 中间快照。用户随后明确将迁移范围扩大到全部 163 条来源路由；末尾“按用户确认扩大到 163 条路由”及“运行态复核”为现行结论，已取代此前范围与统计。当前 DAG 为 149 项（98 项 MVP 必须、51 项 MVP 后续），不得再按 35 条白名单或 144 项总量执行。

## 结论

OpenCode 主会话和 loop 仍在运行，不是一个已停止的进程。最新现场读取显示主会话持续使用工具，已从 WADM-04 导航/目录继续到 WADM-16 权限审计前端；当前任务仍是 planned，说明活动代码在 task 级验收/写证据前不会改状态。服务器 health 正常，attach 与 server 仍在运行。此前观测 runCount 为 270，后续审计快照为 271；maxRuns、maxRuntimeMs、timeoutMs 均为 0，job enabled 且未暂停。

用户感知的“循环”由过去的错误恢复和低效编排共同造成：历史日志有 253 次 active-stale-recovery 和 5,156 次 session-busy 延迟；progress.md 反复写入无归属变化的 BLOCKED/ownership 记录；旧 DAG 混入 134 个不相关候选；普通实现反复执行完整方案覆盖与跨端发布门禁。stale recovery 已从默认 45 秒调为 20 分钟，loop 无轮数/运行时长限制；普通任务现按专项测试验收，跨端 E2E 留给集成/发布任务。运行进程当前有 CPU 和工具调用，故不能把长时间 busy 本身当成死循环；应看 task/path/test/commit 的有效变化。

## DAG 与项目注册

- 产品基线已从 143 项扩至 144 项：98 项 MVP必须、46 项 MVP后续；新增 WADM-17 管理端组织 SSO，图中无缺失依赖引用、无循环。
- default 执行轨初始有 277 项：其中 143 项来自产品方案，另外 134 项是 APP18/APP19、SHARED、Render Core、WellLog 等 dashboard/历史工程任务。134 项全标 MVP后续，且均没有来源文件、目标路径或 targeted_tests；它们不是健康 APP / Wish 交付范围。已将这 134 项完整隔离到 archived 项目 dashboard-maintenance-archive，原状态和证据保留。
- 任务选择原规则先按全图拓扑深度，再看 MVP 范围。污染任务里 BASE-02、ENV-01、UPGRADE-01 是无依赖候选，会排在有较长已完成前置链的健康客户端和管理端 MVP 任务之前。第一次快照的 15 个 ready 候选里只有 8 个属于 143 项产品基线。
- projects.json 原写 129 项、workspace=/home/musk/code/jiankang_app_uniapp；该路径在当前环境不存在。已把 default 纠正到 /home/agent/code，并将 134 个外来任务归档。加入 WADM-17 后，default 与源基线各有 144 项，项目描述和统计同步。
- 当前 runtime 快照 144 项：117 code-ready、25 planned、2 contract-ready；按依赖计算 9 项 ready。WADM-17 排在最高优先级且依赖 WADM-01/02/03、API-03、SEC-01/02 均为 code-ready，应该在正在处理的 WADM-16 切片结束后优先认领。其余 ready 包含 HLT-04、WADM-04、WADM-11、WADM-13..16 和 HLT-02。code-ready 是模块专项证据，不等于整个产品可发布。
- 35 个 formal-app-migration 页面任务在 runtime 被标 code-ready；34 项具备旧 evidence report 引用，MEM-08 缺 report 引用。该状态说明有实现/专项证据，不等于 35 项已通过目标平台和 MAPP 真服务的最终联调。现行方案选择 35/163 条路由迁入 APP，其余路由保持原小程序调用 MAPP server。

## loop 与记忆

- 运行 job musahdj0-a4d674：enabled=true、paused=false、runCount=270、无轮数/运行时长/任务超时限制、compactEveryRuns=5、activeRecoveryMs=1,200,000。
- Hermes watchdog 已有每 10 分钟执行一次的 no-agent cron，Server 和 attach 都健康；没有重复启动，也没有额外产品实现者。
- 当前 `askNever=true` 让循环遇到常规实现选择时自行判断并继续；`noOverlap=true` 保证一个实现会话串行推进，避免同一工作树并发写入。`safe=true` 仅针对删除数据、强制清理/推送、生产部署或生产迁移等破坏性操作，不限制正常代码编辑、构建或专项验证。
- loop 日志 1005 次历史 run 中存在 253 次 stale recovery。此前 45 秒 guard 会在正常的模型工具轮次结束前误恢复，造成重复读取/停滞描述。当前 20 分钟保护窗避免这一类短轮次误判。
- progress.md 当前约 123 KB，含大量重复 BLOCKED/ownership 记录。完整快照已原样保存到 `docs/reports/tasks/archive/progress-20261004-before-rollup.md`（SHA-256 与源文件相同）；在线 progress 暂不覆盖，等当前 OpenCode 代码切片到边界后再压成滚动摘要。
- watchdog 曾把完整 TUI ANSI repaint 用 tee 写入 attach.log，文件达到约 313 MB。本次恢复命令改为直接运行 attach，保留 OpenCode loop/server 诊断日志；已保存末尾 256 KB 作为短期排障尾档并清理在线 TUI 日志。

## 总体方案与原型

首轮检查时，三端职责相互匹配，没有发现需重画业务工作域的结构性冲突；当时缺少管理端登录原型，已补为工作台外的 SSO 补充页。扩围后的商户/员工工作台原型见下表：

| 入口 | 正式原型 | 流程范围 |
| --- | --- | --- |
| 客户 APP | customer-miniapp-prototype.html | 首页、健康、商城、我的；健康记录/授权/预约与 MAPP 商城路由 |
| 疗愈师 APP | staff-workbench-prototype.html | 今日任务、服务过程、回访跟进、授权范围；签到、SOP、记录、更正、暂停/升级/完成 |
| MAPP 商户/员工工作台 | merchant-staff-workbench-prototype.html | 商户员工登录、站点与角色权限、客户/服务目录、订单核销、预约与服务工作流 |
| 前台 PC Web | operations-admin-prototype.html | 客户档案、健康预约、服务记录、客户跟进、服务账、权限与审计六域 |

`admin-sso-login-prototype.html` 展示独立组织登录入口、服务端 operator/site 授权和拒绝语义，不调用真实 IdP；它是管理端角色的补充页面，不构成独立业务工作台。health-scrm-wireframe-prototype.html 是旧原型地址导航页。所有原型数据均为合成示例，不能作为实现证据。当前角色覆盖与任务统计为 149 项，路由清单覆盖 163 条来源路由。

## 发现的管理端交付缺口

- 旧总体方案和 cross-project architecture 把管理员登录标成明确范围外；dashboard AGENTS 与 validator 禁止新增 AUTH 任务。这会让“管理端可交付使用”的目标始终缺少正式登录依赖。
- Wish Admin 前端 `IS_MOCK_AUTH = true`，provider 硬编码 `on_seed_admin` 并自动登录；后端只允许显式启用的开发数据库登录，production 硬关闭。`/me` 和业务 API 虽验证 operator Principal，但生产用户没有可用入口。
- 找到 archived Feishu OAuth proposal，但它仍引用过时的 `employee_id/open_id`。当前 `_auth.py`、`feishu_contact.py` 与 JWT contract 采用 `union_id`；新方案沿用现行身份键，不移植旧提案的身份假设，也不允许 SSO 自助授予角色。
- 已将上位架构、总体方案、仓库实施指令和 DAG 改为生产 SSO 交付目标；新增 WADM-17（I0、MVP必须），其接受条件包含 OAuth callback、operator 权威解析、session/logout/expiry/revocation、生产 mock/seed 关闭、部署配置与隔离验收。REL-05 现依赖 WADM-17。
- 计划覆盖 validator 已执行：6 项 PASS（144/98/46、依赖无环、58 项双向覆盖、35+13 泳道、迁移清单 35 项映射）。

## 本次调整

- 根 AGENTS.md 与 loop-prompt.md 统一成 OpenCode 单实现者、高周转循环：active baseline 过滤、MVP/交付波次优先、接续现有 WIP、任务级测试、阻塞局部化、滚动 progress。当前任务基线为 144/98/46，保留 35 个正式 MAPP 页面 allowlist（用户对是否扩大迁移面尚未回复，继续遵循当前上位方案）。
- dag-claim-next、dag-validate、dag-record 已在 .agents、.opencode、APP 与 dashboard 镜像更新。普通任务不再运行完整 coverage validator 或跨端发布验收；任务图/registry 变化和集成发布仍有相应检查。
- 角色/原型覆盖文档不再把历史 129 项写成当前快照；补充管理端 SSO 原型及进入规则。
- Watchdog 不再无限记录 ANSI TUI 输出，当前 OpenCode 和 watchdog 均保持在线。

## 后续编排修复

1. DAG 与 projects.json 已过滤归档并扩展到 144 项；既有任务状态/证据保留，仅新增 WADM-17 planned 及其来源映射。
2. OpenCode 此刻仍在做 WADM-16 相关代码。不要覆盖活跃工作树或并发清理其任务记录；待任务边界时将 progress.md 原样归档并压缩为 WIP、最近证据、真实 blocker 和 DAG next task。
3. 继续按 DAG 交付，不在 MVP 或“所有任务变色”时提前完成；目标平台构建、隔离环境跨端 E2E、部署与回滚证据均通过后才允许 DONE。

## Addendum：按用户确认扩大到 163 条路由（2026-10-04）

用户确认小程序迁移范围扩大至全部 163 条来源路由。此前“35 条 formal migration”的白名单和员工/商户路由永久排除规则已失效，现行交付范围如下：

- 40 个 `formal-app-migration` 任务承接 159 条 MAPP 客户与员工/商户页面，继续调用原 MAPP server 服务契约；员工/商户页面使用独立 manager session，并在服务端核验 tenant/site/role/permission。
- 另外 4 条 shell/Wish 路由由现有 FND/HWI 任务承接。DAG 清单里的 163 个 route id 均须映射到存在的任务，且每个任务的 `route_inventory_page_ids` 必须与来源表精确一致。
- 补上此前没有真实任务承接的 24 条员工/商户页面，新增 5 个后续波次任务：MER-02（MP040、MP046）、MER-03（MP141、MP151）、MER-04（MP142–MP150、MP159）、MER-05（MP152–MP158）、MER-06（MP160–MP162）。原来的 `MER-03（MVP后续）` 注记已改成真实 DAG 任务 ID。
- 总图变为 149 项（98 项 MVP必须、51 项 MVP后续）。default runtime 已增补 5 个 planned 节点；已有任务的状态、证据、lease 与活跃 WIP 保留，未覆盖 OpenCode 正在编辑的业务代码或 progress 文件。
- 更新了迁移清单、总体方案和 HTML 蓝图、两张架构图、商户/员工 DAG 域文档、任务索引、角色/原型覆盖说明、OpenCode AGENTS/prompt 与 DAG skill mirrors。新增 `merchant-staff-workbench-prototype.html`，任务对到原型 screen keys。
- 维持边界：APP MAPP 页面调用 MAPP server；Wish 健康/SCRM 与管理员仍走各自 Wish BFF/API/DDD；商户 manager session 与客户、疗愈师和 Wish Admin 会话隔离。三个首页第三方小程序入口不计入这 163 条路由。WADM-17 生产 SSO 要求继续有效。
- 后续逐项复核发现旧“排除”条文仍会把 MP141–MP162 商户/员工来源页挡在实施之外；现已统一改为“排除 Wish 新业务域，但 163 路由中已登记的 MAPP 页面必须迁移并调用 MAPP/Commerce 原服务”。尤其 MP151 销售统计、MP152–MP158 核销/余额、MP160–MP162 商品/库存继续按 MER-03..06 交付，不扩建 Wish 商户后台、账本或库存域。
- GOV-01 的 `MIG-03-STAFF-MERCHANT-ROUTES` 已从 `current-state-retained` 改为 `planned`，双向链接 MER-02..06；OUT-02/OUT-03 只表示不新建 Wish 原生库存、绩效、BI、收银及商户管理域，并关联相应 MER 页面迁移任务。同步更新 default runtime 的 registry 与 MER 源路径字段，已有状态、证据和 lease 保持不变。
- 根 AGENTS 和 loop prompt 已加入 MAPP 商户/员工原型，并取消“每回合最多一个业务任务”的软限制；OpenCode 可在同一关键纵向切片中连续完成任意数量的已就绪且无文件冲突任务，逐任务记录验收证据。疗愈师 `features/staff` 与 MAPP 员工 `features/mapp-staff` 路径已在 MER 任务定义中分开。

计划覆盖校验已重跑并通过：149 个 planned 源任务、98/51 统计、依赖无环、60 个需求登记双向完整、40/13 泳道边界通过、163 页完整映射（159 formal MAPP pages、45 个 route-linked DAG tasks）。此项是计划/路由映射校验，不代表 163 页功能已实现；OpenCode 应按新 DAG 继续实施，不能把新增登记当作完成证据。

## 运行态复核

截至 2026-10-04 04:38（Asia/Shanghai），OpenCode serve/attach、LangGraph 与 dashboard 服务均保持运行。default loop `enabled=true`、`paused=false`、`maxRuns=0`、`maxRuntimeMs=0`、`timeoutMs=0`、`runCount=273`；没有轮数、运行时长或任务超时上限。最近一次完整 loop turn 约在 04:33；主会话之后持续刷新，04:36–04:38 仍有 read/edit/grep 工具调用完成或执行中，当前 API 显示新的 `edit` pending。`noOverlap` 继续记 `session-busy` 是串行保护，未见会话/进程僵死证据。未重启、终止或覆盖其 WIP；当前回合完成后 loop 会读取更新后的 prompt 与 runtime DAG。本轮审计只运行了 DAG/路由计划覆盖校验，没有运行产品测试。
