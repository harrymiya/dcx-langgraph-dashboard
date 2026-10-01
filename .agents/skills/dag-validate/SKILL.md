---
name: dag-validate
description: 跑基线覆盖率校验加本轮实施证据验收，解读 FAIL 并限制重试
---

# dag-validate：机器校验（双层）

每轮收尾调用。两层都 PASS 才算过，没有“大概行”。

## A 层：基线冻结门禁（cwd 固定 `/home/agent/code`）

```sh
python3 dcx-langgraph-dashboard/scripts/validate_plan_coverage.py --source-root /home/agent/code/jiankang_app_uniapp
```

期望 6 行全 PASS（143 planned / 97+46 / 58 双向 / 35+13 泳道 / 状态集 / 清单逐项）。FAIL 即修即回滚，不顺势改基线 `backend/tasks.json`。

## B 层：本轮实施证据

- 跑本轮任务的 `targeted_tests`（任务 `data.targeted_tests` / `verify` 注明的命令），要求 exit 0，记录命令、退出码、机器摘要。
- `git diff --check` 两边仓库 exit 0；制品路径存在（测试/构建/契约产物）。
- 缺外部配置用合成/沙箱夹具，真实写入保持关闭。

## FAIL 处理

1. 把首个 `FAIL <原因>` 原样记入 `progress.md`。
2. 只修本轮引入的漂移，不顺手重构无关任务。
3. 同一 FAIL 最多重试 3 次；超限即停轮，在 progress 记 `BLOCKED: <原因>`。
4. 常见根因速查：
   - `expected 143 tasks` → 基线被动过，回滚基线。
   - `data.depends_on does not match deps` → 以顶层 `deps` 为准同步。
   - `migration page IDs do not match inventory` → 以清单表为准回填。
   - `task/registry coverage links are not bidirectional` → 同步两侧链接。
   - 本轮测试非 0 → 修代码/夹具，不改状态蒙混。

## 纪律

- A 层未全 PASS 或 B 层非 0，不得标 `code-ready`，不得写 `<promise>DONE</promise>`；不许用 Markdown 叙述代替机器证据。
