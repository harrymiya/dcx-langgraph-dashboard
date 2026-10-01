# DEV-02 管理端 H5 构建矩阵

`DEV-02` 单写 `ci/admin-h5/`。管理工作台按 H5 验收（`implementation` 约束）。

| 平台 | 产物 | 渠道/env | 工具链（pin） |
|---|---|---|---|
| H5 | 管理工作台 Web 构建（`apps/wish-adm`） | dev / test | Node pin 见 `validate-matrix.mjs`；来源 SHA 固定 |

规则：
1. 构建必须记录 `sourceSHA`（40 位 hex）+ Node 版本；缺失即 fail-closed。
2. H5 构建不打 APP 壳、不复用 `app-ios-android` 矩阵键；出现 `apk`/`ipa`/`xcode` 关键字即拒绝。
3. dev/test 产物不连 production 数据源（复用 DEV-01 `PROD_HINTS` 思想：`prod`/`production`/生产 IP 即拒绝）。
4. 小程序业务端不进矩阵；历史兼容只走 `features/legacy/mapp-compat-adapter/` 的短期 adapter 检查。
