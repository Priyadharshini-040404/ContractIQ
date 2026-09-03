"""
ContractIQ - Tests for Generators, Validators, and Analyzers
"""

import pytest
import json
from pathlib import Path

from generators.postman_generator import PostmanCollectionGenerator
from validators.contract_validator import (
    SchemathesisValidator, DreddValidator, ContractValidator
)
from execution.test_runner import DirectTestRunner, AllureReportGenerator
from reports.failure_analyzer import FailureAnalyzer
from core.langchain_orchestrator import LangChainOrchestrator


# ─── Postman Generator Tests ───

class TestPostmanCollectionGenerator:
    """Tests for Postman Collection generation."""

    def test_generate_collection_structure(self, sample_pipeline_result):
        gen = PostmanCollectionGenerator(base_url="http://localhost:8000")
        collection = gen.generate_collection(sample_pipeline_result)

        assert "info" in collection
        assert "item" in collection
        assert "variable" in collection
        assert collection["info"]["schema"] == "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

    def test_collection_has_folders(self, sample_pipeline_result):
        gen = PostmanCollectionGenerator()
        collection = gen.generate_collection(sample_pipeline_result)

        assert len(collection["item"]) == 2  # 2 test suites

    def test_collection_has_requests(self, sample_pipeline_result):
        gen = PostmanCollectionGenerator()
        collection = gen.generate_collection(sample_pipeline_result)

        total_requests = sum(len(f["item"]) for f in collection["item"])
        assert total_requests == 4  # 4 test cases total

    def test_request_has_method_and_url(self, sample_pipeline_result):
        gen = PostmanCollectionGenerator()
        collection = gen.generate_collection(sample_pipeline_result)

        first_req = collection["item"][0]["item"][0]
        assert "request" in first_req
        assert "method" in first_req["request"]
        assert "url" in first_req["request"]

    def test_post_request_has_body(self, sample_pipeline_result):
        gen = PostmanCollectionGenerator()
        collection = gen.generate_collection(sample_pipeline_result)

        # Find POST requests
        for folder in collection["item"]:
            for item in folder["item"]:
                if item["request"]["method"] == "POST":
                    assert "body" in item["request"]
                    assert item["request"]["body"]["mode"] == "raw"

    def test_request_has_test_events(self, sample_pipeline_result):
        gen = PostmanCollectionGenerator()
        collection = gen.generate_collection(sample_pipeline_result)

        for folder in collection["item"]:
            for item in folder["item"]:
                events = item.get("event", [])
                test_events = [e for e in events if e.get("listen") == "test"]
                assert len(test_events) > 0, "Each request should have test scripts"

    def test_save_collection(self, sample_pipeline_result, tmp_path):
        gen = PostmanCollectionGenerator()
        collection = gen.generate_collection(sample_pipeline_result)

        output_file = tmp_path / "collection.json"
        gen.save_collection(collection, str(output_file))

        assert output_file.exists()
        loaded = json.loads(output_file.read_text())
        assert loaded["info"]["name"] == collection["info"]["name"]

    def test_generate_and_save(self, sample_pipeline_result, tmp_path):
        gen = PostmanCollectionGenerator()
        stats = gen.generate_and_save(
            sample_pipeline_result, str(tmp_path / "test_collection.json")
        )

        assert "collection_name" in stats
        assert stats["total_folders"] == 2
        assert stats["total_requests"] == 4
        assert "output_path" in stats

    def test_collection_variables(self, sample_pipeline_result):
        gen = PostmanCollectionGenerator()
        collection = gen.generate_collection(sample_pipeline_result)

        var_keys = [v["key"] for v in collection["variable"]]
        assert "base_url" in var_keys


# ─── Contract Validator Tests ───

