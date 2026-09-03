"""
ContractIQ - CLI Entry Point Tests
Covers main.py: argument parsing and each subcommand handler
(parse, validate, generate, execute, run-api, pipeline).

main.py talks to the filesystem (output/, configs/) and, for `generate`
and `execute`, to LangChainOrchestrator / DirectTestRunner / FailureAnalyzer.
Those collaborators already have their own dedicated unit tests, so here
we mock them out and focus on verifying main.py's own wiring: argument
parsing, command dispatch, output-file writing, and CLI exit behavior.
"""

import json
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import main


@pytest.fixture
def spec_path_arg():
    return str(Path(__file__).parent.parent / "configs" / "openapi_spec.yaml")


class TestParseSpecCommand:
    """python main.py parse --spec ..."""

    def test_parse_spec_prints_summary(self, spec_path_arg, capsys):
        args = Namespace(spec=spec_path_arg)
        main.parse_spec(args)
        out = capsys.readouterr().out
        assert "Endpoints" in out
        assert "Schemas" in out


class TestValidateSpecCommand:
    """python main.py validate --spec ..."""

    def test_validate_spec_valid(self, spec_path_arg, capsys):
        args = Namespace(spec=spec_path_arg)
        main.validate_spec(args)
        out = capsys.readouterr().out
        assert "Spec Validation" in out
        assert "Total Paths" in out

    def test_validate_spec_reports_issues(self, tmp_path, capsys):
        bad_spec = tmp_path / "bad.yaml"
        bad_spec.write_text("openapi: 3.0.3\ninfo:\n  title: x\n  version: '1'\npaths: {}\n")
        args = Namespace(spec=str(bad_spec))
        main.validate_spec(args)
        out = capsys.readouterr().out
        assert "Spec Validation" in out


