---
name: dag-claim-next
description: 从活跃产品实施轨筛出依赖就绪任务，按产品交付优先级返回下一个任务
---

# 认领下一个产品任务

每轮开头使用。本 skill 只选任务，不改任务状态。

## 输入

- cwd 为 /home/agent/code。
- 当前执行者已读 AGENTS.md 和 progress.md 最近摘要。
- 方案基线：dcx-langgraph-dashboard/backend/tasks.json；状态轨：dcx-langgraph-dashboard/backend/.project-runtime/projects/default/tasks.json。

## 步骤

1. 只认领基线 149 个任务 ID 在活跃实施轨中的记录。default 中超出基线的 APP18/APP19、Render Core、WellLog 等历史任务不是本产品任务：不得选择，不计数；缺失的基线项列明 ID 并继续可用任务。
2. 候选状态为 planned/contract-ready；所有顶层 deps 必须是 code-ready/release-ready。不要仅凭旧进度或 target 文件存在认定依赖完成。
3. 排序：MVP必须 优先；其内按 I0 基础、I1 核心业务、I2 管理运营、I3 集成发布；同一波次优先能解锁较多未完成后续任务的节点，然后按 ID。MVP完成后，后续优先163 条路由登记的正式 MAPP 页面迁移与其余 MVP后续能力，再处理其它登记的 MVP后续能力。
4. 仅对被选中的迁移/Wish 任务核对 GOV-01 登记的 allowlist、migration_lane、migration_source_page_ids、route_inventory_page_ids 和对应迁移清单。formal-app-migration 只能调用 MAPP server 原服务；Wish 原生业务按其 Wish BFF/API/DDD 链。缺失字段则依据源方案一次性补全并记录，不能无限期停在检查。
5. 输出唯一 next_task：ID、标题、仓库/target_paths_or_modules、直接依赖、targeted_tests、相关原型或迁移清单。不要将完整 JSON 或所有任务数据展开到上下文。

无候选时，报告未完成任务最直接的阻塞依赖并指出能继续实现的前置工作。不得发明状态、删除真实依赖或以空队列宣告全部交付。
