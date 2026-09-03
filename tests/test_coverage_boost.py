"""
ContractIQ - Additional tests to ensure ≥80% code coverage.
"""

import pytest
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from execution.test_runner import DirectTestRunner, AllureReportGenerator, NewmanRunner
from validators.contract_validator import ContractValidator, SchemathesisValidator, DreddValidator
from reports.failure_analyzer import FailureAnalyzer
from generators.postman_generator import PostmanCollectionGenerator
from core.langchain_orchestrator import LangChainOrchestrator


class TestDirectTestRunnerExecution:
    """More tests for DirectTestRunner to cover execution paths."""

    def test_execute_single_get_test(self, api_client):
        """Test executing a GET test against running API."""
        runner = DirectTestRunner(base_url="http://testserver")
        # Use test client session
        runner.session = api_client

        test_case = {
            "test_id": "test_get_health",
            "name": "Health check",
            "type": "positive",
            "request": {
                "method": "GET",
                "path": "/health",
                "headers": {"Content-Type": "application/json"},
                "query_params": {},
                "body": None,
            },
            "expected": {
                "status_code": 200,
                "response_body_contains": ["status"],
                "response_type": "json",
            },
        }

        result = runner._execute_test(test_case, {})
        assert result["status"] == "passed"
        assert result["actual_status_code"] == 200
        assert result["response_time_ms"] > 0

    def test_execute_post_test(self, api_client):
        """Test executing a POST test."""
        runner = DirectTestRunner(base_url="http://testserver")
        runner.session = api_client

        test_case = {
            "test_id": "test_create_pet",
            "name": "Create pet",
            "type": "positive",
            "request": {
                "method": "POST",
                "path": "/api/v1/pets",
                "headers": {"Content-Type": "application/json"},
                "query_params": {},
                "body": {"name": "Rover", "species": "Dog", "age": 3, "price": 200.0},
            },
            "expected": {
                "status_code": 201,
                "response_body_contains": ["id", "name"],
                "response_type": "json",
            },
        }

        result = runner._execute_test(test_case, {})
        assert result["status"] == "passed"
        assert result["actual_status_code"] == 201
        assert "id" in result["response_body"]

    def test_execute_negative_test(self, api_client):
        """Test executing a negative test case."""
        runner = DirectTestRunner(base_url="http://testserver")
        runner.session = api_client

        test_case = {
            "test_id": "test_get_missing",
            "name": "Get missing pet",
            "type": "negative",
            "request": {
                "method": "GET",
                "path": "/api/v1/pets/nonexistent",
                "headers": {},
                "query_params": {},
                "body": None,
            },
            "expected": {
                "status_code": 404,
                "response_body_contains": ["detail"],
                "response_type": "json",
            },
        }

        result = runner._execute_test(test_case, {})
        assert result["status"] == "passed"
        assert result["actual_status_code"] == 404

    def test_execute_failed_assertion(self, api_client):
        """Test a case where assertion fails (wrong expected status)."""
        runner = DirectTestRunner(base_url="http://testserver")
        runner.session = api_client

        test_case = {
            "test_id": "test_wrong_status",
            "name": "Wrong expected status",
            "type": "negative",
            "request": {
                "method": "GET",
                "path": "/health",
                "headers": {},
                "query_params": {},
                "body": None,
            },
            "expected": {
                "status_code": 404,  # Incorrect — will fail
                "response_body_contains": [],
                "response_type": "json",
            },
        }

        result = runner._execute_test(test_case, {})
        assert result["status"] == "failed"

    def test_execute_connection_error(self):
        """Test handling connection errors."""
        runner = DirectTestRunner(base_url="http://localhost:19999")
        test_case = {
            "test_id": "test_conn_err",
            "name": "Connection error",
            "type": "positive",
            "request": {
                "method": "GET",
                "path": "/health",
                "headers": {},
                "query_params": {},
                "body": None,
            },
            "expected": {"status_code": 200, "response_body_contains": [], "response_type": "json"},
        }

        result = runner._execute_test(test_case, {})
        assert result["status"] == "error"
        assert "error" in result

    def test_execute_full_suite(self, api_client):
        """Test full suite execution with stored IDs."""
        runner = DirectTestRunner(base_url="http://testserver")
        runner.session = api_client

        pipeline = {
            "test_suites": [{
                "endpoint": "POST /api/v1/pets",
                "operation_id": "create_pet",
                "test_cases": [{
                    "test_id": "create_01",
                    "name": "Create",
                    "type": "positive",
                    "request": {
                        "method": "POST",
                        "path": "/api/v1/pets",
                        "headers": {"Content-Type": "application/json"},
                        "query_params": {},
                        "body": {"name": "X", "species": "Cat", "age": 1, "price": 50.0},
                    },
                    "expected": {"status_code": 201, "response_body_contains": ["id"], "response_type": "json"},
                }],
            }]
        }

        results = runner.execute_test_suite(pipeline)
        assert results["total_tests"] == 1
        assert results["passed"] == 1
        assert "50.0%" not in results["pass_rate"]  # Should be 100%

    def test_missing_body_field_assertion(self, api_client):
        """Test response_contains assertion for missing field."""
        runner = DirectTestRunner(base_url="http://testserver")
        runner.session = api_client

        test_case = {
            "test_id": "test_missing_field",
            "name": "Missing field check",
            "type": "positive",
            "request": {
                "method": "GET",
                "path": "/health",
                "headers": {},
                "query_params": {},
                "body": None,
            },
            "expected": {
                "status_code": 200,
                "response_body_contains": ["nonexistent_field"],
                "response_type": "json",
            },
        }

        result = runner._execute_test(test_case, {})
        assert result["status"] == "failed"


