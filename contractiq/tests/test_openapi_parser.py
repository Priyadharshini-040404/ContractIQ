"""
ContractIQ - Unit Tests for OpenAPI Parser
"""

import pytest
import json
import yaml
import tempfile
from pathlib import Path

from core.openapi_parser import OpenAPIParser, Endpoint, Parameter, RequestBody, Response


class TestOpenAPIParser:
    """Test suite for OpenAPI specification parsing."""

    def test_load_yaml_spec(self, spec_path):
        """Test loading a YAML OpenAPI spec."""
        parser = OpenAPIParser(spec_path)
        spec = parser.load_spec()
        assert spec is not None
        assert "openapi" in spec
        assert "paths" in spec
        assert "info" in spec

    def test_load_nonexistent_spec(self):
        """Test loading a nonexistent spec file raises error."""
        parser = OpenAPIParser("nonexistent.yaml")
        with pytest.raises(FileNotFoundError):
            parser.load_spec()

    def test_load_json_spec(self, tmp_path):
        """Test loading a JSON OpenAPI spec."""
        spec_data = {
            "openapi": "3.1.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {},
        }
        json_file = tmp_path / "spec.json"
        json_file.write_text(json.dumps(spec_data))

        parser = OpenAPIParser(str(json_file))
        spec = parser.load_spec()
        assert spec["info"]["title"] == "Test API"

    def test_get_api_info(self, spec_path):
        """Test extracting API metadata."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        info = parser.get_api_info()

        assert "title" in info
        assert "version" in info
        assert "description" in info
        assert "openapi_version" in info
        assert info["title"] == "ContractIQ PetStore API"
        assert info["version"] == "1.0.0"

    def test_parse_endpoints(self, spec_path):
        """Test parsing all endpoints."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        endpoints = parser.parse_endpoints()

        assert len(endpoints) > 0
        assert all(isinstance(ep, Endpoint) for ep in endpoints)

        # Check we have various HTTP methods
        methods = set(ep.method for ep in endpoints)
        assert "GET" in methods
        assert "POST" in methods

    def test_endpoint_has_required_fields(self, spec_path):
        """Test that parsed endpoints have all required fields."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        endpoints = parser.parse_endpoints()

        for ep in endpoints:
            assert ep.path, "Endpoint path should not be empty"
            assert ep.method, "Endpoint method should not be empty"
            assert ep.operation_id, "Operation ID should not be empty"
            assert isinstance(ep.parameters, list)
            assert isinstance(ep.responses, list)
            assert len(ep.responses) > 0, "Each endpoint should have at least one response"

    def test_parse_parameters(self, spec_path):
        """Test parsing endpoint parameters."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        endpoints = parser.parse_endpoints()

        # Find GET /api/v1/pets which should have query params
        list_pets = [ep for ep in endpoints if ep.path == "/api/v1/pets" and ep.method == "GET"]
        assert len(list_pets) == 1

        ep = list_pets[0]
        assert len(ep.parameters) > 0
        param_names = [p.name for p in ep.parameters]
        assert "limit" in param_names
        assert "offset" in param_names

    def test_parse_request_body(self, spec_path):
        """Test parsing request body schemas."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        endpoints = parser.parse_endpoints()

        # Find POST /api/v1/pets which should have a request body
        create_pet = [ep for ep in endpoints if ep.path == "/api/v1/pets" and ep.method == "POST"]
        assert len(create_pet) == 1

        ep = create_pet[0]
        assert ep.request_body is not None
        assert ep.request_body.content_type == "application/json"
        assert "properties" in ep.request_body.schema or "type" in ep.request_body.schema

    def test_parse_responses(self, spec_path):
        """Test parsing response definitions."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        endpoints = parser.parse_endpoints()

        for ep in endpoints:
            for resp in ep.responses:
                assert resp.status_code, "Status code should not be empty"
                assert resp.description, "Description should not be empty"

    def test_extract_schemas(self, spec_path):
        """Test extracting component schemas."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        schemas = parser.extract_schemas()

        assert len(schemas) > 0
        assert "PetCreate" in schemas
        assert "Pet" in schemas
        assert "OrderCreate" in schemas
        assert "HealthResponse" in schemas

    def test_resolve_refs(self, spec_path):
        """Test that $ref references are resolved."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        parser.parse_endpoints()

        # PetCreate should be fully resolved (no $ref left)
        pet_create = parser.schemas.get("PetCreate", {})
        assert "$ref" not in json.dumps(pet_create)

    def test_endpoint_to_dict(self, spec_path):
        """Test endpoint serialization to dict."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        endpoints = parser.parse_endpoints()

        for ep in endpoints:
            d = ep.to_dict()
            assert "path" in d
            assert "method" in d
            assert "operation_id" in d
            assert "parameters" in d
            assert "responses" in d

    def test_get_endpoint_summary(self, spec_path):
        """Test getting endpoint summary for AI prompting."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        parser.parse_endpoints()
        summary = parser.get_endpoint_summary()

        assert isinstance(summary, list)
        assert len(summary) > 0
        assert all(isinstance(s, dict) for s in summary)

    def test_to_prompt_context(self, spec_path):
        """Test generating prompt context."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        parser.parse_endpoints()
        context = parser.to_prompt_context()

        assert isinstance(context, str)
        assert "API:" in context
        assert "Endpoints:" in context
        assert "GET" in context
        assert "POST" in context

    def test_get_schema_definitions(self, spec_path):
        """Test schema definitions formatting."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        parser.parse_endpoints()
        defs = parser.get_schema_definitions()

        assert isinstance(defs, str)
        assert "Schema:" in defs
        assert "Properties:" in defs

    def test_server_url_extraction(self, spec_path):
        """Test server URL extraction."""
        parser = OpenAPIParser(spec_path)
        parser.load_spec()
        parser.parse_endpoints()

        assert parser.server_url == "http://localhost:8000"