class TestContractValidator:
    """Tests for contract validation."""

    def test_validate_spec_compliance(self, spec_path):
        validator = SchemathesisValidator(spec_path)
        result = validator.validate_schema_compliance()

        assert result["status"] in ("valid", "invalid")
        assert "total_paths" in result
        assert "total_schemas" in result
        assert result["total_paths"] > 0

    def test_validate_valid_spec(self, spec_path):
        validator = SchemathesisValidator(spec_path)
        result = validator.validate_schema_compliance()

        assert result["status"] == "valid"
        errors = [i for i in result.get("issues", []) if i["level"] == "error"]
        assert len(errors) == 0

    def test_validate_invalid_spec(self, tmp_path):
        """Test validation of an incomplete spec."""
        bad_spec = tmp_path / "bad.yaml"
        bad_spec.write_text("openapi: '3.1.0'\ninfo:\n  title: Bad\n  version: '1.0'\n")

        validator = SchemathesisValidator(str(bad_spec))
        result = validator.validate_schema_compliance()
        # Should report missing paths
        has_paths_issue = any("paths" in i.get("message", "").lower() for i in result.get("issues", []))
        assert has_paths_issue or result["status"] == "invalid"

    def test_unified_validator(self, spec_path):
        validator = ContractValidator(spec_path)
        result = validator.validate_spec_only()

        assert result["status"] == "valid"
        assert result["openapi_version"] == "3.1.0"

    def test_response_schema_validation_valid(self, spec_path):
        """Test response validation against schema."""
        import requests as req_lib
        from unittest.mock import MagicMock

        validator = ContractValidator(spec_path)

        # Mock a valid response
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "healthy",
            "timestamp": "2024-01-01T00:00:00",
            "version": "1.0.0"
        }

        schema = {
            "type": "object",
            "required": ["status", "timestamp", "version"],
            "properties": {
                "status": {"type": "string"},
                "timestamp": {"type": "string"},
                "version": {"type": "string"},
            }
        }

        result = validator.validate_response_against_schema(mock_resp, schema)
        assert result["valid"] is True
        assert len(result["issues"]) == 0

    def test_response_schema_validation_missing_field(self, spec_path):
        """Test response validation with missing required field."""
        from unittest.mock import MagicMock

        validator = ContractValidator(spec_path)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "healthy"}

        schema = {
            "type": "object",
            "required": ["status", "timestamp"],
            "properties": {
                "status": {"type": "string"},
                "timestamp": {"type": "string"},
            }
        }

        result = validator.validate_response_against_schema(mock_resp, schema)
        assert result["valid"] is False
        assert any("timestamp" in i for i in result["issues"])

    def test_response_schema_validation_type_mismatch(self, spec_path):
        """Test response validation with type mismatch."""
        from unittest.mock import MagicMock

        validator = ContractValidator(spec_path)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"age": "not_a_number"}

        schema = {
            "type": "object",
            "properties": {"age": {"type": "integer"}}
        }

        result = validator.validate_response_against_schema(mock_resp, schema)
        assert result["valid"] is False

    def test_dredd_config_generation(self, spec_path, tmp_path):
        dredd = DreddValidator(spec_path)
        config_path = dredd.generate_dredd_config(str(tmp_path / "dredd.yml"))

        assert Path(config_path).exists()


# ─── Direct Test Runner Tests ───

class TestDirectTestRunner:
    """Tests for the direct test execution engine."""

    def test_execute_against_running_api(self, api_client, sample_pipeline_result):
        """Test execution against the FastAPI test client."""
        runner = DirectTestRunner(base_url="http://testserver")
        # We can't use runner directly with TestClient, but we can test structure
        assert runner.base_url == "http://testserver"
        assert runner.results == []

    def test_execute_test_suite_structure(self, sample_pipeline_result):
        """Test that execution results have correct structure."""
        # Test with unreachable server to validate error handling
        runner = DirectTestRunner(base_url="http://localhost:19999")
        results = runner.execute_test_suite(sample_pipeline_result)

        assert "total_tests" in results
        assert "passed" in results
        assert "failed" in results
        assert "pass_rate" in results
        assert "total_duration_seconds" in results
        assert "results" in results
        assert results["total_tests"] == 4


# ─── Allure Report Generator Tests ───

class TestAllureReportGenerator:
    """Tests for Allure report generation."""

    def test_generate_results(self, sample_execution_results, tmp_path):
        gen = AllureReportGenerator(output_dir=str(tmp_path / "allure"))
        result_dir = gen.generate_results(sample_execution_results)

        assert Path(result_dir).exists()

        # Check environment file
        env_file = Path(result_dir) / "environment.properties"
        assert env_file.exists()
        content = env_file.read_text()
        assert "API.URL" in content
        assert "Test.Total" in content

    def test_allure_result_files_created(self, sample_execution_results, tmp_path):
        gen = AllureReportGenerator(output_dir=str(tmp_path / "allure"))
        gen.generate_results(sample_execution_results)

        # Should create result files for each test
        result_files = list(Path(tmp_path / "allure").glob("*-result.json"))
        assert len(result_files) >= 2  # At least for results in the fixture

    def test_allure_result_format(self, sample_execution_results, tmp_path):
        gen = AllureReportGenerator(output_dir=str(tmp_path / "allure"))
        gen.generate_results(sample_execution_results)

        result_files = list(Path(tmp_path / "allure").glob("*-result.json"))
        for rf in result_files:
            data = json.loads(rf.read_text())
            assert "name" in data
            assert "status" in data
            assert data["status"] in ("passed", "failed", "broken", "skipped", "unknown")
            assert "labels" in data

    def test_status_mapping(self):
        gen = AllureReportGenerator()
        assert gen._map_status("passed") == "passed"
        assert gen._map_status("failed") == "failed"
        assert gen._map_status("error") == "broken"
        assert gen._map_status("skipped") == "skipped"
        assert gen._map_status("unknown") == "unknown"


