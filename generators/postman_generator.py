"""
ContractIQ - Postman Collection Generator
Converts AI-generated test cases into executable Postman Collection v2.1 JSON format.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PATH_PARAM_RE = re.compile(r"\{([^{}]+)\}")
# Matches a single-brace {param} placeholder while explicitly NOT
# matching the inner "{token}" that appears inside a Postman-style
# "{{token}}" collection-variable reference (used by setup blocks —
# see _build_prerequest_script). The lookarounds require the opening
# brace not be preceded by another '{' and the closing brace not be
# followed by another '}'.
SINGLE_BRACE_PARAM_RE = re.compile(r"(?<!\{)\{([^{}]+)\}(?!\})")


class PostmanCollectionGenerator:
    """Generates Postman Collection v2.1 JSON from test suite data."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.collection_id = str(uuid.uuid4())

    def generate_collection(self, pipeline_result: dict) -> dict:
        """Generate a complete Postman Collection from pipeline results."""
        collection = {
            "info": {
                "_postman_id": self.collection_id,
                "name": f"ContractIQ - {pipeline_result.get('api_info', {}).get('title', 'API')} Tests",
                "description": (
                    f"Auto-generated test collection by ContractIQ\n"
                    f"API: {pipeline_result.get('api_info', {}).get('title', 'Unknown')}\n"
                    f"Version: {pipeline_result.get('api_info', {}).get('version', '1.0.0')}\n"
                    f"Generated: {datetime.now(timezone.utc).isoformat()}"
                ),
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
            },
            "item": [],
            "variable": [
                {"key": "base_url", "value": self.base_url, "type": "string"},
                {"key": "token", "value": "", "type": "string"},
            ],
            "event": [
                {
                    "listen": "prerequest",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            "// ContractIQ Pre-request Script",
                            "console.log('Running: ' + pm.info.requestName);",
                        ]
                    }
                }
            ]
        }

        # Build assertions lookup
        assertions_map = {}
        for assertion_group in pipeline_result.get("assertions", []):
            test_id = assertion_group.get("test_id", "")
            assertions_map[test_id] = assertion_group.get("assertions", [])

        # Group test cases by endpoint into folders
        for suite in pipeline_result.get("test_suites", []):
            folder = {
                "name": suite.get("endpoint", "Unknown Endpoint"),
                "description": f"Tests for {suite.get('endpoint', '')}",
                "item": []
            }

            for tc in suite.get("test_cases", []):
                request_item = self._build_request_item(tc, assertions_map)
                folder["item"].append(request_item)

            collection["item"].append(folder)

        return collection

    def _build_request_item(self, test_case: dict, assertions_map: dict) -> dict:
        """Build a single Postman request item from a test case."""
        request_data = test_case.get("request", {})
        method = request_data.get("method", "GET")
        path = request_data.get("path", "/")

        # Build URL
        url_parts = self._parse_url(path, request_data.get("query_params", {}))

        # Build request
        request = {
            "method": method,
            "header": [
                {"key": k, "value": v}
                for k, v in request_data.get("headers", {}).items()
            ],
            "url": url_parts,
        }

        # Add body for POST/PUT/PATCH
        body = request_data.get("body")
        if body is not None and method in ("POST", "PUT", "PATCH"):
            request["body"] = {
                "mode": "raw",
                "raw": json.dumps(body, indent=2),
                "options": {
                    "raw": {"language": "json"}
                }
            }

        # Build test scripts from assertions
        test_script = self._build_test_script(test_case, assertions_map)

        # Build pre-request scripts for dynamic data
        pre_request_script = self._build_prerequest_script(test_case)

        item = {
            "name": f"[{test_case.get('type', 'test').upper()}] {test_case.get('name', 'Unnamed')}",
            "request": request,
            "response": [],
            "event": []
        }

        if test_script:
            item["event"].append({
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": test_script
                }
            })

        if pre_request_script:
            item["event"].append({
                "listen": "prerequest",
                "script": {
                    "type": "text/javascript",
                    "exec": pre_request_script
                }
            })

        return item

    def _parse_url(self, path: str, query_params: dict) -> dict:
        """Parse URL into Postman URL structure.

        Replaces EVERY single-brace {param} placeholder with Postman's
        `:param` path-variable syntax via a generic regex — works for
        any parameter name in any API, not just pet_id/order_id. The
        Postman-style "{{token}}" placeholder used by destructive
        tests' setup blocks is left untouched (it's already valid
        Postman collection-variable syntax, filled in by the
        pre-request script — see _build_prerequest_script)."""
        postman_path = path
        for param in SINGLE_BRACE_PARAM_RE.findall(path):
            postman_path = postman_path.replace("{" + param + "}", f":{param}")

        url_obj = {
            "raw": f"{{{{base_url}}}}{postman_path}",
            "host": ["{{base_url}}"],
            "path": [p for p in postman_path.lstrip("/").split("/") if p],
        }

        if query_params:
            url_obj["query"] = [
                {"key": k, "value": str(v)} for k, v in query_params.items()
            ]

        return url_obj

    def _build_test_script(self, test_case: dict, assertions_map: dict) -> list[str]:
        """Build Postman test script from assertions."""
        test_id = test_case.get("test_id", "")
        expected = test_case.get("expected", {})
        lines = [
            f"// ContractIQ Auto-Generated Tests for: {test_case.get('name', '')}",
            f"// Test Type: {test_case.get('type', 'unknown')}",
            "",
        ]

        # Status code assertion
        status = expected.get("status_code", 200)
        lines.append(f'pm.test("Status code is {status}", function () {{')
        lines.append(f"    pm.response.to.have.status({status});")
        lines.append("});")
        lines.append("")

        # Response time assertion
        lines.append('pm.test("Response time is acceptable", function () {')
        lines.append("    pm.expect(pm.response.responseTime).to.be.below(5000);")
        lines.append("});")
        lines.append("")

        # JSON response validation — 204 No Content correctly has no body,
        # so never assert JSON there even though it's a 2xx status.
        if expected.get("response_type") == "json" and status < 300 and status != 204:
            lines.append('pm.test("Response is valid JSON", function () {')
            lines.append("    pm.response.to.be.json;")
            lines.append("    var jsonData = pm.response.json();")
            lines.append("    pm.expect(jsonData).to.not.be.null;")
            lines.append("});")
            lines.append("")

        # Custom assertions from AI
        custom_assertions = assertions_map.get(test_id, [])
        for assertion in custom_assertions:
            script = self._assertion_to_script(assertion)
            if script:
                lines.extend(script)
                lines.append("")

        # Store dynamic values for chaining — generic across any
        # resource type, derived from the request path itself (e.g.
        # POST /api/v1/pets -> collection variable "pets_id") rather
        # than a hardcoded "pet_id".
        request_path = test_case.get("request", {}).get("path", "")
        if test_case.get("type") == "positive" and test_case.get("request", {}).get("method") == "POST":
            var_name = self._infer_resource_var(request_path)
            success_status = expected.get("status_code", 201)
            lines.append("// Store created resource ID for subsequent tests")
            lines.append(f"if (pm.response.code === {success_status}) {{")
            lines.append("    var jsonData = pm.response.json();")
            lines.append("    if (jsonData.id) {")
            lines.append(f'        pm.collectionVariables.set("{var_name}", jsonData.id);')
            lines.append("    }")
            lines.append("}")

        return lines

    @staticmethod
    def _infer_resource_var(path: str) -> str:
        """Derive a collection-variable name for a resource created at
        this path — e.g. '/api/v1/pets' -> 'pets_id'. Purely
        string-based on the path itself, no knowledge of any specific
        API's resource names."""
        segments = [p for p in path.split("/") if p and not p.startswith(("{", ":"))]
        resource = segments[-1] if segments else "resource"
        return f"{resource}_id"

    def _assertion_to_script(self, assertion: dict) -> list[str] | None:
        """Convert a single assertion to Postman test script."""
        a_type = assertion.get("type", "")
        operator = assertion.get("operator", "")
        field = assertion.get("field", "")
        expected = assertion.get("expected_value")
        desc = assertion.get("description", "Assertion check")

        lines = [f'pm.test("{desc}", function () {{']

        if a_type == "response_body" and field:
            lines.append("    var jsonData = pm.response.json();")
            if operator == "exists":
                lines.append(f'    pm.expect(jsonData).to.have.property("{field}");')
            elif operator == "not_null":
                lines.append(f'    pm.expect(jsonData.{field}).to.not.be.null;')
            elif operator == "equals":
                if isinstance(expected, str):
                    lines.append(f'    pm.expect(jsonData.{field}).to.eql("{expected}");')
                else:
                    lines.append(f"    pm.expect(jsonData.{field}).to.eql({json.dumps(expected)});")
            elif operator == "type_check":
                lines.append(f'    pm.expect(typeof jsonData.{field}).to.eql("{expected}");')
            elif operator == "contains":
                lines.append(f'    pm.expect(JSON.stringify(jsonData)).to.include("{expected}");')
            else:
                lines.append(f"    // Custom: {operator} check on {field}")
                lines.append(f"    pm.expect(jsonData).to.not.be.undefined;")
        elif a_type == "header":
            if operator == "exists":
                lines.append(f'    pm.response.to.have.header("{field}");')
            else:
                lines.append(f'    pm.expect(pm.response.headers.get("{field}")).to.eql("{expected}");')
        elif a_type == "schema_validation":
            lines.append("    var jsonData = pm.response.json();")
            lines.append("    pm.expect(jsonData).to.be.an('object');")
        else:
            return None

        lines.append("});")
        return lines

    def _build_prerequest_script(self, test_case: dict) -> list[str]:
        """Build the pre-request script for a test case.

        When the test case carries a "setup" block (emitted by
        core/test_synthesizer.py for destructive tests — see Group 2),
        this creates the resource via pm.sendRequest() and stores the
        captured ID as the "token" collection variable *before* the
        actual request fires, so "{{token}}" in the request URL
        resolves to a fresh, currently-valid resource on every run —
        instead of a fixed ID a previous run already consumed."""
        setup = test_case.get("setup")
        if setup:
            method = setup.get("method", "POST")
            path = setup.get("path", "/")
            body = json.dumps(setup.get("body") or {})
            capture_field = setup.get("capture", "id")

            return [
                "// ContractIQ: create a disposable resource for this",
                "// destructive test so it doesn't depend on state a",
                "// previous run left behind.",
                "var setupRequest = {",
                f"    url: pm.collectionVariables.get('base_url') + '{path}',",
                f"    method: '{method}',",
                "    header: { 'Content-Type': 'application/json' },",
                "    body: {",
                "        mode: 'raw',",
                f"        raw: JSON.stringify({body})",
                "    }",
                "};",
                "",
                "pm.sendRequest(setupRequest, function (err, res) {",
                "    if (err) {",
                "        console.warn('ContractIQ setup request failed: ' + err);",
                "        return;",
                "    }",
                "    var json = res.json();",
                f"    if (json && json['{capture_field}'] !== undefined) {{",
                f"        pm.collectionVariables.set('token', String(json['{capture_field}']));",
                "    } else {",
                "        console.warn('ContractIQ setup response missing capture field "
                f"\"{capture_field}\"');",
                "    }",
                "});",
            ]

        # No setup block — fall back to a generic readiness check for
        # any collection variable this test's path references, purely
        # from the path text itself (never a hardcoded field name).
        lines = []
        request = test_case.get("request", {})
        path = request.get("path", "")
        for var_name in re.findall(r"\{\{(\w+)\}\}", path):
            lines.append(f"var _v_{var_name} = pm.collectionVariables.get('{var_name}');")
            lines.append(f"if (!_v_{var_name}) {{")
            lines.append(f'    console.warn("{var_name} not set - test may fail");')
            lines.append("}")

        return lines

    def save_collection(self, collection: dict, output_path: str = "output/postman_collection.json") -> str:
        """Save the Postman collection to a JSON file."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(collection, indent=2))
        return str(output.resolve())

    def generate_and_save(self, pipeline_result: dict, output_path: str = "output/postman_collection.json") -> dict:
        """Generate and save the complete Postman collection."""
        collection = self.generate_collection(pipeline_result)
        saved_path = self.save_collection(collection, output_path)

        stats = {
            "collection_name": collection["info"]["name"],
            "total_folders": len(collection["item"]),
            "total_requests": sum(len(f.get("item", [])) for f in collection["item"]),
            "output_path": saved_path,
        }
        return stats
