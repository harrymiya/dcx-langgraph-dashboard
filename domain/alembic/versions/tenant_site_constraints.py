from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence


# DB-02 contributes a canonical model, not a predecessor DDL revision. Keep this
# as an isolated Alembic base until a canonical schema-creation revision exists.
revision = "db03_tenant_site_constraints"
down_revision = None
branch_labels = ("canonical_scope",)
depends_on = None

MODEL_SCHEMA_VERSION = "db02-canonical-models-1.1.0"
CONSTRAINT_MANIFEST = json.loads(r'''{"entity_count":60,"entities":[{"name":"plat_tenant","entity_kind":"directory","tenant_site_required":false,"pk":["tenant_id"],"unique_keys":[["tenant_code"]],"fks":[]},{"name":"plat_site","entity_kind":"directory","tenant_site_required":true,"pk":["tenant_id","site_id"],"unique_keys":[["tenant_id","site_code"],["tenant_id","site_id"]],"fks":[{"columns":["tenant_id"],"ref_entity":"plat_tenant","ref_columns":["tenant_id"],"on_delete":"RESTRICT"}]},{"name":"plat_org_unit","entity_kind":"directory","tenant_site_required":false,"pk":["tenant_id","org_unit_id"],"unique_keys":[["tenant_id","parent_org_unit_id","org_code"]],"fks":[{"columns":["tenant_id"],"ref_entity":"plat_tenant","ref_columns":["tenant_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","parent_org_unit_id"],"ref_entity":"plat_org_unit","ref_columns":["tenant_id","org_unit_id"],"on_delete":"RESTRICT"}]},{"name":"plat_staff_identity","entity_kind":"identity_anchor","tenant_site_required":false,"pk":["tenant_id","staff_id"],"unique_keys":[["tenant_id","source_system","subject_hash"]],"fks":[{"columns":["tenant_id"],"ref_entity":"plat_tenant","ref_columns":["tenant_id"],"on_delete":"RESTRICT"}]},{"name":"plat_role_binding","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","binding_id"],"unique_keys":[["tenant_id","site_id","staff_id","role_code","scope_code","valid_from"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","staff_id"],"ref_entity":"plat_staff_identity","ref_columns":["tenant_id","staff_id"],"on_delete":"RESTRICT"}]},{"name":"crm_customer","entity_kind":"identity_anchor","tenant_site_required":false,"pk":["tenant_id","customer_id"],"unique_keys":[["tenant_id","customer_id"]],"fks":[{"columns":["tenant_id"],"ref_entity":"plat_tenant","ref_columns":["tenant_id"],"on_delete":"RESTRICT"}]},{"name":"crm_identity_map","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","identity_map_id"],"unique_keys":[["tenant_id","site_id","provider","external_key_hmac"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"}]},{"name":"crm_relationship","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","relationship_id"],"unique_keys":[["tenant_id","site_id","principal_customer_id","delegate_customer_id","relationship_type","valid_from"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","principal_customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","delegate_customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"}]},{"name":"crm_consent_record","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","consent_id"],"unique_keys":[["tenant_id","site_id","subject_customer_id","purpose_code","recipient_code","target_site_id","consent_version"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","subject_customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","grantor_customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"}]},{"name":"crm_consent_history","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","history_id"],"unique_keys":[["tenant_id","site_id","consent_id","sequence_no"]],"fks":[{"columns":["tenant_id","site_id","consent_id"],"ref_entity":"crm_consent_record","ref_columns":["tenant_id","site_id","consent_id"],"on_delete":"RESTRICT"}]},{"name":"crm_tag_definition","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","tag_id"],"unique_keys":[["tenant_id","site_id","tag_code","version_no"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"crm_customer_tag","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","customer_tag_id"],"unique_keys":[["tenant_id","site_id","customer_id","tag_id","source_ref_hash"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","tag_id"],"ref_entity":"crm_tag_definition","ref_columns":["tenant_id","site_id","tag_id"],"on_delete":"RESTRICT"}]},{"name":"crm_segment_definition","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","segment_id"],"unique_keys":[["tenant_id","site_id","segment_code","version_no"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"crm_segment_snapshot","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","snapshot_id"],"unique_keys":[["tenant_id","site_id","segment_id","definition_version","as_of"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","segment_id"],"ref_entity":"crm_segment_definition","ref_columns":["tenant_id","site_id","segment_id"],"on_delete":"RESTRICT"}]},{"name":"crm_attribution_touch","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","touch_id"],"unique_keys":[["tenant_id","site_id","channel","source_code","occurred_at","anonymous_key_hmac"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"}]},{"name":"crm_attribution_result","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","attribution_id"],"unique_keys":[["tenant_id","site_id","conversion_ref_hash","model_version","touch_id"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","touch_id"],"ref_entity":"crm_attribution_touch","ref_columns":["tenant_id","site_id","touch_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"}]},{"name":"hlth_health_record","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","health_record_id"],"unique_keys":[["tenant_id","site_id","customer_id","record_type","occurred_at","source_key"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","consent_id"],"ref_entity":"crm_consent_record","ref_columns":["tenant_id","site_id","consent_id"],"on_delete":"RESTRICT"}]},{"name":"hlth_record_revision","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","revision_id"],"unique_keys":[["tenant_id","site_id","health_record_id","revision_no"]],"fks":[{"columns":["tenant_id","site_id","health_record_id"],"ref_entity":"hlth_health_record","ref_columns":["tenant_id","site_id","health_record_id"],"on_delete":"RESTRICT"}]},{"name":"hlth_source_link","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","source_link_id"],"unique_keys":[["tenant_id","site_id","source_code","external_key_hmac"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","consent_id"],"ref_entity":"crm_consent_record","ref_columns":["tenant_id","site_id","consent_id"],"on_delete":"RESTRICT"}]},{"name":"svc_service_item","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","service_id"],"unique_keys":[["tenant_id","site_id","service_code"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"svc_service_version","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","service_version_id"],"unique_keys":[["tenant_id","site_id","service_id","version_no"]],"fks":[{"columns":["tenant_id","site_id","service_id"],"ref_entity":"svc_service_item","ref_columns":["tenant_id","site_id","service_id"],"on_delete":"RESTRICT"}]},{"name":"svc_resource","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","resource_id"],"unique_keys":[["tenant_id","site_id","resource_code"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"svc_employee_skill","entity_kind":"directory","tenant_site_required":false,"pk":["tenant_id","skill_id"],"unique_keys":[["tenant_id","skill_code"]],"fks":[{"columns":["tenant_id"],"ref_entity":"plat_tenant","ref_columns":["tenant_id"],"on_delete":"RESTRICT"}]},{"name":"svc_employee_skill_binding","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","binding_id"],"unique_keys":[["tenant_id","site_id","staff_id","skill_id","valid_from"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","staff_id"],"ref_entity":"plat_staff_identity","ref_columns":["tenant_id","staff_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","skill_id"],"ref_entity":"svc_employee_skill","ref_columns":["tenant_id","skill_id"],"on_delete":"RESTRICT"}]},{"name":"svc_shift","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","shift_id"],"unique_keys":[["tenant_id","site_id","staff_id","starts_at","ends_at"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","staff_id"],"ref_entity":"plat_staff_identity","ref_columns":["tenant_id","staff_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","resource_id"],"ref_entity":"svc_resource","ref_columns":["tenant_id","site_id","resource_id"],"on_delete":"RESTRICT"}]},{"name":"svc_appointment","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","appointment_id"],"unique_keys":[["tenant_id","idempotency_key"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","subject_customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","service_version_id"],"ref_entity":"svc_service_version","ref_columns":["tenant_id","site_id","service_version_id"],"on_delete":"RESTRICT"}]},{"name":"svc_appointment_history","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","history_id"],"unique_keys":[["tenant_id","site_id","appointment_id","row_version"]],"fks":[{"columns":["tenant_id","site_id","appointment_id"],"ref_entity":"svc_appointment","ref_columns":["tenant_id","site_id","appointment_id"],"on_delete":"RESTRICT"}]},{"name":"svc_resource_lock","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","lock_id"],"unique_keys":[["tenant_id","site_id","resource_id","slot_start_utc"]],"fks":[{"columns":["tenant_id","site_id","resource_id"],"ref_entity":"svc_resource","ref_columns":["tenant_id","site_id","resource_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","appointment_id"],"ref_entity":"svc_appointment","ref_columns":["tenant_id","site_id","appointment_id"],"on_delete":"RESTRICT"}]},{"name":"svc_work_order","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","work_order_id"],"unique_keys":[["tenant_id","site_id","appointment_id"]],"fks":[{"columns":["tenant_id","site_id","appointment_id"],"ref_entity":"svc_appointment","ref_columns":["tenant_id","site_id","appointment_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","service_version_id"],"ref_entity":"svc_service_version","ref_columns":["tenant_id","site_id","service_version_id"],"on_delete":"RESTRICT"}]},{"name":"svc_work_order_history","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","history_id"],"unique_keys":[["tenant_id","site_id","work_order_id","row_version"]],"fks":[{"columns":["tenant_id","site_id","work_order_id"],"ref_entity":"svc_work_order","ref_columns":["tenant_id","site_id","work_order_id"],"on_delete":"RESTRICT"}]},{"name":"svc_sop_definition","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","sop_id"],"unique_keys":[["tenant_id","site_id","sop_code"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"svc_sop_version","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","sop_version_id"],"unique_keys":[["tenant_id","site_id","sop_id","version_no"]],"fks":[{"columns":["tenant_id","site_id","sop_id"],"ref_entity":"svc_sop_definition","ref_columns":["tenant_id","site_id","sop_id"],"on_delete":"RESTRICT"}]},{"name":"svc_sop_execution","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","execution_id"],"unique_keys":[["tenant_id","site_id","work_order_id","sop_version_id","step_code"]],"fks":[{"columns":["tenant_id","site_id","work_order_id"],"ref_entity":"svc_work_order","ref_columns":["tenant_id","site_id","work_order_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","sop_version_id"],"ref_entity":"svc_sop_version","ref_columns":["tenant_id","site_id","sop_version_id"],"on_delete":"RESTRICT"}]},{"name":"svc_followup_task","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","followup_id"],"unique_keys":[["tenant_id","site_id","source_event_id","customer_id","task_type"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","appointment_id"],"ref_entity":"svc_appointment","ref_columns":["tenant_id","site_id","appointment_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","staff_id"],"ref_entity":"plat_staff_identity","ref_columns":["tenant_id","staff_id"],"on_delete":"RESTRICT"}]},{"name":"svc_followup_result","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","result_id"],"unique_keys":[["tenant_id","site_id","followup_id","result_no"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","followup_id"],"ref_entity":"svc_followup_task","ref_columns":["tenant_id","site_id","followup_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","staff_id"],"ref_entity":"plat_staff_identity","ref_columns":["tenant_id","staff_id"],"on_delete":"RESTRICT"}]},{"name":"fin_payment","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","payment_id"],"unique_keys":[["tenant_id","idempotency_key_hash"],["tenant_id","provider_code","provider_event_id"]],"fks":[{"columns":["tenant_id","site_id","appointment_id"],"ref_entity":"svc_appointment","ref_columns":["tenant_id","site_id","appointment_id"],"on_delete":"RESTRICT"}]},{"name":"fin_refund","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","refund_id"],"unique_keys":[["tenant_id","refund_key_hash"],["tenant_id","provider_code","provider_event_id"]],"fks":[{"columns":["tenant_id","site_id","payment_id"],"ref_entity":"fin_payment","ref_columns":["tenant_id","site_id","payment_id"],"on_delete":"RESTRICT"}]},{"name":"fin_transaction_history","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","history_id"],"unique_keys":[["tenant_id","site_id","provider_code","provider_event_hash"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"fin_service_card","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","card_id"],"unique_keys":[["tenant_id","site_id","card_number_hmac"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"}]},{"name":"fin_service_card_ledger","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","ledger_entry_id"],"unique_keys":[["tenant_id","site_id","idempotency_key_hash"],["tenant_id","site_id","source_type","source_id","entry_type"]],"fks":[{"columns":["tenant_id","site_id","card_id"],"ref_entity":"fin_service_card","ref_columns":["tenant_id","site_id","card_id"],"on_delete":"RESTRICT"}]},{"name":"fin_commission_rule","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","rule_id"],"unique_keys":[["tenant_id","site_id","channel_code","version_no"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"fin_commission_batch","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","batch_id"],"unique_keys":[["tenant_id","site_id","period_start","period_end","channel_code"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","rule_id"],"ref_entity":"fin_commission_rule","ref_columns":["tenant_id","site_id","rule_id"],"on_delete":"RESTRICT"}]},{"name":"fin_commission_entry","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","entry_id"],"unique_keys":[["tenant_id","site_id","appointment_id","staff_id","rule_version"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","batch_id"],"ref_entity":"fin_commission_batch","ref_columns":["tenant_id","site_id","batch_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","appointment_id"],"ref_entity":"svc_appointment","ref_columns":["tenant_id","site_id","appointment_id"],"on_delete":"RESTRICT"}]},{"name":"msg_template","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","template_id"],"unique_keys":[["tenant_id","site_id","template_code","channel","version_no"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"msg_policy","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","policy_id"],"unique_keys":[["tenant_id","site_id","purpose_code","channel","version_no"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"msg_preference","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","preference_id"],"unique_keys":[["tenant_id","site_id","customer_id","channel"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"}]},{"name":"msg_send","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","send_id"],"unique_keys":[["tenant_id","idempotency_key_hash"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","template_id"],"ref_entity":"msg_template","ref_columns":["tenant_id","site_id","template_id"],"on_delete":"RESTRICT"}]},{"name":"msg_send_attempt","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","attempt_id"],"unique_keys":[["tenant_id","site_id","send_id","attempt_no"]],"fks":[{"columns":["tenant_id","site_id","send_id"],"ref_entity":"msg_send","ref_columns":["tenant_id","site_id","send_id"],"on_delete":"RESTRICT"}]},{"name":"msg_failure_queue","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","failure_id"],"unique_keys":[["tenant_id","site_id","send_id","failure_code"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","send_id"],"ref_entity":"msg_send","ref_columns":["tenant_id","site_id","send_id"],"on_delete":"RESTRICT"}]},{"name":"msg_unsubscribe","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","unsubscribe_id"],"unique_keys":[["tenant_id","site_id","customer_id","channel","purpose_code"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"}]},{"name":"mkt_order_ref","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","order_ref_id"],"unique_keys":[["tenant_id","site_id","mer_order_id_hash"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"}]},{"name":"mkt_product_benefit_map","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","mapping_id"],"unique_keys":[["tenant_id","site_id","external_sku_hash","version_no"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","site_id","service_version_id"],"ref_entity":"svc_service_version","ref_columns":["tenant_id","site_id","service_version_id"],"on_delete":"RESTRICT"}]},{"name":"evt_outbox","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","event_id"],"unique_keys":[["tenant_id","site_id","producer","idempotency_key"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"evt_inbox","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","inbox_id"],"unique_keys":[["tenant_id","site_id","producer","event_id","consumer"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"evt_dead_letter","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","dead_letter_id"],"unique_keys":[["tenant_id","site_id","event_id","consumer"]],"fks":[{"columns":["tenant_id","site_id","inbox_id"],"ref_entity":"evt_inbox","ref_columns":["tenant_id","site_id","inbox_id"],"on_delete":"RESTRICT"}]},{"name":"aud_audit_event","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","audit_id"],"unique_keys":[["tenant_id","site_id","request_id","action_code","occurred_at"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"aud_access_log","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","access_id"],"unique_keys":[["tenant_id","site_id","actor_id","request_id"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","subject_customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"}]},{"name":"aud_export_job","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","export_id"],"unique_keys":[["tenant_id","site_id","requester_id","idempotency_key_hash"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"rpt_daily_metrics","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","metric_id"],"unique_keys":[["tenant_id","site_id","metric_code","metric_date","dimension_hash"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"}]},{"name":"rpt_customer_service_summary","entity_kind":"business_fact","tenant_site_required":true,"pk":["tenant_id","site_id","summary_id"],"unique_keys":[["tenant_id","site_id","customer_id"]],"fks":[{"columns":["tenant_id","site_id"],"ref_entity":"plat_site","ref_columns":["tenant_id","site_id"],"on_delete":"RESTRICT"},{"columns":["tenant_id","customer_id"],"ref_entity":"crm_customer","ref_columns":["tenant_id","customer_id"],"on_delete":"RESTRICT"}]}]}''')


