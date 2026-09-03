"""
ContractIQ - Dashboard Generator Tests

Covers reports/dashboard_generator.py: graceful behavior with no data
at all, with full synthetic data (all severities, mixed pass/fail,
contract validation, coverage), and the final generate() file-write.
"""

import json
from pathlib import Path

import pytest

from reports.dashboard_generator import DashboardGenerator, _load_json, _pct


class TestLoadJsonHelper:
    def test_missing_file_returns_none(self, tmp_path):
        assert _load_json(tmp_path / "nope.json") is None

    def test_invalid_json_returns_none(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        assert _load_json(bad) is None

    def test_valid_json_loads(self, tmp_path):
        good = tmp_path / "good.json"
        good.write_text(json.dumps({"a": 1}))
        assert _load_json(good) == {"a": 1}


class TestPctHelper:
    def test_formats_percentage(self):
        assert _pct(42.567, 1) == "42.6%"
        assert _pct(100) == "100%"


class TestDashboardEmptyState:
    """No pipeline has run yet — output/ is empty."""

    def test_collect_data_all_none(self, tmp_path):
        gen = DashboardGenerator(output_dir=str(tmp_path))
        data = gen.collect_data()
        assert data["pipeline_result"] is None
        assert data["execution_results"] is None
        assert data["failure_analysis"] is None
        assert data["contract_validation"] is None
        assert data["coverage"] is None

    def test_generate_produces_valid_html_with_no_data(self, tmp_path):
        gen = DashboardGenerator(output_dir=str(tmp_path))
        out_path = gen.generate(out_path=str(tmp_path / "dashboard.html"))
        content = Path(out_path).read_text()
        assert "<!DOCTYPE html>" in content
        assert "ContractIQ" in content
        assert "NOT RUN YET" in content
        assert "No execution results yet" in content

    def test_overall_health_not_run(self, tmp_path):
        gen = DashboardGenerator(output_dir=str(tmp_path))
        data = gen.collect_data()
        label, css_class = gen._overall_health(data)
        assert label == "NOT RUN YET"
        assert css_class == "pill-muted"


class TestDashboardWithFullData:
    @pytest.fixture
    def populated_output_dir(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()

        (out / "pipeline_result.json").write_text(json.dumps({
            "api_info": {"title": "Demo API", "version": "1.0.0"},
            "server_url": "http://localhost:8000",
            "metadata": {
                "total_endpoints": 10, "total_test_cases": 17,
                "total_assertions": 51, "generation_method": "template",
            },
        }))

        (out / "execution_results.json").write_text(json.dumps({
            "total_tests": 4, "passed": 2, "failed": 2, "pass_rate": "50.0%",
            "results": [
                {"test_id": "a_01", "test_name": "A", "test_type": "positive",
                 "method": "GET", "status": "passed", "actual_status_code": 200,
                 "response_time_ms": 12.3},
            ],
            "failures": [
                {"test_id": "b_01", "test_name": "B", "test_type": "negative",
                 "method": "GET", "status": "failed", "actual_status_code": 404,
                 "response_time_ms": 5.0},
                {"test_id": "c_01", "test_name": "C", "test_type": "edge_case",
                 "method": "PUT", "status": "failed", "actual_status_code": 422,
                 "response_time_ms": 8.0},
            ],
        }))

        (out / "failure_analysis.json").write_text(json.dumps({
            "status": "analyzed",
            "total_failures": 2,
            "analyses": [
                {"test_id": "b_01", "severity": "high", "root_cause": "Not found",
                 "contract_mismatch": "404 instead of 200",
                 "recommended_actions": ["Check routing", "Seed data"],
                 "explanation": "Resource missing.", "analysis_method": "rule_based"},
                {"test_id": "c_01", "severity": "critical", "root_cause": "Server error",
                 "contract_mismatch": None,
                 "recommended_actions": ["Check logs"],
                 "explanation": "Server failed.", "analysis_method": "ai_gemini"},
            ],
            "summary": {
                "severity_breakdown": {"critical": 1, "high": 1, "medium": 0, "low": 0},
                "overall_health": "critical",
            },
        }))

        (out / "contract_validation.json").write_text(json.dumps({
            "overall_status": "failed",
            "schemathesis": {"status": "passed"},
            "dredd": {"status": "failed"},
        }))

        (out / "coverage.json").write_text(json.dumps({
            "totals": {"percent_covered": 91.5, "covered_lines": 900, "num_statements": 984},
            "files": {
                "core/openapi_parser.py": {"summary": {"percent_covered": 96.0, "num_statements": 164, "missing_lines": 6}},
                "tests/test_x.py": {"summary": {"percent_covered": 100.0, "num_statements": 50, "missing_lines": 0}},
                "api/__init__.py": {"summary": {"percent_covered": 100.0, "num_statements": 0, "missing_lines": 0}},
                "core/langchain_orchestrator.py": {"summary": {"percent_covered": 60.0, "num_statements": 211, "missing_lines": 84}},
            },
        }))

        return out

    def test_full_generate_writes_all_sections(self, populated_output_dir, tmp_path):
        gen = DashboardGenerator(output_dir=str(populated_output_dir))
        out_path = gen.generate(out_path=str(tmp_path / "dashboard.html"))
        content = Path(out_path).read_text()

        assert "Demo API" in content
        assert "b_01" in content and "c_01" in content
        assert "Resource missing." in content
        assert "AI (Gemini)" in content
        assert "Rule-based" in content
        assert "Schemathesis" in content
        assert "Dredd" in content
        assert "91.5%" in content
        # tests/ and __init__ files must be excluded from coverage breakdown
        assert "tests/test_x.py" not in content
        assert "api/__init__.py" not in content
        assert "core/langchain_orchestrator.py" in content

    def test_coverage_summary_excludes_tests_and_init(self, populated_output_dir):
        gen = DashboardGenerator(output_dir=str(populated_output_dir))
        data = gen.collect_data()
        summary = gen._coverage_summary(data)
        paths = [f["path"] for f in summary["files"]]
        assert "tests/test_x.py" not in paths
        assert "api/__init__.py" not in paths
        assert "core/langchain_orchestrator.py" in paths
        # sorted ascending by coverage percent (worst first)
        assert summary["files"][0]["percent"] <= summary["files"][-1]["percent"]

    def test_pipeline_stages_reflects_metadata(self, populated_output_dir):
        gen = DashboardGenerator(output_dir=str(populated_output_dir))
        data = gen.collect_data()
        stages = gen._pipeline_stages(data)
        labels = [s["label"] for s in stages]
        assert "Endpoints Parsed" in labels
        assert "Contract Validation" in labels
        exec_stage = next(s for s in stages if s["label"] == "Executed")
        assert exec_stage["value"] == "2/4"

    def test_overall_health_critical(self, populated_output_dir):
        gen = DashboardGenerator(output_dir=str(populated_output_dir))
        data = gen.collect_data()
        label, css_class = gen._overall_health(data)
        assert label == "CRITICAL FAILURES"
        assert css_class == "pill-critical"

    def test_coverage_color_thresholds(self):
        gen = DashboardGenerator()
        assert gen._coverage_color(95) == "var(--cyan)"
        assert gen._coverage_color(80) == "var(--amber-dim)"
        assert gen._coverage_color(50) == "var(--coral)"


class TestDashboardHealthyState:
    @pytest.fixture
    def healthy_output_dir(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()
        (out / "execution_results.json").write_text(json.dumps({
            "total_tests": 5, "passed": 5, "failed": 0, "pass_rate": "100.0%",
            "results": [], "failures": [],
        }))
        (out / "failure_analysis.json").write_text(json.dumps({
            "status": "no_failures", "message": "All tests passed",
        }))
        (out / "contract_validation.json").write_text(json.dumps({
            "overall_status": "passed",
            "schemathesis": {"status": "passed"},
            "dredd": {"status": "passed"},
        }))
        return out

    def test_overall_health_good(self, healthy_output_dir):
        gen = DashboardGenerator(output_dir=str(healthy_output_dir))
        data = gen.collect_data()
        label, css_class = gen._overall_health(data)
        assert label == "ALL SYSTEMS GO"
        assert css_class == "pill-good"

    def test_no_failures_renders_good_empty_state(self, healthy_output_dir, tmp_path):
        gen = DashboardGenerator(output_dir=str(healthy_output_dir))
        out_path = gen.generate(out_path=str(tmp_path / "dashboard.html"))
        content = Path(out_path).read_text()
        assert "No failures to analyze" in content
