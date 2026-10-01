# FUT-04 旅居与专业康复拓展后续评估边界

`FUT-04` 单写 `docs/migration/future-scope/fut-04-*`。上游 GOV-05 已就绪。
状态：`out-of-scope-with-reason`（MVP后续）。目标设计/未实现：本文是评估边界，不代表已立项或已签约。

## 后续能力（明确不进本期）

| 能力 | 说明 | 启动前提（另立 change） |
|---|---|---|
| 酒店/PMS 深度接入 | 旅居场景的酒店、PMS 系统对接 | 独立商务与合规评估；不得复用健康数据授权 |
| 医疗/专业康复能力 | 医疗级诊疗、专业康复处方与执行 | 医疗资质 owner 确认 + 独立验收；健康服务账不与其混账 |
| 旅居行程与健康服务编排 | 跨站行程 + 服务预约联动 | 以两站隔离验收通过为前提，另立集成任务 |

- 以上能力不计 MVP DoD；MVP UI 不得声明已交付；默认关闭。
- 酒店/PMS 与医疗康复的任何数据往来须走独立授权，不得沿用本期 `crm_consent_record` 的健康/营销目的。

## 本期仍属验收（不得以后续为由削减）

- 健康服务的 `tenant/site` 隔离仍属于本期验收：两站（site-a/site-b 合成 tenant，见 DEV-01 `env-matrix.md`）隔离与配置复制必须通过。
- 本期入口复核（2026-10-01，`jiankang_app_uniapp/pages.json` 共 22 页）：无旅居/酒店/PMS/医疗康复页面，清单如下 —
  `pages/index/index`、`pages/foundation/*`、`pages/auth/*`、`pages/home/index`、`pages/health/*`（index/exercise/weight/roster/roster-add/roster-edit）、`pages/profile/*`、`pages/settings/*`、`pages/legal/agreement`、`pages/shell/*`。
  后续能力零出现在本期入口。

## 回退

默认关闭；误入本期的后续入口一经发现即下线并另立 change（`rollback_or_fallback`）。