class TestGenerateTestsCommand:
    """python main.py generate --spec ..."""

    def test_generate_tests_writes_outputs(self, spec_path_arg, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        fake_pipeline_result = {
            "api_info": {"title": "T", "version": "1.0.0"},
            "server_url": "http://localhost:8000",
            "test_suites": [],
            "assertions": [],
            "metadata": {
                "total_endpoints": 1,
                "total_test_cases": 1,
                "total_assertions": 1,
                "generation_method": "template",
            },
        }

        mock_orchestrator = MagicMock()
        mock_orchestrator.run_full_pipeline.return_value = fake_pipeline_result

        with patch("main.LangChainOrchestrator", return_value=mock_orchestrator):
            args = Namespace(spec=spec_path_arg)
            main.generate_tests(args)

        out = capsys.readouterr().out
        assert "Postman Collection Generated" in out
        assert Path("output/pipeline_result.json").exists()
        assert Path("output/postman_collection.json").exists()

        saved = json.loads(Path("output/pipeline_result.json").read_text())
        assert saved["metadata"]["generation_method"] == "template"


class TestRunTestsCommand:
    """python main.py execute --base-url ..."""

    def test_execute_requires_generate_first(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = Namespace(base_url="http://localhost:8000", spec="configs/openapi_spec.yaml")
        with pytest.raises(SystemExit) as exc_info:
            main.run_tests(args)
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "Run 'generate' first" in out

    def test_execute_runs_and_saves_results(self, tmp_path, monkeypatch, capsys, sample_pipeline_result):
        monkeypatch.chdir(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "pipeline_result.json").write_text(json.dumps(sample_pipeline_result))

        fake_exec_results = {
            "total_tests": 4,
            "passed": 4,
            "failed": 0,
            "pass_rate": "100.0%",
            "total_duration_seconds": 0.1,
        }

        mock_runner = MagicMock()
        mock_runner.execute_test_suite.return_value = fake_exec_results

        mock_allure_gen = MagicMock()
        mock_allure_gen.generate_results.return_value = "output/allure-results"

        with patch("main.DirectTestRunner", return_value=mock_runner), \
             patch("main.AllureReportGenerator", return_value=mock_allure_gen):
            args = Namespace(base_url="http://localhost:9999", spec="configs/openapi_spec.yaml")
            main.run_tests(args)

        out = capsys.readouterr().out
        assert "Execution Results" in out
        assert "Pass Rate" in out
        assert (output_dir / "execution_results.json").exists()
        saved = json.loads((output_dir / "execution_results.json").read_text())
        assert saved["base_url"] == "http://localhost:9999"

    def test_execute_triggers_failure_analysis_on_failures(
        self, tmp_path, monkeypatch, capsys, sample_pipeline_result
    ):
        monkeypatch.chdir(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "pipeline_result.json").write_text(json.dumps(sample_pipeline_result))

        fake_exec_results = {
            "total_tests": 4,
            "passed": 2,
            "failed": 2,
            "pass_rate": "50.0%",
            "total_duration_seconds": 0.2,
            "failures": [{"test_id": "x", "test_name": "x", "assertions": []}],
        }

        mock_runner = MagicMock()
        mock_runner.execute_test_suite.return_value = fake_exec_results
        mock_allure_gen = MagicMock()
        mock_allure_gen.generate_results.return_value = "output/allure-results"

        mock_analyzer = MagicMock()
        mock_analyzer.analyze_failures.return_value = {
            "total_failures": 2,
            "summary": {
                "severity_breakdown": {"critical": 0, "high": 1, "medium": 1, "low": 0},
                "overall_health": "degraded",
                "top_recommended_actions": ["Check required fields"],
            },
        }

        with patch("main.DirectTestRunner", return_value=mock_runner), \
             patch("main.AllureReportGenerator", return_value=mock_allure_gen), \
             patch("main.FailureAnalyzer", return_value=mock_analyzer):
            args = Namespace(base_url="http://localhost:9999", spec="configs/openapi_spec.yaml")
            main.run_tests(args)

        out = capsys.readouterr().out
        assert "AI Failure Analysis" in out
        assert "Top Recommended Actions" in out
        mock_analyzer.analyze_failures.assert_called_once()
        mock_analyzer.save_report.assert_called_once()


class TestRunApiCommand:
    """python main.py run-api"""

    def test_run_api_invokes_uvicorn(self, capsys):
        args = Namespace()
        with patch("uvicorn.run") as mock_run:
            main.run_api(args)
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["port"] == 8000
        out = capsys.readouterr().out
        assert "Starting Target API" in out


class TestFullPipelineCommand:
    """python main.py pipeline --spec ..."""

    def test_full_pipeline_runs_all_phases(self, spec_path_arg, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        fake_pipeline_result = {
            "api_info": {"title": "T", "version": "1.0.0"},
            "server_url": "http://localhost:8000",
            "test_suites": [],
            "assertions": [],
            "metadata": {
                "total_endpoints": 1, "total_test_cases": 1,
                "total_assertions": 1, "generation_method": "template",
            },
        }
        mock_orchestrator = MagicMock()
        mock_orchestrator.run_full_pipeline.return_value = fake_pipeline_result

        with patch("main.LangChainOrchestrator", return_value=mock_orchestrator):
            args = Namespace(spec=spec_path_arg)
            main.full_pipeline(args)

        out = capsys.readouterr().out
        assert "FULL PIPELINE EXECUTION" in out
        assert "PHASE 1: Specification Validation" in out
        assert "PHASE 2: AI Test Generation" in out
        assert "PHASE 3: Contract Validation" in out
        assert "Pipeline Complete!" in out


class TestMainDispatcher:
    """python main.py <command> — top-level argparse wiring."""

    def test_no_command_prints_help(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["main.py"])
        with pytest.raises(SystemExit) as exc_info:
            main.main()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "usage" in out.lower() or "ContractIQ" in out

    def test_dispatches_parse_command(self, spec_path_arg, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["main.py", "parse", "--spec", spec_path_arg])
        main.main()
        out = capsys.readouterr().out
        assert "Endpoints" in out

    def test_dispatches_validate_command(self, spec_path_arg, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["main.py", "validate", "--spec", spec_path_arg])
        main.main()
        out = capsys.readouterr().out
        assert "Spec Validation" in out

    def test_run_api_default_args(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["main.py", "run-api"])
        with patch("uvicorn.run") as mock_run:
            main.main()
        mock_run.assert_called_once()


class TestContractValidationCommand:
    """python main.py contract --base-url ..."""

    def test_contract_validation_saves_report(self, spec_path_arg, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        fake_result = {
            "overall_status": "passed",
            "schemathesis": {"status": "passed"},
            "dredd": {"status": "passed"},
        }
        mock_validator = MagicMock()
        mock_validator.run_live_validation.return_value = fake_result

        with patch("main.ContractValidator", return_value=mock_validator):
            args = Namespace(base_url="http://localhost:8000", spec=spec_path_arg)
            main.run_contract_validation(args)

        out = capsys.readouterr().out
        assert "Schemathesis: PASSED" in out
        assert "Dredd:        PASSED" in out
        assert "Overall Status: PASSED" in out

        saved = json.loads(Path("output/contract_validation.json").read_text())
        assert saved["overall_status"] == "passed"


class TestDashboardCommand:
    """python main.py dashboard"""

    def test_dashboard_invokes_generator(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        mock_generator = MagicMock()
        mock_generator.generate.return_value = str(tmp_path / "output" / "dashboard.html")

        with patch("main.DashboardGenerator", return_value=mock_generator) as mock_cls:
            args = Namespace(output_dir="output")
            main.build_dashboard(args)

        mock_cls.assert_called_once_with(output_dir="output")
        mock_generator.generate.assert_called_once()
        out = capsys.readouterr().out
        assert "Building Reporting Dashboard" in out
        assert "dashboard.html" in out
