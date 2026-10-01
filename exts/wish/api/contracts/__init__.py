"""Shared Wish API contract value objects; no HTTP framework dependencies."""

from .envelope import (
    API_VERSION,
    AuthorizationContext,
    Page,
    PageInfo,
    PageRequest,
    RequestMetadata,
    ResponseMeta,
    SuccessEnvelope,
    resolve_field_selection,
)
from .errors import (
    ERROR_HTTP_STATUS,
    RETRYABLE_ERROR_CODES,
    RETRY_AFTER_REQUIRED_CODES,
    ErrorCode,
    ErrorDetail,
    WishAPIError,
)

__all__ = [
    "API_VERSION",
    "AuthorizationContext",
    "ERROR_HTTP_STATUS",
    "ErrorCode",
    "ErrorDetail",
    "Page",
    "PageInfo",
    "PageRequest",
    "RequestMetadata",
    "RETRYABLE_ERROR_CODES",
    "RETRY_AFTER_REQUIRED_CODES",
    "ResponseMeta",
    "SuccessEnvelope",
    "WishAPIError",
    "resolve_field_selection",
]