# These six constraints intentionally serialize idempotency/provider event keys
# tenant-wide. All site-local business codes and references remain site-scoped.
TENANT_WIDE_UNIQUE_KEYS = {
    "svc_appointment": (("tenant_id", "idempotency_key"),),
    "fin_payment": (
        ("tenant_id", "idempotency_key_hash"),
        ("tenant_id", "provider_code", "provider_event_id"),
    ),
    "fin_refund": (
        ("tenant_id", "refund_key_hash"),
        ("tenant_id", "provider_code", "provider_event_id"),
    ),
    "msg_send": (("tenant_id", "idempotency_key_hash"),),
}

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class MigrationPreconditionError(RuntimeError):
    """The canonical schema or its data is not safe for this migration."""


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    entities = manifest.get("entities", ())
    by_name = {entity["name"]: entity for entity in entities}
    if len(by_name) != manifest.get("entity_count"):
        raise ValueError("DB-02 manifest entity count or names are inconsistent")

    for entity in entities:
        name = entity["name"]
        primary_key = tuple(entity["pk"])
        if not primary_key:
            raise ValueError(f"{name} has no primary key")
        if entity["tenant_site_required"]:
            if not {"tenant_id", "site_id"} <= set(primary_key):
                raise ValueError(f"{name} requires tenant/site in its primary key")

        if entity["entity_kind"] == "business_fact":
            if not {"tenant_id", "site_id"} <= set(primary_key):
                raise ValueError(f"business fact {name} is not tenant/site keyed")
            scoped_fk = any(
                by_name[fk["ref_entity"]]["tenant_site_required"]
                and {"tenant_id", "site_id"} <= set(fk["columns"])
                and {"tenant_id", "site_id"} <= set(fk["ref_columns"])
                for fk in entity["fks"]
            )
            if not scoped_fk:
                raise ValueError(f"business fact {name} lacks a composite tenant/site FK")
            allowed_wide = set(TENANT_WIDE_UNIQUE_KEYS.get(name, ()))
            for key in entity["unique_keys"]:
                key_tuple = tuple(key)
                if "tenant_id" not in key_tuple:
                    raise ValueError(f"{name} has an unscoped unique key")
                if "site_id" not in key_tuple and key_tuple not in allowed_wide:
                    raise ValueError(f"{name} has a site-local unique key without site_id")

        for fk in entity["fks"]:
            parent = by_name.get(fk["ref_entity"])
            if parent is None:
                raise ValueError(f"{name} references missing entity {fk['ref_entity']}")
            if len(fk["columns"]) != len(fk["ref_columns"]):
                raise ValueError(f"{name} has an FK arity mismatch")
            if fk["on_delete"] != "RESTRICT":
                raise ValueError(f"{name} FK delete action must be RESTRICT")
            if parent["tenant_site_required"] and not (
                {"tenant_id", "site_id"} <= set(fk["columns"])
                and {"tenant_id", "site_id"} <= set(fk["ref_columns"])
            ):
                raise ValueError(f"{name} -> {parent['name']} drops tenant/site scope")


