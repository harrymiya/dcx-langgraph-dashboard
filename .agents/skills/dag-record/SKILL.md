---
name: dag-record
description: 将当前任务的实现、专项验收和交付证据写回活跃执行轨
---

# 写回执行记录

每个已完成或遇到真实阻塞的任务及时记录。只修改当前任务记录，不展开或重写整个任务图。

## 实施轨

文件：dcx-langgraph-dashboard/backend/.project-runtime/projects/default/tasks.json

完成专项实现和 targeted_tests 后，将状态从 planned/contract-ready 推进为 code-ready，并写入机器可读的 automated_result：目标仓、变更路径、命令、退出码、摘要、制品、commit/push 结果、安全降级或遗留项。完整部署与跨端集成验收通过后，发布任务才可标 release-ready。失败任务保留原状态并记录 blocker，不伪装完成。

不改冻结方案基线 backend/tasks.json，除非发现可追溯的方案覆盖缺口；确需修改时同步 source registry、deps、目标路径与来源映射，再运行完整计划 validator。

## progress.md

保持滚动摘要而非重复历史日志，记录：
- 当前 WIP/task id 和已改目标；
- 最近完成项的测试/commit/push 结果；
- 具体 open/blocker 与直接依赖；
- 从活跃 DAG 重算的 next task。

保留最近 10 个完成记录。详细执行日志留在对应仓库 docs/reports/tasks，周期性将更早内容归档，禁止重复追加相同 BLOCKED 说明。
