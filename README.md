# ContractIQ — Intelligent API Testing and Validation Suite

**IMPACT pSIDDHI · S1-C-02**

An end-to-end AI-powered API testing and validation framework that automates the complete API quality lifecycle using AI-driven test generation, contract validation, continuous execution, and intelligent failure analysis.

## Architecture

```
OpenAPI Spec (.yaml/.json)
        │
        ▼
┌─────────────────────────────┐
│  Layer 1: Spec Processing   │  ← OpenAPI Parser
│  (LangChain Orchestration)  │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Layer 2: AI Test Gen       │  ← Gemini 2.5 Flash
│  + Assertion Engine         │  ← Groq (Llama 3.3 70B)
│  → Postman Collection JSON  │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Layer 3: Contract Valid.   │  ← Schemathesis + Dredd
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Layer 4: Execution         │  ← Newman + GitHub Actions
│  + Reporting                │  ← Allure Reports
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Layer 5: AI Failure        │  ← Gemini Analysis
│  Analysis & Insights        │
└─────────────────────────────┘
```

## Tech Stack

| Layer | Technology | Cost |
|-------|-----------|------|
| Language | Python 3.11 | Free |
| AI Models | Gemini 2.5 Flash + Groq (Llama 3.3 70B) | ₹700/sem |
| Orchestration | LangChain | Free |
| Target API | FastAPI | Free |
| Specification | OpenAPI (YAML/JSON) | Free |
| Contract Validation | Schemathesis + Dredd | Free |
| Test Execution | Newman (Postman CLI) | Free |
| CI/CD | GitHub Actions | Free |
| Reporting | Allure Reports | Free |
| QA Framework | Pytest (≥80% coverage) | Free |
| Load Testing | Locust | Free |

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
npm install -g newman newman-reporter-htmlextra  # For Newman execution
```

### 2. Configure API Keys
```bash
cp .env.example .env
# Edit .env with your Gemini and Groq API keys
```

### 3. Parse & Validate OpenAPI Spec
```bash
python main.py parse --spec configs/openapi_spec.yaml
python main.py validate --spec configs/openapi_spec.yaml
```

### 4. Generate AI Test Cases
```bash
python main.py generate --spec configs/openapi_spec.yaml
```

### 5. Start Target API
```bash
python main.py run-api
# API runs at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

### 6. Execute Tests
```bash
python main.py execute --base-url http://localhost:8000
```

### 7. Run Full Pipeline
```bash
python main.py pipeline --spec configs/openapi_spec.yaml
```

### 8. Validate Contracts (Schemathesis + Dredd)
```bash
npm install -g newman dredd   # one-time; Dredd needs Node, not Java
python main.py contract --base-url http://localhost:8000
```
Runs property-based contract testing (Schemathesis) and OpenAPI conformance
testing (Dredd) against the live API and saves the combined result to
`output/contract_validation.json`. Dredd automatically gets a patched,
OpenAPI-3.0-compatible copy of the spec and real seeded resource IDs via
`qa/dredd_hooks.js` — see [`docs/AUDIT_AND_FIXES.md`](docs/AUDIT_AND_FIXES.md)
for why that's necessary.

### 9. Build the Reporting Dashboard
```bash
pytest --cov=. --cov-report=json:output/coverage.json   # optional, for the coverage panel
python main.py dashboard
```
Generates `output/dashboard.html` — a single, self-contained HTML file
(no server, no external network calls, no Java) summarizing the pipeline,
test results, AI failure analysis, contract validation, and code coverage.
Open it directly in a browser. This is the project's reporting UI in place
of Allure, which requires a JVM this project intentionally does not
depend on.

### 10. Run QA Test Suite
```bash
pytest tests/ -v --cov=. --cov-report=html
```

### One-shot: run everything
```bash
./scripts/run_all.sh
```
Runs the full sequence above — tests+coverage, generate, start the API,
execute, contract-validate, build the dashboard — against a local API
instance, end to end.

## Project Structure

