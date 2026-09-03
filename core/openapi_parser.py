"""
ContractIQ - OpenAPI Specification Parser
Parses OpenAPI specs (.yaml/.json) and extracts endpoint definitions,
schemas, parameters, and request/response structures.
"""

import yaml
import json
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field


@dataclass
class Parameter:
    """Represents an API parameter."""
    name: str
    location: str  # query, path, header
    required: bool
    schema: dict
    description: str = ""


@dataclass
class RequestBody:
    """Represents an API request body."""
    required: bool
    content_type: str
    schema: dict


@dataclass
class Response:
    """Represents an API response."""
    status_code: str
    description: str
    schema: dict = field(default_factory=dict)


@dataclass
class Endpoint:
    """Represents a parsed API endpoint."""
    path: str
    method: str
    operation_id: str
    summary: str
    tags: list
    parameters: list[Parameter]
    request_body: RequestBody | None
    responses: list[Response]

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "method": self.method,
            "operation_id": self.operation_id,
            "summary": self.summary,
            "tags": self.tags,
            "parameters": [
                {"name": p.name, "location": p.location,
                 "required": p.required, "schema": p.schema, "description": p.description}
                for p in self.parameters
            ],
            "request_body": {
                "required": self.request_body.required,
                "content_type": self.request_body.content_type,
                "schema": self.request_body.schema
            } if self.request_body else None,
            "responses": [
                {"status_code": r.status_code, "description": r.description, "schema": r.schema}
                for r in self.responses
            ]
        }


