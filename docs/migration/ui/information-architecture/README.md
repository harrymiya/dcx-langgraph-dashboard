# UX-02 主壳IA与旧路由意图（最小）

`UX-02` 单写本目录。依赖 GOV-03 登记表 + GOV-05 范围。

## 一级入口（4个）
首页 / 健康 / 商城 / 我的。底栏健康管理只留一个一级入口。

## 旧路由意图
- 163 条见 `features/navigation/legacy-route-registry/legacy-route-registry.json`。
- 参数原样透传，未知参数保留不信任；分享/码/Deep Link 带 scene/source/activity_id，不带 token。
- 返回栈：迁移页由 APP 中心路由接管；未迁历史路由走短期 adapter/安全外链。
- 登录恢复：未登录打开需登页 → 登录后回到原 target + query。

## 原型对照
`docs/prototypes/customer-miniapp-prototype.html` home + health-services 为交互参考，人物数据为合成示例。
