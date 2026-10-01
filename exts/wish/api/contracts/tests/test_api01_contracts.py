from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest


CONTRACTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT))

from exts.wish.api.contracts.envelope import (  # noqa: E402
    API_VERSION,
    AuthorizationContext,
    FieldScopeDenied,
    InvalidFieldSelection,
    InvalidPageRequest,
    InvalidRequestMetadata,
    MissingIdempotencyKey,
    Page,
    PageInfo,
    PageRequest,
    RequestMetadata,
    ResponseMeta,
    SuccessEnvelope,
    resolve_field_selection,
)
from exts.wish.api.contracts.errors import (  # noqa: E402
    ERROR_HTTP_STATUS,
    RETRYABLE_ERROR_CODES,
    RETRY_AFTER_REQUIRED_CODES,
    ErrorCode,
    ErrorDetail,
    WishAPIError,
)
from exts.wish.api.contracts.contract_lint import (  # noqa: E402
    CONTRACT_PATH,
    find_breaking_changes,
    lint_document,
    lint_text_fallback,
    load_yaml,
)

try:
    import yaml as _yaml  # noqa: F401

    HAS_PYYAML = True
except ImportError:
    HAS_PYYAML = False


class InMemoryWishClientMock:
    """Small client-side wire mock; it does not open sockets or call a server."""

    def success(self, metadata: RequestMetadata, data: dict[str, object]) -> dict[str, object]:
        meta = ResponseMeta.from_request(metadata)
        response = SuccessEnvelope(data=data, meta=meta).to_dict()
        headers = metadata.response_headers()
        if headers["X-Wish-API-Version"] != response["meta"]["apiVersion"]:
            raise AssertionError("response API version header/body mismatch")
        if headers["X-Request-Id"] != response["meta"]["requestId"]:
            raise AssertionError("response request ID header/body mismatch")
        return response


class OpenAPIContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document, cls.text = load_yaml(CONTRACT_PATH)

    def test_openapi_yaml_and_shared_contract_lint(self) -> None:
        if self.document is None:
            self.assertEqual(lint_text_fallback(self.text), [])
        else:
            self.assertEqual(lint_document(self.document), [])
            self.assertEqual(self.document["openapi"], "3.1.0")
            self.assertEqual(self.document["servers"][0]["url"], "/api/wish/v1")

    def test_channel_boundary_and_server_resolved_authorization_are_explicit(self) -> None:
        self.assertIn("same Wish application services", self.text)
        self.assertIn("second business backend", self.text)
        self.assertIn("serverResolvedAuthorizationFacts", self.text)
        self.assertIn("fieldScope", self.text)
        self.assertIn("selection hint only", self.text.casefold())
        self.assertIn("MAPP server", self.text)
        self.assertIn("do not route through Wish BFF", self.text)

    @unittest.skipUnless(HAS_PYYAML, "deep OpenAPI structure check uses installed PyYAML; fallback text checks still run")
    def test_all_operations_have_unique_ids_and_safe_standard_errors(self) -> None:
        self.assertIsNotNone(self.document)
        operation_ids = []
        for path, path_item in self.document["paths"].items():
            self.assertTrue(path.startswith("/"))
            refs = {
                parameter["$ref"].rsplit("/", 1)[-1]
                for parameter in path_item["parameters"]
                if "$ref" in parameter
            }
            self.assertTrue({"RequestId", "CorrelationId", "ApiVersion"}.issubset(refs))
            for method, operation in path_item.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                operation_ids.append(operation["operationId"])
                self.assertIn("default", operation["responses"])
                for status in ("400", "401", "403", "422", "429", "503"):
                    self.assertIn(status, operation["responses"], f"{method.upper()} {path}")
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        catalog = self.document["x-wish-contract"]["errorHandling"]["catalog"]
        self.assertEqual(
            catalog["httpStatus"],
            {code.value: status for code, status in ERROR_HTTP_STATUS.items()},
        )
        self.assertEqual(set(catalog["retryableCodes"]), {code.value for code in RETRYABLE_ERROR_CODES})
        self.assertEqual(
            set(catalog["retryAfterRequiredCodes"]),
            {code.value for code in RETRY_AFTER_REQUIRED_CODES},
        )

    @unittest.skipUnless(HAS_PYYAML, "deep OpenAPI structure check uses installed PyYAML; fallback text checks still run")
    def test_read_lists_use_bounded_cursor_paging_and_named_allowlists(self) -> None:
        self.assertIsNotNone(self.document)
        for path, path_item in self.document["paths"].items():
            operation = path_item.get("get")
            if not operation or "x-wish-result-schema" not in operation:
                continue
            refs = {parameter["$ref"].rsplit("/", 1)[-1] for parameter in operation["parameters"]}
            self.assertTrue({"PageLimit", "PageCursor", "FieldSelection"}.issubset(refs), path)
            self.assertEqual(operation["responses"]["200"]["$ref"], "#/components/responses/WishCollection")
            schema = self.document["components"]["schemas"][operation["x-wish-result-schema"]]
            self.assertFalse(schema.get("additionalProperties", True), path)
        page_limit = self.document["components"]["parameters"]["PageLimit"]["schema"]
        self.assertEqual((page_limit["default"], page_limit["minimum"], page_limit["maximum"]), (20, 1, 100))

    @unittest.skipUnless(HAS_PYYAML, "deep OpenAPI structure check uses installed PyYAML; fallback text checks still run")
    def test_every_command_requires_idempotency_and_expected_version(self) -> None:
        self.assertIsNotNone(self.document)
        for path, path_item in self.document["paths"].items():
            for method in ("post", "put", "patch", "delete"):
                operation = path_item.get(method)
                if not operation:
                    continue
                refs = {parameter["$ref"].rsplit("/", 1)[-1] for parameter in operation["parameters"]}
                self.assertTrue({"IdempotencyKey", "IfMatch"}.issubset(refs), f"{method.upper()} {path}")
                self.assertTrue(operation["requestBody"]["required"])

    @unittest.skipUnless(HAS_PYYAML, "deep OpenAPI structure check uses installed PyYAML; fallback text checks still run")
    def test_write_request_schemas_do_not_accept_authority_facts(self) -> None:
        self.assertIsNotNone(self.document)
        forbidden = {
            "tenantid", "principal", "principalid", "actorid", "relationshipid",
            "consentid", "consentids", "fieldscope", "role", "purposecode",
        }
        schemas = self.document["components"]["schemas"]
        for name in ("CreateAppointmentRequest", "CancelAppointmentRequest"):
            properties = {key.lower() for key in schemas[name].get("properties", {})}
            self.assertFalse(properties & forbidden, name)
        body = schemas["CreateAppointmentRequest"]
        self.assertIn("siteId", body["properties"])
        self.assertIn("subjectId", body["properties"])
        self.assertIn("selection hint only", body["properties"]["siteId"]["description"].casefold())
        self.assertIn("selection hint only", body["properties"]["subjectId"]["description"].casefold())

    @unittest.skipUnless(HAS_PYYAML, "deep OpenAPI structure check uses installed PyYAML; fallback text checks still run")
    def test_field_key_allowlist_matches_python_contract(self) -> None:
        self.assertIsNotNone(self.document)
        yaml_fields = set(self.document["components"]["schemas"]["FieldKey"]["enum"])
        from exts.wish.api.contracts.envelope import FIELD_ALLOWLISTS

        self.assertEqual(yaml_fields, set().union(*FIELD_ALLOWLISTS.values()))
        self.assertFalse(self.document["components"]["schemas"]["HealthRecordSummary"]["additionalProperties"])

    @unittest.skipUnless(HAS_PYYAML, "deep OpenAPI structure check uses installed PyYAML; fallback text checks still run")
    def test_gov06_client_status_vocabulary_stays_bounded(self) -> None:
        schemas = self.document["components"]["schemas"]
        self.assertEqual(
            schemas["AppointmentSummary"]["properties"]["status"]["enum"],
            ["PENDING", "CONFIRMED", "COMPLETED", "CANCELLED"],
        )
        self.assertEqual(
            schemas["FollowUpSummary"]["properties"]["status"]["enum"],
            ["PENDING", "COMPLETED"],
        )
        self.assertEqual(
            schemas["ServiceRightSummary"]["properties"]["status"]["enum"],
            ["ACTIVE", "FROZEN", "EXPIRED"],
        )

    @unittest.skipUnless(HAS_PYYAML, "deep OpenAPI structure check uses installed PyYAML; fallback text checks still run")
    def test_version_compatibility_and_codegen_policy_are_frozen(self) -> None:
        contract = self.document["x-wish-contract"]
        self.assertEqual(contract["apiVersion"], API_VERSION)
        self.assertIn("new major route version", contract["compatibility"]["breakingChanges"])
        self.assertIn("Never edit", contract["codeGeneration"]["generatedCode"])
        self.assertIn("unknown error codes", contract["compatibility"]["compatibleChanges"])


