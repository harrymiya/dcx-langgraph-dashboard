"""Service-note model contracts; sensitive note text is ciphertext only."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final


SERVICE_NOTE_STATUSES: Final = frozenset({"DRAFT", "SUBMITTED", "AMENDED", "RESTRICTED"})
MEDIA_STATUSES: Final = frozenset({"QUARANTINED", "AVAILABLE", "REVOKED", "EXPIRED"})


@dataclass(frozen=True)
class ServiceNote:
    tenant_id: str
    site_id: str
    service_note_id: str
    customer_id: str
    appointment_id: str
    author_staff_id: str
    note_ciphertext: bytes
    note_hash: str
    idempotency_key_hash: str
    occurred_at: datetime
    status: str = "SUBMITTED"
    work_order_id: str | None = None
    service_version_id: str | None = None
    note_version: int = 1
    amends_note_id: str | None = None

    def __post_init__(self) -> None:
        if self.status not in SERVICE_NOTE_STATUSES:
            raise ValueError(f"unsupported service note status: {self.status}")
        if not self.note_ciphertext:
            raise ValueError("service note content must be encrypted before persistence")
        if len(self.note_hash) < 32 or len(self.idempotency_key_hash) < 32:
            raise ValueError("service note hashes must be non-reversible digests")
        if self.note_version < 1:
            raise ValueError("note_version must be positive")


@dataclass(frozen=True)
class ServiceNoteMedia:
    tenant_id: str
    site_id: str
    media_id: str
    service_note_id: str
    object_ref_ciphertext: bytes
    object_hash: str
    mime_type: str
    byte_size: int
    status: str
    purpose_code: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.status not in MEDIA_STATUSES:
            raise ValueError(f"unsupported media status: {self.status}")
        if self.byte_size <= 0 or not self.object_ref_ciphertext:
            raise ValueError("media requires a private encrypted object reference and positive size")
        if len(self.object_hash) < 32:
            raise ValueError("media object hash must be non-reversible")
