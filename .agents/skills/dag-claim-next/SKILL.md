---
name: dag-claim-next
description: 从实施轨 tasks.json 的 deps 就绪集中选出唯一下一个可实施任务，含泳道三查与 MVP 优先级
---

# dag-claim-next：认领下一个任务

每轮 loop 开头调用。本 skill 只做选择，不改文件。

## 输入

- cwd 必须为 `/home/agent/code`
- 已读 `Agents.md` + `progress.md`（上一轮的 `next_hint` 即起点，但必须重算，不盲从）

## 步骤

1. 从实施轨计算就绪集（依赖须 `code-ready`/`release-ready`，候选须 `planned`/`contract-ready`）：
   ```sh
   python3 -c "
   import json
   R='dcx-langgraph-dashboard/backend/.project-runtime/projects/default/tasks.json'
   d=json.load(open(R))
   ok={'code-ready','release-ready'}
   st={t['id']:t.get('status') for t in d}
   ready=[t['id'] for t in d if t.get('status') in ('planned','contract-ready') and all(st.get(x) in ok for x in t.get('deps',[]))]
   print(len(ready), ready[:30])
   "
   ```
   - 不要读基线 `backend/tasks.json` 选任务（它冻结全 `planned`，只做 validator 门禁）。
2. 排序：拓扑深度小者优先 → `data.scope == MVP必须` 优先 → id 字典序。一次只取 1 个。
3. 泳道三查（仅当候选是迁移/ Wish 任务；allowlist 以基线 `backend/tasks.json` 的 `GOV-01.data.migration_scope_policy` 为准）：
   - `formal-app-migration`：id 在 `selected_task_ids`（35 个）内 + `migration_backend == MAPP server` + `migration_source_page_ids` 非空且与 `docs/migration/mapp-page-migration-inventory.md` 逐项相等。任一失败 → 拒绝认领为迁移任务，记阻塞，换下一个候选。
   - `wish-formal-business`：id 在 `wish_native_task_ids`（13 个）内 + `migration_backend is null` + `backend_target_chain == [APP, Wish APP BFF, Wish API/application service, DDD]`。失败同上处理。
   - `AUTH-*`：直接拒绝（范围外）。
4. 输出本轮 `next_task`：`id + 标题 + target_paths_or_modules + targeted_tests`。若就绪集为空 → 走完成检查（见 loop-prompt），不要编造任务。

## 禁止

- 不预设“下一个一定是 X”；不跳过未就绪依赖；不把横向集成（`REL-*`）排到参与模块闭环之前。
