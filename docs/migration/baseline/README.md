# GOV-01 来源快照与零删除基线

- 任务：`GOV-01`，状态保持 `planned`；本目录记录设计基线，不代表业务已实现。
- 采集时间：`2026-10-01T09:22:37Z`。
- 台账范围：`docs/migration/baseline`；GOV-01 单写本目录。

## 来源与路由基线

任务输入与迁移清单均声明 MAPP 来源为 `/home/musk/code/mapp/mapp_app` 的 `origin/release`，SHA `ce281ef0d9a6c05a43e87a4799b730c36112ff75`。本次核对了任务输入和清单声明相同；本次确认声明路径 `/home/musk/code/mapp/mapp_app/.git` 不存在，因此无法检查独立 MAPP 仓库的 Git 对象。此 SHA 是已与 GOV-01 输入交叉匹配的声明来源，不声称已验证该 Git 对象。

本次清单仓库快照位于 `/home/agent/code/jiankang_app_uniapp`，分支 `dev_lirui`，HEAD `e25dd3c5481a017d10b7264292721cb18e2aba91`，工作区干净。这个仓库承载总体方案和迁移清单，不是上面的 MAPP 源仓库。逐路由台账从 `docs/migration/mapp-page-migration-inventory.md` 的 163 行生成，ID 为连续且唯一的 `MP001`–`MP163`。清单声明主包 6、分包 157、分包根 11；路由拆分数来自清单声明，未对独立 MAPP 源码进行重新解析。

## 零删除规则

`zero-deletion-ledger.csv` 为 163 条路由逐项保留记录。基线删除数为 0；每行 `deletion_approval=none`、`deletion_status=not-deleted`。没有逐路由批准证据时不得删改来源路由事实；以后如获批准，应在新变更中记录对应路由、批准人/依据和验收证据，保留此基线版本。

## 受保护路径

`protected-paths.csv` 锁定当前清单仓库中的登录页和共享网络 client：`pages/auth/login.uvue`、`foundation/network/client.uts`。它们对应 DAG 来源文档中的 `login.uvue`、`network/client.uts` 保护要求。基线采集时两文件均存在；其 SHA-256 也记录在路径表中，专项检查会拒绝静默内容漂移。此任务没有修改它们；未来拟改动必须逐路径说明、评审并登记，不得被批量覆盖或删除。

## 工作区登记

`workspace-change-register.csv` 记录两个检查过的工作区：DAG 仓库 `b33884643df102395d9aa0c42d64ee19350fa01d` (`main`) 与清单仓库 `e25dd3c5481a017d10b7264292721cb18e2aba91` (`dev_lirui`)。两者采集前均无未提交改动；来源仓库按只读方式检查。`workspace-change-register-template.csv` 可供后续逐路径登记既有 modified/deleted/untracked changes；对每个脏路径单独填行，注明 owner/task、保护路径审查和处置，不得用提交后的状态替代开工前快照。

## 机器快照

完整机器可读快照及源文件 SHA-256 见 `source-snapshot.json`。后续验收结果见 `execution-report.md`。本台账是来源与变更管理证据，不证明来源功能在生产可用。
