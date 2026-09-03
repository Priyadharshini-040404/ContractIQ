# ContractIQ — Audit & Fixes Report

This document records a full audit of the ContractIQ codebase against the
`S1-C-02` use-case proposal, everything that was found broken or missing,
what was changed, and the evidence backing each claim. Everything below
was actually run against the live target API during this audit — none of
it is projected or assumed.

**Scope note on Allure:** per instruction, Allure/Java was left alone.
`execution/test_runner.py` still emits Allure-compatible JSON to
`output/allure-results/`, so anyone with Java installed can still run
`allure generate` on it. Everywhere else, the new `python main.py
dashboard` HTML dashboard is the reporting UI — it needs nothing beyond
Python.

---

## 1. Summary

| | Before | After |
|---|---|---|
| Unit tests | 115 passing | **152 passing** |
| Statement coverage | 86% | **96%** |
| Live test execution (17 generated tests) | 15/17 passing | **17/17 passing** |
| Dredd contract validation | 10/17 passing (spec incompatibility) | **17/17 passing** |
| Schemathesis contract validation | 171/171 checks passing | 171/171 checks passing (unchanged, already correct) |
| `.env` API keys | present but never loaded | loaded correctly when running as CLI |
| Contract validation CLI command | did not exist | `python main.py contract` |
| Reporting dashboard | none (Allure requires Java) | `python main.py dashboard` — static HTML, no Java |

---

## 2. Bugs found and fixed

### 2.1 Empty-body edge-case tests silently sent no body at all
**File:** `execution/test_runner.py`
**Severity:** High — this was actively producing a wrong test verdict.

The request body was passed to `requests` as:
```python
json=body if body and method in ("POST", "PUT", "PATCH") else None,
```
`body` is a plain dict, and `{}` (an empty dict) is falsy in Python. Every
"send an empty JSON body" edge-case test — exactly the case the test was
designed to exercise — was silently sent as no body at all. Against
`PUT /api/v1/pets/{pet_id}`, the API correctly accepts an empty body
(`{}`, a no-op partial update) but correctly rejects a *missing* body, so
the test failed with a 422 that had nothing to do with what it was
supposed to check.

**Fix:** changed the condition to `body is not None`.