_validate_manifest(CONSTRAINT_MANIFEST)


def _safe_name(*parts: str) -> str:
    name = "_".join(parts)
    if len(name) > 60 or not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"unsafe or overlong database identifier: {name}")
    return name


def _unique_name(table: str, ordinal: int) -> str:
    return _safe_name("db03_uq", table, str(ordinal))


def _foreign_key_name(table: str, ordinal: int) -> str:
    return _safe_name("db03_fk", table, str(ordinal))


def _index_name(table: str, ordinal: int) -> str:
    return _safe_name("db03_ix", table, str(ordinal))


def _planned_indexes(entity: Mapping[str, Any]) -> list[tuple[str, ...]]:
    """Return FK indexes not already covered by the entity's PK/unique keys."""
    covered = [tuple(entity["pk"])]
    covered.extend(tuple(key) for key in entity["unique_keys"])
    result: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for fk in entity["fks"]:
        columns = tuple(fk["columns"])
        if columns in seen:
            continue
        seen.add(columns)
        if any(index[: len(columns)] == columns for index in covered):
            continue
        result.append(columns)
    return result


def _load_runtime(
    operations: Any | None,
    inspector: Any | None,
) -> tuple[Any, Any, Any]:
    if operations is None:
        from alembic import op as operations
    bind = operations.get_bind()
    if inspector is None:
        import sqlalchemy as sa

        inspector = sa.inspect(bind)
    return operations, bind, inspector


