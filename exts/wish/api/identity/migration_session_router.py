"""Framework-neutral API-02 adapter using the API-01 Wish response envelope.

The hosting service supplies ``trusted_adapter`` only after authenticating its
server-side adapter identity. Request JSON can never create that value. Ticket,
nonce, APP session, and legacy credentials are intentionally absent from audit
and response metadata; the host must also redact credential-bearing bodies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
import secrets

from exts.wish.api.contracts.envelope import (
    InvalidRequestMetadata,
    MissingIdempotencyKey,
    RequestMetadata,
    ResponseMeta,
    SuccessEnvelope,
)
from exts.wish.api.contracts.errors import ErrorCode, WishAPIError
from domain.identity_migration.application.service import MigrationBridgeApplicationService
from domain.identity_migration.domain.models import TrustedAdapter, VerifiedAppSession


BASE_PATH = "/api/wish/v1/identity/migration-bridges"
ISSUE_PATH = BASE_PATH
REDEEM_PATH = BASE_PATH + "/redeem"
LEGACY_EXCHANGE_PATH = BASE_PATH + "/legacy-exchange"
REVOKE_TICKET_PATH = BASE_PATH + "/revoke-ticket"
REVOKE_SESSION_PATH = BASE_PATH + "/revoke-session"

_ROUTE_FIELDS = {
    ISSUE_PATH: frozenset({"audience", "route", "origin", "nonce"}),
    REDEEM_PATH: frozenset({"ticket", "audience", "route", "origin", "nonce"}),
    LEGACY_EXCHANGE_PATH: frozenset(
        {"legacyCredential", "audience", "route", "origin", "nonce"}
    ),
    REVOKE_TICKET_PATH: frozenset({"ticket"}),
    REVOKE_SESSION_PATH: frozenset(),
}


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: dict[str, str]
    body: dict[str, object]


class MigrationSessionRouter:
    """Small adapter surface: issue, redeem, one-time legacy exchange, revoke."""

    def __init__(self, application: MigrationBridgeApplicationService):
        self._application = application

    def dispatch(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: object,
        trusted_adapter: TrustedAdapter | None,
    ) -> HTTPResponse:
        metadata, metadata_error = _request_metadata(headers, require_idempotency_key=True)
        if metadata_error is not None:
            self._application.record_boundary_rejection(
                reason=(
                    "idempotency_key_missing"
                    if metadata_error.code == ErrorCode.IDEMPOTENCY_KEY_REQUIRED
                    else "api_metadata_invalid"
                ),
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
            )
            return _error_response(metadata_error, metadata)
        try:
            if method.upper() != "POST" or path not in _ROUTE_FIELDS:
                if path not in _ROUTE_FIELDS:
                    self._application.record_boundary_rejection(
                        reason="route_not_found",
                        request_id=metadata.request_id,
                        correlation_id=metadata.correlation_id,
                    )
                    raise WishAPIError(ErrorCode.RESOURCE_NOT_FOUND, "Migration route was not found.")
                self._application.record_boundary_rejection(
                    reason="method_not_allowed",
                    request_id=metadata.request_id,
                    correlation_id=metadata.correlation_id,
                )
                raise WishAPIError(ErrorCode.BAD_REQUEST, "Request method is invalid.")
            try:
                data = _read_body(body, _ROUTE_FIELDS[path])
            except WishAPIError:
                self._application.record_boundary_rejection(
                    reason="request_fields_invalid",
                    request_id=metadata.request_id,
                    correlation_id=metadata.correlation_id,
                )
                raise
            try:
                session_credential = _bearer_credential(headers)
            except WishAPIError:
                self._application.record_boundary_rejection(
                    reason="session_header_invalid",
                    request_id=metadata.request_id,
                    correlation_id=metadata.correlation_id,
                )
                raise
            if path == ISSUE_PATH:
                result = self._application.issue(
                    app_session_credential=session_credential,
                    adapter=trusted_adapter,
                    audience=data["audience"],
                    route=data["route"],
                    origin=data["origin"],
                    nonce=data["nonce"],
                    request_id=metadata.request_id,
                    correlation_id=metadata.correlation_id,
                )
            elif path == REDEEM_PATH:
                result = self._application.redeem(
                    app_session_credential=session_credential,
                    ticket=data["ticket"],
                    adapter=trusted_adapter,
                    audience=data["audience"],
                    route=data["route"],
                    origin=data["origin"],
                    nonce=data["nonce"],
                    request_id=metadata.request_id,
                    correlation_id=metadata.correlation_id,
                )
            elif path == LEGACY_EXCHANGE_PATH:
                result = self._application.exchange_legacy_and_issue(
                    app_session_credential=session_credential,
                    legacy_credential=data["legacyCredential"],
                    adapter=trusted_adapter,
                    audience=data["audience"],
                    route=data["route"],
                    origin=data["origin"],
                    nonce=data["nonce"],
                    request_id=metadata.request_id,
                    correlation_id=metadata.correlation_id,
                )
            elif path == REVOKE_TICKET_PATH:
                result = {
                    "revoked": self._application.revoke_ticket(
                        app_session_credential=session_credential,
                        ticket=data["ticket"],
                        request_id=metadata.request_id,
                        correlation_id=metadata.correlation_id,
                    )
                }
            else:
                result = {
                    "revokedCount": self._application.revoke_pending_for_session_credential(
                        app_session_credential=session_credential,
                        request_id=metadata.request_id,
                        correlation_id=metadata.correlation_id,
                    )
                }
            envelope = SuccessEnvelope(result, ResponseMeta.from_request(metadata)).to_dict()
            return _response(200, metadata, envelope)
        except WishAPIError as error:
            return _error_response(error, metadata)
        except Exception:
            # Never serialize backend exception messages, request values, or credentials.
            return _error_response(
                WishAPIError(ErrorCode.INTERNAL_ERROR, "The request could not be completed."),
                metadata,
            )

    def on_app_logout(
        self,
        *,
        session: VerifiedAppSession,
        headers: Mapping[str, str] | None = None,
    ) -> int:
        """Trusted lifecycle hook to call before APP session invalidation."""

        metadata, error = _request_metadata(headers or {}, require_idempotency_key=False)
        if error is not None:
            raise error
        return self._application.revoke_session_for_logout(
            session,
            request_id=metadata.request_id,
            correlation_id=metadata.correlation_id,
        )


def _request_metadata(
    headers: Mapping[str, str], *, require_idempotency_key: bool
) -> tuple[RequestMetadata, WishAPIError | None]:
    try:
        return (
            RequestMetadata.from_headers(
                headers,
                require_idempotency_key=require_idempotency_key,
            ),
            None,
        )
    except MissingIdempotencyKey:
        metadata = RequestMetadata(
            request_id=secrets.token_hex(16),
            correlation_id=secrets.token_hex(16),
        )
        return metadata, WishAPIError(
            ErrorCode.IDEMPOTENCY_KEY_REQUIRED,
            "Idempotency-Key is required for this command.",
        )
    except InvalidRequestMetadata:
        metadata = RequestMetadata(
            request_id=secrets.token_hex(16),
            correlation_id=secrets.token_hex(16),
        )
        supplied_version = next(
            (value for name, value in headers.items() if name.lower() == "x-wish-api-version"),
            None,
        )
        code = (
            ErrorCode.API_VERSION_MISMATCH
            if supplied_version is not None and supplied_version != "v1"
            else ErrorCode.BAD_REQUEST
        )
        return metadata, WishAPIError(code, "Request metadata is invalid.")
    except Exception:
        metadata = RequestMetadata(
            request_id=secrets.token_hex(16),
            correlation_id=secrets.token_hex(16),
        )
        return metadata, WishAPIError(ErrorCode.BAD_REQUEST, "Request metadata is invalid.")


def _bearer_credential(headers: Mapping[str, str]) -> str:
    value = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
    if not isinstance(value, str) or not value.startswith("Bearer "):
        raise WishAPIError(ErrorCode.AUTH_REQUIRED, "APP session is not valid.")
    credential = value[7:]
    if not credential or credential.strip() != credential or any(ch.isspace() for ch in credential):
        raise WishAPIError(ErrorCode.AUTH_REQUIRED, "APP session is not valid.")
    return credential


def _read_body(body: object, allowed_fields: frozenset[str]) -> dict[str, str]:
    if not isinstance(body, dict) or set(body) != set(allowed_fields):
        raise WishAPIError(ErrorCode.BAD_REQUEST, "Request fields are invalid.")
    if any(not isinstance(value, str) for value in body.values()):
        raise WishAPIError(ErrorCode.VALIDATION_FAILED, "Request fields are invalid.")
    return body


def _response(status: int, metadata: RequestMetadata, body: dict[str, object]) -> HTTPResponse:
    return HTTPResponse(
        status=status,
        headers={
            **metadata.response_headers(),
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
        body=body,
    )


def _error_response(error: WishAPIError, metadata: RequestMetadata) -> HTTPResponse:
    return _response(
        error.http_status,
        metadata,
        error.to_envelope(ResponseMeta.from_request(metadata)),
    )
