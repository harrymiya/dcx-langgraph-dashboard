---
name: dag-validate
description: 按任务风险执行专项验收，并在图定义变化或发布阶段运行对应全量门禁
---

# 任务验收

## 普通实现任务

- 执行所选任务 data.targeted_tests、verify 或 acceptance 中与本轮目标对应的命令，记录实际命令、退出码、摘要和制品路径。
- 对本任务修改的每个目标仓运行 git diff --check，并核对变更路径属于登记范围。
- 根据目标平台选择必要的类型检查、构建或静态检查。无需为孤立模块重复跑跨端 E2E 和全套项目基线覆盖校验。

## DAG、registry 或迁移映射变化

运行：

    python3 dcx-langgraph-dashboard/scripts/validate_plan_coverage.py --source-root /home/agent/code/jiankang_app_uniapp

记录 6 项机器输出。修复任务 ID、依赖、来源双向映射或泳道差异后重跑；基线应保持 149 项、98/51、40 项 MAPP 页面迁移、163 条路由逐项有 DAG 任务，以及 13 项 Wish 原生业务。

## 集成/发布任务

执行任务登记的完整客户端/管理端/API/数据库集成、目标平台 build、隔离环境 E2E、权限负向、部署与回滚验收。release-ready 需要全部明确验收项通过；真实生产写入使用独立授权和环境。

## 失败处理

将失败隔离在本任务，保留首条真实命令和错误、修复可确定的根因。仍失败时记录缺失前置并保持任务未完成，继续其他 ready task；不要重复跑相同失败命令，也不要停止整个 loop。
