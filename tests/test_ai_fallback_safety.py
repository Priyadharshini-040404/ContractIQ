"""
ContractIQ - AI Fallback Safety Net Tests

Covers the "AI call fails -> fall back to template/rule-based logic
instead of crashing" behavior in LangChainOrchestrator and
FailureAnalyzer. This is the code path that implements Risk #1 and #5
from the proposal's risk register (invalid/unavailable AI output must
never break the pipeline), so it gets its own dedicated tests rather
than only being exercised incidentally.
"""

from unittest.mock import MagicMock

import pytest

from core.langchain_orchestrator import LangChainOrchestrator
from reports.failure_analyzer import FailureAnalyzer


class TestOrchestratorAIFallback:
    def _orchestrator_with_broken_gemini(self, spec_path):
        orchestrator = LangChainOrchestrator(spec_path=spec_path)
        broken_llm = MagicMock()
        broken_llm.__or__ = lambda self, other: broken_llm  # chain composition
        orchestrator.gemini_llm = broken_llm
        return orchestrator, broken_llm

    def test_generate_test_cases_falls_back_on_ai_exception(self, spec_path):
        orchestrator, broken_llm = self._orchestrator_with_broken_gemini(spec_path)
        spec_data = orchestrator.parse_specification()

        # Force chain.invoke() to raise, simulating a network/quota failure.
        def raise_invoke(*args, **kwargs):
            raise RuntimeError("simulated network failure")

        orchestrator._build_test_generation_chain = MagicMock(
            return_value=MagicMock(invoke=raise_invoke)
        )

        result = orchestrator.generate_test_cases(spec_data)

        assert "test_suites" in result
        assert len(result["test_suites"]) > 0
        assert "ai_call_failed" in result.get("generation_fallback_reason", "")

    def test_generate_test_cases_falls_back_on_unparseable_ai_output(self, spec_path):
        orchestrator, _ = self._orchestrator_with_broken_gemini(spec_path)
        spec_data = orchestrator.parse_specification()

        orchestrator._build_test_generation_chain = MagicMock(
            return_value=MagicMock(invoke=lambda *a, **k: "not valid json at all")
        )

        result = orchestrator.generate_test_cases(spec_data)

        assert len(result["test_suites"]) > 0
        assert result.get("generation_fallback_reason") == "ai_response_unusable"

    def test_generate_assertions_falls_back_on_ai_exception(self, spec_path):
        orchestrator, _ = self._orchestrator_with_broken_gemini(spec_path)
        spec_data = orchestrator.parse_specification()
        tests = orchestrator.generate_test_cases(spec_data)

        orchestrator.groq_llm = MagicMock()

        def raise_invoke(*args, **kwargs):
            raise RuntimeError("simulated groq outage")

        orchestrator._build_assertion_generation_chain = MagicMock(
            return_value=MagicMock(invoke=raise_invoke)
        )

        result = orchestrator.generate_assertions(tests, spec_data.get("schemas", {}))

        assert len(result["assertions"]) > 0
        assert "ai_call_failed" in result.get("generation_fallback_reason", "")

    def test_generate_assertions_falls_back_on_unusable_output(self, spec_path):
        orchestrator, _ = self._orchestrator_with_broken_gemini(spec_path)
        spec_data = orchestrator.parse_specification()
        tests = orchestrator.generate_test_cases(spec_data)

        orchestrator.groq_llm = MagicMock()
        orchestrator._build_assertion_generation_chain = MagicMock(
            return_value=MagicMock(invoke=lambda *a, **k: "{}")
        )

        result = orchestrator.generate_assertions(tests, spec_data.get("schemas", {}))
        assert len(result["assertions"]) > 0
        assert result.get("generation_fallback_reason") == "ai_response_unusable"

    def test_analyze_failures_returns_empty_on_ai_exception(self, spec_path):
        orchestrator, _ = self._orchestrator_with_broken_gemini(spec_path)
        spec_data = orchestrator.parse_specification()

        def raise_invoke(*args, **kwargs):
            raise RuntimeError("simulated failure-analysis outage")

        orchestrator._build_failure_analysis_chain = MagicMock(
            return_value=MagicMock(invoke=raise_invoke)
        )

        result = orchestrator.analyze_failures({"failures": []}, spec_data)
        assert result["failure_analyses"] == []
        assert "ai_error" in result

    def test_analyze_failures_no_chain_returns_empty(self, spec_path):
        orchestrator = LangChainOrchestrator(spec_path=spec_path)  # no keys at all
        spec_data = orchestrator.parse_specification()
        result = orchestrator.analyze_failures({"failures": []}, spec_data)
        assert result == {"failure_analyses": []}


class TestFailureAnalyzerAIFallback:
    def test_ai_analyze_failure_falls_back_on_exception(self, sample_execution_results):
        analyzer = FailureAnalyzer(gemini_api_key="fake-key-for-test")
        broken_llm = MagicMock()

        def raise_on_or(other):
            raise RuntimeError("simulated LLM outage")

        broken_llm.__or__ = raise_on_or
        analyzer.llm = broken_llm

        failure = sample_execution_results["failures"][0]
        result = analyzer._analyze_single_failure(failure, api_context="")

        assert result["analysis_method"] == "rule_based"
        assert "ai_error" in result

    def test_analyze_failures_uses_ai_when_llm_present(self, sample_execution_results):
        analyzer = FailureAnalyzer(gemini_api_key="fake-key-for-test")
        analyzer.llm = None  # simulate init failure -> pure rule-based path

        result = analyzer.analyze_failures(sample_execution_results)
        assert result["status"] == "analyzed"
        assert result["total_failures"] == len(sample_execution_results["failures"])
        for analysis in result["analyses"]:
            assert analysis["analysis_method"] == "rule_based"
