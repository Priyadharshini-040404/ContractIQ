"""
ContractIQ - Intelligent API Testing and Validation Suite
Main entry point for the complete pipeline.

Usage:
    python main.py --spec configs/openapi_spec.yaml
    python main.py --run-api          # Start the target API
    python main.py --full-pipeline    # Run complete pipeline
"""

import argparse
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.openapi_parser import OpenAPIParser
from core.langchain_orchestrator import LangChainOrchestrator
from generators.postman_generator import PostmanCollectionGenerator
from validators.contract_validator import ContractValidator
from execution.test_runner import DirectTestRunner, AllureReportGenerator
from reports.failure_analyzer import FailureAnalyzer
from reports.dashboard_generator import DashboardGenerator


def parse_spec(args):
    """Parse and display OpenAPI specification."""
    parser = OpenAPIParser(args.spec)
    parser.load_spec()

    info = parser.get_api_info()
    print(f"\n{'='*60}")
    print(f"API: {info['title']} v{info['version']}")
    print(f"OpenAPI Version: {info['openapi_version']}")
    print(f"{'='*60}")

    endpoints = parser.parse_endpoints()
    print(f"\nEndpoints ({len(endpoints)}):")
    for ep in endpoints:
        print(f"  {ep.method:6s} {ep.path:40s} [{ep.operation_id}]")

    schemas = parser.extract_schemas()
    print(f"\nSchemas ({len(schemas)}):")
    for name in schemas:
        print(f"  - {name}")

    print(f"\n{parser.get_schema_definitions()}")


def validate_spec(args):
    """Validate OpenAPI specification."""
    validator = ContractValidator(args.spec)
    result = validator.validate_spec_only()

    print(f"\n{'='*60}")
    print(f"Spec Validation: {result['status'].upper()}")
    print(f"{'='*60}")
    print(f"OpenAPI Version: {result.get('openapi_version', 'unknown')}")
    print(f"Total Paths: {result.get('total_paths', 0)}")
    print(f"Total Schemas: {result.get('total_schemas', 0)}")

    if result.get("issues"):
        print(f"\nIssues ({len(result['issues'])}):")
        for issue in result["issues"]:
            print(f"  [{issue['level'].upper():7s}] {issue['message']}")
    else:
        print("\n  ✓ No issues found!")


