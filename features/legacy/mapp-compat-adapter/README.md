# DEV-02 短期历史路由 compat adapter 安全检查

`DEV-02` 单写 `features/legacy/mapp-compat-adapter/`。
`legacy-compatibility-fallback` 泳道：只处理历史 route 身份续接与受控回退，保持对 `MAPP server` 原服务边界；
不建第二业务后台、不签发长期 token、不进业务构建矩阵。目标设计/未实现。

## 规则（机器校验见 `adapter-check.mjs`）

1. adapter 只允许登记表内的历史路由（`ALLOWLIST`）；未知路由 → fail-closed 回 APP 原生页。
2. adapter 绝不携带业务写操作（只读 route 映射）；出现 `POST`/`write`/`ledger` 即拒绝。
3. 小程序业务端整体不进构建矩阵；adapter 存在不代表业务已迁移。
4. bridge 参数（一次性、audience/route 受限）只做格式检查，真实签发/兑换不在本任务执行。