def _quote(bind: Any, identifier: str) -> str:
    if not _IDENTIFIER.fullmatch(identifier):
        raise MigrationPreconditionError("unsafe database identifier in manifest")
    dialect = getattr(bind, "dialect", None)
    preparer = getattr(dialect, "identifier_preparer", None)
    if preparer is None:
        return identifier
    return preparer.quote(identifier)


def _execute(bind: Any, sql: str) -> Any:
    import sqlalchemy as sa

    return bind.execute(sa.text(sql))


def _first_row(result: Any) -> Any | None:
    first = getattr(result, "first", None)
    if callable(first):
        return first()
    return next(iter(result), None)


def _column_names(columns: Sequence[Mapping[str, Any]]) -> set[str]:
    return {column["name"] for column in columns}


def _pk_columns(inspector: Any, table: str) -> tuple[str, ...]:
    return tuple((inspector.get_pk_constraint(table) or {}).get("constrained_columns") or ())


def _unique_constraints(inspector: Any, table: str) -> list[Mapping[str, Any]]:
    return list(inspector.get_unique_constraints(table) or ())


def _indexes(inspector: Any, table: str) -> list[Mapping[str, Any]]:
    return list(inspector.get_indexes(table) or ())


def _has_unique(
    inspector: Any,
    table: str,
    columns: tuple[str, ...],
    entity: Mapping[str, Any],
) -> bool:
    if _pk_columns(inspector, table) == columns:
        return True
    if any(tuple(item.get("column_names") or ()) == columns for item in _unique_constraints(inspector, table)):
        return True
    return any(
        item.get("unique") and tuple(item.get("column_names") or ()) == columns
        for item in _indexes(inspector, table)
    )