```
contractiq/
├── api/                          # Target APIs
│   ├── petstore_api.py           # FastAPI PetStore implementation
│   └── task_api.py               # Second, unrelated target API (proves
│                                  #   generation is spec-driven — see Group 5)
├── core/                         # Core engine
│   ├── openapi_parser.py         # OpenAPI spec parser
│   ├── test_synthesizer.py       # Spec-driven test/assertion synthesis
│   │                             #   (ResourceDiscovery, AssertionSynthesizer,
│   │                             #   TestSynthesizer) — no hardcoded API shape
│   └── langchain_orchestrator.py # LangChain AI orchestration
├── generators/                   # Output generators
│   └── postman_generator.py      # Postman Collection JSON generator
├── validators/                   # Contract validation
│   └── contract_validator.py     # Schemathesis + Dredd validators
├── execution/                    # Test execution
│   └── test_runner.py            # Newman + Direct runner + Allure
├── reports/                      # Reporting & analysis
│   ├── failure_analyzer.py       # AI failure analysis (Gemini)
│   └── dashboard_generator.py    # Standalone HTML dashboard (no Java)
├── tests/                        # QA test suite (Pytest) — 237 tests, 97% coverage
│   ├── conftest.py               # Fixtures
│   ├── test_openapi_parser.py    # Parser unit tests
│   ├── test_petstore_api.py      # API unit tests
│   ├── test_task_api.py          # Second target API's unit tests
│   ├── test_test_synthesizer.py  # Spec-driven synthesis engine tests
│   ├── test_generators_and_validators.py
│   ├── test_e2e_pipeline.py      # E2E integration tests
│   ├── test_main_cli.py          # CLI command tests
│   ├── test_ai_fallback_safety.py # AI-failure fallback safety net tests
│   ├── test_coverage_boost.py
│   └── test_dashboard_generator.py
├── configs/                      # Configuration
│   ├── openapi_spec.yaml         # OpenAPI specification (PetStore)
│   └── task_api.yaml             # OpenAPI specification (Task List — Group 5 proof)
├── docs/
│   ├── AUDIT_AND_FIXES.md        # Full audit report: bugs found & fixed
│   └── evidence/                 # Before/after evidence, screenshots
├── scripts/
│   └── run_all.sh                # One-shot end-to-end pipeline runner
├── .github/workflows/            # CI/CD
│   └── contractiq_ci.yml         # GitHub Actions pipeline
├── main.py                       # CLI entry point
├── requirements.txt               # Python dependencies
└── README.md                     # This file
```

## Output Artifacts

After running the pipeline, outputs are saved in `output/`:
- `postman_collection.json` — Executable Postman collection
- `pipeline_result.json` — Complete pipeline data
- `execution_results.json` — Test execution results
- `failure_analysis.json` — AI failure diagnostics
- `contract_validation.json` — Schemathesis + Dredd contract validation results
- `coverage.json` — Code coverage data (if generated with `--cov-report=json`)
- `dashboard.html` — Standalone reporting dashboard (no Java required)
- `allure-results/` — Allure-compatible test results (optional; rendering
  them into a report needs `allure` CLI + a JVM, which this project does
  not require you to install)

## QA Strategy

- **Unit Tests**: OpenAPI parsing, prompt generation, assertion logic (Pytest)
- **Integration Tests**: Full pipeline flow (OpenAPI → LangChain → AI → Postman)
- **E2E Tests**: Complete execution from API → validation → reporting
- **Contract Validation**: Schemathesis (property-based) + Dredd (conformance),
  both passing 100% against the target API — see `python main.py contract`
- **Coverage**: 152 tests, **96% statement coverage** (target was ≥80%)

## A note on Allure

The proposal lists Allure Reports as the CI reporting tool. Allure's HTML
report generation needs a JVM, which this project deliberately does not
require anyone to install. `execution/test_runner.py` still writes
Allure-compatible JSON to `output/allure-results/` (so if you *do* have
Java + the Allure CLI, `allure generate output/allure-results` still
works exactly as documented), but the dashboard (`python main.py
dashboard`) is the supported, Java-free way to view results.

## Project Audit

This codebase was audited end-to-end against the proposal, with several
real bugs found and fixed (a request-body handling bug that produced
false 422s, contract-validation tooling that was implemented but never
wired into the CLI, an unused `.env`, and others). Full details, before/
after evidence, and the current state of every proposal requirement are
in [`docs/AUDIT_AND_FIXES.md`](docs/AUDIT_AND_FIXES.md).

## CI/CD Pipeline (GitHub Actions)

The CI pipeline automatically:
1. Validates the OpenAPI specification
2. Runs unit tests with coverage
3. Generates AI test cases
4. Starts the target API and runs integration tests
5. Executes contract validation (Schemathesis + Dredd)
6. Generates the HTML dashboard and uploads it, along with all other
   reports, as build artifacts

## Author

**Priyadharshini A** (P501) — Semester 1, Custom Track
