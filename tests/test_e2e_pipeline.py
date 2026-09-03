"""
ContractIQ - End-to-End Pipeline Tests
Tests the complete pipeline from spec parsing to report generation.
"""

import pytest
import json
from pathlib import Path

from core.openapi_parser import OpenAPIParser
from core.langchain_orchestrator import LangChainOrchestrator
from generators.postman_generator import PostmanCollectionGenerator
from validators.contract_validator import ContractValidator
from execution.test_runner import AllureReportGenerator
from reports.failure_analyzer import FailureAnalyzer


class TestE2EPipeline:
    """End-to-end tests for the complete ContractIQ pipeline."""

    def test_e2e_spec_to_tests(self, spec_path, tmp_path):
        """E2E: Parse spec → Generate tests → Create Postman collection."""
        # Step 1: Parse
        orchestrator = LangChainOrchestrator(spec_path=spec_path)
        spec_data = orchestrator.parse_specification()
        assert spec_data["endpoint_count"] > 0

        # Step 2: Generate tests
        tests = orchestrator.generate_test_cases(spec_data)
        assert len(tests["test_suites"]) > 0

        # Step 3: Generate assertions
        assertions = orchestrator.generate_assertions(tests, spec_data.get("schemas", {}))
        assert len(assertions["assertions"]) > 0

        # Step 4: Create Postman collection
        pipeline_result = {
            "api_info": spec_data["api_info"],
            "server_url": spec_data["server_url"],
            "test_suites": tests["test_suites"],
            "assertions": assertions["assertions"],
        }
        gen = PostmanCollectionGenerator()
        output_file = str(tmp_path / "e2e_collection.json")
        stats = gen.generate_and_save(pipeline_result, output_file)

        assert stats["total_requests"] > 0
        assert Path(output_file).exists()

        # Validate the collection JSON
        collection = json.loads(Path(output_file).read_text())
        assert "info" in collection
        assert len(collection["item"]) > 0

    def test_e2e_validation_pipeline(self, spec_path):
        """E2E: Validate spec → Check compliance."""
        validator = ContractValidator(spec_path)

        # Validate spec
        result = validator.validate_spec_only()
        assert result["status"] == "valid"
        assert result["total_paths"] > 0
        assert result["total_schemas"] > 0

    def test_e2e_failure_analysis_pipeline(self, sample_execution_results, tmp_path):
        """E2E: Execute tests → Analyze failures → Generate report."""
        # Analyze failures
        analyzer = FailureAnalyzer()
        analysis = analyzer.analyze_failures(sample_execution_results)
        assert analysis["status"] == "analyzed"

        # Save report
        report_path = str(tmp_path / "failure_report.json")
        analyzer.save_report(analysis, report_path)
        assert Path(report_path).exists()

        # Generate Allure results
        allure_gen = AllureReportGenerator(output_dir=str(tmp_path / "allure"))
        result_dir = allure_gen.generate_results(sample_execution_results)
        assert Path(result_dir).exists()

        # Verify allure files
        result_files = list(Path(result_dir).glob("*-result.json"))
        assert len(result_files) >= 1

    def test_e2e_full_pipeline(self, spec_path, tmp_path):
        """E2E: Complete pipeline execution."""
        # Parse spec
        orchestrator = LangChainOrchestrator(spec_path=spec_path)
        result = orchestrator.run_full_pipeline()

        assert result["metadata"]["total_test_cases"] > 0
        assert result["metadata"]["total_assertions"] > 0

        # Generate Postman collection
        gen = PostmanCollectionGenerator()
        stats = gen.generate_and_save(result, str(tmp_path / "full_pipeline.json"))
        assert stats["total_requests"] > 0

        # Validate spec
        validator = ContractValidator(spec_path)
        val_result = validator.validate_spec_only()
        assert val_result["status"] == "valid"

        # Verify outputs
        assert Path(tmp_path / "full_pipeline.json").exists()
