"""Standard-library Wish OpenAPI contract lint and compatibility diff tool.

PyYAML is used when already present. Without it, lint falls back to structural
text assertions; this script never installs packages or contacts a service.
"""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path
import re
import sys
from typing import Any

try:
    from .envelope import FIELD_ALLOWLISTS
    from .errors import (
        ERROR_HTTP_STATUS,
        RETRYABLE_ERROR_CODES,
        RETRY_AFTER_REQUIRED_CODES,
        ErrorCode,
    )
except ImportError:  # pragma: no cover - direct script entry point
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from envelope import FIELD_ALLOWLISTS
    from errors import (
        ERROR_HTTP_STATUS,
        RETRYABLE_ERROR_CODES,
        RETRY_AFTER_REQUIRED_CODES,
        ErrorCode,
    )


CONTRACT_PATH = Path(__file__).resolve().parents[2] / "openapi" / "wish-v1.yaml"
MUTATING_METHODS = {"post", "put", "patch", "delete"}
FORBIDDEN_REQUEST_PROPERTIES = {
    "tenantid",
    "principal",
    "principalid",
    "actorid",
    "relationshipid",
    "consentid",
    "consentids",
    "fieldscope",
    "role",
    "purposecode",
}
RESOURCE_SCHEMAS = {
    "CustomerSummary",
    "RelationshipSummary",
    "ConsentSummary",
    "HealthRecordSummary",
    "ServiceSummary",
    "AppointmentSummary",
    "WorkOrderSummary",
    "ServiceRecordSummary",
    "FollowUpSummary",
    "NotificationSummary",
    "ServiceRightSummary",
    "ServiceLedgerSummary",
}


class ContractLintError(ValueError):
    pass


def load_yaml(path: Path) -> tuple[dict[str, Any] | None, str]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return None, text
    try:
        value = yaml.safe_load(text)
    except Exception as exc:
        raise ContractLintError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractLintError(f"OpenAPI root must be a mapping: {path}")
    return value, text


def _ref_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    ref = value.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/components/schemas/"):
        return None
    return ref.rsplit("/", 1)[-1]


def _iter_properties(schema: Any):
    if not isinstance(schema, dict):
        return
    yield from (schema.get("properties") or {}).items()
    for key in ("allOf", "oneOf", "anyOf"):
        for child in schema.get(key, []) or []:
            yield from _iter_properties(child)