class TestNewmanRunner:
    """Tests for the Newman runner."""

    def test_newman_not_installed(self, tmp_path):
        runner = NewmanRunner(str(tmp_path / "fake.json"))
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = runner.run_collection()
            assert result["status"] == "skipped"

    def test_newman_summary_extraction(self):
        runner = NewmanRunner("fake.json")
        report = {
            "run": {
                "stats": {
                    "requests": {"total": 10, "failed": 2},
                    "assertions": {"total": 30, "failed": 5},
                },
                "timings": {"completed": 1500, "responseAverage": 150},
            }
        }
        summary = runner._extract_summary(report)
        assert summary["total_requests"] == 10
        assert summary["failed_requests"] == 2
        assert summary["total_assertions"] == 30


class TestContractValidatorExtended:
    """Extended contract validator tests."""

    def test_schemathesis_run_not_installed(self, spec_path):
        validator = SchemathesisValidator(spec_path)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = validator.run_validation()
            assert result["status"] == "skipped"

    def test_schemathesis_run_timeout(self, spec_path):
        import subprocess
        validator = SchemathesisValidator(spec_path)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 120)):
            result = validator.run_validation()
            assert result["status"] == "timeout"

    def test_dredd_run_not_installed(self, spec_path):
        validator = DreddValidator(spec_path)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = validator.run_validation()
            assert result["status"] == "skipped"

    def test_dredd_run_timeout(self, spec_path):
        import subprocess
        validator = DreddValidator(spec_path)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 120)):
            result = validator.run_validation()
            assert result["status"] == "timeout"

    def test_live_validation_all_skipped(self, spec_path):
        validator = ContractValidator(spec_path)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = validator.run_live_validation()
            assert result["overall_status"] in ("partial", "unknown")

    def test_enum_validation(self, spec_path):
        from unittest.mock import MagicMock

        validator = ContractValidator(spec_path)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "invalid_value"}

        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["available", "pending", "sold"]}
            }
        }

        result = validator.validate_response_against_schema(mock_resp, schema)
        assert result["valid"] is False
        assert any("enum" in i.lower() for i in result["issues"])

    def test_non_json_response_validation(self, spec_path):
        from unittest.mock import MagicMock

        validator = ContractValidator(spec_path)
        mock_resp = MagicMock()
        mock_resp.json.side_effect = Exception("Not JSON")

        result = validator.validate_response_against_schema(mock_resp, {"type": "object"})
        assert result["valid"] is False

    def test_non_json_response_no_schema(self, spec_path):
        from unittest.mock import MagicMock

        validator = ContractValidator(spec_path)
        mock_resp = MagicMock()
        mock_resp.json.side_effect = Exception("Not JSON")

        result = validator.validate_response_against_schema(mock_resp, {})
        assert result["valid"] is True

    def test_type_matches_helper(self):
        assert ContractValidator._type_matches("hello", "string") is True
        assert ContractValidator._type_matches(42, "integer") is True
        assert ContractValidator._type_matches(3.14, "number") is True
        assert ContractValidator._type_matches(True, "boolean") is True
        assert ContractValidator._type_matches([], "array") is True
        assert ContractValidator._type_matches({}, "object") is True
        assert ContractValidator._type_matches("hello", "integer") is False
        assert ContractValidator._type_matches("hello", "unknown_type") is True