def _has_index_prefix(inspector: Any, table: str, columns: tuple[str, ...]) -> bool:
    if _pk_columns(inspector, table)[: len(columns)] == columns:
        return True
    if any(
        tuple(item.get("column_names") or ())[: len(columns)] == columns
        for item in _unique_constraints(inspector, table)
    ):
        return True
    return any(
        tuple(item.get("column_names") or ())[: len(columns)] == columns
        for item in _indexes(inspector, table)
    )


def _matching_fk(
    inspector: Any,
    table: str,
    fk: Mapping[str, Any],
) -> bool:
    source = tuple(fk["columns"])
    target = fk["ref_entity"]
    target_columns = tuple(fk["ref_columns"])
    for current in inspector.get_foreign_keys(table) or ():
        current_source = tuple(current.get("constrained_columns") or ())
        current_target = current.get("referred_table")
        current_target_columns = tuple(current.get("referred_columns") or ())
        if current_source != source:
            continue
        options = current.get("options") or {}
        ondelete = (options.get("ondelete") or current.get("ondelete") or "").upper()
        onupdate = (options.get("onupdate") or current.get("onupdate") or "").upper()
        if (
            current_target == target
            and current_target_columns == target_columns
            and ondelete == "RESTRICT"
            and onupdate == "RESTRICT"
        ):
            return True
        raise MigrationPreconditionError(
            f"{table} already has a conflicting FK over {','.join(source)}"
        )
    return False