class EnvelopeAndErrorTests(unittest.TestCase):
    def test_request_metadata_normalizes_trace_ids_and_idempotency(self) -> None:
        metadata = RequestMetadata.from_headers(
            {
                "x-request-id": "req.01",
                "X-Correlation-Id": "flow:abc",
                "IDEMPOTENCY-KEY": "appt.01",
                "X-Wish-API-Version": "v1",
            },
            require_idempotency_key=True,
        )
        self.assertEqual(metadata.request_id, "req.01")
        self.assertEqual(metadata.correlation_id, "flow:abc")
        self.assertEqual(metadata.idempotency_key, "appt.01")
        self.assertEqual(metadata.api_version, "v1")

    def test_request_metadata_generates_missing_ids_and_requires_command_key(self) -> None:
        metadata = RequestMetadata.from_headers({}, request_id_factory=lambda: "generated-1")
        self.assertEqual(metadata.request_id, "generated-1")
        self.assertEqual(metadata.correlation_id, "generated-1")
        with self.assertRaises(MissingIdempotencyKey):
            RequestMetadata.from_headers({}, require_idempotency_key=True)

    def test_request_metadata_rejects_bad_ids_and_version_mismatch(self) -> None:
        with self.assertRaises(InvalidRequestMetadata):
            RequestMetadata.from_headers({"X-Request-Id": "line\nbreak"})
        with self.assertRaises(InvalidRequestMetadata):
            RequestMetadata.from_headers({"X-Wish-API-Version": "v2"})
        with self.assertRaises(InvalidRequestMetadata):
            RequestMetadata.from_headers({"Idempotency-Key": " "})

    def test_authorization_context_is_server_resolved_and_immutable(self) -> None:
        context = AuthorizationContext(
            principal_id="principal-1",
            tenant_id="tenant-1",
            site_id="site-1",
            subject_id="subject-1",
            purpose_code="service_delivery",
            relationship_id=None,
            consent_ids=("consent-1",),
            field_scope=frozenset({"appointment.status"}),
        )
        with self.assertRaises(AttributeError):
            context.site_id = "site-client-override"  # type: ignore[misc]

    def test_page_request_bounds_and_cursor_invariants(self) -> None:
        self.assertEqual(PageRequest().limit, 20)
        self.assertEqual(PageRequest(limit=100).limit, 100)
        for value in (0, 101, True):
            with self.subTest(limit=value), self.assertRaises(InvalidPageRequest):
                PageRequest(limit=value)  # type: ignore[arg-type]
        with self.assertRaises(InvalidPageRequest):
            PageRequest(cursor="bad cursor")
        with self.assertRaises(InvalidPageRequest):
            PageInfo(next_cursor=None, has_more=True)
        with self.assertRaises(InvalidPageRequest):
            Page([{}] * 101, PageInfo(None, False))
        page = Page([{"resourceType": "appointment"}], PageInfo("opaque.cursor", True))
        self.assertEqual(page.to_data()["hasMore"], True)
        self.assertEqual(page.to_data()["nextCursor"], "opaque.cursor")

    def test_field_selection_intersects_resource_allowlist_and_resolved_scope(self) -> None:
        context = AuthorizationContext(
            principal_id="p1",
            tenant_id="t1",
            site_id="s1",
            subject_id="u1",
            purpose_code="health_read",
            relationship_id=None,
            consent_ids=("c1",),
            field_scope=frozenset({"healthRecord.recordType"}),
        )
        self.assertEqual(
            resolve_field_selection("health-records", None, context),
            frozenset({"healthRecord.recordType"}),
        )
        with self.assertRaises(InvalidFieldSelection):
            resolve_field_selection("health-records", ["healthRecord.payload"], context)
        with self.assertRaises(FieldScopeDenied):
            resolve_field_selection("health-records", ["healthRecord.occurredAt"], context)

    def test_error_codes_http_mapping_and_retry_contract(self) -> None:
        self.assertEqual(ERROR_HTTP_STATUS[ErrorCode.AUTH_REQUIRED], 401)
        self.assertEqual(ERROR_HTTP_STATUS[ErrorCode.CONSENT_REQUIRED], 403)
        self.assertEqual(ERROR_HTTP_STATUS[ErrorCode.VERSION_CONFLICT], 409)
        self.assertEqual(ERROR_HTTP_STATUS[ErrorCode.RATE_LIMITED], 429)
        document, text = load_yaml(CONTRACT_PATH)
        if document is None:
            self.assertIn("Retry-After", text)
        else:
            self.assertEqual(document["components"]["headers"]["RetryAfter"]["schema"]["minimum"], 1)
        rate_limited = WishAPIError(
            ErrorCode.RATE_LIMITED,
            "Please retry after the stated delay.",
            retryable=True,
            retry_after_seconds=30,
        )
        self.assertEqual(rate_limited.http_status, 429)
        self.assertEqual(rate_limited.to_error_dict()["retryAfterSeconds"], 30)
        with self.assertRaises(ValueError):
            WishAPIError(ErrorCode.RATE_LIMITED, "Rate limited.")
        with self.assertRaises(ValueError):
            WishAPIError(ErrorCode.RATE_LIMITED, "Rate limited.", retryable=True)
        with self.assertRaises(ValueError):
            WishAPIError(ErrorCode.CONSENT_REQUIRED, "Consent is required.", retryable=True)
        with self.assertRaises(ValueError):
            WishAPIError(ErrorCode.VERSION_CONFLICT, "Version changed.", retry_after_seconds=2)

    def test_error_envelope_contains_safe_fields_without_rejected_values(self) -> None:
        error = WishAPIError(
            ErrorCode.VALIDATION_FAILED,
            "Check the highlighted fields.",
            details=(ErrorDetail("startsAt", "INVALID_DATETIME", "Use a valid UTC timestamp."),),
        )
        meta = ResponseMeta("req-2", "flow-2", "idem-2")
        body = error.to_envelope(meta)
        self.assertEqual(body["data"], None)
        self.assertEqual(body["meta"]["idempotencyKey"], "idem-2")
        self.assertNotIn("value", body["error"]["details"][0])
        self.assertNotIn("debug", body["error"])

    def test_in_memory_client_mock_checks_version_and_metadata_headers(self) -> None:
        metadata = RequestMetadata.from_headers(
            {"X-Request-Id": "mock-req", "Idempotency-Key": "mock-idem"},
            require_idempotency_key=True,
        )
        response = InMemoryWishClientMock().success(
            metadata,
            {"resourceType": "appointment", "appointmentId": "synthetic-1", "status": "CONFIRMED"},
        )
        self.assertEqual(response["meta"]["requestId"], "mock-req")
        self.assertEqual(response["meta"]["correlationId"], "mock-req")
        self.assertEqual(response["meta"]["apiVersion"], "v1")
        self.assertEqual(response["meta"]["idempotencyKey"], "mock-idem")
        self.assertIsNone(response["error"])


