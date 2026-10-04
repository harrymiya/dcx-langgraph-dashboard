---
name: dag-claim-next
description: 按 DAG 依赖选择一个待开发任务
---

# dag-claim-next：领取下一个任务

每轮开始时从当前运行时任务快照选择一个任务。DAG 只负责拆分工作和表达依赖，不要求额外研究任务证据。

1. 选择 `data.scope` 为 `MVP必须` 或 `MVP后续` 且状态为 `planned` 的任务，且其 `deps` 都是 `code-ready`、`contract-ready` 或 `release-ready`。
2. 按依赖顺序和任务 ID 选择；每轮只处理一个任务。MVP 完成后继续领取其余任务，直到客户 App、疗愈师 App、MAPP/Commerce 员工工作台和管理端原型功能完成。
3. 按任务自身的目标、范围和文件声明实施。不要为选任务而遍历原型、来源文档、证据目录或生产系统。
4. `AUTH-*` 仍属于明确排除范围，不领取。
5. 输出 `id`、标题、目标路径和任务声明的相关自动化测试。没有 ready task 时停止领取，不做额外完成审计。

不要改任务 ID 或 `deps`，不要跳过未完成依赖，也不要把测试之外的证据调查设为开始或完成门槛。
