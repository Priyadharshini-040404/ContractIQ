"""
ContractIQ - Spec-Driven Test Synthesis Engine

Generates test cases and assertions ENTIRELY from a parsed OpenAPI
specification. No path, parameter name, or payload shape for any
specific API is hardcoded anywhere in this module — every decision is
derived from the spec that is passed in.

This replaces the PetStore-specific fallback generation that used to
live inline in core/langchain_orchestrator.py
(_generate_fallback_tests / _generate_fallback_assertions), and is
what lets ContractIQ run against ANY OpenAPI 3.x spec — proven in
Group 5 by running this exact code, unmodified, against a second,
unrelated Task-List API (see configs/task_api.yaml).

Three collaborating pieces:

- ResourceDiscovery     For every path parameter used anywhere in the
                        spec, works out which endpoint can be POSTed
                        to in order to create a fresh instance of that
                        resource, and which response field holds its
                        ID. Pure path-structure matching (collection
                        path -> POST, item path -> {id}) — never
                        matching on a specific parameter name.

- AssertionSynthesizer  Builds validation assertions (status code,
                        response shape, required-field presence) using
                        only each endpoint's own declared responses
                        and schemas.

- TestSynthesizer       Orchestrates the above into full test suites:
                        a positive test per endpoint, a negative-ID
                        test wherever the spec itself declares a 404,
                        an empty-body edge case wherever there's a
                        request body, and boundary/invalid-value tests
                        for every constrained property (min/max,
                        length, enum) wherever the spec declares a
                        validation-error response — so test volume
                        scales with how richly-constrained the spec
                        actually is, not a fixed count.

Destructive (DELETE) test cases never bake in a specific resource ID.
Instead they carry a "setup" block describing how to create their own
disposable resource at execution time (consumed by
execution/test_runner.py and generators/postman_generator.py), so
re-running the suite never depends on state a previous run left
behind.
"""

import re
from typing import Any, Callable, Optional

PATH_PARAM_RE = re.compile(r"\{([^{}]+)\}")

# Constraint keys we know how to derive a boundary/invalid value from.
_STRING_CONSTRAINTS = ("minLength", "maxLength", "enum", "pattern")
_NUMERIC_CONSTRAINTS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")


def _collection_path_for(path: str, param_name: str) -> Optional[str]:
    """Given '/api/v1/pets/{pet_id}' and 'pet_id', return the parent
    'collection' path '/api/v1/pets' that a POST creating a new
    instance of this resource would live at. Pure string surgery on
    the path template — no knowledge of what the resource is called.
    Returns None if the path doesn't actually end with that param."""
    suffix = "{" + param_name + "}"
    stripped = path.rstrip("/")
    if not stripped.endswith(suffix):
        return None
    trimmed = stripped[: -len(suffix)].rstrip("/")
    return trimmed or "/"


def _status_codes(endpoint: dict, prefix: str) -> list[int]:
    """All declared status codes for an endpoint starting with `prefix`
    (e.g. '2' or '4'), sorted ascending."""
    codes = []
    for r in endpoint.get("responses", []):
        code = str(r.get("status_code", ""))
        if code.isdigit() and code.startswith(prefix):
            codes.append(int(code))
    return sorted(codes)


def _primary_success_status(endpoint: dict) -> int:
    codes = _status_codes(endpoint, "2")
    if codes:
        return codes[0]
    # No 2xx declared at all — extremely unusual, but never crash.
    return 200


def _declared_validation_status(endpoint: dict) -> Optional[int]:
    """The status code this endpoint's spec uses for validation
    failures, if it declares one. Prefers 422 (FastAPI/Pydantic
    convention) then 400, since both are common request-validation
    codes — but ONLY if the spec actually documents it, so we never
    assert an expectation the contract doesn't make."""
    fours = _status_codes(endpoint, "4")
    for preferred in (422, 400):
        if preferred in fours:
            return preferred
    return None


def _response_schema_for_status(endpoint: dict, status: int) -> dict:
    for r in endpoint.get("responses", []):
        if str(r.get("status_code", "")) == str(status):
            return r.get("schema") or {}
    return {}


def _required_response_fields(endpoint: dict, status: int, cap: int = 5) -> list[str]:
    schema = _response_schema_for_status(endpoint, status)
    required = schema.get("required") or list(schema.get("properties", {}).keys())
    return required[:cap]


