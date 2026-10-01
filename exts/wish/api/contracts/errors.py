"""Stable Wish API v1 error vocabulary and safe response envelope helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Iterable
import re

try:  # Support both package imports and direct execution from this directory.
    from .envelope import ResponseMeta
except ImportError:  # pragma: no cover - exercised by direct script execution
    from envelope import ResponseMeta


class ErrorCode(str, Enum):
    BAD_REQUEST = "BAD_REQUEST"
    API_VERSION_MISMATCH = "API_VERSION_MISMATCH"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    FILTER_NOT_ALLOWED = "FILTER_NOT_ALLOWED"
    FIELD_NOT_ALLOWED = "FIELD_NOT_ALLOWED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    TOKEN_AUDIENCE_INVALID = "TOKEN_AUDIENCE_INVALID"
    SCOPE_DENIED = "SCOPE_DENIED"
    FIELD_SCOPE_DENIED = "FIELD_SCOPE_DENIED"
    SITE_SCOPE_DENIED = "SITE_SCOPE_DENIED"
    CROSS_SITE_REFERENCE_DENIED = "CROSS_SITE_REFERENCE_DENIED"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    RELATIONSHIP_INVALID = "RELATIONSHIP_INVALID"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    RESOURCE_SLOT_CONFLICT = "RESOURCE_SLOT_CONFLICT"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    PAYMENT_STATUS_UNKNOWN = "PAYMENT_STATUS_UNKNOWN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ERROR_HTTP_STATUS = MappingProxyType(
    {
        ErrorCode.BAD_REQUEST: 400,
        ErrorCode.API_VERSION_MISMATCH: 400,
        ErrorCode.FILTER_NOT_ALLOWED: 400,
        ErrorCode.FIELD_NOT_ALLOWED: 400,
        ErrorCode.IDEMPOTENCY_KEY_REQUIRED: 400,
        ErrorCode.VALIDATION_FAILED: 422,
        ErrorCode.AUTH_REQUIRED: 401,
        ErrorCode.TOKEN_AUDIENCE_INVALID: 401,
        ErrorCode.SCOPE_DENIED: 403,
        ErrorCode.FIELD_SCOPE_DENIED: 403,
        ErrorCode.SITE_SCOPE_DENIED: 403,
        ErrorCode.CROSS_SITE_REFERENCE_DENIED: 403,
        ErrorCode.CONSENT_REQUIRED: 403,
        ErrorCode.RELATIONSHIP_INVALID: 403,
        ErrorCode.RESOURCE_NOT_FOUND: 404,
        ErrorCode.IDEMPOTENCY_CONFLICT: 409,
        ErrorCode.VERSION_CONFLICT: 409,
        ErrorCode.RESOURCE_SLOT_CONFLICT: 409,
        ErrorCode.INVALID_STATE_TRANSITION: 409,
        ErrorCode.RATE_LIMITED: 429,
        ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
        ErrorCode.PAYMENT_STATUS_UNKNOWN: 503,
        ErrorCode.INTERNAL_ERROR: 500,
    }
)

RETRYABLE_ERROR_CODES = frozenset(
    {ErrorCode.RATE_LIMITED, ErrorCode.DEPENDENCY_UNAVAILABLE}
)
RETRY_AFTER_REQUIRED_CODES = frozenset({ErrorCode.RATE_LIMITED})
_SAFE_FIELD = re.compile(r"\A[A-Za-z][A-Za-z0-9.\[\]_-]{0,127}\Z")


@dataclass(frozen=True)
class ErrorDetail:
    """Safe validation detail: field path and reason only, never rejected value."""

    field: str
    code: str
    message: str

    def __post_init__(self) -> None:
        if not _SAFE_FIELD.fullmatch(self.field):
            raise ValueError("error detail field must be a safe field path")
        if not self.code or len(self.code) > 64:
            raise ValueError("error detail code is required and must be at most 64 characters")
        _validate_safe_message(self.message)

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


def _validate_safe_message(message: str) -> None:
    if not isinstance(message, str) or not message.strip() or len(message) > 240:
        raise ValueError("error message must be a non-empty safe message of at most 240 characters")
    if any(ord(character) < 32 for character in message):
        raise ValueError("error message cannot contain control characters")


class WishAPIError(Exception):
    """A public, stable API error without backend exception details."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
        details: Iterable[ErrorDetail] = (),
    ) -> None:
        if not isinstance(code, ErrorCode):
            raise TypeError("code must be a stable ErrorCode")
        _validate_safe_message(message)
        if retryable and code not in RETRYABLE_ERROR_CODES:
            raise ValueError(f"{code.value} is not a retryable error code")
        if code in RETRY_AFTER_REQUIRED_CODES and not retryable:
            raise ValueError(f"{code.value} responses must set retryable=true")
        if code in RETRY_AFTER_REQUIRED_CODES and retry_after_seconds is None:
            raise ValueError(f"{code.value} responses must include retry_after_seconds")
        if retry_after_seconds is not None:
            if (
                isinstance(retry_after_seconds, bool)
                or not isinstance(retry_after_seconds, int)
                or retry_after_seconds <= 0
            ):
                raise ValueError("retry_after_seconds must be a positive integer")
            if not retryable:
                raise ValueError("retry_after_seconds is only valid when retryable=true")
        self.code = code
        self.message = message.strip()
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.details = tuple(details)
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        return ERROR_HTTP_STATUS[self.code]

    def to_error_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "retryAfterSeconds": self.retry_after_seconds,
            "details": [detail.to_dict() for detail in self.details],
        }

    def to_envelope(self, meta: ResponseMeta) -> dict[str, object]:
        return {"data": None, "meta": meta.to_dict(), "error": self.to_error_dict()}
