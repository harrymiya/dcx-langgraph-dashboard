# DEV-03 运行报告：签名制品、版本追溯和测试部署流水线

时间：2026-10-01 Asia/Shanghai。执行人：supervisor（opencode local 实施）。

## 制品（`DEV-03` 单写 `ci/release/`）
- `ci/release/artifact-registry.md`：registry 契约（只 dev/test、test-only 签名、preflight/backup 门禁、失败回退）
- `ci/release/registry.mjs`：`validateArtifact`/`preflight`/`deploy`（失败自动回退上一件同 env 制品）
- `ci/release/dev03.test.mjs`：9 pass

## 测试（均为 exit 0）
- `node --test ci/release/dev03.test.mjs`：9 pass / 0 fail
- `python scripts/validate_plan_coverage.py --source-root /home/agent/code/jiankang_app_uniapp`：全 PASS
- `git diff --check`：exit 0

## 安全降级
- 真实签名密钥、生产发布、真实数据库迁移一律关闭；migration 只做 preflight 契约检查。
- DB 回滚引用 DB-06（未就绪，记 `deferred: DB-06`）；本地 dfp_wish 库未就绪期间不连库。
