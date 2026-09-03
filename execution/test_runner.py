"""
ContractIQ - Test Execution Engine
Executes generated Postman collections using Newman and generates Allure reports.
"""

import json
import subprocess
import time
from pathlib import Path
from datetime import datetime
from typing import Any
import requests


class NewmanRunner:
    """Executes Postman collections using Newman CLI."""

    def __init__(self, collection_path: str, base_url: str = "http://localhost:8000"):
        self.collection_path = collection_path
        self.base_url = base_url

    def run_collection(
        self,
        output_dir: str = "output/newman",
        environment: dict | None = None,
    ) -> dict:
        """Execute a Postman collection using Newman."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        report_path = output_path / "newman_report.json"
        html_report = output_path / "newman_report.html"

        cmd = [
            "newman", "run", self.collection_path,
            "--reporters", "cli,json,htmlextra",
            "--reporter-json-export", str(report_path),
            "--reporter-htmlextra-export", str(html_report),
            "--timeout-request", "10000",
            "--delay-request", "100",
        ]

        # Add environment variables
        if environment:
            env_file = output_path / "newman_env.json"
            env_data = {
                "id": "contractiq-env",
                "name": "ContractIQ Environment",
                "values": [
                    {"key": k, "value": v, "enabled": True}
                    for k, v in environment.items()
                ]
            }
            env_file.write_text(json.dumps(env_data, indent=2))
            cmd.extend(["--environment", str(env_file)])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=180
            )

            execution_result = {
                "status": "passed" if result.returncode == 0 else "failed",
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr[:1000],
                "report_path": str(report_path),
                "html_report": str(html_report),
            }

            # Parse JSON report if available
            if report_path.exists():
                with open(report_path) as f:
                    report_data = json.load(f)
                execution_result["summary"] = self._extract_summary(report_data)

            return execution_result

        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "Newman execution timed out (180s)"}
        except FileNotFoundError:
            return {"status": "skipped", "error": "Newman not installed (npm install -g newman)"}

    def _extract_summary(self, report: dict) -> dict:
        """Extract summary from Newman JSON report."""
        run = report.get("run", {})
        stats = run.get("stats", {})

        return {
            "total_requests": stats.get("requests", {}).get("total", 0),
            "failed_requests": stats.get("requests", {}).get("failed", 0),
            "total_assertions": stats.get("assertions", {}).get("total", 0),
            "failed_assertions": stats.get("assertions", {}).get("failed", 0),
            "total_duration_ms": run.get("timings", {}).get("completed", 0),
            "avg_response_time_ms": run.get("timings", {}).get("responseAverage", 0),
        }


class DirectTestRunner:
    """Executes test cases directly using Python requests (fallback when Newman unavailable)."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.results: list[dict] = []
        self.session = requests.Session()

    def execute_test_suite(self, pipeline_result: dict) -> dict:
        """Execute all test cases from the pipeline result."""
        self.results = []
        start_time = time.time()

        stored_ids = {}

        for suite in pipeline_result.get("test_suites", []):
            for tc in suite.get("test_cases", []):
                result = self._execute_test(tc, stored_ids)
                self.results.append(result)

                # Store IDs from successful POST requests
                if (result["status"] == "passed" and
                    tc.get("request", {}).get("method") == "POST" and
                    result.get("response_body", {}).get("id")):
                    resource_type = "pet_id" if "pets" in tc["request"]["path"] else "order_id"
                    stored_ids[resource_type] = result["response_body"]["id"]

        duration = time.time() - start_time
        passed = sum(1 for r in self.results if r["status"] == "passed")
        failed = sum(1 for r in self.results if r["status"] == "failed")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_tests": len(self.results),
            "passed": passed,
            "failed": failed,
            "skipped": len(self.results) - passed - failed,
            "pass_rate": f"{(passed / len(self.results) * 100):.1f}%" if self.results else "0%",
            "total_duration_seconds": round(duration, 2),
            "results": self.results,
            "failures": [r for r in self.results if r["status"] == "failed"],
        }

    def _execute_test(self, test_case: dict, stored_ids: dict) -> dict:
        """Execute a single test case."""
        request = test_case.get("request", {})
        expected = test_case.get("expected", {})
        method = request.get("method", "GET")
        path = request.get("path", "/")

        # Replace path parameters with stored IDs
        for key, value in stored_ids.items():
            param_name = key.replace("_id", "_id")
            path = path.replace(f"{{{param_name}}}", value)

        url = f"{self.base_url}{path}"
        headers = request.get("headers", {"Content-Type": "application/json"})
        body = request.get("body")

        result = {
            "test_id": test_case.get("test_id", ""),
            "test_name": test_case.get("name", ""),
            "test_type": test_case.get("type", ""),
            "method": method,
            "url": url,
            "status": "unknown",
            "assertions": [],
        }

        try:
            start = time.time()
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                # NOTE: must check "is not None", not truthiness — an empty
                # dict body ({}) is a deliberate edge-case payload (e.g. a
                # partial-update PUT with no fields changed) and is falsy in
                # Python, so `body and ...` was silently dropping it and
                # sending NO body at all. That sent a different request than
                # the test intended and produced a misleading 422 (missing
                # body) instead of validating the actual empty-body behavior.
                json=body if body is not None and method in ("POST", "PUT", "PATCH") else None,
                params=request.get("query_params"),
                timeout=10,
            )
            response_time = (time.time() - start) * 1000  # ms

            result["actual_status_code"] = response.status_code
            result["response_time_ms"] = round(response_time, 2)

            try:
                result["response_body"] = response.json()
            except Exception:
                result["response_body"] = response.text[:500]

            # Run assertions
            assertions_passed = True
            expected_status = expected.get("status_code", 200)

            # Status code check
            status_match = response.status_code == expected_status
            result["assertions"].append({
                "type": "status_code",
                "expected": expected_status,
                "actual": response.status_code,
                "passed": status_match,
            })
            if not status_match:
                assertions_passed = False

            # Response time check
            time_ok = response_time < 5000
            result["assertions"].append({
                "type": "response_time",
                "expected": "<5000ms",
                "actual": f"{response_time:.0f}ms",
                "passed": time_ok,
            })

            # Response body contains check
            for field in expected.get("response_body_contains", []):
                if isinstance(result["response_body"], dict):
                    has_field = field in result["response_body"]
                else:
                    has_field = field in str(result["response_body"])
                result["assertions"].append({
                    "type": "response_contains",
                    "field": field,
                    "passed": has_field,
                })
                if not has_field:
                    assertions_passed = False

            result["status"] = "passed" if assertions_passed else "failed"

        except requests.ConnectionError:
            result["status"] = "error"
            result["error"] = "Connection refused - is the API running?"
        except requests.Timeout:
            result["status"] = "error"
            result["error"] = "Request timed out"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result