class ContractDiffTests(unittest.TestCase):
    def test_compatibility_diff_accepts_optional_additions(self) -> None:
        baseline = {
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "parameters": [{"name": "limit", "in": "query", "required": False}],
                        "responses": {"200": {}},
                    }
                }
            },
            "components": {"schemas": {"Item": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}}}},
        }
        candidate = copy.deepcopy(baseline)
        candidate["paths"]["/items"]["get"]["parameters"].append(
            {"name": "fields", "in": "query", "required": False}
        )
        candidate["paths"]["/new-items"] = {"get": {"operationId": "listNewItems", "responses": {"200": {}}}}
        candidate["components"]["schemas"]["Item"]["properties"]["label"] = {"type": "string"}
        self.assertEqual(find_breaking_changes(baseline, candidate), [])

    def test_compatibility_diff_rejects_removed_fields_and_new_required_parameters(self) -> None:
        baseline = {
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "parameters": [{"name": "cursor", "in": "query", "required": False}],
                        "responses": {"200": {}},
                    }
                }
            },
            "components": {"schemas": {"Item": {"type": "object", "properties": {"id": {"type": "string"}}}}},
        }
        candidate = copy.deepcopy(baseline)
        candidate["paths"]["/items"]["get"]["parameters"][0]["required"] = True
        del candidate["components"]["schemas"]["Item"]["properties"]["id"]
        changes = find_breaking_changes(baseline, candidate)
        self.assertTrue(any("made query parameter cursor on GET /items required" in change for change in changes))
        self.assertTrue(any("removed property Item.id" in change for change in changes))


if __name__ == "__main__":
    unittest.main()
