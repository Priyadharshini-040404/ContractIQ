"""
ContractIQ - LangChain Orchestration Engine
Orchestrates the AI-powered test generation workflow using LangChain.
Connects OpenAPI parsing → AI test generation → Assertion generation → Output.
"""

import os
import json
from typing import Any
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from core.openapi_parser import OpenAPIParser
from core.test_synthesizer import TestSynthesizer


class LangChainOrchestrator:
    """
    Orchestrates the ContractIQ pipeline using LangChain.
    Converts OpenAPI specifications into AI-generated test cases and assertions.
    """

    def __init__(
        self,
        gemini_api_key: str | None = None,
        groq_api_key: str | None = None,
        spec_path: str = "configs/openapi_spec.yaml",
    ):
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "")
        self.spec_path = spec_path
        self.parser = OpenAPIParser(spec_path)
        self._last_spec_data: dict | None = None

        # Initialize LLMs
        self.gemini_llm = None
        self.groq_llm = None
        self._init_llms()

    def _init_llms(self):
        """Initialize the LLM models."""
        if self.gemini_api_key:
            self.gemini_llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash-preview-05-20",
                google_api_key=self.gemini_api_key,
                temperature=0.3,
                max_output_tokens=8192,
                # REST (not the default gRPC) transport fails fast with a
                # normal exception on network problems instead of retrying
                # internally for a long time — important so our try/except
                # fallback-to-template logic actually kicks in promptly.
                transport="rest",
                timeout=20,
            )

        if self.groq_api_key:
            self.groq_llm = ChatGroq(
                model="llama-3.3-70b-versatile",
                groq_api_key=self.groq_api_key,
                temperature=0.2,
                max_tokens=8192,
            )

    def parse_specification(self) -> dict:
        """Step 1: Parse the OpenAPI specification."""
        self.parser.load_spec()
        endpoints = self.parser.parse_endpoints()
        spec_data = {
            "api_info": self.parser.get_api_info(),
            "endpoints": self.parser.get_endpoint_summary(),
            "prompt_context": self.parser.to_prompt_context(),
            "schemas": self.parser.schemas,
            "server_url": self.parser.server_url,
            "endpoint_count": len(endpoints),
        }
        # Cached so _generate_fallback_assertions (which only receives
        # test_cases + schemas from generate_assertions()) can still get
        # at endpoint definitions for schema-driven assertion synthesis.
        self._last_spec_data = spec_data
        return spec_data

    def _build_test_generation_chain(self):
        """Build the LangChain chain for AI test case generation using Gemini."""
        test_gen_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert API test engineer. Given an API specification,
generate comprehensive test cases covering positive, negative, and edge-case scenarios.

Output ONLY valid JSON — no markdown, no code fences, no explanation.

For each endpoint, generate test cases in this JSON structure:
{{
  "test_suites": [
    {{
      "endpoint": "<METHOD> <PATH>",
      "operation_id": "<operation_id>",
      "test_cases": [
        {{
          "test_id": "<unique_id>",
          "name": "<descriptive_name>",
          "type": "positive|negative|edge_case",
          "description": "<what_this_tests>",
          "request": {{
            "method": "<HTTP_METHOD>",
            "path": "<full_path_with_params>",
            "headers": {{}},
            "query_params": {{}},
            "body": {{}} or null
          }},
          "expected": {{
            "status_code": <int>,
            "response_body_contains": [<key_fields>],
            "response_type": "json|empty"
          }}
        }}
      ]
    }}
  ]
}}

Generate at least 3 positive, 2 negative, and 2 edge-case tests per endpoint."""),
            ("human", """Generate comprehensive API test cases for this API specification:

{api_context}

Base URL: {server_url}

