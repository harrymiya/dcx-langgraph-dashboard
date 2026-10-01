"""Dependency-free Wish API v1 envelope and request context contracts.

These value objects describe the boundary shared by Wish adapters and
application services.  They do not implement HTTP handling or authorization.
Only the Wish API/application boundary may populate ``AuthorizationContext``
after resolving trusted identity, tenant/site, relationship, purpose, consent,
and field-scope facts.  Never bind caller JSON directly into that type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Iterable, Mapping, TypeVar
import re
import secrets


API_VERSION = "v1"
API_VERSION_HEADER = "X-Wish-API-Version"
REQUEST_ID_HEADER = "X-Request-Id"
CORRELATION_ID_HEADER = "X-Correlation-Id"
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_CURSOR_LENGTH = 2048

_SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SAFE_CURSOR = re.compile(r"\A[A-Za-z0-9._~+/=-]{1,2048}\Z")


class InvalidRequestMetadata(ValueError):
    """Raised when untrusted request metadata does not match the v1 contract."""


class MissingIdempotencyKey(InvalidRequestMetadata):
    """Raised when a command is missing its required idempotency key."""


class InvalidPageRequest(ValueError):
    """Raised for an invalid cursor or page size."""


class InvalidFieldSelection(ValueError):
    """Raised when a requested field is not in the resource field allowlist."""


class FieldScopeDenied(PermissionError):
    """Raised when a requested field is not in the server-resolved field scope."""


def _validate_safe_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise InvalidRequestMetadata(f"{label} must be 1-128 safe ASCII characters")
    return value


def _header_map(headers: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise InvalidRequestMetadata("request header names and values must be strings")
        key = name.strip().lower()
        if key in normalized:
            raise InvalidRequestMetadata(f"duplicate request header: {name}")
        normalized[key] = value.strip()
    return normalized


@dataclass(frozen=True)
class RequestMetadata:
    """Canonical trace and idempotency metadata after ingress validation.

    ``request_id`` and ``correlation_id`` are always present in the normalized
    context.  A caller may offer them as trace candidates; the server validates
    them or generates replacements. ``idempotency_key`` is required only for
    state-changing operations. ``api_version`` is fixed by the versioned route.
    """

    request_id: str
    correlation_id: str
    idempotency_key: str | None = None
    api_version: str = API_VERSION

    def __post_init__(self) -> None:
        _validate_safe_id(self.request_id, "request_id")
        _validate_safe_id(self.correlation_id, "correlation_id")
        if self.idempotency_key is not None:
            _validate_safe_id(self.idempotency_key, "idempotency_key")
        if self.api_version != API_VERSION:
            raise InvalidRequestMetadata(f"api_version must be {API_VERSION!r}")

    @classmethod
    def from_headers(
        cls,
        headers: Mapping[str, str],
        *,
        api_version: str = API_VERSION,
        require_idempotency_key: bool = False,
        request_id_factory= lambda: secrets.token_hex(16),
    ) -> "RequestMetadata":
        """Build normalized metadata from a case-insensitive header mapping.

        This helper validates tracing inputs only. It intentionally has no
        tenant, site, subject, consent, relationship, purpose, or field-scope
        inputs; those facts come from trusted server-side resolution.
        """

        values = _header_map(headers)
        supplied_version = values.get(API_VERSION_HEADER.lower())
        if supplied_version is not None and supplied_version != api_version:
            raise InvalidRequestMetadata("api version header does not match route version")
        if api_version != API_VERSION:
            raise InvalidRequestMetadata(f"unsupported api version: {api_version}")

        request_id = values.get(REQUEST_ID_HEADER.lower()) or request_id_factory()
        request_id = _validate_safe_id(request_id, "request_id")
        correlation_id = values.get(CORRELATION_ID_HEADER.lower()) or request_id
        correlation_id = _validate_safe_id(correlation_id, "correlation_id")
        idempotency_key = values.get(IDEMPOTENCY_KEY_HEADER.lower())
        if require_idempotency_key and not idempotency_key:
            raise MissingIdempotencyKey("Idempotency-Key is required for this operation")
        if idempotency_key is not None:
            _validate_safe_id(idempotency_key, "idempotency_key")
        return cls(
            request_id=request_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            api_version=api_version,
        )

    def response_headers(self) -> dict[str, str]:
        """Return only the canonical response trace/version headers."""

        return {
            REQUEST_ID_HEADER: self.request_id,
            CORRELATION_ID_HEADER: self.correlation_id,
            API_VERSION_HEADER: self.api_version,
        }


@dataclass(frozen=True)
class AuthorizationContext:
    """Server-resolved Wish authorization facts; never a request DTO.

    The caller's site/subject/purpose selectors are only hints. The Wish API
    and application service resolve these values from verified principal,
    tenant/site membership, current relationship, purpose policy, consent,
    and field authorization. ``field_scope`` contains allowlisted field names
    only; it is not serialized in response envelopes.
    """

    principal_id: str
    tenant_id: str
    site_id: str
    subject_id: str
    purpose_code: str
    relationship_id: str | None
    consent_ids: tuple[str, ...]
    field_scope: frozenset[str]

    def __post_init__(self) -> None:
        for name in ("principal_id", "tenant_id", "site_id", "subject_id", "purpose_code"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required in resolved authorization context")
        if self.relationship_id == "":
            raise ValueError("relationship_id must be omitted when not applicable")
        consent_ids = tuple(self.consent_ids)
        field_scope = frozenset(self.field_scope)
        if any(not consent_id for consent_id in consent_ids):
            raise ValueError("consent_ids cannot contain empty values")
        known_fields = set().union(*FIELD_ALLOWLISTS.values())
        if field_scope - known_fields:
            raise ValueError("field_scope contains fields outside the API v1 allowlist")
        object.__setattr__(self, "consent_ids", consent_ids)
        object.__setattr__(self, "field_scope", field_scope)


@dataclass(frozen=True)
class ResponseMeta:
    request_id: str
    correlation_id: str
    idempotency_key: str | None = None
    api_version: str = API_VERSION

    @classmethod
    def from_request(cls, metadata: RequestMetadata) -> "ResponseMeta":
        return cls(
            request_id=metadata.request_id,
            correlation_id=metadata.correlation_id,
            idempotency_key=metadata.idempotency_key,
            api_version=metadata.api_version,
        )

    def __post_init__(self) -> None:
        _validate_safe_id(self.request_id, "request_id")
        _validate_safe_id(self.correlation_id, "correlation_id")
        if self.idempotency_key is not None:
            _validate_safe_id(self.idempotency_key, "idempotency_key")
        if self.api_version != API_VERSION:
            raise InvalidRequestMetadata(f"api_version must be {API_VERSION!r}")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "requestId": self.request_id,
            "correlationId": self.correlation_id,
            "apiVersion": self.api_version,
            "idempotencyKey": self.idempotency_key,
        }


T = TypeVar("T")


@dataclass(frozen=True)
class PageRequest:
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise InvalidPageRequest("limit must be an integer")
        if not 1 <= self.limit <= MAX_PAGE_SIZE:
            raise InvalidPageRequest(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if self.cursor is not None and (
            not isinstance(self.cursor, str)
            or len(self.cursor) > MAX_CURSOR_LENGTH
            or not _SAFE_CURSOR.fullmatch(self.cursor)
        ):
            raise InvalidPageRequest("cursor must be an opaque 1-2048 character token")


@dataclass(frozen=True)
class PageInfo:
    next_cursor: str | None
    has_more: bool

    def __post_init__(self) -> None:
        if self.has_more != (self.next_cursor is not None):
            raise InvalidPageRequest("has_more must be true exactly when next_cursor is present")
        if self.next_cursor is not None and (
            len(self.next_cursor) > MAX_CURSOR_LENGTH
            or not _SAFE_CURSOR.fullmatch(self.next_cursor)
        ):
            raise InvalidPageRequest("next_cursor must be an opaque 1-2048 character token")

    def to_dict(self) -> dict[str, object]:
        return {"nextCursor": self.next_cursor, "hasMore": self.has_more}


@dataclass(frozen=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    info: PageInfo

    def __init__(self, items: Iterable[T], info: PageInfo):
        materialized = tuple(items)
        if len(materialized) > MAX_PAGE_SIZE:
            raise InvalidPageRequest(f"page cannot contain more than {MAX_PAGE_SIZE} items")
        object.__setattr__(self, "items", materialized)
        object.__setattr__(self, "info", info)

    def to_data(self) -> dict[str, object]:
        return {
            "items": list(self.items),
            "nextCursor": self.info.next_cursor,
            "hasMore": self.info.has_more,
        }


@dataclass(frozen=True)
class SuccessEnvelope(Generic[T]):
    data: T
    meta: ResponseMeta

    def to_dict(self) -> dict[str, object]:
        return {"data": self.data, "meta": self.meta.to_dict(), "error": None}


# These are DTO field allowlists, not authorization grants. A request asking
# for one of these fields is still subject to the server-resolved field_scope.
FIELD_ALLOWLISTS: dict[str, frozenset[str]] = {
    "customers": frozenset({"customer.displayName", "customer.maskedPhone"}),
    "relationships": frozenset({"relationship.relationshipType", "relationship.status"}),
    "consents": frozenset({"consent.purposeCode", "consent.status", "consent.expiresAt"}),
    "health-records": frozenset(
        {"healthRecord.recordType", "healthRecord.occurredAt", "healthRecord.reportAvailable"}
    ),
    "service-catalog": frozenset({"service.serviceCode", "service.name", "service.status"}),
    "appointments": frozenset(
        {"appointment.status", "appointment.startsAt", "appointment.endsAt"}
    ),
    "work-orders": frozenset({"workOrder.status"}),
    "service-records": frozenset({"serviceRecord.recordedAt", "serviceRecord.status"}),
    "follow-ups": frozenset({"followUp.status", "followUp.dueAt"}),
    "notifications": frozenset({"notification.status"}),
    "service-rights": frozenset({"serviceRight.status", "serviceRight.validTo"}),
    "service-ledger": frozenset({"serviceLedger.entryType", "serviceLedger.occurredAt"}),
}


def resolve_field_selection(
    resource: str,
    requested_fields: Iterable[str] | None,
    authorization: AuthorizationContext,
) -> frozenset[str]:
    """Intersect the global/resource field allowlist with trusted field scope."""

    allowed = FIELD_ALLOWLISTS.get(resource)
    if allowed is None:
        raise InvalidFieldSelection(f"unknown resource field allowlist: {resource}")
    requested = frozenset(requested_fields or ())
    unknown = requested - allowed
    if unknown:
        raise InvalidFieldSelection("requested fields are not in the resource allowlist")
    unauthorized = requested - authorization.field_scope
    if unauthorized:
        raise FieldScopeDenied("requested fields are outside the resolved field scope")
    if requested:
        return requested
    return allowed & authorization.field_scope
