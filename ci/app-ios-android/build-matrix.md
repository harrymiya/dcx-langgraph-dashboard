# DEV-02 客户 APP 构建矩阵（iOS / Android）

`DEV-02` 单写 `ci/app-ios-android/`。上游 DEV-01（隔离 env/test）/ UX-03（设计 token）/ FND-03（shell 22 页）已就绪。
目标设计/未实现：本矩阵是 CI 契约与静态校验，不代表已出包、已上架或具备生产签名。真实签名/上架保持关闭。

## 构建目标（只含正式业务端）

| 平台 | 产物 | 渠道/env | 工具链（pin） | 来源 |
|---|---|---|---|---|
| iOS | APP（uni-app x → Xcode archive） | dev / test | Xcode pin 见 `validate-matrix.mjs` TOOLCHAINS；来源 SHA 固定 | `jiankang_app_uniapp` `dev_lirui` |
| Android | APP（uni-app x → Gradle bundle/apks） | dev / test | JDK/Gradle/AGP pin 见同上 | 同上 |

- 小程序业务端不进矩阵（`implementation` 约束）。
- production 签名与发布不在本任务执行，只留矩阵占位 + fail-closed 门禁。

## 可复现规则（机器校验见 `validate-matrix.mjs`）

1. 每次构建必须记录 `sourceSHA`（40 位 hex）+ 工具链版本；缺失或格式不对 → fail-closed。
2. dev/test 构建绝不使用 production 签名/证书/profile；出现 `prod`/`release-sign`/`distribution` 即拒绝。
3. 同一 `sourceSHA + toolchain + platform + env` 必须给出相同矩阵键（幂等 `matrixKey`）。
4. 平台限制必须显式声明（见下节），未知平台直接拒绝，不猜测。

## 目标平台限制说明（合成，无真机/证书）

- iOS：无 Apple 证书与真机，仅做矩阵/契约静态检查；archive/上架动作为后续门禁项。
- Android：无 keystore，仅做矩阵/契约静态检查；签名包动作为后续门禁项。
- 管理端 H5 见 `ci/admin-h5/`；两者矩阵键互不复用。
