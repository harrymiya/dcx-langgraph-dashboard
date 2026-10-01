# UX-01 三端原型与现状差异基线（最小）

`UX-01` 单写本目录。上游 GOV-05 已就绪。

## 对照源
- 客户 APP / 疗愈师 APP / 前台 PC Web 三端原型
- 现状：`jiankang_app_uniapp/pages/*` 20页 + shell 2页（FND-03）

## 差异清单（摘录）
- 首页：原型有预约/提醒+服务快捷入口，现状 `pages/home/index` 缺提醒挂件 → 交 UX-04 补 async-state。
- 健康：一级入口唯一，`pages/health/*` 已有 roster/exercise/weight，按 UX-02 只留一个底栏入口。
- 第三方小程序：APP 首页三个外部按钮只拉起外部，不列入迁移（MIG-04）。

## 输出
本目录为 UX-03/UX-04 的输入，不改业务代码。
