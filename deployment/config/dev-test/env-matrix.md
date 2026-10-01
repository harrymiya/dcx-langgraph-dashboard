# DEV-01 环境矩阵（dev/test 隔离，合成数据）

`DEV-01` 单写本目录。上游 GOV-01/GOV-05 已就绪。真实写入关闭，未知值一律合成/沙箱。

| 环境 | APP 后端 | Wish 后端 | DB | Commerce | 站点 |
|---|---|---|---|---|---|
| dev | MAPP server (sandbox) | Wish API (mock) | Wish DB (synthetic) | MER mock | site-a / site-b（合成 tenant） |
| test | MAPP server (sandbox) | Wish API (sandbox) | Wish DB (sandbox) | MER sandbox | site-a / site-b（合成 tenant） |
| production | 不在本任务连接 | 不在本任务连接 | 不连 | 不连 | — |

规则：
- dev/test 绝不连 production 任何地址；出现 prod host 即 fail-closed。
- secret 只从外部注入（见 `secret-injection.example.sh`），绝不写入 git/log/制品。
- 两站（site-a/site-b）均为合成 tenant，仅做隔离验证。