def _check_reserved_name(
    existing: Sequence[Mapping[str, Any]],
    desired_name: str,
    desired_columns: tuple[str, ...],
    table: str,
    kind: str,
) -> None:
    for item in existing:
        if item.get("name") != desired_name:
            continue
        columns = tuple(item.get("column_names") or item.get("constrained_columns") or ())
        if columns != desired_columns:
            raise MigrationPreconditionError(
                f"{table} has a conflicting reserved DB-03 {kind} name"
            )


def _key_conflict_query(bind: Any, table: str, columns: tuple[str, ...]) -> str:
    quoted_table = _quote(bind, table)
    quoted_columns = ", ".join(_quote(bind, column) for column in columns)
    return (
        f"SELECT 1 FROM {quoted_table} GROUP BY {quoted_columns} "
        "HAVING COUNT(*) > 1 LIMIT 1"
    )


def _fk_orphan_query(bind: Any, table: str, fk: Mapping[str, Any]) -> str:
    child_alias = _quote(bind, "db03_child")
    parent_alias = _quote(bind, "db03_parent")
    child_table = _quote(bind, table)
    parent_table = _quote(bind, fk["ref_entity"])
    joins = " AND ".join(
        f"{child_alias}.{_quote(bind, child)} = {parent_alias}.{_quote(bind, parent)}"
        for child, parent in zip(fk["columns"], fk["ref_columns"])
    )
    present = " AND ".join(
        f"{child_alias}.{_quote(bind, column)} IS NOT NULL" for column in fk["columns"]
    )
    missing_parent = f"{parent_alias}.{_quote(bind, fk['ref_columns'][0])} IS NULL"
    return (
        f"SELECT 1 FROM {child_table} AS {child_alias} "
        f"LEFT JOIN {parent_table} AS {parent_alias} ON {joins} "
        f"WHERE {present} AND {missing_parent} LIMIT 1"
    )