Generate test cases for ALL endpoints. Include boundary values, invalid inputs,
missing required fields, and proper error handling tests."""),
        ])

        if self.gemini_llm:
            chain = test_gen_prompt | self.gemini_llm | StrOutputParser()
            return chain
        return None

    def _build_assertion_generation_chain(self):
        """Build the LangChain chain for assertion generation using Groq."""
        assertion_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an API testing assertion specialist. Given test cases and API schemas,
generate detailed assertion logic for validating API responses.

Output ONLY valid JSON — no markdown, no code fences, no explanation.

Generate assertions in this JSON structure:
{{
  "assertions": [
    {{
      "test_id": "<matching_test_id>",
      "assertions": [
        {{
          "type": "status_code|response_body|schema_validation|header|response_time",
          "field": "<field_path_or_null>",
          "operator": "equals|contains|exists|not_null|type_check|greater_than|less_than|matches_regex",
          "expected_value": "<value>",
          "description": "<what_this_validates>"
        }}
      ]
    }}
  ]
}}"""),
            ("human", """Generate detailed assertions for these test cases:

{test_cases}

Schema definitions:
{schemas}

Generate at least 3 assertions per test case covering:
1. Status code validation
2. Response body field validation
3. Schema/type validation
4. Business logic validation where applicable"""),
        ])

        if self.groq_llm:
            chain = assertion_prompt | self.groq_llm | StrOutputParser()
            return chain
        return None

    def _build_failure_analysis_chain(self):
        """Build chain for AI-powered failure analysis using Gemini."""
        failure_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an API failure diagnostics expert. Analyze test execution failures
and provide human-readable explanations.

Output ONLY valid JSON — no markdown, no code fences, no explanation.

For each failure, provide:
{{
  "failure_analyses": [
    {{
      "test_id": "<test_id>",
      "test_name": "<test_name>",
      "severity": "critical|high|medium|low",
      "root_cause": "<detailed_root_cause>",
      "contract_mismatch": "<description_of_contract_deviation_or_none>",
      "impacted_components": ["<component1>", "<component2>"],
      "recommended_actions": ["<action1>", "<action2>"],
      "explanation": "<human_readable_explanation_for_stakeholders>"
    }}
  ]
}}"""),
            ("human", """Analyze these API test failures and provide detailed diagnostics:

Test Results:
{test_results}

API Specification Context:
{api_context}