class TestFailureAnalyzerExtended:
    """Extended failure analysis tests."""

    def test_422_failure_analysis(self):
        analyzer = FailureAnalyzer()
        failure = {
            "test_id": "test_422",
            "test_name": "Validation error",
            "actual_status_code": 422,
            "assertions": [
                {"type": "status_code", "expected": 201, "actual": 422, "passed": False}
            ],
        }
        result = analyzer._rule_based_analyze(failure)
        assert result["severity"] == "medium"
        assert "validation" in result["root_cause"].lower()

    def test_missing_field_failure(self):
        analyzer = FailureAnalyzer()
        failure = {
            "test_id": "test_field",
            "test_name": "Missing field",
            "actual_status_code": 200,
            "assertions": [
                {"type": "response_contains", "field": "missing_field", "passed": False}
            ],
        }
        result = analyzer._rule_based_analyze(failure)
        assert "missing_field" in result["root_cause"]

    def test_generic_status_failure(self):
        analyzer = FailureAnalyzer()
        failure = {
            "test_id": "test_generic",
            "test_name": "Generic",
            "actual_status_code": 403,
            "assertions": [
                {"type": "status_code", "expected": 200, "actual": 403, "passed": False}
            ],
        }
        result = analyzer._rule_based_analyze(failure)
        assert "403" in result["root_cause"]


class TestPostmanGeneratorExtended:
    """Extended Postman generator tests."""

    def test_assertion_to_script_exists(self):
        gen = PostmanCollectionGenerator()
        assertion = {
            "type": "response_body", "field": "name",
            "operator": "exists", "expected_value": None,
            "description": "Name field should exist"
        }
        script = gen._assertion_to_script(assertion)
        assert script is not None
        assert any("property" in line for line in script)

    def test_assertion_to_script_not_null(self):
        gen = PostmanCollectionGenerator()
        assertion = {
            "type": "response_body", "field": "id",
            "operator": "not_null", "expected_value": None,
            "description": "ID should not be null"
        }
        script = gen._assertion_to_script(assertion)
        assert script is not None

    def test_assertion_to_script_equals_string(self):
        gen = PostmanCollectionGenerator()
        assertion = {
            "type": "response_body", "field": "status",
            "operator": "equals", "expected_value": "healthy",
            "description": "Status should be healthy"
        }
        script = gen._assertion_to_script(assertion)
        assert script is not None
        assert any("healthy" in line for line in script)

    def test_assertion_to_script_header(self):
        gen = PostmanCollectionGenerator()
        assertion = {
            "type": "header", "field": "Content-Type",
            "operator": "exists", "expected_value": None,
            "description": "Content-Type header should exist"
        }
        script = gen._assertion_to_script(assertion)
        assert script is not None

    def test_assertion_to_script_schema(self):
        gen = PostmanCollectionGenerator()
        assertion = {
            "type": "schema_validation", "field": None,
            "operator": "valid", "expected_value": None,
            "description": "Schema should be valid"
        }
        script = gen._assertion_to_script(assertion)
        assert script is not None

    def test_assertion_to_script_unknown_type(self):
        gen = PostmanCollectionGenerator()
        assertion = {
            "type": "unknown_type", "field": None,
            "operator": "equals", "expected_value": None,
            "description": "Unknown"
        }
        result = gen._assertion_to_script(assertion)
        assert result is None

    def test_url_with_query_params(self):
        gen = PostmanCollectionGenerator()
        url = gen._parse_url("/api/v1/pets", {"status": "available", "limit": "10"})
        assert "query" in url
        assert len(url["query"]) == 2

    def test_prerequest_script_with_pet_id(self):
        gen = PostmanCollectionGenerator()
        tc = {"request": {"path": "/api/v1/pets/{pet_id}"}}
        script = gen._build_prerequest_script(tc)
        assert len(script) > 0
        assert any("petId" in line or "pet_id" in line for line in script)

    def test_assertion_contains(self):
        gen = PostmanCollectionGenerator()
        assertion = {
            "type": "response_body", "field": "name",
            "operator": "contains", "expected_value": "test",
            "description": "Should contain test"
        }
        script = gen._assertion_to_script(assertion)
        assert script is not None

    def test_assertion_equals_number(self):
        gen = PostmanCollectionGenerator()
        assertion = {
            "type": "response_body", "field": "age",
            "operator": "equals", "expected_value": 5,
            "description": "Age should be 5"
        }
        script = gen._assertion_to_script(assertion)
        assert script is not None

    def test_assertion_header_equals(self):
        gen = PostmanCollectionGenerator()
        assertion = {
            "type": "header", "field": "Content-Type",
            "operator": "equals", "expected_value": "application/json",
            "description": "Content type check"
        }
        script = gen._assertion_to_script(assertion)
        assert script is not None
        assert any("application/json" in line for line in script)


class TestAllureReportGeneratorExtended:
    """Extended Allure tests."""

    def test_generate_html_report_not_installed(self, tmp_path):
        gen = AllureReportGenerator(output_dir=str(tmp_path / "allure"))
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = gen.generate_allure_report()
            assert result["status"] == "skipped"
