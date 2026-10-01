# DB-07 合成 seed 数据字典与待确认项

本目录与 `../tenant_site/seed.json` 是 DB-07 的设计/合成 seed。它们只供标准库 Python/内存 SQLite 验证，不是生产数据或迁移脚本，不执行真实 DDL，也不连接应用数据库。`DEMO-PHX-01..09` 是稳定的技术幂等键，不是经业务确认的正式项目编码。

## 数据对象

| JSON / canonical 对象 | Seed 字段 | 约束与当前值 |
| --- | --- | --- |
| `plat_tenant` | `tenant_id`, `tenant_code`, `name`, `status` | `tenant-demo`；UUID 固定；`inactive`；合成租户，不启用业务。 |
| `plat_site` | `tenant_id`, `site_id`, `site_code`, `name`, `timezone`, `status` | 同租户下 `site-a` / `凤凰谷` 与 `site-b` / `第二站`；组合范围 `(tenant_id, site_id)`；时区留空，两个站点均 `inactive`。站名是逻辑演示标签，不是地址/位置描述。 |
| `svc_service_item`（DB-02 的 `svc_service_catalog` 逻辑映射） | `service_id`, `service_code`, `name`, `service_type`, `status` | 仅 site-a 有九个项目；名称逐字对齐客户原型和数据架构 §12；`service_type=null`、`status=inactive`。项目项按 `(tenant_id, site_id, service_code)` 唯一。 |
| `svc_service_version` | `service_version_id`, `service_id`, `version_no`, `status`, 规则/价格/时长/位置/资质/容量/现场要求等 | 每项 seed 一条 `version_no=1` 的 `draft / pending / unpublished` 版本；所有未确认业务字段为 `null`；版本按 `(tenant_id, site_id, service_id, version_no)` 唯一。已引用版本不得覆盖，变更另建版本。 |
| DB-07 fixture `svc_appointment.snapshot_json` | 项目名、版本 ID 及可选的已确认快照字段 | 仅测试冻结行为。预约快照保存当时值；导入新版本不回写历史快照。seed loader 不创建预约。 |

`approval_status`、`publication_status` 以及发布输入完整性检查是 DB-07 seed/fixture 门禁元数据，待 schema owner 评审如何映射到正式 schema；没有通过评审或批准前，不应执行任何生产变更。GOV-06 预约词汇按 `待确认 / 已确认 / 已完成 / 已取消`；该 seed 不生成预约状态。

## 待确认项清单

每个凤凰谷项目都需要责任人确认以下内容并形成经批准的新版本。当前均未提供，seed 不填默认值：

- 服务责任 owner、服务类型、正式服务编码、项目说明与健康数据 owner。
- 价格、币种、时长、适用条件/限制及对应的规则版本。
- 服务人员资格与核验责任；“3R专项康复疗愈”的专业资质和责任边界单独确认。
- 服务位置 ID、公开指引，以及房间/设备/人员角色等资源需求。
- 容量策略、可预约时段、提前期、缓冲、候补与安全限制。
- 准备事项、现场服务规则、取消规则、客户授权文本、SOP 和对应版本。
- 生效时间、审批人/审批记录、发布日期及站点开通状态。
- 两个 site 的实际时区；site-a/site-b 名称是否可作为正式展示名；site-b 是否继承任何受批准的目录配置。

未经明示批准的服务版本不可发布或预约。任一缺少审批、价格/币种、时长、适用规则、资格、位置、容量、准备/现场/取消规则或生效时间的版本均被发布门禁拒绝。网站点配置当前停用；名称 seed 不代表服务已经上线。

## 隔离与回滚说明

- 所有服务事实按 tenant/site 复合范围落库；九项目录只属于 `tenant-demo/site-a`。site-b 只创建空站点目录，不复制客户、资源、排班、预约、余额/账务、事件或健康明细。
- 同站、同租户的重导入若内容相同为无操作；同一稳定键的内容漂移会报冲突，需另建版本或人工处理，不会覆写既有事实。
- 仅可回滚 seed manifest 所有、且尚未被预约快照或其他合成夹具引用的行；有预约引用时整批回滚前置失败，不做部分删除。rollback 后 reapply 的 seed 行应与原始行完全相同。
- 内存 SQLite fixture 用合成占位行验证 site-b 对凤凰谷客户/资源/账务 scope 的拒绝。这不是客户、资源或账务数据，也不实现生产授权服务。
