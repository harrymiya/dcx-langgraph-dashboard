# GOV-01 执行报告

- 任务：`GOV-01` — 锁定来源快照与零删除基线
- 任务状态：`planned`（按 `AGENTS.md` 保持设计任务状态）
- 采集时间：`2026-10-01T09:22:37Z`
- 执行分支与基线：`main` @ `b33884643df102395d9aa0c42d64ee19350fa01d`
- 结果索引：[`verification-results.json`](verification-results.json)，记录命令、退出码和机器摘要。

## 交付文件

所有改动均位于任务声明的 `docs/migration/baseline` 范围内：

- `README.md`：来源版本、职责边界、零删除及登记规则。
- `source-snapshot.json`：任务输入和来源清单版本、两个仓库快照、源文件 SHA-256 与 163 条路由计数。
- `zero-deletion-ledger.csv`：MP001–MP163 逐项保留，删除数为 0。
- `protected-paths.csv`：登录页和网络 client 路径、采集时 SHA-256 与变更规则。
- `workspace-change-register.csv`：记录 DAG 仓库与清单仓库的开工前干净状态。
- `workspace-change-register-template.csv`：未来逐路径登记既有改动的模板。
- `validate_baseline.py`：标准库专项基线检查器。
- `verification-results.json`：命令、退出码和机器输出。

## 来源核对范围

任务输入与迁移清单都声明 MAPP `origin/release` SHA 为 `ce281ef0d9a6c05a43e87a4799b730c36112ff75`。该 SHA 与清单声明一致。清单仓库 `/home/agent/code/jiankang_app_uniapp` 的 `dev_lirui` HEAD 为 `e25dd3c5481a017d10b7264292721cb18e2aba91`、工作区干净；它承载清单，不是 MAPP 源仓库。声明的 MAPP checkout 路径 `/home/musk/code/mapp/mapp_app/.git` 不存在，因此没有直接校验该 MAPP Git 对象。该限制已写入快照和机器结果，不将来源声明等同于源对象验证。

## 验收结果

- `validate_baseline.py` 通过：163/163 路由 ID 连续、唯一，全部来源字段与原清单逐项匹配；清册删除数为 0；登录和网络受保护文件存在且 SHA-256 未变化；两个工作区均登记。
- `validate_plan_coverage.py` 通过：143 项均为 planned、97/46 范围统计正确、依赖无环、覆盖双向完整、35 个 MAPP 迁移任务和 13 个 Wish 原生任务边界通过。
- 初次暂存区空白检查发现 CSV 的 CRLF 行尾被判为尾随空白（退出码 2）；已统一为 LF。修复后专项检查通过，最终 `git diff --check` 与 `git diff --cached --check` 均退出码 0。
- 所有命令输出摘要和退出码见 `verification-results.json`。

## 检查命令

| 检查 | 命令 | 退出码 |
| --- | --- | ---: |
| MAPP 来源路径可用性 | `if test -d /home/musk/code/mapp/mapp_app/.git; then git -C /home/musk/code/mapp/mapp_app rev-parse HEAD && git -C /home/musk/code/mapp/mapp_app status --porcelain=v1; else echo 'MAPP source checkout unavailable at inventory-declared path'; fi` | 0（路径不存在；仅声明 SHA 可匹配） |
| GOV-01 targeted checks | `python docs/migration/baseline/validate_baseline.py --source-root /home/agent/code/jiankang_app_uniapp` | 0 |
| DAG/coverage validator | `python scripts/validate_plan_coverage.py --source-root /home/agent/code/jiankang_app_uniapp` | 0 |
| 初次暂存内容检查 | `git diff --cached --check` | 2（已修复 CSV CRLF） |
| 最终工作区检查 | `git diff --check` | 0 |
| 最终暂存内容检查 | `git diff --cached --check` | 0 |

本台账是设计阶段的来源与工作区管理证据，不表示路由功能、MAPP 源代码或 Wish 业务已在生产实现。没有修改 `backend/tasks.json`，任务状态保持 `planned`。
