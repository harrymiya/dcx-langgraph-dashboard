# DB-06 健康与 SCRM 分阶段迁移/回滚契约

状态：实施设计 / 未连接数据库 / 未执行 SQL 或 DDL。该 runbook 描述未来经审批的操作顺序；此仓当前不含可连接数据库的 adapter，也不含真实路由切换实现。

## 来源与边界

- 以 DB-01 的只读 legacy 基线、DB-02 的 60 个 canonical 实体模型和 DB-03 的复合 tenant/site 约束为输入。DB-01 映射文件中的样例仍标记为 `unverified/synthetic`，不得据此推断实际列映射或生产数据质量。
- legacy 表名保持不变并进入只读兼容期。每个事实只有一个权威写主；回填写入隔离 shadow 区，不双写。Commerce/MER 订单、退款、商品和库存仍由 MER 独占写入，Wish 只接收最小只读引用。
- tenant/site 是每条业务事实的显式范围；不能从手机号、姓名、union ID、默认站点或客户身份锚点推导业务归属。来源不明、身份冲突、owner/用途/同意不明的数据必须隔离，不进入可读或可写路由。
- 健康记录仍受 health owner、用途、同意和字段范围门禁约束。不能迁入认证凭证、session、验证码、token、健康正文明文、消息正文或完整商城订单快照。
- `fin_service_card_ledger`、预约/履约历史、事件、审计和其他 append-only 事实不可更新或删除；余额只是由分录重算的投影。更正要通过经业务规则批准的冲正/补偿事实完成。

## 阶段与进入条件

| 阶段 | 操作 | 通过门槛/产物 |
|---|---|---|
| 1. 只读盘点 | DBA 固定来源版本、owner、schema fingerprint 与水位；统计表/列/索引/FK、按逻辑数据集计数和按币种金额汇总。只读取必要元数据与聚合值，不导出行值或健康正文。 | 只读权限和来源快照已审批；schema/计数/金额摘要可复核；备份恢复演练完成；未知归属列入隔离清单。 |
| 2. Shadow backfill | 使用已评审的字段映射、身份/站点映射和目标 owner，在隔离 shadow 写入。按 tenant/site 分批处理；每批用 contract version、scope、源 fingerprint 和 opaque cursor 派生幂等键。 | checkpoint 可持久化并 CAS 更新；重复批次效果幂等；中断后从最后已提交 cursor 续跑；任何未映射数据都隔离，不能填默认 tenant/site。 |
| 3. 双读对比 | 对同一 source watermark 在 legacy 与 shadow 读取聚合摘要，不双写。比对逻辑数据集计数、金额和币种、映射/状态覆盖、tenant/site 范围、复合 FK 孤儿数及来源水位。 | 行数/金额/币种无未豁免差异；孤儿 FK 与 scope violation 为 0；所有差异归因并获 owner 签核；输出仅含受控聚合摘要/差异码，不含原始行。 |
| 4. Tenant/site 灰度 | 单次只对一个明确 tenant/site 开启 canary 路由，保留原 legacy 只读路径；完成一个完整业务周期和对账后再申请扩大范围。不得全租户或全站点一键切换。 | 映射与 owner、scope、安全、parity、备份恢复、回滚演练证据均齐全；无未决隔离项；切换负责人和审批引用已登记。 |

回填按领域顺序准备 canonical customer/身份对照、关系/同意、服务目录/资源/预约与履约、卡账及支付/退款引用；健康数据单独审批并加密分批；消息只保留必要偏好/退订和脱敏回执；商城只读引用从 MER 权威 API/事件取得。历史笼统同意不能推定为健康或营销授权，旧余额不能倒造 ledger 分录，手机号不能用于自动合并客户。

## Checkpoint 与幂等恢复

契约版本是 `db06-health-scrm-backfill-v1`。checkpoint 主键范围为 `(contract_version, tenant_id, site_id)`，至少保存：phase、revision、source fingerprint、水位对应的 opaque cursor、已完成批次数及处理/复制/隔离计数。实际 CheckpointStore 必须提供 compare-and-swap，禁止并发 worker 覆盖较新 revision。

每批先用稳定幂等键执行 shadow 效果，再 CAS 落 checkpoint。若进程在两步之间中断，恢复时会以同一 cursor 重新发出同一键，adapter 必须返回已完成结果而不能重复插入。该语义是 at-least-once 调用 + 幂等效果，不宣称分布式 exactly-once。cursor 不得含手机号、姓名、健康字段或其他明文直接标识。

源 schema、scope、水位、计数或金额摘要一旦变化，旧 checkpoint 必须拒绝续跑；需重新评审并使用新 contract version/新 checkpoint namespace。恢复先核对 checkpoint scope 与当前 tenant/site 完全相等。checkpoint 是恢复进度证据，不等同于数据已验收或已切换。

## 比对与路由门禁

- 金额使用精确 Decimal 汇总，并按 ISO 币种分别对比；禁止浮点容差或跨币种净额抵消。必要时由财务 owner 明确取整口径。
- 比较产物包含各逻辑数据集的行数、金额/币种差异摘要、source watermark、orphan FK count、tenant/site scope violation count 与质量状态，不导出 row payload。健康正文和身份原值不得写入日志或报告。
- 预约、服务卡、ledger、支付/退款、outbox/event 与审计关联都按相同 tenant/site 验证；site ID 只是范围键，不是授权结论。不存在父记录、跨站引用或 owner 不明均 fail closed。
- canary 必须引用字段映射/owner 审核、tenant/site 隔离复核、健康 owner 批准（涉及健康数据时）、备份恢复、双读签核和回滚演练结果。发现未解决 quarantine、金额/计数差、孤儿 FK 或 scope 越界时不切换。

## 回滚与保留策略

回滚只针对明确 tenant/site：关闭新 canonical 路由，恢复 legacy **只读**兼容路径，并保留 checkpoint、shadow 副本及审计摘要以供调查。回滚不物理删除或反向覆盖任何数据，不删除在途预约、资源锁历史、已发生履约、支付/退款结果或 append-only 服务账分录；不要盲目双写。已经发生的业务事实按预约取消/改期、支付退款、卡账冲正、权益撤销或客户通知等各自补偿流程处理，并保留责任人、原因与审批审计。

恢复后复核路由开关、legacy 可读状态、tenant/site 隔离、未完成预约与锁、ledger 分录重算、事件水位、退订传播和备份恢复证据。任一状态无法确认时保持新路由关闭并暂停扩大灰度。

## 执行状态

`domain/alembic/versions/db06_health_scrm_backfill.py` 是 schema-neutral 的 Alembic contract marker；upgrade/downgrade 不发 DDL，版本标记也不代表数据回填已运行。`domain/migrations/health_scrm_backfill/runner.py` 只定义阶段协议、门禁和 checkpoint 状态机。生产 adapter、持久 checkpoint 存储、人工批准、SQL/DDL、真实业务数据和线上路由均未实现/未使用。合成测试命令：

```sh
python3 -m unittest discover -s domain/migrations/health_scrm_backfill/tests -p 'test_*.py' -v
```