class ResourceDiscovery:
    """Maps every path-parameter name used across the spec to the
    endpoint that creates that kind of resource."""

    def __init__(self, endpoints: list[dict]):
        self.endpoints = endpoints
        self._by_method_path = {(ep["method"], ep["path"]): ep for ep in endpoints}

    def discover(self) -> dict[str, dict]:
        creators: dict[str, dict] = {}
        for ep in self.endpoints:
            for param_name in PATH_PARAM_RE.findall(ep["path"]):
                if param_name in creators:
                    continue
                collection_path = _collection_path_for(ep["path"], param_name)
                if collection_path is None:
                    continue
                creator = self._by_method_path.get(("POST", collection_path))
                if not creator:
                    continue
                creators[param_name] = {
                    "method": "POST",
                    "path": collection_path,
                    "operation_id": creator["operation_id"],
                    "request_body": creator.get("request_body"),
                    "capture": self._infer_id_field(creator, param_name),
                    "success_status": _primary_success_status(creator),
                }
        return creators

    @staticmethod
    def _infer_id_field(creator_endpoint: dict, param_name: str) -> str:
        """Which field of the creator's success response becomes this
        resource's ID. Prefers an 'id' property (the overwhelming REST
        convention); falls back to a property that happens to share
        the path parameter's own name; defaults to 'id' either way so
        callers always get a usable field name."""
        for status in _status_codes(creator_endpoint, "2"):
            props = _response_schema_for_status(creator_endpoint, status).get("properties", {})
            if "id" in props:
                return "id"
            if param_name in props:
                return param_name
        return "id"


class AssertionSynthesizer:
    """Builds assertion lists from an endpoint's own declared responses
    and schemas — never from a hardcoded field name."""

    def __init__(self, schemas: dict | None = None):
        self.schemas = schemas or {}

    def synthesize(self, test_case: dict, endpoint: dict | None) -> list[dict]:
        expected = test_case.get("expected", {})
        status = expected.get("status_code", 200)

        assertions = [
            {
                "type": "status_code",
                "field": None,
                "operator": "equals",
                "expected_value": status,
                "description": f"Status code should be {status}",
            },
            {
                "type": "response_time",
                "field": None,
                "operator": "less_than",
                "expected_value": 5000,
                "description": "Response time should be under 5 seconds",
            },
        ]

        is_json = expected.get("response_type") == "json" and status != 204
        assertions.append({
            "type": "response_body",
            "field": None,
            "operator": "type_check",
            "expected_value": "dict" if is_json else "none",
            "description": "Response should be valid JSON" if is_json else "Response should have no body",
        })

        if is_json and endpoint is not None:
            for field in _required_response_fields(endpoint, status):
                assertions.append({
                    "type": "response_body",
                    "field": field,
                    "operator": "exists",
                    "expected_value": None,
                    "description": f"Response should contain '{field}' (declared required by the spec)",
                })

        for field in expected.get("response_body_contains", []):
            # Avoid duplicate 'exists' assertions for fields already
            # covered by the schema-required loop above.
            if not any(a["field"] == field and a["operator"] == "exists" for a in assertions):
                assertions.append({
                    "type": "response_body",
                    "field": field,
                    "operator": "exists",
                    "expected_value": None,
                    "description": f"Response should contain '{field}'",
                })

        return assertions


