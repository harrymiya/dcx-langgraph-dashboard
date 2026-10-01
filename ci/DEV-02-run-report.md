# DEV-02 运行报告：CI 与 iOS/Android APP、管理端 H5 构建矩阵

时间：2026-10-01 Asia/Shanghai。执行人：supervisor（opencode local 实施）。
codex 额度：`codex login status` = ChatGPT 已登录；read-only 探针因沙箱 loopback 被禁失败（含 tokens used，无 429/quota 类错误），本轮由本模型直接实施。

## 制品（`DEV-02` 单写范围）
- `ci/app-ios-android/build-matrix.md`：iOS/Android 双平台矩阵，可复现规则，平台限制声明
- `ci/app-ios-android/validate-matrix.mjs`：SHA40/工具链 pin/禁用词 fail-closed 校验 + `matrixKey` 幂等
- `ci/app-ios-android/dev02-app.test.mjs`：8 pass
- `ci/admin-h5/build-matrix.md` + `validate-matrix.mjs` + `dev02-admin.test.mjs`：7 pass
- `features/legacy/mapp-compat-adapter/README.md` + `adapter-check.mjs` + `adapter.test.mjs`：5 pass（allowlist/只读/fail-closed）

## 测试（均为 exit 0）
- `node --test ci/app-ios-android/dev02-app.test.mjs`：8 pass / 0 fail
- `node --test ci/admin-h5/dev02-admin.test.mjs`：7 pass / 0 fail
- `node --test features/legacy/mapp-compat-adapter/adapter.test.mjs`：5 pass / 0 fail
- `python scripts/validate_plan_coverage.py --source-root /home/agent/code/jiankang_app_uniapp`：全 PASS
- `git diff --check`：exit 0

## 安全降级
- 真实签名（Apple 证书/keystore）、上架发布、生产数据源一律关闭；SHA/tenant 均为合成。
- 小程序业务端未进矩阵；compat adapter 仅短期历史路由只读映射。
