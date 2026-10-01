# GOV-02：身份、会话与账本边界 v1

配套 [责任矩阵](system-ownership.md) 和 [机器契约](contract-policy.json)。所有标为 `fixture:*` 的 audience、route、origin 和身份是合成验收值，不是生产配置或新的 API 契约。领域名与错误原因用于设计验收；对外错误码/HTTP 映射仍由 API-01/APPBFF-01 等单写任务确定。

## 单次登录与隔离会话

“双登录”验收检查 Commerce/Wish 两个隔离业务上下文可同时存在，以及任何第二次客户登录请求均被拒绝。客户只在 APP 以手机号 + 短信验证码登录一次；Wish/Commerce 的 client、storage、audience 和域级登出隔离，不表示客户需分别输入凭据，也不表示 MAPP 签发独立长期 token。

| 操作 | 必须发生 | 必须保留 / 拒绝责任 |
| --- | --- | --- |
| APP 首次登录 | 经客户身份源验证后建立 APP session | 不把手机号当 customer_id，不写商城/健康业务事实 |
| 进入正式迁移页 / Wish 页 | 从已验证 APP principal 续接各自受限业务上下文；按各域原契约验权 | 不交换 Commerce/Wish token，不弹第二次登录；FND-01 拒绝错误续接配置 |
| Wish 域级 logout | 撤销 Wish 上下文、清理 Wish client/storage | APP 和 Commerce 上下文保留；不是 APP 全局退出 |
| Commerce 域级 logout | 撤销 Commerce 上下文、清理 Commerce client/storage | APP 和 Wish 上下文保留 |
| APP 全局 logout | APP session 失效，阻断该 session 派生业务上下文；撤销待兑 bridge 及已兑兼容态 | 不能以独立登出为由保留可用 bridge；不退出其他客户端/其他 APP session，不修改账本 |
| logout / 撤销服务失败 | 本地停止使用相应上下文，服务端不能确认有效性时 fail closed，后续请求拒绝 | FND-01 负责 APP 阻断；API-02 负责 bridge/派生态撤销，MAPP/Commerce 按原契约拒绝失效上下文 |

APP root session 与业务 audience 不等同。Wish API/application/DDD 拒绝 Commerce 或 bridge audience；MAPP/Commerce 原服务入口拒绝 Wish audience；兼容兑换端拒绝 Wish/Commerce audience。有效会话仍需验证来源、时效、撤销、principal、tenant/site、subject、relationship、purpose、consent 及 field scope。客户端自报这些字段只表示选择意图，不能形成授权事实。BFF 只适配渠道，不兜底授权，不替写主接受越权请求。

## 历史身份映射与 bridge

小程序微信登录/授权及按配置进行的手机号核验/短信验证是历史来源。Wish CRM 以 `customer_id` 维护带 source system、旧 subject、已验证 APP principal 引用、验证证据/状态、有效期、tenant/site、版本与撤销记录的映射。手机号、union_id、平台 ID 相同不能自动合并；未知、冲突、过期、撤销映射均拒绝，由 Wish CRM 身份映射应用服务负责确认。旧协议只在主体、协议版本及证据可验证时续接，不推定健康/营销 purpose consent。

正式迁移页面直接按原服务契约调用 MAPP server，不走 Wish bridge。历史 route 需要 bridge 时由 Wish 服务端验证 APP session，签发短期、opaque、单次、绑定 audience、allowlisted route/origin、nonce/jti、subject、tenant/site、relationship、purpose、consent 的票据。服务端原子兑换，仅返回绑定原 session 和 route 的临时上下文；不返回可复用旧 token。旧 token 仅允许服务端一次性兑换且立即失效；不能确认失效时拒绝兑换。旧 token 不能回传或续期。

API-02 的 bridge 服务对重放、过期、撤销、错 audience/route/origin、上下文不匹配及超时负责拒绝；FND-08 执行安全回退。APP session 有效时回 APP 原生安全页/明确错误，无效时回 APP 登录入口；不得打开 MAPP 独立登录或签发长期 token。原子消费的并发正确性留给 API-02/TST-05 的真实实现验收；本目录只用顺序合成状态验证契约。

## 双账本与跨域引用