def _preflight(bind: Any, inspector: Any) -> None:
    manifest = CONSTRAINT_MANIFEST
    entities = manifest["entities"]
    by_name = {entity["name"]: entity for entity in entities}
    available = set(inspector.get_table_names())
    missing_tables = sorted(set(by_name) - available)
    if missing_tables:
        raise MigrationPreconditionError(
            "canonical schema is incomplete; missing tables: " + ", ".join(missing_tables)
        )

    columns_by_table: dict[str, set[str]] = {}
    for entity in entities:
        table = entity["name"]
        columns = inspector.get_columns(table) or ()
        names = _column_names(columns)
        columns_by_table[table] = names
        required = set(entity["pk"])
        required.update(column for key in entity["unique_keys"] for column in key)
        required.update(column for fk in entity["fks"] for column in fk["columns"])
        if entity["tenant_site_required"]:
            required.update(("tenant_id", "site_id"))
        missing_columns = sorted(required - names)
        if missing_columns:
            raise MigrationPreconditionError(
                f"{table} is missing required columns: {', '.join(missing_columns)}"
            )
        actual_pk = _pk_columns(inspector, table)
        if actual_pk != tuple(entity["pk"]):
            raise MigrationPreconditionError(
                f"{table} primary key does not match the DB-02 scoped key"
            )
        if entity["tenant_site_required"]:
            nullable = {
                column["name"]
                for column in columns
                if column["name"] in {"tenant_id", "site_id"} and column.get("nullable", True)
            }
            if nullable:
                raise MigrationPreconditionError(
                    f"{table} has nullable scope columns: {', '.join(sorted(nullable))}"
                )

    # Validate every unique key and relationship before emitting the first DDL.
    for entity in entities:
        table = entity["name"]
        unique_constraints = _unique_constraints(inspector, table)
        indexes = _indexes(inspector, table)
        for ordinal, key in enumerate(entity["unique_keys"]):
            columns = tuple(key)
            name = _unique_name(table, ordinal)
            _check_reserved_name(
                unique_constraints + indexes, name, columns, table, "unique constraint"
            )
            if not _has_unique(inspector, table, columns, entity):
                if _first_row(_execute(bind, _key_conflict_query(bind, table, columns))) is not None:
                    raise MigrationPreconditionError(
                        f"{table} contains duplicate rows for a required composite unique key"
                    )

        foreign_keys = list(inspector.get_foreign_keys(table) or ())
        for ordinal, fk in enumerate(entity["fks"]):
            parent = by_name[fk["ref_entity"]]
            parent_key = tuple(fk["ref_columns"])
            parent_keys = {tuple(parent["pk"])}
            parent_keys.update(tuple(key) for key in parent["unique_keys"])
            parent_keys.update(
                tuple(item.get("column_names") or ())
                for item in _unique_constraints(inspector, fk["ref_entity"])
            )
            parent_keys.update(
                tuple(item.get("column_names") or ())
                for item in _indexes(inspector, fk["ref_entity"])
                if item.get("unique")
            )
            if parent_key not in parent_keys:
                raise MigrationPreconditionError(
                    f"{table} FK target {fk['ref_entity']} is not a declared unique key"
                )
            name = _foreign_key_name(table, ordinal)
            _check_reserved_name(foreign_keys, name, tuple(fk["columns"]), table, "FK")
            if not _matching_fk(inspector, table, fk):
                if _first_row(_execute(bind, _fk_orphan_query(bind, table, fk))) is not None:
                    raise MigrationPreconditionError(
                        f"{table} contains rows with a missing same-scope FK target"
                    )