For each failure, explain:
1. Root cause
2. Contract mismatches
3. Likely impacted downstream components
4. Recommended corrective actions"""),
        ])

        if self.gemini_llm:
            chain = failure_prompt | self.gemini_llm | StrOutputParser()
            return chain
        return None

    def generate_test_cases(self, spec_data: dict) -> dict:
        """Generate AI-powered test cases using Gemini via LangChain.

        Falls back to template-based generation if the AI call fails for
        any reason (network issue, quota exceeded, invalid key, timeout) —
        per Risk #1 and #5 in the proposal's risk register, a failed AI
        call must never crash the pipeline.
        """
        chain = self._build_test_generation_chain()
        if not chain:
            return self._generate_fallback_tests(spec_data)

        try:
            result = chain.invoke({
                "api_context": spec_data["prompt_context"],
                "server_url": spec_data["server_url"],
            })
            parsed = self._parse_json_response(result, "test_suites")
            if parsed.get("parse_error") or not parsed.get("test_suites"):
                # AI returned something we couldn't use — fall back rather
                # than ship an empty/broken suite.
                fallback = self._generate_fallback_tests(spec_data)
                fallback["generation_fallback_reason"] = "ai_response_unusable"
                return fallback
            return parsed
        except Exception as e:
            fallback = self._generate_fallback_tests(spec_data)
            fallback["generation_fallback_reason"] = f"ai_call_failed: {e}"
            return fallback

    def generate_assertions(self, test_cases: dict, schemas: dict) -> dict:
        """Generate assertions using Groq via LangChain.

        Falls back to template-based assertions if the AI call fails —
        same rationale as generate_test_cases above.
        """
        chain = self._build_assertion_generation_chain()
        if not chain:
            return self._generate_fallback_assertions(test_cases)

        try:
            result = chain.invoke({
                "test_cases": json.dumps(test_cases, indent=2),
                "schemas": json.dumps(schemas, indent=2),
            })
            parsed = self._parse_json_response(result, "assertions")
            if parsed.get("parse_error") or not parsed.get("assertions"):
                fallback = self._generate_fallback_assertions(test_cases)
                fallback["generation_fallback_reason"] = "ai_response_unusable"
                return fallback
            return parsed
        except Exception as e:
            fallback = self._generate_fallback_assertions(test_cases)
            fallback["generation_fallback_reason"] = f"ai_call_failed: {e}"
            return fallback

    def analyze_failures(self, test_results: dict, spec_data: dict) -> dict:
        """Analyze test failures using Gemini via LangChain.

        Returns an empty result (rather than raising) if the AI call
        fails — the caller (FailureAnalyzer) already has its own
        rule-based fallback for this scenario.
        """
        chain = self._build_failure_analysis_chain()
        if not chain:
            return {"failure_analyses": []}

        try:
            result = chain.invoke({
                "test_results": json.dumps(test_results, indent=2),
                "api_context": spec_data.get("prompt_context", ""),
            })
            return self._parse_json_response(result, "failure_analyses")
        except Exception as e:
            return {"failure_analyses": [], "ai_error": str(e)}

    def _parse_json_response(self, response: str, expected_key: str) -> dict:
        """Parse JSON from LLM response, handling code fences."""
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
            return {expected_key: data}
        except json.JSONDecodeError:
            return {expected_key: [], "raw_response": response, "parse_error": True}

    def _create_live_resource(self, base_url: str, path: str, body: dict) -> dict | None:
        """POST `body` to `{base_url}{path}` and return the parsed JSON
        response, or None if the API isn't reachable / the call fails.
        Fully generic — used by TestSynthesizer to obtain real,
        currently-valid resource IDs for whatever resource types the
        SPEC ITSELF declares (via ResourceDiscovery), never for a
        hardcoded endpoint. Fails gracefully so test generation never
        crashes even without a live server."""
        import requests
        try:
            resp = requests.post(f"{base_url}{path}", json=body, timeout=5)
            if 200 <= resp.status_code < 300:
                return resp.json()
        except requests.RequestException:
            pass
        return None

    def _get_synthesizer(self, spec_data: dict) -> TestSynthesizer:
        """Build a TestSynthesizer bound to a live-resource-creation
        callback for this orchestrator's target API."""
        base_url = spec_data.get("server_url", "http://localhost:8000")
        return TestSynthesizer(
            spec_data,
            create_resource=lambda path, body: self._create_live_resource(base_url, path, body),
        )

    def _generate_fallback_tests(self, spec_data: dict) -> dict:
        """Generate template-based tests when AI is unavailable.

        Entirely spec-driven — delegates to TestSynthesizer /
        ResourceDiscovery / AssertionSynthesizer (core/test_synthesizer.py),
        which derive resource IDs, expected status codes, request
        bodies, and boundary/invalid values from the parsed OpenAPI
        spec alone. No path, parameter name, or payload shape for any
        specific API is hardcoded here or in the synthesizer."""
        synthesizer = self._get_synthesizer(spec_data)
        return synthesizer.generate_tests()

    def _generate_fallback_assertions(self, test_cases: dict) -> dict:
        """Generate template-based assertions when AI is unavailable.

        Delegates to AssertionSynthesizer via a TestSynthesizer built
        from whatever spec_data was last parsed (cached by
        parse_specification), so assertions are derived from each
        endpoint's own declared responses/schemas rather than a fixed
        hardcoded template."""
        spec_data = self._last_spec_data or {"endpoints": [], "schemas": {}}
        synthesizer = self._get_synthesizer(spec_data)
        return synthesizer.generate_assertions(test_cases)

    def _generate_sample_body(self, request_body: dict | None) -> dict | None:
        """Generate sample request body from schema."""
        if not request_body:
            return None

        schema = request_body.get("schema", {})
        return self._generate_sample_from_schema(schema)

    def _generate_sample_from_schema(self, schema: dict) -> dict:
        """Generate sample data from a JSON schema."""
        if schema.get("type") != "object" or "properties" not in schema:
            return {}

        sample = {}
        for prop_name, prop_def in schema.get("properties", {}).items():
            prop_type = prop_def.get("type", "string")
            if prop_type == "string":
                if "enum" in prop_def:
                    sample[prop_name] = prop_def["enum"][0]
                else:
                    sample[prop_name] = f"test_{prop_name}"
            elif prop_type == "integer":
                min_val = prop_def.get("minimum", 0)
                sample[prop_name] = min_val + 1
            elif prop_type == "number":
                sample[prop_name] = 100.0
            elif prop_type == "boolean":
                sample[prop_name] = True
            elif prop_type == "array":
                sample[prop_name] = ["test_item"]
            elif prop_type == "object":
                sample[prop_name] = {}

        return sample

    def run_full_pipeline(self) -> dict:
        """Execute the complete ContractIQ pipeline."""
        print("=" * 60)
        print("ContractIQ - Intelligent API Testing Pipeline")
        print("=" * 60)

        # Step 1: Parse spec
        print("\n[1/4] Parsing OpenAPI Specification...")
        spec_data = self.parse_specification()
        print(f"  ✓ Found {spec_data['endpoint_count']} endpoints")
        print(f"  ✓ API: {spec_data['api_info']['title']} v{spec_data['api_info']['version']}")

        # Step 2: Generate test cases
        print("\n[2/4] Generating AI Test Cases...")
        test_cases = self.generate_test_cases(spec_data)
        total_tests = sum(
            len(s.get("test_cases", []))
            for s in test_cases.get("test_suites", [])
        )
        print(f"  ✓ Generated {total_tests} test cases")

        # Step 3: Generate assertions
        print("\n[3/4] Generating AI Assertions...")
        assertions = self.generate_assertions(test_cases, spec_data.get("schemas", {}))
        total_assertions = sum(
            len(a.get("assertions", []))
            for a in assertions.get("assertions", [])
        )
        print(f"  ✓ Generated {total_assertions} assertions")

        # Step 4: Combine results
        print("\n[4/4] Assembling Test Suite...")
        # Report what actually happened, not just whether an LLM client
        # object was constructed — constructing ChatGoogleGenerativeAI
        # only needs an API key string, not a working connection, so
        # `self.gemini_llm` being truthy does NOT mean generation actually
        # used AI. generate_test_cases()/generate_assertions() stamp a
        # "generation_fallback_reason" whenever they had to fall back, so
        # check that instead of re-deriving a possibly-wrong signal here.
        used_fallback = bool(
            test_cases.get("generation_fallback_reason")
            or assertions.get("generation_fallback_reason")
        )
        if used_fallback:
            generation_method = "template"
        elif self.gemini_llm:
            generation_method = "ai"
        else:
            generation_method = "template"

        result = {
            "api_info": spec_data["api_info"],
            "server_url": spec_data["server_url"],
            "test_suites": test_cases.get("test_suites", []),
            "assertions": assertions.get("assertions", []),
            "metadata": {
                "total_endpoints": spec_data["endpoint_count"],
                "total_test_cases": total_tests,
                "total_assertions": total_assertions,
                "generation_method": generation_method,
            }
        }
        if used_fallback:
            result["metadata"]["fallback_reason"] = (
                test_cases.get("generation_fallback_reason")
                or assertions.get("generation_fallback_reason")
            )
        print(f"  ✓ Pipeline complete!")
        print(f"\n{'=' * 60}")
        print(f"Summary: {total_tests} tests, {total_assertions} assertions")
        print(f"{'=' * 60}")

        return result