| 命令/数据 | 唯一写主 | 禁止 / 拒绝责任 |
| --- | --- | --- |
| 商城订单、会员余额/积分/券、支付退款、商城账 | Commerce/MER | Wish、BFF、APP、投影、provider 直接写账均由 Commerce/MER 拒绝 |
| 服务费用/卡、应收、健康退款审核、健康服务账 | Wish 服务账 application/DDD | Commerce/MER、BFF、APP、投影、provider 直接写账均由 Wish 服务账拒绝 |
| Wish 已记账更正 | Wish 原账追加冲正/补充分录 | 禁止覆盖、删除历史或直接改余额；账务事实与 Outbox 同事务 |
| provider 回调 / 已验证权益事件 | 对应写主验证签名、金额、版本、幂等、tenant/site 后执行本域命令 | 事件/回调不是通用写权限；支付状态未知不报成功，不能跨域双写 |
| Commerce → Wish 最小引用 | Commerce 按获批 scope 输出，Wish application 校验后只读消费 | 不共享 DB、token、完整订单、钱包流水或健康正文；双方都验证授权与字段范围 |

本版本的合成只读引用只含 `order_ref`、`entitlement_ref`、`source_version`、`status`，且全部必填；它是验收用的最小投影，不定义线上 DTO。授权元数据（已验证源、tenant/site、subject、purpose、consent、field scope、有效期、审批版本）在可信服务端上下文中校验，不能靠 payload 自报。服务端批准前默认关闭；客户端带 `approved=true` 不算批准。生产字段、purpose、状态词表和批准流程须由 API-01/HWI-03/GOV-05 后续冻结。

最小引用通过只能产生只读映射/展示结果，账本增量必须为零；商城购买不自动创建健康预约、健康参与、服务卡或扣费。未知字段、缺字段、未批准、过期/撤销、错误站点/主体/目的/同意/字段 scope、写入模式、复制完整订单或自动创建健康事实均由 Wish 跨域引用 application 拒绝。后续若批准权益事件，仍需目标 Wish 写主独立授权、版本化规则及 Inbox 幂等；不得借只读交接变相写账。

## 拒绝与最小审计

设计检查固定记录 `decision`、`reason`、`responsible`、`fallback` 和 `ledger_delta`，拒绝的账务增量恒为 0。真实最小审计仅记录事件/关联引用、脱敏 actor/object 引用、经验证的 tenant/site 引用、目的、原因、决策、责任域、策略版本与时间；未知上下文不抄录客户端自报值。禁止 token/bridge、密码、验证码、手机号、完整订单、健康正文及被拒字段值。审计失败不能把拒绝变成允许，安全返回页不泄露受限对象。

| 拒绝类型 | 主责（执行任务） | 受保护状态 |
| --- | --- | --- |
| 第二次客户登录 / session 失效 | APP session boundary（FND-01）；各域服务端重复校验 | 其他域 session 不被域级操作清空，账本不变 |
| 错 audience | 被调用服务端：Wish API/application/DDD、MAPP/Commerce service 或 Wish bridge service | 不更换 token 重试、不转另一写主 |
| 错账本 / 双写 / 分录覆盖 | 目标账本写主：Commerce/MER ledger 或 Wish service ledger | 两账本均无部分写入 |
| 非最小/越权跨域引用 | Wish reference application；Commerce 出口也按契约裁剪 | 不创建账务、预约或参与事实 |
| bridge 生命周期/绑定失败 | Wish bridge service（API-02）；FND-08 负责回退 | 旧 token 不复用，失效上下文不能恢复授权 |
| 历史身份冲突/自动合并 | Wish CRM identity mapping | 不创建或合并客户事实 |

## 自动验收与限制

```sh
python docs/migration/domain-contracts/validate_contracts.py
python scripts/validate_plan_coverage.py --source-root /home/agent/code/jiankang_app_uniapp
git diff --check
```

专项程序从机器契约读取约束，以独立期望值验证登录、独立登出、audience、账本与引用的正负向场景，并检查 session/storage/账本状态、拒绝责任、审计字段及典型错误契约变体。输出逐场景 JSON；任何失败退出非零。`verification-results.json` 保存原始 stdout/stderr、命令和退出码。

本验收不访问真实服务，不运行真实登录、密码学验签、数据库事务、并发原子兑换、支付、消息或生产发布。身份源、真实 issuer/audience、短期 TTL、MAPP 对 APP session 的实际原契约适配、支付/权益规则和跨域批准都未据此确认。未配置部分保持关闭，未来由 IDN-01、FND-01、API-02、API-03、HWI-03、API-07、TST-05/SEC-04 逐项实施验收。任务状态保持 `planned`，本任务不写回范围外的 `backend/tasks.json`；机器证据交由任务图维护方按权限登记。
