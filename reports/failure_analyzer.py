"""
ContractIQ - AI-Based Failure Analysis & Insights
Uses Gemini to analyze test failures and generate human-readable explanations.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


class FailureAnalyzer:
    """Analyzes test failures and generates AI-powered diagnostics."""

    def __init__(self, gemini_api_key: str | None = None):
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self.llm = None
        self._init_llm()

    def _init_llm(self):
        """Initialize Gemini LLM for failure analysis."""
        if self.gemini_api_key:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                self.llm = ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash-preview-05-20",
                    google_api_key=self.gemini_api_key,
                    temperature=0.2,
                    transport="rest",
                    timeout=20,
                )
            except Exception:
                self.llm = None

    def analyze_failures(self, execution_results: dict, api_context: str = "") -> dict:
        """Analyze all test failures and generate diagnostics."""
        failures = execution_results.get("failures", [])
        if not failures:
            return {
                "status": "no_failures",
                "message": "All tests passed - no failures to analyze",
                "timestamp": datetime.utcnow().isoformat(),
            }

        analyses = []
        for failure in failures:
            analysis = self._analyze_single_failure(failure, api_context)
            analyses.append(analysis)

        summary = self._generate_summary(analyses, execution_results)

        return {
            "status": "analyzed",
            "timestamp": datetime.utcnow().isoformat(),
            "total_failures": len(failures),
            "analyses": analyses,
            "summary": summary,
        }

    def _analyze_single_failure(self, failure: dict, api_context: str) -> dict:
        """Analyze a single test failure."""
        if self.llm:
            return self._ai_analyze_failure(failure, api_context)
        return self._rule_based_analyze(failure)

    def _ai_analyze_failure(self, failure: dict, api_context: str) -> dict:
        """Use Gemini to analyze a failure."""
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an API failure diagnostics expert. Analyze this test failure
and provide a structured diagnosis. Output ONLY valid JSON with these fields:
{{
  "severity": "critical|high|medium|low",
  "root_cause": "detailed explanation",
  "contract_mismatch": "description or null",
  "impacted_components": ["list", "of", "components"],
  "recommended_actions": ["action1", "action2"],
  "explanation": "plain-language explanation for stakeholders"
}}"""),
            ("human", """Analyze this API test failure:

Test: {test_name}
Type: {test_type}
Method: {method}
URL: {url}
Expected Status: {expected_status}
Actual Status: {actual_status}
Response Body: {response_body}
Assertions: {assertions}

API Context: {api_context}"""),
        ])

        try:
            chain = prompt | self.llm
            result = chain.invoke({
                "test_name": failure.get("test_name", ""),
                "test_type": failure.get("test_type", ""),
                "method": failure.get("method", ""),
                "url": failure.get("url", ""),
                "expected_status": str(failure.get("assertions", [{}])[0].get("expected", "")),
                "actual_status": str(failure.get("actual_status_code", "")),
                "response_body": json.dumps(failure.get("response_body", {}))[:500],
                "assertions": json.dumps(failure.get("assertions", [])),
                "api_context": api_context[:1000],
            })

            # Parse the AI response
            text = result.content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines)

            analysis = json.loads(text)
            analysis["test_id"] = failure.get("test_id", "")
            analysis["test_name"] = failure.get("test_name", "")
            analysis["analysis_method"] = "ai_gemini"
            return analysis

        except Exception as e:
            # Fallback to rule-based
            result = self._rule_based_analyze(failure)
            result["ai_error"] = str(e)
            return result

    def _rule_based_analyze(self, failure: dict) -> dict:
        """Rule-based failure analysis (fallback when AI unavailable)."""
        assertions = failure.get("assertions", [])
        failed_assertions = [a for a in assertions if not a.get("passed", True)]
        actual_status = failure.get("actual_status_code", 0)

        # Determine severity
        severity = "medium"
        if actual_status >= 500:
            severity = "critical"
        elif actual_status == 404:
            severity = "high"
        elif actual_status == 422:
            severity = "medium"

        # Determine root cause
        root_cause = "Unknown failure"
        contract_mismatch = None
        impacted = []
        actions = []

        for fa in failed_assertions:
            if fa.get("type") == "status_code":
                expected = fa.get("expected")
                actual = fa.get("actual")
                if actual == 404:
                    root_cause = f"Resource not found. Expected {expected} but got 404."
                    contract_mismatch = "Endpoint returned 404 instead of expected response"
                    impacted = ["API routing", "Resource management"]
                    actions = ["Verify resource exists", "Check URL path parameters", "Ensure data seeding"]
                elif actual == 422:
                    root_cause = f"Validation error. Request body failed schema validation."
                    contract_mismatch = "Request payload doesn't match schema requirements"
                    impacted = ["Input validation", "Schema definitions"]
                    actions = ["Review request body against schema", "Check required fields", "Validate data types"]
                elif actual >= 500:
                    root_cause = f"Server error ({actual}). Internal API failure."
                    contract_mismatch = "Server should not return 5xx for valid contract requests"
                    impacted = ["API server", "Backend services", "Database"]
                    actions = ["Check server logs", "Review error handling", "Test database connectivity"]
                else:
                    root_cause = f"Status mismatch: expected {expected}, got {actual}"
                    contract_mismatch = f"Response status {actual} differs from contract-specified {expected}"
                    impacted = ["API implementation"]
                    actions = [f"Review endpoint behavior for status {actual}"]

            elif fa.get("type") == "response_contains":
                field = fa.get("field", "unknown")
                root_cause = f"Missing expected field '{field}' in response body"
                contract_mismatch = f"Response schema missing required field: {field}"
                impacted = ["Response serialization", "Data model"]
                actions = [f"Add '{field}' to response model", "Update serialization logic"]

        explanation = (
            f"The test '{failure.get('test_name', '')}' failed because {root_cause.lower()} "
            f"This indicates a {'critical ' if severity == 'critical' else ''}"
            f"{'contract deviation' if contract_mismatch else 'test configuration issue'}."
        )

        return {
            "test_id": failure.get("test_id", ""),
            "test_name": failure.get("test_name", ""),
            "severity": severity,
            "root_cause": root_cause,
            "contract_mismatch": contract_mismatch,
            "impacted_components": impacted,
            "recommended_actions": actions,
            "explanation": explanation,
            "analysis_method": "rule_based",
        }

    def _generate_summary(self, analyses: list[dict], execution_results: dict) -> dict:
        """Generate an overall failure analysis summary."""
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for a in analyses:
            sev = a.get("severity", "medium")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        all_actions = []
        for a in analyses:
            all_actions.extend(a.get("recommended_actions", []))

        return {
            "total_analyzed": len(analyses),
            "severity_breakdown": severity_counts,
            "unique_root_causes": len(set(a.get("root_cause", "") for a in analyses)),
            "contract_mismatches": sum(1 for a in analyses if a.get("contract_mismatch")),
            "top_recommended_actions": list(dict.fromkeys(all_actions))[:5],
            "overall_health": "critical" if severity_counts["critical"] > 0
                else "degraded" if severity_counts["high"] > 0
                else "fair" if severity_counts["medium"] > 0
                else "good",
        }

    def save_report(self, analysis_results: dict, output_path: str = "output/failure_analysis.json") -> str:
        """Save the failure analysis report."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(analysis_results, indent=2))
        return str(out.resolve())
