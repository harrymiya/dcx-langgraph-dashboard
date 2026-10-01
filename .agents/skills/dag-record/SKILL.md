---
name: dag-record
description: 把单轮实施结果写回实施轨 tasks.json 与 progress.md，保持连续体不断
---

# dag-record：写回证据与连续体

每轮在 `dag-validate` 双层 PASS 后调用。本 skill 是 loop 跨轮记忆的唯一载体。

## 1. 写实施轨 `backend/.project-runtime/projects/default/tasks.json`

- 只改本轮 `next_task`：`status` 按验收推进（`planned`→`contract-ready`→`code-ready`，发布项才到 `release-ready`），补 `automated_result`（命令、退出码、摘要、制品路径、安全降级说明）与相关证据字段；不改 `id`/`deps`，不碰 `AUTH`，不动基线 `backend/tasks.json`。
- 基线登记（`GOV-01` registry 双向链接）如需同步，只在 validator 要求时改，且改后立即重跑 A 层，PASS 才算成功。

## 2. 写 `/home/agent/code/progress.md`（每轮必写）

在文件尾追加一轮小节：

```text
## <日期> <TASK_ID> <一句话>
- DONE: <本轮完成的实施轨 id；就绪集由 dag-claim-next 从实施轨重算，本行仅审计用>
- 做了什么：（改了哪些 target_paths，测试命令+退出码，一行一条）
- 校验：A 层 validator 全 PASS + B 层 targeted_tests exit 0
- 下轮 next_hint：（按实施轨 deps 拓扑建议 1 个，不要写死）
- open/blocked：（无则写 无）
```

- 旧 `DONE_TASKS:` 累积行已废弃（实施轨状态即真相），保留历史行不再追加新格式即可。
- 大批量落地（≥3 任务）时同步追加 `dcx-langgraph-dashboard/docs/reports/tasks/RUN-<日期>-<范围>.md`（命令、退出码、commit、推送实录，参照 `RUN-20261001-gov-ux-fnd.md`）。
- `git commit/push` 仅用户明确要求才做；默认只留工作区文件 + 校验日志。

## 3. 一轮小结输出

- 3~5 行中文：next_task、改动点、双层校验结果、下轮起点。
- 只有同时满足（实施轨就绪集为空 + A/B 全 PASS + 无 open 项）才在末尾另起一行输出 `<promise>DONE</promise>`；否则绝不输出。
