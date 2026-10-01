from __future__ import annotations

from datetime import datetime, timezone
import unittest

from domain.scrm.infrastructure.models import (
    CONTACT_PURPOSES,
    FOLLOWUP_RESULT_TABLE,
    FOLLOWUP_TASK_TABLE,
    CustomerContactLog,
    FollowupTask,
)


class ScrmModelTests(unittest.TestCase):
    def test_followup_alias_uses_existing_canonical_service_table(self) -> None:
        self.assertEqual("svc_followup_task", FOLLOWUP_TASK_TABLE)
        self.assertEqual("svc_followup_result", FOLLOWUP_RESULT_TABLE)
        task = FollowupTask(
            tenant_id="tenant-a", site_id="site-a", followup_id="task-a",
            customer_id="customer-a", task_type="POST_SERVICE", status="OPEN",
            due_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            plan_id="plan-a", plan_version=2, plan_day_offset=3, staff_id="staff-a",
        )
        self.assertEqual("staff-a", task.staff_id)
        with self.assertRaises(ValueError):
            FollowupTask(
                tenant_id="tenant-a", site_id="site-a", followup_id="task-b",
                customer_id="customer-a", task_type="POST_SERVICE", status="UNKNOWN",
                due_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            )

    def test_contact_log_purpose_is_explicit_and_never_implicitly_marketing(self) -> None:
        self.assertEqual({"SERVICE_FOLLOWUP", "CUSTOMER_SUPPORT"}, set(CONTACT_PURPOSES))
        with self.assertRaises(ValueError):
            CustomerContactLog(
                tenant_id="tenant-a", site_id="site-a", contact_log_id="contact-a",
                customer_id="customer-a", staff_id="staff-a", purpose="MARKETING",
                channel="PHONE", result_code="REACHED",
                occurred_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