**Evidence:** `docs/evidence/failure_analysis_before_fix.json` is the
real AI/rule-based failure analysis generated against the broken code —
note its root cause for `update_pet_edge_01` ("Validation error. Request
body failed schema validation") is itself slightly misleading, because
the *real* problem was upstream in the test runner, not the API. After
the fix, the same test passes: `output/execution_results.json` shows
17/17 passing.

### 2.2 `.env` was never loaded
**File:** `main.py`
**Severity:** High — the proposal's core AI features were silently
inactive by default, even with valid API keys configured.

Nothing in the codebase called `load_dotenv()`. `os.getenv("GEMINI_API_KEY")`
always returned `None`, so the pipeline always used template-based
generation, regardless of what was in `.env`.

**Fix:** `load_dotenv()` is now called, but only inside `if __name__ ==
"__main__":` — not at module import time. (An earlier version of this
fix called it unconditionally at the top of `main.py`, which caused a
second bug: importing `main.py` in a test — e.g. to test the CLI —
silently loaded real API keys into the test process and broke an
unrelated test that assumed no keys were present. Scoping it to actual
CLI execution fixes both problems.)

### 2.3 AI calls had no failure fallback — contradicting the proposal's own risk register
**File:** `core/langchain_orchestrator.py`
**Severity:** High.

The proposal's risk table names this exact scenario ("AI generates
invalid test cases" / "Gemini API limits exceeded") and promises a
template/backup fallback. The code that would provide that fallback only
triggered if no API key was configured at all — an actual failure from
`chain.invoke()` (bad key, quota, network) was an uncaught exception that
crashed the whole pipeline.

**Fix:** `generate_test_cases`, `generate_assertions`, and
`analyze_failures` now wrap the AI call in `try/except` and fall back to
the existing template/rule-based logic on any exception, or on
unparsable output. The fallback reason is recorded in the result
(`generation_fallback_reason`) instead of being silently swallowed.

Also switched `ChatGoogleGenerativeAI` from its default gRPC transport to
`transport="rest"` with an explicit timeout. gRPC's internal retry logic
was retrying silently for a very long time on connection failure, which
meant the new try/except fallback existed in principle but wouldn't
trigger for a long time in practice. REST fails fast and predictably.

**Evidence:** `tests/test_ai_fallback_safety.py` (8 tests) exercises
every one of these fallback paths directly. Live evidence: running
`python main.py generate` in this sandboxed environment (no access to
`generativelanguage.googleapis.com`) now fails over to templates in
about 2 seconds with a clear logged reason, rather than hanging.

### 2.4 Pipeline metadata claimed "ai" generation even when it had fallen back to templates
**File:** `core/langchain_orchestrator.py`
**Severity:** Medium — a reporting-accuracy bug, not a functional one.

`generation_method` was set to `"ai" if self.gemini_llm else "template"`
— i.e. it checked whether an LLM *client object* had been constructed
(which only requires an API key string), not whether a call had actually
*succeeded*. With a real key configured but no network access to Google,
the dashboard would report `"ai"` for a run that had silently used
templates throughout.

**Fix:** the pipeline now checks whether `generate_test_cases` /
`generate_assertions` actually recorded a fallback reason, and reports
`"template"` (plus the reason, in `metadata.fallback_reason`) whenever
that happened — regardless of whether an LLM object existed.

### 2.5 Dredd contract validation was wired to fail on this project's spec
**File:** `validators/contract_validator.py`
**Severity:** High — an entire layer of the proposal's QA strategy
(100% contract conformance validation) was non-functional.

Two separate problems, both already anticipated by other files in the
repo that just weren't connected to anything:

- Dredd's parser doesn't fully support OpenAPI 3.1 (this spec's version)
  and wants parameter `example`s directly on the parameter object, not
  nested in `schema.example`. A conversion script already existed
  (`qa/make_dredd_spec.py`) that fixes exactly this — but `DreddValidator`
  never called it, so Dredd was always pointed at the raw, incompatible
  spec and failed immediately with a parser error.
- Even with a compatible spec, Dredd uses the spec's static example IDs
  (`sample-pet-id-001`) for every request, which don't exist in the
  live API's in-memory store, so every ID-based request 404'd. A hooks
  file already existed to fix this too (`qa/dredd_hooks.js`, which seeds
  real pet/order IDs and substitutes them in) — but it was never passed
  to the `dredd` CLI invocation.

**Fix:** `DreddValidator.run_validation()` now generates the compatible
spec itself before running (equivalent to running `qa/make_dredd_spec.py`)
and passes `--hookfiles qa/dredd_hooks.js`.

**Evidence:** before this fix, Dredd reported **10 passing, 7 failing**.
After, **17 passing, 0 failing** — see `output/contract_validation.json`
after running `python main.py contract`.

### 2.6 Contract validation was implemented but had no CLI entry point at all
**File:** `main.py`
**Severity:** High — a whole layer of the proposal ("Layer 3: Contract
Validation & Intelligent Verification") was dead code. `ContractValidator`,
`SchemathesisValidator`, and `DreddValidator` all worked correctly in
isolation but nothing in `main.py` ever instantiated or called them.

**Fix:** added `python main.py contract --base-url ... --spec ...`,
which runs both validators and saves the combined result to
`output/contract_validation.json`.

### 2.7 Schemathesis silently reported "skipped" outside an activated virtualenv
**File:** `validators/contract_validator.py`
**Severity:** Medium — environment-dependent false negative.

`subprocess.run(["schemathesis", ...])` only resolves if `schemathesis`
happens to be on `PATH`, which is only guaranteed inside an activated
venv. Running via `/path/to/venv/bin/python main.py ...` without that
venv's `bin/` directory also on `PATH` — a completely normal way to
invoke a script, and how this was first discovered — silently reported
`"skipped"` even though schemathesis was installed right next to the
interpreter that was running.

**Fix:** added a fallback that looks for a `schemathesis` binary next to
`sys.executable` if the plain `PATH` lookup fails.

---

## 3. Proposal requirement coverage

| Proposal item | Status | Notes |
|---|---|---|
| OpenAPI parsing (Layer 1) | ✅ Working | `core/openapi_parser.py`, 96% covered |
| AI test generation — Gemini (Layer 2) | ✅ Working, with fallback | Uses real key from `.env` when network allows; falls back to templates otherwise (§2.3) |
| AI assertion generation — Groq (Layer 2) | ✅ Working, with fallback | Same fallback behavior |
| Postman Collection JSON output | ✅ Working | `output/postman_collection.json`, valid v2.1 format |
| Schemathesis contract validation | ✅ Working | 171/171 checks passing |
| Dredd contract validation | ✅ Fixed (§2.5) | 17/17 passing after fix |
| Newman execution | ✅ Working | Wired into CI (`newman run`) |
| GitHub Actions CI/CD | ✅ Working, extended | Added contract-validation and dashboard jobs |
| Allure Reports | ⏸ Intentionally untouched | Requires Java, per instruction. JSON results still generated; dashboard is the Java-free substitute |
| AI failure analysis (Layer 5) | ✅ Working, with fallback | Rule-based fallback verified against a real bug (§2.1); AI path has dedicated tests |
| Reporting dashboard | ✅ Added (was missing) | `python main.py dashboard`; see `docs/evidence/` for screenshots |
| QA: ≥80% code coverage | ✅ Exceeded | 96%, 152 tests |
| QA: Unit / integration / E2E tests | ✅ Working | `tests/` — 8 files, all passing |
| QA: Load testing (Locust) | ⚠️ Present, not audited | `qa/locustfile.py` exists; out of scope for this pass — not exercised or modified |

---

## 4. Evidence index

- `docs/evidence/failure_analysis_before_fix.json` — real AI failure
  analysis output from the broken code (§2.1), before the fix.
- `docs/evidence/dashboard_demo_failure_analysis.html` — the dashboard
  rendered against that same before-fix data, to demonstrate the failure
  analysis UI with real (if historical) content.
- `docs/evidence/dashboard_demo_screenshot.png` /
  `dashboard_current_screenshot.png` — rendered screenshots of both
  states.
- `output/contract_validation.json`, `output/execution_results.json`,
  `output/coverage.json` — current, clean run (regenerate any time with
  `./scripts/run_all.sh`).

## 5. How to reproduce any of this

```bash
pip install -r requirements.txt
npm install -g newman dredd   # optional, for contract command

./scripts/run_all.sh
# then open output/dashboard.html
```

Or step by step — see the numbered sections in `README.md`.

---

## 6. Round 2 — Generalization, replayability, and hygiene (this pass)

Everything below was actually run against live target APIs during this
pass — the numbers are real tool output, not projections. This round
closed a specific, numbered list of gaps; each item is addressed in
order.

### Group 1 — Generalized test generation (was hardcoded to PetStore)

Added `core/test_synthesizer.py`: `ResourceDiscovery`,
`AssertionSynthesizer`, and `TestSynthesizer`, which derive resource
IDs, expected status codes, request bodies, and boundary/invalid
values **entirely from the parsed OpenAPI spec** — no hardcoded path,
parameter name, or payload shape for any specific API anywhere in this
module. `core/langchain_orchestrator.py`'s `_generate_fallback_tests`
/ `_generate_fallback_assertions` now delegate to it.

**Verified:** ran `python main.py generate` against the live PetStore
API with no API keys set — **23 test cases generated from 10
endpoints**, scaling with schema constraint richness (`PetCreate`'s 6
constrained properties produced 5 boundary tests; `PetUpdate`'s
unconstrained fields produced 0). Confirmed **zero unsubstituted
`{param}`** in any generated request path.

### Group 2 — Replayable Postman collection

The synthesizer now emits a `"setup"` block on every destructive
(DELETE) test case (resource to create, its body, and which response
field to capture as its ID) instead of baking in a fixed ID a prior
run already consumed. `execution/test_runner.py`'s `_execute_test`
runs the setup block before path substitution.
`generators/postman_generator.py`'s `_parse_url` now uses a generic
regex over **all** `{param}` placeholders (not a hardcoded
pet_id/order_id list), and `_build_prerequest_script` emits a real
`pm.sendRequest()` script for setup blocks instead of a warning-only
stub.

**Verified:** started the API, ran `python main.py generate`, then ran
`newman run output/postman_collection.json` **twice in a row** against
the same running instance:

| | Run 1 | Run 2 |
|---|---|---|
| requests | 24/24 | 24/24 |
| assertions | 127/127 | 127/127 |
| failed | 0 | 0 |

Both runs fully passed — destructive tests no longer depend on state a
previous run left behind.

### Group 3 — Confirmed still-working fixes from round 1

- **`.env` load scoping** (item 8): confirmed `load_dotenv()` is still
  only called inside `if __name__ == "__main__":` in `main.py` — never
  at import time.
- **Dredd + OpenAPI 3.1 spec patch** (item 9): ran `python main.py
  contract --base-url http://localhost:8000` with Dredd installed —
  `dredd.status == "passed"` (not `"skipped"` or `"error"`).
- **Schemathesis PATH fallback** (item 10): confirmed
  `_resolve_schemathesis_binary()` correctly resolves the binary next
  to `sys.executable` even with the venv's `bin/` stripped from `PATH`
  (verified with `env -i PATH=... python -c "..."`, simulating exactly
  this invocation style).

### Group 4 — Remaining hygiene issues

- **`datetime.utcnow()` deprecation** (item 11): replaced with
  `datetime.now(timezone.utc)` — all 6 occurrences in
  `api/petstore_api.py` (the item description said 5; the actual count
  was 6), and for full consistency, every other occurrence project-wide
  (`main.py`, `execution/test_runner.py`,
  `validators/contract_validator.py`, `reports/failure_analyzer.py`,
  `generators/postman_generator.py`). The full test suite went from
  156 deprecation warnings to 2 (both from third-party libraries,
  unrelated to this codebase).
- **CI Newman step no longer swallows failures** (item 12): removed
  `|| true` from `.github/workflows/contractiq_ci.yml`'s Newman step.
- **Exposed API keys** (item 13): the real `GEMINI_API_KEY` /
  `GROQ_API_KEY` values that were committed in `.env` have been
  **removed from this deliverable** (replaced with empty placeholders
  and a rotation note). `.env` was already listed in `.gitignore`.
  **This does not revoke the already-exposed keys** — that requires
  action on the provider's console:
    - Gemini: <https://aistudio.google.com/app/apikey> — delete the old
      key, generate a new one.
    - Groq: <https://console.groq.com/keys> — revoke the old key,
      create a new one.
  A full repo-wide search confirmed the leaked key strings do not
  appear anywhere else in the codebase or output artifacts.
- **Dashboard "Assertions Generated" tile** (item 14): now shows a
  pass/fail breakdown (e.g. `"128/150"` with sub-label `"22 failed"`)
  pulled from `execution_results.json`'s per-test assertion list
  whenever an execution has actually happened, falling back to the
  original generation-count display when nothing has been executed
  yet. See `reports/dashboard_generator.py::_assertion_results_breakdown`.

### Group 5 — Coverage gap: multi-API scaling, actually proven

Added `configs/task_api.yaml` — a second OpenAPI spec for a small
Task-List API, written independently of the PetStore spec (different
resource names, different constraints, different enum values) — plus
`api/task_api.py`, a matching FastAPI implementation, so the proof is
end-to-end executable rather than just "the generator didn't crash."

**Verified:** ran the exact same `TestSynthesizer` /
`ResourceDiscovery` / `AssertionSynthesizer` code (zero changes) against
this new spec + live API:

- **15 test cases generated from 7 endpoints**, boundary-test count
  again scaling with constraint richness (`title` min/maxLength,
  `priority` enum, `due_in_days` min/max → 3 boundary tests;
  `completed` — unconstrained — → 0).
- Zero unsubstituted `{param}` in any generated path.
- Ran `newman run` **twice in a row** against the live Task API:
  **80/80 assertions passed, 0 failed, both times.**

This is the actual proof of generality the proposal's Week 15
"multi-API scaling" deliverable calls for — not just that the code
*could* handle another spec, but that it demonstrably does.

### Test suite / coverage after this round

| | Before this round | After this round |
|---|---|---|
| Unit tests | 152 passing | **237 passing** |
| Statement coverage | 96% | **97%** |
| Newman (PetStore, 2 runs) | not replayable | **0 failures, both runs** |
| Newman (Task API, 2 runs) | didn't exist | **0 failures, both runs** |
| Deprecation warnings | 156 | **2** (third-party only) |

New test files: `tests/test_test_synthesizer.py` (51 tests covering
`core/test_synthesizer.py` in isolation) and `tests/test_task_api.py`
(20 tests covering the new second target API). Extended
`tests/test_coverage_boost.py` with setup-block execution tests and
`tests/test_dashboard_generator.py` with assertion-breakdown tests.