class TestSynthesizer:
    """Turns parsed spec data into a full, executable test-suite
    structure, using ResourceDiscovery + AssertionSynthesizer under
    the hood. Entirely spec-driven: pass in a PetStore spec and you
    get PetStore tests; pass in a Task-List spec and you get Task-List
    tests, with zero code changes (see Group 5)."""

    def __init__(
        self,
        spec_data: dict,
        create_resource: Optional[Callable[[str, dict], Optional[dict]]] = None,
    ):
        """
        spec_data: the dict produced by OpenAPIParser (endpoints,
            schemas, server_url, ...).
        create_resource: optional callable(path, body) -> parsed JSON
            response dict or None, used ONLY to obtain real,
            currently-valid resource IDs for non-destructive tests by
            POSTing to a live target API. When omitted (or when it
            returns None because the API isn't reachable), synthetic
            placeholder IDs are used instead — generation never
            depends on a live server being up.
        """
        self.endpoints: list[dict] = spec_data.get("endpoints", [])
        self.schemas: dict = spec_data.get("schemas", {})
        self.server_url: str = spec_data.get("server_url", "http://localhost:8000")
        self.discovery = ResourceDiscovery(self.endpoints)
        self.creators = self.discovery.discover()
        self.create_resource = create_resource
        self.assertion_synth = AssertionSynthesizer(self.schemas)

        self._shared_ids: dict[str, str] = {}
        self._resolve_shared_ids()

    # ------------------------------------------------------------------
    # Sample value / ID generation
    # ------------------------------------------------------------------

    def _resolve_shared_ids(self) -> None:
        """Obtain one real, shared resource ID per discovered resource
        type by POSTing to its creator endpoint (via create_resource),
        for use by non-destructive tests (GET/PUT/negative-ID tests,
        and any request body field that references this resource type).
        Never used for DELETE — DELETE always gets a disposable
        resource of its own via a 'setup' block at execution time."""
        for param_name, creator in self.creators.items():
            body = self._sample_body_for(creator.get("request_body"))
            created = None
            if self.create_resource:
                created = self.create_resource(creator["path"], body or {})
            if created and creator["capture"] in created:
                self._shared_ids[param_name] = str(created[creator["capture"]])

    def _placeholder_id(self, param_name: str, endpoint: dict) -> str:
        """A synthetic ID to use when no live resource could be
        created (or none applies) for this path parameter — derived
        from the parameter's own schema example when the spec supplies
        one, otherwise a generic type-appropriate placeholder."""
        for p in endpoint.get("parameters", []):
            if p["name"] == param_name and p.get("location") == "path":
                schema = p.get("schema") or {}
                if "example" in schema:
                    return str(schema["example"])
                if schema.get("type") == "integer":
                    return "1"
                break
        return f"sample-{param_name}"

    def _resolved_id_for(self, param_name: str, endpoint: dict) -> str:
        if param_name in self._shared_ids:
            return self._shared_ids[param_name]
        return self._placeholder_id(param_name, endpoint)

    def _substitute_path(self, path: str, endpoint: dict, skip_param: Optional[str] = None) -> str:
        """Replace every {param} in path with a resolved value, except
        `skip_param` (used for the destructive resource, which is left
        as the Postman-style '{{token}}' placeholder for the setup
        block to fill in at execution time — see Group 2)."""
        result = path
        for param_name in PATH_PARAM_RE.findall(path):
            if param_name == skip_param:
                result = result.replace("{" + param_name + "}", "{{token}}")
            else:
                result = result.replace(
                    "{" + param_name + "}", self._resolved_id_for(param_name, endpoint)
                )
        return result

    def _sample_body_for(self, request_body: dict | None) -> dict | None:
        if not request_body:
            return None
        return self._sample_from_schema(request_body.get("schema", {}))

    def _sample_from_schema(self, schema: dict) -> dict:
        """Generate a realistic sample object from a JSON schema.
        Prefers the spec's own `example`s; falls back to type-driven
        synthetic values. If a property name matches a path parameter
        we've already resolved a real ID for (e.g. a body's 'pet_id'
        matching the path parameter 'pet_id'), that real ID is reused
        so cross-references (like an order pointing at a pet) stay
        valid — a naming-convention match, not a hardcoded field name."""
        if "example" in schema and isinstance(schema["example"], dict):
            base = dict(schema["example"])
        else:
            base = {}

        if schema.get("type") != "object" or "properties" not in schema:
            return base

        sample = dict(base)
        for prop_name, prop_def in schema.get("properties", {}).items():
            if prop_name in self._shared_ids:
                sample[prop_name] = self._shared_ids[prop_name]
                continue
            if prop_name in sample:
                continue  # already covered by schema-level `example`
            sample[prop_name] = self._sample_scalar(prop_name, prop_def)
        return sample

    @staticmethod
    def _sample_scalar(prop_name: str, prop_def: dict) -> Any:
        if "example" in prop_def:
            return prop_def["example"]
        prop_type = prop_def.get("type", "string")
        if prop_type == "string":
            if "enum" in prop_def and prop_def["enum"]:
                return prop_def["enum"][0]
            min_len = prop_def.get("minLength", 0)
            value = f"test_{prop_name}"
            if len(value) < min_len:
                value += "x" * (min_len - len(value))
            return value
        if prop_type == "integer":
            return prop_def.get("minimum", 0) + 1
        if prop_type == "number":
            minimum = prop_def.get("minimum")
            return float(minimum) + 1.0 if minimum is not None else 100.0
        if prop_type == "boolean":
            return True
        if prop_type == "array":
            return ["test_item"]
        if prop_type == "object":
            return {}
        return None

    # ------------------------------------------------------------------
    # Boundary / invalid value derivation (spec-constraint-driven)
    # ------------------------------------------------------------------

    @staticmethod
    def _invalid_value_for(prop_def: dict) -> Optional[tuple[Any, str]]:
        """Return (invalid_value, human_description) that violates one
        of this property's own declared constraints, or None if the
        property has no constraint to violate."""
        if "enum" in prop_def and prop_def["enum"]:
            enum_vals = prop_def["enum"]
            invalid = "__contractiq_invalid_enum_value__"
            if invalid in enum_vals:
                invalid = invalid + "_2"
            return invalid, f"value outside declared enum {enum_vals}"

        prop_type = prop_def.get("type")
        if prop_type in ("integer", "number"):
            if "maximum" in prop_def:
                bump = 1 if prop_type == "integer" else 0.01
                return prop_def["maximum"] + bump, f"exceeds maximum of {prop_def['maximum']}"
            if "exclusiveMaximum" in prop_def and isinstance(prop_def["exclusiveMaximum"], (int, float)):
                return prop_def["exclusiveMaximum"], f"at/above exclusiveMaximum of {prop_def['exclusiveMaximum']}"
            if "minimum" in prop_def:
                bump = 1 if prop_type == "integer" else 0.01
                return prop_def["minimum"] - bump, f"below minimum of {prop_def['minimum']}"
            if "exclusiveMinimum" in prop_def and isinstance(prop_def["exclusiveMinimum"], (int, float)):
                return prop_def["exclusiveMinimum"], f"at/below exclusiveMinimum of {prop_def['exclusiveMinimum']}"
        if prop_type == "string":
            if "maxLength" in prop_def:
                return "x" * (prop_def["maxLength"] + 1), f"exceeds maxLength of {prop_def['maxLength']}"
            if "minLength" in prop_def and prop_def["minLength"] > 0:
                return "", f"shorter than minLength of {prop_def['minLength']}"
        return None

    def _boundary_test_cases(self, ep: dict, base_path: str) -> list[dict]:
        """One boundary/invalid-value test per constrained request-body
        property, but ONLY for endpoints whose spec actually declares a
        validation-error status — so we never assert an expectation
        the contract doesn't make, and test volume naturally scales
        with how richly-constrained the spec is."""
        cases: list[dict] = []
        request_body = ep.get("request_body")
        if not request_body:
            return cases

        validation_status = _declared_validation_status(ep)
        if validation_status is None:
            return cases

        schema = request_body.get("schema", {})
        properties = schema.get("properties", {})
        base_body = self._sample_body_for(request_body) or {}

        for idx, (prop_name, prop_def) in enumerate(properties.items(), start=1):
            invalid = self._invalid_value_for(prop_def)
            if invalid is None:
                continue
            invalid_value, reason = invalid
            body = dict(base_body)
            body[prop_name] = invalid_value

            cases.append({
                "test_id": f"{ep['operation_id']}_boundary_{idx:02d}",
                "name": f"Invalid '{prop_name}' for {ep['method']} {ep['path']}",
                "type": "edge_case",
                "description": f"Test with '{prop_name}' {reason}",
                "request": {
                    "method": ep["method"],
                    "path": base_path,
                    "headers": {"Content-Type": "application/json"},
                    "query_params": {},
                    "body": body,
                },
                "expected": {
                    "status_code": validation_status,
                    "response_body_contains": ["detail"],
                    "response_type": "json",
                },
            })
        return cases

    # ------------------------------------------------------------------
    # Test-case generation
    # ------------------------------------------------------------------

    @staticmethod
    def _response_type_for(ep: dict, status: int) -> str:
        """'empty' when the spec declares no response schema for this
        status (e.g. a 204), else 'json' — derived from the spec, not
        assumed from the HTTP method."""
        schema = _response_schema_for_status(ep, status)
        return "json" if schema else "empty"

    def _positive_test(self, ep: dict) -> dict:
        path = ep["path"]
        # DELETE gets a disposable resource of its own via a setup
        # block instead of sharing state with other tests.
        is_destructive = ep["method"] == "DELETE"
        delete_param = None
        if is_destructive:
            params_in_path = PATH_PARAM_RE.findall(path)
            delete_param = params_in_path[-1] if params_in_path else None

        resolved_path = self._substitute_path(path, ep, skip_param=delete_param)
        body = self._sample_body_for(ep.get("request_body"))

        test_case = {
            "test_id": f"{ep['operation_id']}_positive_01",
            "name": f"Valid {ep['method']} request to {ep['path']}",
            "type": "positive",
            "description": f"Test valid {ep['method']} request",
            "request": {
                "method": ep["method"],
                "path": resolved_path,
                "headers": {"Content-Type": "application/json"},
                "query_params": {},
                "body": body,
            },
            "expected": {
                "status_code": _primary_success_status(ep),
                "response_body_contains": [],
                "response_type": self._response_type_for(ep, _primary_success_status(ep)),
            },
        }

        if is_destructive and delete_param is not None:
            creator = self.creators.get(delete_param)
            if creator:
                test_case["setup"] = {
                    "method": creator["method"],
                    "path": creator["path"],
                    "body": self._sample_body_for(creator.get("request_body")) or {},
                    "capture": creator["capture"],
                }

        return test_case

    def _negative_id_test(self, ep: dict) -> Optional[dict]:
        params = PATH_PARAM_RE.findall(ep["path"])
        if not params:
            return None
        not_found_status = 404 if 404 in _status_codes(ep, "4") else None
        if not_found_status is None:
            return None

        path = ep["path"]
        for param_name in params:
            path = path.replace("{" + param_name + "}", "nonexistent-contractiq-999")

        return {
            "test_id": f"{ep['operation_id']}_negative_01",
            "name": f"Invalid ID for {ep['path']}",
            "type": "negative",
            "description": "Test with a non-existent resource ID",
            "request": {
                "method": ep["method"],
                "path": path,
                "headers": {"Content-Type": "application/json"},
                "query_params": {},
                "body": self._sample_body_for(ep.get("request_body")),
            },
            "expected": {
                "status_code": not_found_status,
                "response_body_contains": ["detail"],
                "response_type": "json",
            },
        }

    def _empty_body_test(self, ep: dict) -> Optional[dict]:
        if ep["method"] not in ("POST", "PUT", "PATCH") or not ep.get("request_body"):
            return None

        body_schema = (ep["request_body"].get("schema") or {})
        has_required_fields = bool(body_schema.get("required"))
        validation_status = _declared_validation_status(ep)

        if has_required_fields and validation_status is not None:
            expected_status = validation_status
            expected_contains = ["detail"]
            description = "Test with empty request body — expects a validation error"
        else:
            expected_status = _primary_success_status(ep)
            expected_contains = []
            description = (
                "Test with empty request body — no required fields, "
                "so this is a valid no-op"
            )

        return {
            "test_id": f"{ep['operation_id']}_edge_01",
            "name": f"Empty body for {ep['method']} {ep['path']}",
            "type": "edge_case",
            "description": description,
            "request": {
                "method": ep["method"],
                "path": self._substitute_path(ep["path"], ep),
                "headers": {"Content-Type": "application/json"},
                "query_params": {},
                "body": {},
            },
            "expected": {
                "status_code": expected_status,
                "response_body_contains": expected_contains,
                "response_type": "json",
            },
        }

    def generate_tests(self) -> dict:
        """Generate the full test_suites structure — the direct,
        spec-driven replacement for the old
        LangChainOrchestrator._generate_fallback_tests."""
        test_suites = []
        for ep in self.endpoints:
            suite = {
                "endpoint": f"{ep['method']} {ep['path']}",
                "operation_id": ep["operation_id"],
                "test_cases": [],
            }

            positive = self._positive_test(ep)
            suite["test_cases"].append(positive)

            negative = self._negative_id_test(ep)
            if negative:
                suite["test_cases"].append(negative)

            empty_body = self._empty_body_test(ep)
            if empty_body:
                suite["test_cases"].append(empty_body)
                suite["test_cases"].extend(
                    self._boundary_test_cases(ep, empty_body["request"]["path"])
                )
            elif ep.get("request_body"):
                suite["test_cases"].extend(
                    self._boundary_test_cases(ep, positive["request"]["path"])
                )

            test_suites.append(suite)

        return {"test_suites": test_suites}

    def generate_assertions(self, test_cases: dict) -> dict:
        """The direct, spec-driven replacement for the old
        LangChainOrchestrator._generate_fallback_assertions."""
        by_operation = {ep["operation_id"]: ep for ep in self.endpoints}
        assertions = []
        for suite in test_cases.get("test_suites", []):
            endpoint = by_operation.get(suite.get("operation_id"))
            for tc in suite.get("test_cases", []):
                assertions.append({
                    "test_id": tc["test_id"],
                    "assertions": self.assertion_synth.synthesize(tc, endpoint),
                })
        return {"assertions": assertions}