class OpenAPIParser:
    """Parses OpenAPI 3.x specifications and extracts structured endpoint data."""

    def __init__(self, spec_path: str):
        self.spec_path = Path(spec_path)
        self.spec: dict = {}
        self.endpoints: list[Endpoint] = []
        self.schemas: dict = {}
        self.server_url: str = ""

    def load_spec(self) -> dict:
        """Load OpenAPI spec from YAML or JSON file."""
        if not self.spec_path.exists():
            raise FileNotFoundError(f"OpenAPI spec not found: {self.spec_path}")

        content = self.spec_path.read_text()

        if self.spec_path.suffix in ('.yaml', '.yml'):
            self.spec = yaml.safe_load(content)
        elif self.spec_path.suffix == '.json':
            self.spec = json.loads(content)
        else:
            # Try YAML first, then JSON
            try:
                self.spec = yaml.safe_load(content)
            except yaml.YAMLError:
                self.spec = json.loads(content)

        return self.spec

    def get_api_info(self) -> dict:
        """Extract API metadata."""
        info = self.spec.get("info", {})
        return {
            "title": info.get("title", "Unknown API"),
            "version": info.get("version", "0.0.0"),
            "description": info.get("description", ""),
            "openapi_version": self.spec.get("openapi", "unknown"),
        }

    def _resolve_ref(self, ref_or_schema: dict) -> dict:
        """Resolve $ref references in the spec."""
        if not isinstance(ref_or_schema, dict):
            return ref_or_schema

        if "$ref" not in ref_or_schema:
            # Resolve nested refs in properties, items, allOf, etc.
            resolved = {}
            for key, value in ref_or_schema.items():
                if key == "allOf" and isinstance(value, list):
                    merged = {}
                    for item in value:
                        resolved_item = self._resolve_ref(item)
                        if "properties" in resolved_item:
                            merged.setdefault("properties", {}).update(resolved_item["properties"])
                        if "required" in resolved_item:
                            merged.setdefault("required", []).extend(resolved_item["required"])
                        merged["type"] = resolved_item.get("type", merged.get("type", "object"))
                    return merged
                elif key == "properties" and isinstance(value, dict):
                    resolved[key] = {
                        k: self._resolve_ref(v) for k, v in value.items()
                    }
                elif key == "items" and isinstance(value, dict):
                    resolved[key] = self._resolve_ref(value)
                else:
                    resolved[key] = value
            return resolved

        ref_path = ref_or_schema["$ref"]
        parts = ref_path.lstrip("#/").split("/")
        result = self.spec
        for part in parts:
            result = result.get(part, {})
        return self._resolve_ref(result)  # Recurse to resolve nested refs

    def extract_schemas(self) -> dict:
        """Extract and resolve all component schemas."""
        components = self.spec.get("components", {})
        raw_schemas = components.get("schemas", {})
        self.schemas = {
            name: self._resolve_ref(schema)
            for name, schema in raw_schemas.items()
        }
        return self.schemas

    def parse_endpoints(self) -> list[Endpoint]:
        """Parse all endpoints from the spec."""
        self.extract_schemas()

        servers = self.spec.get("servers", [])
        self.server_url = servers[0]["url"] if servers else "http://localhost:8000"

        paths = self.spec.get("paths", {})
        self.endpoints = []

        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    continue

                # Parse parameters
                parameters = []
                for param in operation.get("parameters", []):
                    param_schema = self._resolve_ref(param.get("schema", {}))
                    parameters.append(Parameter(
                        name=param.get("name", ""),
                        location=param.get("in", "query"),
                        required=param.get("required", False),
                        schema=param_schema,
                        description=param.get("description", ""),
                    ))

                # Parse request body
                request_body = None
                rb = operation.get("requestBody")
                if rb:
                    content = rb.get("content", {})
                    for content_type, ct_data in content.items():
                        schema = self._resolve_ref(ct_data.get("schema", {}))
                        request_body = RequestBody(
                            required=rb.get("required", False),
                            content_type=content_type,
                            schema=schema,
                        )
                        break  # Take first content type

                # Parse responses
                responses = []
                for status, resp_data in operation.get("responses", {}).items():
                    resp_schema = {}
                    resp_content = resp_data.get("content", {})
                    for ct, ct_data in resp_content.items():
                        resp_schema = self._resolve_ref(ct_data.get("schema", {}))
                        break
                    responses.append(Response(
                        status_code=str(status),
                        description=resp_data.get("description", ""),
                        schema=resp_schema,
                    ))

                endpoint = Endpoint(
                    path=path,
                    method=method.upper(),
                    operation_id=operation.get("operationId", f"{method}_{path}"),
                    summary=operation.get("summary", ""),
                    tags=operation.get("tags", []),
                    parameters=parameters,
                    request_body=request_body,
                    responses=responses,
                )
                self.endpoints.append(endpoint)

        return self.endpoints

    def get_endpoint_summary(self) -> list[dict]:
        """Get a simplified summary of all endpoints for AI prompting."""
        return [ep.to_dict() for ep in self.endpoints]

    def get_schema_definitions(self) -> str:
        """Get formatted schema definitions for AI context."""
        lines = []
        for name, schema in self.schemas.items():
            lines.append(f"\n### Schema: {name}")
            lines.append(f"Type: {schema.get('type', 'object')}")
            if "properties" in schema:
                lines.append("Properties:")
                for prop_name, prop_def in schema["properties"].items():
                    prop_type = prop_def.get("type", "any")
                    constraints = []
                    for c in ["minimum", "maximum", "minLength", "maxLength", "enum"]:
                        if c in prop_def:
                            constraints.append(f"{c}={prop_def[c]}")
                    constraint_str = f" ({', '.join(constraints)})" if constraints else ""
                    required = "required" if prop_name in schema.get("required", []) else "optional"
                    lines.append(f"  - {prop_name}: {prop_type}{constraint_str} [{required}]")
        return "\n".join(lines)

    def to_prompt_context(self) -> str:
        """Generate a formatted context string for AI prompts."""
        info = self.get_api_info()
        context = f"""API: {info['title']} v{info['version']}
Base URL: {self.server_url}
Description: {info['description']}

## Endpoints:
"""
        for ep in self.endpoints:
            context += f"\n### {ep.method} {ep.path}"
            context += f"\nSummary: {ep.summary}"
            context += f"\nOperation ID: {ep.operation_id}"
            if ep.parameters:
                context += "\nParameters:"
                for p in ep.parameters:
                    context += f"\n  - {p.name} ({p.location}, {'required' if p.required else 'optional'}): {json.dumps(p.schema)}"
            if ep.request_body:
                context += f"\nRequest Body ({ep.request_body.content_type}):"
                context += f"\n  Schema: {json.dumps(ep.request_body.schema, indent=2)}"
            context += "\nResponses:"
            for r in ep.responses:
                context += f"\n  {r.status_code}: {r.description}"
                if r.schema:
                    context += f"\n    Schema: {json.dumps(r.schema, indent=2)}"

        context += "\n\n## Schema Definitions:"
        context += self.get_schema_definitions()

        return context