def _apply_upgrade(operations: Any, inspector: Any) -> None:
    # This list is deliberately materialized before DDL so a preflight failure
    # cannot leave a partially constrained schema.
    for entity in CONSTRAINT_MANIFEST["entities"]:
        table = entity["name"]
        for ordinal, key in enumerate(entity["unique_keys"]):
            columns = tuple(key)
            if not _has_unique(inspector, table, columns, entity):
                operations.create_unique_constraint(
                    _unique_name(table, ordinal), table, list(columns)
                )

    for entity in CONSTRAINT_MANIFEST["entities"]:
        table = entity["name"]
        existing_indexes = _indexes(inspector, table)
        for ordinal, columns in enumerate(_planned_indexes(entity)):
            if not _has_index_prefix(inspector, table, columns):
                _check_reserved_name(
                    existing_indexes, _index_name(table, ordinal), columns, table, "index"
                )
                operations.create_index(_index_name(table, ordinal), table, list(columns))

    for entity in CONSTRAINT_MANIFEST["entities"]:
        table = entity["name"]
        for ordinal, fk in enumerate(entity["fks"]):
            if not _matching_fk(inspector, table, fk):
                operations.create_foreign_key(
                    _foreign_key_name(table, ordinal),
                    table,
                    fk["ref_entity"],
                    list(fk["columns"]),
                    list(fk["ref_columns"]),
                    ondelete="RESTRICT",
                    onupdate="RESTRICT",
                )


def upgrade(
    *,
    operations: Any | None = None,
    inspector: Any | None = None,
) -> None:
    operations, bind, inspector = _load_runtime(operations, inspector)
    _preflight(bind, inspector)
    _apply_upgrade(operations, inspector)


def _preflight_downgrade(inspector: Any) -> None:
    """Validate every revision-owned object before dropping the first one."""
    for entity in CONSTRAINT_MANIFEST["entities"]:
        table = entity["name"]
        current = inspector.get_foreign_keys(table) or ()
        for ordinal, fk in enumerate(entity["fks"]):
            name = _foreign_key_name(table, ordinal)
            found = next((item for item in current if item.get("name") == name), None)
            if found is not None and (
                tuple(found.get("constrained_columns") or ()) != tuple(fk["columns"])
                or found.get("referred_table") != fk["ref_entity"]
                or tuple(found.get("referred_columns") or ()) != tuple(fk["ref_columns"])
            ):
                raise MigrationPreconditionError(
                    f"{table} has a conflicting reserved DB-03 FK name"
                )

        current = inspector.get_indexes(table) or ()
        for ordinal, columns in enumerate(_planned_indexes(entity)):
            name = _index_name(table, ordinal)
            found = next((item for item in current if item.get("name") == name), None)
            if found is not None and tuple(found.get("column_names") or ()) != columns:
                raise MigrationPreconditionError(
                    f"{table} has a conflicting reserved DB-03 index name"
                )

        current = inspector.get_unique_constraints(table) or ()
        for ordinal, key in enumerate(entity["unique_keys"]):
            name = _unique_name(table, ordinal)
            found = next((item for item in current if item.get("name") == name), None)
            if found is not None and tuple(found.get("column_names") or ()) != tuple(key):
                raise MigrationPreconditionError(
                    f"{table} has a conflicting reserved DB-03 unique name"
                )


def downgrade(
    *,
    operations: Any | None = None,
    inspector: Any | None = None,
) -> None:
    operations, _, inspector = _load_runtime(operations, inspector)

    # Drop only objects carrying this revision's reserved names. Existing
    # equivalent constraints owned by earlier revisions remain untouched.
    # Check all names before the first drop so a conflict cannot leave a
    # partially rolled-back schema.
    _preflight_downgrade(inspector)

    for entity in CONSTRAINT_MANIFEST["entities"]:
        table = entity["name"]
        current = inspector.get_foreign_keys(table) or ()
        for ordinal, fk in reversed(list(enumerate(entity["fks"]))):
            name = _foreign_key_name(table, ordinal)
            found = next((item for item in current if item.get("name") == name), None)
            if found is not None:
                operations.drop_constraint(name, table, type_="foreignkey")

    for entity in CONSTRAINT_MANIFEST["entities"]:
        table = entity["name"]
        current = _indexes(inspector, table)
        for ordinal, columns in reversed(list(enumerate(_planned_indexes(entity)))):
            name = _index_name(table, ordinal)
            found = next((item for item in current if item.get("name") == name), None)
            if found is not None:
                operations.drop_index(name, table_name=table)

    for entity in CONSTRAINT_MANIFEST["entities"]:
        table = entity["name"]
        current = _unique_constraints(inspector, table)
        for ordinal, key in reversed(list(enumerate(entity["unique_keys"]))):
            name = _unique_name(table, ordinal)
            found = next((item for item in current if item.get("name") == name), None)
            if found is not None:
                operations.drop_constraint(name, table, type_="unique")
