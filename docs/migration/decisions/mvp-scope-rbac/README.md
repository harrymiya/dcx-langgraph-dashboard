# GOV-05 MVP范围与RBAC最小决策

`GOV-05` 单写本目录。承接 GOV-01/GOV-02，不新增登录与账本写主。

## MVP边界
- 健康管理 + SCRM：客户档案、健康记录、服务目录与预约、履约/SOP、回访触达、健康服务账。
- Commerce/MER：商城事实唯一写主，Wish 只读引用。
- 范围外：员工排班、库存、绩效KPI、收银、商户经营、管理员认证。

## 角色
- 客户：APP 手机号+短信登录一次，`tenant_id+site_id` 隔离。
- 疗愈师/前台：各自工作台经 Admin BFF 同一 Wish 写主，不管商城。

## tenant/site矩阵
| 域 | 写主 | 读约束 |
|---|---|---|
| 健康/SCRM/预约/履约/服务账 | Wish DB | tenant+site 必带，跨域只传引用ID |
| 商城/订单/支付/会员 | Commerce/MER | Wish 不写，只读 |
| MAPP既有业务 | MAPP server | APP迁移页按原契约调，不新建后端 |

## 回退
恢复上一版本目录即可；有冲突的下游退回 ready。