def _resolve_ref(document: dict[str, Any], ref: str) -> Any:
    current: Any = document
    for part in ref.removeprefix("#/").split("/"):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def lint_document(document: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if document.get("openapi") != "3.1.0":
        problems.append("OpenAPI dialect must be 3.1.0")
    info = document.get("info") or {}
    if info.get("version") != "1.0.0":
        problems.append("info.version must be 1.0.0 for the initial Wish v1 contract")
    servers = document.get("servers") or []
    if not servers or servers[0].get("url") != "/api/wish/v1":
        problems.append("server base path must be /api/wish/v1")

    contract = document.get("x-wish-contract") or {}
    if contract.get("apiVersion") != "v1":
        problems.append("x-wish-contract.apiVersion must be v1")
    auth = contract.get("applicationServiceBoundary") or {}
    expected_facts = {"principal", "tenant", "site", "subject", "relationship", "purpose", "consent", "fieldScope"}
    if set(auth.get("serverResolvedAuthorizationFacts") or []) != expected_facts:
        problems.append("server-resolved authorization facts do not match the v1 boundary")
    if not (contract.get("channelOwnership") or {}).get("appBff") or not (contract.get("channelOwnership") or {}).get("adminBff"):
        problems.append("APP BFF and Admin BFF channel ownership must be documented")
    for section in ("compatibility", "codeGeneration", "idempotency", "pagination", "errorHandling"):
        if not contract.get(section):
            problems.append(f"x-wish-contract.{section} is required")

    schemas = ((document.get("components") or {}).get("schemas") or {})
    error_codes = set((schemas.get("ErrorCode") or {}).get("enum") or [])
    python_codes = {code.value for code in ErrorCode}
    if error_codes != python_codes:
        problems.append("OpenAPI ErrorCode enum and errors.py ErrorCode values differ")
    error_catalog = ((contract.get("errorHandling") or {}).get("catalog") or {})
    expected_statuses = {code.value: status for code, status in ERROR_HTTP_STATUS.items()}
    if error_catalog.get("httpStatus") != expected_statuses:
        problems.append("OpenAPI stable error HTTP status catalog and errors.py mapping differ")
    retryable = set(error_catalog.get("retryableCodes") or [])
    if retryable != {code.value for code in RETRYABLE_ERROR_CODES}:
        problems.append("OpenAPI retryable code set and errors.py policy differ")
    retry_after_required = set(error_catalog.get("retryAfterRequiredCodes") or [])
    if retry_after_required != {code.value for code in RETRY_AFTER_REQUIRED_CODES}:
        problems.append("OpenAPI required Retry-After code set and errors.py policy differ")
    field_keys = set((schemas.get("FieldKey") or {}).get("enum") or [])
    python_field_keys = set().union(*FIELD_ALLOWLISTS.values())
    if field_keys != python_field_keys:
        problems.append("OpenAPI FieldKey enum and envelope.py resource field allowlists differ")
    for name in RESOURCE_SCHEMAS:
        schema = schemas.get(name) or {}
        if schema.get("additionalProperties") is not False:
            problems.append(f"{name} must reject fields outside its DTO allowlist")
    error_schema = schemas.get("WishError") or {}
    required_error_fields = {"code", "message", "retryable", "retryAfterSeconds", "details"}
    if not required_error_fields.issubset(set(error_schema.get("required") or [])):
        problems.append("WishError must require stable code, safe message, retryable, retryAfterSeconds, and details")
    meta_schema = schemas.get("EnvelopeMeta") or {}
    expected_meta = {"requestId", "correlationId", "apiVersion", "idempotencyKey"}
    if not expected_meta.issubset(set(meta_schema.get("required") or [])):
        problems.append("EnvelopeMeta must expose requestId, correlationId, apiVersion, and idempotencyKey")

    paths = document.get("paths") or {}
    operation_ids: list[str] = []
    standard_path_params = {"RequestId", "CorrelationId", "ApiVersion"}
    expected_error_statuses = {"400", "401", "403", "422", "429", "503"}
    for path, path_item in paths.items():
        if not path.startswith("/"):
            problems.append(f"path must be absolute relative to the server base path: {path}")
        path_params = {
            item.get("$ref", "").rsplit("/", 1)[-1]
            for item in (path_item.get("parameters") or [])
            if isinstance(item, dict)
        }
        if not standard_path_params.issubset(path_params):
            problems.append(f"{path} is missing request/correlation/version metadata headers")
        for method, operation in path_item.items():
            if method.lower() not in {"get", *MUTATING_METHODS}:
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                problems.append(f"{method.upper()} {path} is missing operationId")
            else:
                operation_ids.append(operation_id)
            params = operation.get("parameters") or []
            param_refs = {
                item.get("$ref", "").rsplit("/", 1)[-1]
                for item in params
                if isinstance(item, dict)
            }
            if method.lower() in MUTATING_METHODS:
                if "IdempotencyKey" not in param_refs:
                    problems.append(f"{method.upper()} {path} is missing required Idempotency-Key")
                if "IfMatch" not in param_refs:
                    problems.append(f"{method.upper()} {path} is missing expected-version If-Match")
                body = operation.get("requestBody") or {}
                if not body.get("required"):
                    problems.append(f"{method.upper()} {path} requestBody must be required")
                body_content = ((body.get("content") or {}).get("application/json") or {})
                request_schema = _resolve_ref(document, (body_content.get("schema") or {}).get("$ref", ""))
                for property_name, _ in _iter_properties(request_schema):
                    if property_name.lower() in FORBIDDEN_REQUEST_PROPERTIES:
                        problems.append(f"{method.upper()} {path} accepts caller-controlled authorization property {property_name}")
            if method.lower() == "get":
                response = ((operation.get("responses") or {}).get("200") or {})
                result_schema = operation.get("x-wish-result-schema")
                if result_schema is not None:
                    if response.get("$ref") != "#/components/responses/WishCollection":
                        problems.append(f"GET {path} must use the cursor collection response")
                    if "PageLimit" not in param_refs or "PageCursor" not in param_refs:
                        problems.append(f"GET {path} is missing cursor pagination parameters")
                    if result_schema not in RESOURCE_SCHEMAS:
                        problems.append(f"GET {path} must declare a known allowlisted result DTO")
                elif response.get("$ref") != "#/components/responses/AppointmentRead":
                    problems.append(f"GET {path} must use a typed Wish detail response")
            response_codes = set((operation.get("responses") or {}).keys())
            required_statuses = set(expected_error_statuses)
            if method.lower() == "get":
                required_statuses.add("404")
            else:
                required_statuses.update({"404", "409"})
            if "default" not in response_codes:
                problems.append(f"{method.upper()} {path} must have a default Wish error response")
            for status in required_statuses:
                if status not in response_codes:
                    problems.append(f"{method.upper()} {path} is missing standardized HTTP {status} errors")

    if len(operation_ids) != len(set(operation_ids)):
        problems.append("operationId values must be unique")

    forbidden_words = {"tenantId", "principalId", "relationshipId", "consentId", "fieldScope", "role"}
    for name, schema in schemas.items():
        if name in {"CreateAppointmentRequest", "CancelAppointmentRequest"}:
            property_names = {key.lower() for key, _ in _iter_properties(schema)}
            forbidden = {word.lower() for word in forbidden_words}
            if property_names & forbidden:
                problems.append(f"{name} exposes caller-supplied authorization facts")
    return problems


def lint_text_fallback(text: str) -> list[str]:
    """Minimal no-PyYAML checks; deliberately uses only standard-library text tests."""

    required_markers = (
        "openapi: 3.1.0",
        "version: 1.0.0",
        "url: /api/wish/v1",
        "serverResolvedAuthorizationFacts:",
        "- principal",
        "- tenant",
        "- site",
        "- subject",
        "- relationship",
        "- purpose",
        "- consent",
        "- fieldScope",
        "Idempotency-Key",
        "retryable",
        "retryAfterSeconds",
        "nextCursor",
        "hasMore",
        "additionalProperties: false",
        "sourceOfTruth: this OpenAPI document",
        "Never edit",
        "If-Match",
        "retryAfterSeconds",
        "Retry-After",
    )
    missing = [marker for marker in required_markers if marker not in text]
    for code in ErrorCode:
        if f"- {code.value}" not in text:
            missing.append(f"ErrorCode {code.value}")
    for field in set().union(*FIELD_ALLOWLISTS.values()):
        if f"- {field}" not in text:
            missing.append(f"FieldKey {field}")
    return [f"fallback YAML text check missing marker: {marker}" for marker in missing]


def _schema_map(document: dict[str, Any]) -> dict[str, Any]:
    return ((document.get("components") or {}).get("schemas") or {})


def find_breaking_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Conservative v1 compatibility check used before replacing a baseline."""

    breaking: list[str] = []
    old_paths = old.get("paths") or {}
    new_paths = new.get("paths") or {}
    for path, old_item in old_paths.items():
        if path not in new_paths:
            breaking.append(f"removed path {path}")
            continue
        new_item = new_paths[path]
        for method, old_operation in old_item.items():
            if method.lower() not in {"get", *MUTATING_METHODS}:
                continue
            new_operation = new_item.get(method)
            if not isinstance(new_operation, dict):
                breaking.append(f"removed operation {method.upper()} {path}")
                continue
            if old_operation.get("operationId") != new_operation.get("operationId"):
                breaking.append(f"changed operationId for {method.upper()} {path}")
            old_codes = set((old_operation.get("responses") or {}).keys())
            new_codes = set((new_operation.get("responses") or {}).keys())
            for code in sorted(old_codes - new_codes):
                breaking.append(f"removed response {code} from {method.upper()} {path}")
            old_params = {
                (item.get("name"), item.get("in")): item
                for item in old_operation.get("parameters", [])
                if isinstance(item, dict) and "name" in item
            }
            new_params = {
                (item.get("name"), item.get("in")): item
                for item in new_operation.get("parameters", [])
                if isinstance(item, dict) and "name" in item
            }
            for key, old_param in old_params.items():
                new_param = new_params.get(key)
                label = f"{key[1]} parameter {key[0]} on {method.upper()} {path}"
                if new_param is None:
                    breaking.append(f"removed {label}")
                elif not old_param.get("required", False) and new_param.get("required", False):
                    breaking.append(f"made {label} required")
            if not (old_operation.get("requestBody") or {}).get("required", False) and (
                new_operation.get("requestBody") or {}
            ).get("required", False):
                breaking.append(f"made request body required on {method.upper()} {path}")

    old_schemas = _schema_map(old)
    new_schemas = _schema_map(new)
    for schema_name, old_schema in old_schemas.items():
        if schema_name not in new_schemas:
            breaking.append(f"removed schema {schema_name}")
            continue
        new_schema = new_schemas[schema_name]
        if old_schema.get("type") != new_schema.get("type"):
            breaking.append(f"changed schema type for {schema_name}")
        old_enum = set(old_schema.get("enum") or [])
        new_enum = set(new_schema.get("enum") or [])
        for value in sorted(old_enum - new_enum, key=str):
            breaking.append(f"removed {value!r} from enum {schema_name}")
        old_props = old_schema.get("properties") or {}
        new_props = new_schema.get("properties") or {}
        for property_name, old_prop in old_props.items():
            if property_name not in new_props:
                breaking.append(f"removed property {schema_name}.{property_name}")
            elif old_prop.get("type") != new_props[property_name].get("type"):
                breaking.append(f"changed type for {schema_name}.{property_name}")
        old_required = set(old_schema.get("required") or [])
        new_required = set(new_schema.get("required") or [])
        for name in sorted(new_required - old_required):
            breaking.append(f"made {schema_name}.{name} required")
    return breaking


def unified_diff(old_path: Path, new_path: Path) -> str:
    old_lines = old_path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = new_path.read_text(encoding="utf-8").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=str(old_path),
            tofile=str(new_path),
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--diff-against", type=Path, help="print a unified diff and reject breaking v1 changes")
    args = parser.parse_args(argv)
    try:
        document, text = load_yaml(args.contract)
        problems = lint_document(document) if document is not None else lint_text_fallback(text)
        if problems:
            for problem in problems:
                print(f"FAIL {problem}")
            return 1
        if args.diff_against:
            old_document, _ = load_yaml(args.diff_against)
            if old_document is None or document is None:
                print("FAIL compatibility diff requires PyYAML to parse the baseline and candidate")
                return 2
            print(unified_diff(args.diff_against, args.contract), end="")
            breaking = find_breaking_changes(old_document, document)
            if breaking:
                for problem in breaking:
                    print(f"BREAKING {problem}")
                return 1
            print("PASS no breaking changes detected")
        else:
            if document is not None:
                operation_count = sum(
                    1
                    for item in document.get("paths", {}).values()
                    for method in item
                    if method.lower() in {"get", *MUTATING_METHODS}
                )
                path_count = len(document.get("paths", {}))
            else:
                path_count = len(re.findall(r"(?m)^  /[^\n]+:$", text))
                operation_count = len(re.findall(r"(?m)^    (?:get|post|put|patch|delete):$", text))
            mode = "PyYAML" if document is not None else "stdlib text fallback"
            print(f"PASS API-01 contract lint; paths={path_count}; operations={operation_count}; parser={mode}")
        return 0
    except (OSError, ContractLintError) as exc:
        print(f"FAIL {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
