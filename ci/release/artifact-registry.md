# DEV-03 签名制品、版本追溯与测试部署流水线

`DEV-03` 单写 `ci/release/`（artifact registry）。上游 DEV-01（隔离 env/secret）/ DEV-02（构建矩阵）已就绪。
目标设计/未实现：本流水线是 registry 契约与静态校验，不代表已签名、已发布或已上线。真实签名密钥与生产发布保持关闭。

## 范围（只测试环境）

- 制品只登记 `dev` / `test` 渠道；`production`/`staging-prod` 一律拒绝登记。
- 每件制品必须绑定：`sourceSHA`（40-hex）+ `schemaVersion` + `configVersion` + 来源矩阵键（DEV-02 `matrixKey`），四者缺一即 fail-closed。
- 签名统一记为 `test-only` 方案（`scheme: test-sha256`）；任何 `production`/`distribution` 签名声明即拒绝。
- secret 独立管理：registry 文件内出现 secret 特征即拒绝（复用 DEV-01 规则思想）。

## migration 门禁（preflight/backup，先行于任何迁移）

任何涉及迁移的部署 job 必须先过 `preflight`（目标 env 非生产 + backup 快照引用非空），否则拒绝执行；
`preflight` 本身只做契约检查，不连真实数据库（本地 dfp_wish 库未就绪期间尤其如此）。

## 部署失败恢复

- deploy job 按 `artifact → test env` 执行；失败时自动回退到上一件同 env 制品（`rollbackToPrevious`），恢复后 registry 标注 `rolled-back`。
- 回滚引用 DB-06 恢复策略（DB-06 未就绪前，DB 相关回滚项记为 `deferred: DB-06`，不伪造通过）。
