# OpenCode loop 与垂直业务闭环复核

复核时间：2026-10-04 08:40（Asia/Shanghai）

## 运行状态与循环表现

OpenCode 没有停机。`http://127.0.0.1:4096/global/health` 返回 healthy，版本 `1.18.31`；活动会话 `ses_f0610053affeUgX6mYiSJCw9Z7` 仍在执行工具/推理。最近可见进展是继续核对 Wish service-item/version 的权威持久化边界，并准备持久化适配实现。`progress.md` 的最新摘要停留在 WADM-04/WADM-11/WADM-17 切片，不能代表当前会话的最新工作。当前现象是持续编码，但完成定义与执行进度记录脱节，不是服务停机。

用户看到的“循环”有实际记录层面的原因：`progress.md` 约 129 KB / 1,307 行，有 239 条 `BLOCKED` 记录，文字变体有 227 种；反复出现的共同原因是 shared-worktree ownership 与 canonical integration。其当前 delivery 摘要仍将 WADM-17 列作 next task，虽然后续已出现 WADM-13 的新提交。这让执行历史、当前状态与下一任务不一致，也把单任务冲突呈现成整轮无进展。

## DAG 中发现的业务覆盖缺口

初次审计发现，163 条来源路由虽全部有任务映射，但 40 个 `formal-app-migration` 任务只承接 159 条 MAPP 页面迁入 APP，没有覆盖商城、订单、会员、内容、用户服务和商户员工域的管理端导航/工作页面与原 MAPP API/数据库复用核验及逐域集成；现行 24 个 V* 节点已补齐这些计划责任。

已在 `backend/tasks.json` 增补 24 个 MAPP/Commerce 业务闭环节点（六域各 4 个：管理端导航/页面、原 MAPP API/领域服务复用核验、原 MAPP 数据模型/持久化复用核验、APP—Admin—原 API—原数据库集成）。按用户最新澄清，迁移项目不新建 MAPP 后端/数据库；确认原系统缺少登记的管理能力时才扩展原 MAPP 权威仓。Wish 健康/SCRM 继续由 Wish Admin → Wish API/DDD → Wish DB 闭环，并与 MAPP/Commerce 保持不同写主。Wish 的人员日历、仓库、薪酬等排除边界不误伤 MAPP 自有后台页面。

## 文档与导航修复

- 根目录 `AGENTS.md` 写入每个垂直业务必须以代码交付 APP、管理端清晰导航与页面、后端、数据库和集成验收的最高优先级规则；`AGENTS.MD` 是指向该规范文件的大小写兼容软链接。
- 同步更新 loop prompt、DAG 子仓约束、总体方案、跨项目架构、DAG 导航索引、需求追踪和 MAPP 合并方案，区分 APP 页面迁移与全栈业务闭环的责任。
- 增加全业务管理端导航原型及逐域矩阵，并将入口加入原型总览、Wish 前台原型、产品架构页和总体方案。
- 对齐默认项目说明和源方案基线：173 项、98 MVP必须、75 MVP后续。
- 再明确代码实现与生产执行的边界：可依据权威 schema/owner 契约补齐版本化迁移并在隔离 DB 验收；缺生产凭据/生产 owner 联调不能阻止代码实现。未确认的健康数据用途或业务字段仍不得臆造，相关真实写入须保持关闭。

## 校验结果

- `python3 scripts/validate_plan_coverage.py --source-root /home/agent/code/jiankang_app_uniapp`：173 个 source tasks；61 项需求登记双向完整；163 条路由全部映射；9 个业务域、24 个 MAPP 管理端/原后端复用核验/集成任务通过；依赖无环。
- validator 另核对了 56 个 MAPP 管理端与原服务/数据核验目标路径，均存在于对应代码仓；后续错误路径会直接导致计划校验失败。
- 静态导航检查：30 个 HTML 本地链接、93 个 Markdown/HTML 本地文档链接均解析成功；DAG 任务索引包含全部 173 个任务 ID。
- 两个相关仓库 `git diff --check` 均通过。未运行 APP 构建或产品测试。

## runtime 与进度记录

初次审计快照（08:40）时，方案源任务与活动 runtime 的 173 个任务 ID 集合无差异，24 个 V* 节点为 planned。之后用户修订了 V* 原后端/数据库复用职责，source definitions 已变化；runtime 的 ID 集合不变，但定义尚待当前 WADM-04 写回边界后安全同步。runtime 状态、lease、执行证据与 runtime-only data 必须保留，不能用方案快照覆盖。

`progress.md` 仍约 129 KB / 1,307 行，积累了 239 条 BLOCKED 记录；当前交付摘要仍是旧基线 149 项，存在严重陈旧信息。当前 active WADM-04 正在编写 Wish service catalog 的 SQLAlchemy 持久化适配，已出现两个未提交的 repository/model 文件；运行态任务仍为 planned。根规则现已要求分开处理代码与生产执行；并已向活动 OpenCode 会话排入 steer 指令，要求核对现存迁移、不要以 adapter/fixture冒充数据库闭环，发现 DAG 缺口时增补 schema task，隔离环境验收并继续 ready 工作。进度文件应在该任务写回边界归档完整历史并压缩，只保留真实状态、最近进展、具体前置和按 DAG 计算的 next task；不得在 OpenCode 正在写任务结果时覆盖它。


## 用户最新边界修正：MAPP 迁移复用原后端与数据库

用户明确：小程序页面迁入 APP 后，后端闭环继续由原 MAPP 系统承担；本迁移项目不再建设一套垂直 MAPP 后端或数据库。六域 24 个 VCOM/VORD/VMEM/VCNT/VUSR/VMER 任务的准确职责为：每域建立管理端清晰导航与工作页面、映射并核验 APP/Admin 使用的原 MAPP API/领域服务、映射并核验原 MAPP 模型/表/持久化、验证两端共用原写主的集成链路。仅当具体已登记管理操作在原服务缺失时，才扩展原 MAPP 权威仓并做兼容验证。Wish 原生健康/SCRM 继续实现其自身 API/DDD/数据库。

`backend/tasks.json` 与相关 AGENTS、loop prompt、总体方案、导航原型及矩阵现已按此口径修改；173 个 task ID 和 DAG 结构未改变。计划 validator 在这些修改后通过。活动 runtime 的 task definitions 仍须在当前 Wish WADM-04 写回边界同步 source 定义；同步前不得据旧 runtime 定义领取或报告新的 MAPP V02/V03 实现任务。同步时保留所有既有 runtime 状态、lease、验收证据及 runtime-only data。