# ─── Failure Analyzer Tests ───

class TestFailureAnalyzer:
    """Tests for AI failure analysis."""

    def test_no_failures(self):
        analyzer = FailureAnalyzer()
        result = analyzer.analyze_failures({"failures": []})

        assert result["status"] == "no_failures"

    def test_rule_based_analysis(self, sample_execution_results):
        analyzer = FailureAnalyzer()  # No API key = rule-based
        result = analyzer.analyze_failures(sample_execution_results)

        assert result["status"] == "analyzed"
        assert result["total_failures"] == 2
        assert len(result["analyses"]) == 2
        assert "summary" in result

    def test_analysis_has_required_fields(self, sample_execution_results):
        analyzer = FailureAnalyzer()
        result = analyzer.analyze_failures(sample_execution_results)

        for analysis in result["analyses"]:
            assert "test_id" in analysis
            assert "severity" in analysis
            assert "root_cause" in analysis
            assert "recommended_actions" in analysis
            assert "explanation" in analysis
            assert analysis["severity"] in ("critical", "high", "medium", "low")

    def test_summary_generation(self, sample_execution_results):
        analyzer = FailureAnalyzer()
        result = analyzer.analyze_failures(sample_execution_results)
        summary = result["summary"]

        assert "total_analyzed" in summary
        assert "severity_breakdown" in summary
        assert "overall_health" in summary
        assert summary["total_analyzed"] == 2

    def test_save_report(self, sample_execution_results, tmp_path):
        analyzer = FailureAnalyzer()
        result = analyzer.analyze_failures(sample_execution_results)
        path = analyzer.save_report(result, str(tmp_path / "analysis.json"))

        assert Path(path).exists()
        loaded = json.loads(Path(path).read_text())
        assert loaded["status"] == "analyzed"

    def test_404_severity(self):
        analyzer = FailureAnalyzer()
        failure = {
            "test_id": "test1",
            "test_name": "Not found test",
            "actual_status_code": 404,
            "assertions": [{"type": "status_code", "expected": 200, "actual": 404, "passed": False}],
        }
        analysis = analyzer._rule_based_analyze(failure)
        assert analysis["severity"] == "high"

    def test_500_severity(self):
        analyzer = FailureAnalyzer()
        failure = {
            "test_id": "test2",
            "test_name": "Server error test",
            "actual_status_code": 500,
            "assertions": [{"type": "status_code", "expected": 200, "actual": 500, "passed": False}],
        }
        analysis = analyzer._rule_based_analyze(failure)
        assert analysis["severity"] == "critical"


# ─── LangChain Orchestrator Tests ───

class TestLangChainOrchestrator:
    """Tests for the LangChain orchestration engine."""

    def test_parse_specification(self, spec_path):
        orchestrator = LangChainOrchestrator(spec_path=spec_path)
        spec_data = orchestrator.parse_specification()

        assert "api_info" in spec_data
        assert "endpoints" in spec_data
        assert "prompt_context" in spec_data
        assert spec_data["endpoint_count"] > 0

    def test_fallback_test_generation(self, spec_path):
        """Test template-based test generation (no API keys)."""
        orchestrator = LangChainOrchestrator(spec_path=spec_path)
        spec_data = orchestrator.parse_specification()
        tests = orchestrator.generate_test_cases(spec_data)

        assert "test_suites" in tests
        assert len(tests["test_suites"]) > 0

        for suite in tests["test_suites"]:
            assert "endpoint" in suite
            assert "test_cases" in suite
            assert len(suite["test_cases"]) > 0

    def test_fallback_assertion_generation(self, spec_path):
        """Test template-based assertion generation (no API keys)."""
        orchestrator = LangChainOrchestrator(spec_path=spec_path)
        spec_data = orchestrator.parse_specification()
        tests = orchestrator.generate_test_cases(spec_data)
        assertions = orchestrator.generate_assertions(tests, spec_data.get("schemas", {}))

        assert "assertions" in assertions
        assert len(assertions["assertions"]) > 0

    def test_sample_body_generation(self, spec_path):
        orchestrator = LangChainOrchestrator(spec_path=spec_path)
        schema = {
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer", "minimum": 0},
                    "tags": {"type": "array"},
                }
            }
        }
        body = orchestrator._generate_sample_body(schema)
        assert body is not None
        assert "name" in body
        assert isinstance(body["age"], int)
        assert isinstance(body["tags"], list)

    def test_full_pipeline_fallback(self, spec_path):
        """Test the full pipeline with fallback (no API keys)."""
        orchestrator = LangChainOrchestrator(spec_path=spec_path)
        result = orchestrator.run_full_pipeline()

        assert "api_info" in result
        assert "test_suites" in result
        assert "assertions" in result
        assert "metadata" in result
        assert result["metadata"]["generation_method"] == "template"
