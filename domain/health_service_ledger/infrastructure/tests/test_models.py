from __future__ import annotations

from datetime import datetime, timezone
import unittest

from domain.health_service_ledger.infrastructure.models import ServiceNote, ServiceNoteMedia


class ServiceNoteModelTests(unittest.TestCase):
    def test_note_requires_ciphertext_and_versioned_hashes(self) -> None:
        note = ServiceNote(
            tenant_id="tenant-a", site_id="site-a", service_note_id="note-a",
            customer_id="customer-a", appointment_id="appointment-a",
            author_staff_id="staff-a", note_ciphertext=b"encrypted-payload",
            note_hash="h" * 64, idempotency_key_hash="i" * 64,
            occurred_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        )
        self.assertEqual("SUBMITTED", note.status)
        with self.assertRaises(ValueError):
            ServiceNote(
                tenant_id="tenant-a", site_id="site-a", service_note_id="note-b",
                customer_id="customer-a", appointment_id="appointment-a",
                author_staff_id="staff-a", note_ciphertext=b"", note_hash="h" * 64,
                idempotency_key_hash="i" * 64,
                occurred_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            )

    def test_media_requires_private_reference_and_positive_size(self) -> None:
        media = ServiceNoteMedia(
            tenant_id="tenant-a", site_id="site-a", media_id="media-a",
            service_note_id="note-a", object_ref_ciphertext=b"private-object-ref",
            object_hash="o" * 64, mime_type="image/jpeg", byte_size=120,
            status="QUARANTINED", purpose_code="SERVICE_EVIDENCE",
            created_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(120, media.byte_size)
        with self.assertRaises(ValueError):
            ServiceNoteMedia(
                tenant_id="tenant-a", site_id="site-a", media_id="media-b",
                service_note_id="note-a", object_ref_ciphertext=b"ref",
                object_hash="o" * 64, mime_type="image/jpeg", byte_size=0,
                status="AVAILABLE", purpose_code="SERVICE_EVIDENCE",
                created_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