def generate_tests(args):
    """Generate AI test cases and Postman collection."""
    orchestrator = LangChainOrchestrator(
        spec_path=args.spec,
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
    )

    # Run pipeline
    pipeline_result = orchestrator.run_full_pipeline()

    # Generate Postman collection
    base_url = pipeline_result.get("server_url", "http://localhost:8000")
    postman_gen = PostmanCollectionGenerator(base_url=base_url)
    stats = postman_gen.generate_and_save(
        pipeline_result,
        output_path="output/postman_collection.json"
    )

    print(f"\nPostman Collection Generated:")
    print(f"  Collection: {stats['collection_name']}")
    print(f"  Folders: {stats['total_folders']}")
    print(f"  Requests: {stats['total_requests']}")
    print(f"  Saved to: {stats['output_path']}")

    # Save pipeline results
    output = Path("output/pipeline_result.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(pipeline_result, indent=2))
    print(f"  Pipeline data: {output}")


def run_tests(args):
    """Execute tests against the running API."""
    # Load pipeline results
    pipeline_file = Path("output/pipeline_result.json")
    if not pipeline_file.exists():
        print("Error: Run 'generate' first to create test cases.")
        print("  python main.py generate --spec configs/openapi_spec.yaml")
        sys.exit(1)

    pipeline_result = json.loads(pipeline_file.read_text())
    base_url = args.base_url or pipeline_result.get("server_url", "http://localhost:8000")

    print(f"\n{'='*60}")
    print(f"ContractIQ - Test Execution")
    print(f"Target: {base_url}")
    print(f"{'='*60}")

    # Execute tests
    runner = DirectTestRunner(base_url=base_url)
    execution_results = runner.execute_test_suite(pipeline_result)
    execution_results["base_url"] = base_url

    print(f"\nExecution Results:")
    print(f"  Total Tests: {execution_results['total_tests']}")
    print(f"  Passed: {execution_results['passed']}")
    print(f"  Failed: {execution_results['failed']}")
    print(f"  Pass Rate: {execution_results['pass_rate']}")
    print(f"  Duration: {execution_results['total_duration_seconds']}s")

    # Generate Allure results
    allure_gen = AllureReportGenerator()
    allure_dir = allure_gen.generate_results(execution_results)
    print(f"  Allure Results: {allure_dir}")

    # Analyze failures
    if execution_results["failed"] > 0:
        print(f"\n{'='*60}")
        print(f"AI Failure Analysis")
        print(f"{'='*60}")

        analyzer = FailureAnalyzer()
        analysis = analyzer.analyze_failures(execution_results)
        analyzer.save_report(analysis, "output/failure_analysis.json")

        print(f"  Total Failures Analyzed: {analysis.get('total_failures', 0)}")
        summary = analysis.get("summary", {})
        print(f"  Severity: {json.dumps(summary.get('severity_breakdown', {}))}")
        print(f"  Overall Health: {summary.get('overall_health', 'unknown')}")

        if summary.get("top_recommended_actions"):
            print(f"\n  Top Recommended Actions:")
            for action in summary["top_recommended_actions"]:
                print(f"    → {action}")

    # Save execution results
    exec_output = Path("output/execution_results.json")
    exec_output.write_text(json.dumps(execution_results, indent=2, default=str))
    print(f"\n  Results saved: {exec_output}")


def run_contract_validation(args):
    """Run Schemathesis + Dredd contract validation against a live API
    and persist the combined result to output/contract_validation.json.

    This closes a real gap: validators/contract_validator.py already
    implements both checks, but nothing in the CLI ever called it — the
    proposal's Layer 3 (Contract Validation) had no entry point.
    """
    print(f"\n{'='*60}")
    print("ContractIQ - Contract Validation (Schemathesis + Dredd)")
    print(f"Target: {args.base_url}")
    print(f"{'='*60}")

    validator = ContractValidator(args.spec, base_url=args.base_url)
    result = validator.run_live_validation()

    st = result["schemathesis"]
    dr = result["dredd"]
    print(f"\n  Schemathesis: {st.get('status', 'unknown').upper()}")
    print(f"  Dredd:        {dr.get('status', 'unknown').upper()}")
    print(f"\n  Overall Status: {result['overall_status'].upper()}")

    out = Path("output/contract_validation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str))
    print(f"\n  Results saved: {out}")


def build_dashboard(args):
    """Generate the standalone HTML reporting dashboard from everything
    in output/ (execution results, failure analysis, contract validation,
    coverage). Doesn't require Java/Allure — pure Python + static HTML.
    """
    print(f"\n{'='*60}")
    print("ContractIQ - Building Reporting Dashboard")
    print(f"{'='*60}")

    generator = DashboardGenerator(output_dir=getattr(args, "output_dir", "output"))
    dashboard_path = generator.generate()
    print(f"\n  Dashboard written to: {dashboard_path}")
    print(f"  Open it directly in a browser — no server required.")


def run_api(args):
    """Start the target FastAPI server."""
    import uvicorn
    print(f"\n{'='*60}")
    print("ContractIQ - Starting Target API")
    print(f"URL: http://0.0.0.0:8000")
    print(f"Docs: http://0.0.0.0:8000/docs")
    print(f"{'='*60}\n")
    uvicorn.run("api.petstore_api:app", host="0.0.0.0", port=8000, reload=True)


def full_pipeline(args):
    """Run the complete ContractIQ pipeline."""
    print(f"\n{'='*60}")
    print("ContractIQ - FULL PIPELINE EXECUTION")
    print(f"{'='*60}")
    print(f"Spec: {args.spec}")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")

    # Step 1: Validate spec
    print(f"\n{'─'*40}")
    print("PHASE 1: Specification Validation")
    print(f"{'─'*40}")
    validate_spec(args)

    # Step 2: Generate tests
    print(f"\n{'─'*40}")
    print("PHASE 2: AI Test Generation")
    print(f"{'─'*40}")
    generate_tests(args)

    # Step 3: Contract validation
    print(f"\n{'─'*40}")
    print("PHASE 3: Contract Validation")
    print(f"{'─'*40}")
    validator = ContractValidator(args.spec)
    spec_result = validator.validate_spec_only()
    print(f"  Spec Status: {spec_result['status']}")

    print(f"\n{'='*60}")
    print(f"Pipeline Complete!")
    print(f"Finished: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}")
    print(f"\nNext steps:")
    print(f"  1. Start API:  python main.py run-api")
    print(f"  2. Run tests:  python main.py execute --base-url http://localhost:8000")
    print(f"  3. View Postman collection: output/postman_collection.json")
    print(f"  4. View results: output/")


def main():
    parser = argparse.ArgumentParser(
        description="ContractIQ - Intelligent API Testing and Validation Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py parse     --spec configs/openapi_spec.yaml
  python main.py validate  --spec configs/openapi_spec.yaml
  python main.py generate  --spec configs/openapi_spec.yaml
  python main.py run-api
  python main.py execute   --base-url http://localhost:8000
  python main.py contract  --base-url http://localhost:8000
  python main.py dashboard
  python main.py pipeline  --spec configs/openapi_spec.yaml
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Parse command
    parse_cmd = subparsers.add_parser("parse", help="Parse OpenAPI specification")
    parse_cmd.add_argument("--spec", default="configs/openapi_spec.yaml", help="Path to OpenAPI spec")

    # Validate command
    validate_cmd = subparsers.add_parser("validate", help="Validate OpenAPI spec")
    validate_cmd.add_argument("--spec", default="configs/openapi_spec.yaml", help="Path to OpenAPI spec")

    # Generate command
    gen_cmd = subparsers.add_parser("generate", help="Generate AI test cases")
    gen_cmd.add_argument("--spec", default="configs/openapi_spec.yaml", help="Path to OpenAPI spec")

    # Run API command
    subparsers.add_parser("run-api", help="Start the target API server")

    # Execute command
    exec_cmd = subparsers.add_parser("execute", help="Execute tests against API")
    exec_cmd.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    exec_cmd.add_argument("--spec", default="configs/openapi_spec.yaml", help="Path to OpenAPI spec")

    # Full pipeline command
    pipe_cmd = subparsers.add_parser("pipeline", help="Run complete pipeline")
    pipe_cmd.add_argument("--spec", default="configs/openapi_spec.yaml", help="Path to OpenAPI spec")

    # Contract validation command (Schemathesis + Dredd against a live API)
    contract_cmd = subparsers.add_parser("contract", help="Run contract validation (Schemathesis + Dredd)")
    contract_cmd.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    contract_cmd.add_argument("--spec", default="configs/openapi_spec.yaml", help="Path to OpenAPI spec")

    # Dashboard command
    dash_cmd = subparsers.add_parser("dashboard", help="Build the standalone HTML reporting dashboard")
    dash_cmd.add_argument("--output-dir", default="output", help="Directory containing pipeline output JSON files")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "parse": parse_spec,
        "validate": validate_spec,
        "generate": generate_tests,
        "run-api": run_api,
        "execute": run_tests,
        "pipeline": full_pipeline,
        "contract": run_contract_validation,
        "dashboard": build_dashboard,
    }

    commands[args.command](args)


if __name__ == "__main__":
    # Load environment variables from .env (GEMINI_API_KEY, GROQ_API_KEY,
    # etc.) only when actually run as the CLI entry point — NOT on import.
    # Loading it at module import time would leak real API keys into the
    # process environment any time something merely `import`s main.py
    # (e.g. tests), silently changing behavior of unrelated code that
    # expects those keys to be absent by default.
    from dotenv import load_dotenv
    load_dotenv()
    main()