class AllureReportGenerator:
    """Generates Allure-compatible test reports."""

    def __init__(self, output_dir: str = "output/allure-results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_results(self, execution_results: dict) -> str:
        """Generate Allure-compatible JSON result files."""
        for result in execution_results.get("results", []):
            allure_result = {
                "uuid": result.get("test_id", "unknown"),
                "historyId": result.get("test_id", ""),
                "name": result.get("test_name", "Unnamed Test"),
                "fullName": f"contractiq.tests.{result.get('test_id', 'test')}",
                "status": self._map_status(result.get("status", "unknown")),
                "stage": "finished",
                "start": int(time.time() * 1000),
                "stop": int(time.time() * 1000) + int(result.get("response_time_ms", 0)),
                "labels": [
                    {"name": "suite", "value": "ContractIQ API Tests"},
                    {"name": "testType", "value": result.get("test_type", "functional")},
                    {"name": "severity", "value": "normal"},
                    {"name": "feature", "value": result.get("method", "API")},
                    {"name": "story", "value": result.get("url", "")},
                ],
                "parameters": [
                    {"name": "method", "value": result.get("method", "")},
                    {"name": "url", "value": result.get("url", "")},
                ],
                "steps": [
                    {
                        "name": f"Assert: {a.get('type', '')}",
                        "status": "passed" if a.get("passed") else "failed",
                        "parameters": [
                            {"name": "expected", "value": str(a.get("expected", ""))},
                            {"name": "actual", "value": str(a.get("actual", ""))},
                        ]
                    }
                    for a in result.get("assertions", [])
                ],
            }

            if result.get("status") == "failed":
                allure_result["statusDetails"] = {
                    "message": f"Test failed: {result.get('test_name', '')}",
                    "trace": json.dumps(result.get("assertions", []), indent=2),
                }

            result_file = self.output_dir / f"{result.get('test_id', 'unknown')}-result.json"
            result_file.write_text(json.dumps(allure_result, indent=2))

        # Generate environment properties
        env_file = self.output_dir / "environment.properties"
        env_file.write_text(
            f"API.URL={execution_results.get('base_url', 'http://localhost:8000')}\n"
            f"Test.Total={execution_results.get('total_tests', 0)}\n"
            f"Test.Passed={execution_results.get('passed', 0)}\n"
            f"Test.Failed={execution_results.get('failed', 0)}\n"
            f"Pass.Rate={execution_results.get('pass_rate', '0%')}\n"
            f"Generated={datetime.utcnow().isoformat()}\n"
        )

        return str(self.output_dir)

    def generate_allure_report(self, results_dir: str = None) -> dict:
        """Generate the final Allure HTML report."""
        results = results_dir or str(self.output_dir)
        report_dir = str(Path(results).parent / "allure-report")

        cmd = ["allure", "generate", results, "--clean", "-o", report_dir]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return {
                "status": "generated" if result.returncode == 0 else "failed",
                "report_path": report_dir,
                "stdout": result.stdout,
            }
        except FileNotFoundError:
            return {"status": "skipped", "error": "Allure CLI not installed"}

    @staticmethod
    def _map_status(status: str) -> str:
        """Map ContractIQ status to Allure status."""
        return {
            "passed": "passed",
            "failed": "failed",
            "error": "broken",
            "skipped": "skipped",
            "unknown": "unknown",
        }.get(status, "unknown")
