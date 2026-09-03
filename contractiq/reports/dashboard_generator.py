"""
ContractIQ - Standalone Reporting Dashboard

Builds a single self-contained HTML file summarizing an entire
ContractIQ run: pipeline generation stats, execution results, AI
failure analysis, contract validation (Schemathesis + Dredd), and
code coverage.

This exists specifically as a Java-free alternative to Allure for
environments where a JVM isn't available — it reads the same JSON
artifacts ContractIQ already produces in output/ and renders them as
one static HTML file with no server, no build step, and no external
network dependency (fonts/CSS/JS are all inlined).

Usage:
    python main.py dashboard
    # or directly:
    DashboardGenerator(output_dir="output").generate()
"""

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _load_json(path: Path) -> Optional[dict]:
    """Load a JSON file, returning None if it doesn't exist or is invalid.

    Dashboard generation must never crash just because an earlier
    pipeline stage (contract validation, failure analysis, ...) hasn't
    been run yet — every section below degrades gracefully to an
    "empty state" instead.
    """
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _esc(value: Any) -> str:
    """HTML-escape any value that gets interpolated into the template."""
    return html.escape(str(value), quote=True)


def _pct(value: float, ndigits: int = 1) -> str:
    return f"{round(value, ndigits)}%"


class DashboardGenerator:
    """Reads ContractIQ's output/ artifacts and renders output/dashboard.html."""

    SEVERITY_ORDER = ["critical", "high", "medium", "low"]
    SEVERITY_COLOR = {
        "critical": "var(--coral)",
        "high": "var(--amber)",
        "medium": "var(--amber-dim)",
        "low": "var(--muted)",
    }

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def collect_data(self) -> dict:
        pipeline_result = _load_json(self.output_dir / "pipeline_result.json")
        execution_results = _load_json(self.output_dir / "execution_results.json")
        failure_analysis = _load_json(self.output_dir / "failure_analysis.json")
        contract_validation = _load_json(self.output_dir / "contract_validation.json")
        coverage = _load_json(self.output_dir / "coverage.json")

        return {
            "pipeline_result": pipeline_result,
            "execution_results": execution_results,
            "failure_analysis": failure_analysis,
            "contract_validation": contract_validation,
            "coverage": coverage,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------

    def _overall_health(self, data: dict) -> tuple[str, str]:
        """Returns (label, css-class) for the top-line status pill."""
        exec_results = data["execution_results"]
        contract = data["contract_validation"]

        if exec_results is None:
            return "NOT RUN YET", "pill-muted"

        failed = exec_results.get("failed", 0)
        contract_ok = True
        if contract:
            contract_ok = contract.get("overall_status") in ("passed", "partial", None)

        if failed == 0 and contract_ok:
            return "ALL SYSTEMS GO", "pill-good"
        if failed > 0 and (data["failure_analysis"] or {}).get("summary", {}).get("overall_health") == "critical":
            return "CRITICAL FAILURES", "pill-critical"
        if failed > 0 or not contract_ok:
            return "DEGRADED", "pill-warn"
        return "UNKNOWN", "pill-muted"

    @staticmethod
    def _assertion_results_breakdown(execution_results: Optional[dict]) -> Optional[tuple[int, int]]:
        """(passed, failed) assertion counts pulled from
        execution_results.json's per-test assertion list — i.e. actual
        RESULTS from running the suite, not just how many were
        generated. Returns None if there's nothing to run over yet."""
        if not execution_results:
            return None
        passed = failed = 0
        for result in execution_results.get("results", []) + execution_results.get("failures", []):
            for a in result.get("assertions", []):
                if a.get("passed"):
                    passed += 1
                else:
                    failed += 1
        if passed == 0 and failed == 0:
            return None
        return passed, failed

    def _pipeline_stages(self, data: dict) -> list[dict]:
        pr = data["pipeline_result"] or {}
        er = data["execution_results"]
        meta = pr.get("metadata", {})

        endpoints = meta.get("total_endpoints", pr.get("endpoint_count", 0))
        tests = meta.get("total_test_cases", 0)
        assertions = meta.get("total_assertions", 0)

        if er:
            exec_label = f"{er.get('passed', 0)}/{er.get('total_tests', 0)}"
            exec_sub = er.get("pass_rate", "—")
        else:
            exec_label = "—"
            exec_sub = "not run"

        # Reflect assertion RESULTS (pass/fail from an actual execution
        # run), not just how many were generated, whenever an
        # execution has happened — falling back to the generation
        # count/sub-label when nothing has been executed yet.
        breakdown = self._assertion_results_breakdown(er)
        if breakdown:
            passed, failed = breakdown
            assertions_value = f"{passed}/{passed + failed}"
            assertions_sub = f"{failed} failed" if failed else "all passed"
        else:
            assertions_value = str(assertions)
            assertions_sub = "positive · negative · edge"

        contract = data["contract_validation"]
        if contract:
            contract_label = contract.get("overall_status", "unknown").upper()
        else:
            contract_label = "—"

        return [
            {"label": "Endpoints Parsed", "value": str(endpoints), "sub": "from OpenAPI spec"},
            {"label": "Tests Generated", "value": str(tests), "sub": meta.get("generation_method", "—")},
            {"label": "Assertions Generated", "value": assertions_value, "sub": assertions_sub},
            {"label": "Executed", "value": exec_label, "sub": exec_sub},
            {"label": "Contract Validation", "value": contract_label, "sub": "Schemathesis + Dredd"},
        ]

    def _coverage_summary(self, data: dict) -> Optional[dict]:
        cov = data["coverage"]
        if not cov:
            return None
        totals = cov.get("totals", {})
        files = []
        for path, info in cov.get("files", {}).items():
            # Skip test files and __init__ stubs — the dashboard is about
            # the shipped product code, not the test harness itself.
            if path.startswith("tests/") or path.endswith("__init__.py"):
                continue
            summary = info.get("summary", {})
            if summary.get("num_statements", 0) == 0:
                continue
            files.append({
                "path": path,
                "percent": summary.get("percent_covered", 0.0),
                "statements": summary.get("num_statements", 0),
                "missing": summary.get("missing_lines", 0),
            })
        files.sort(key=lambda f: f["percent"])

        return {
            "percent": totals.get("percent_covered", 0.0),
            "covered_lines": totals.get("covered_lines", 0),
            "num_statements": totals.get("num_statements", 0),
            "files": files,
        }

    @staticmethod
    def _coverage_color(percent: float) -> str:
        if percent >= 90:
            return "var(--cyan)"
        if percent >= 75:
            return "var(--amber-dim)"
        return "var(--coral)"

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_pipeline_schematic(self, stages: list[dict]) -> str:
        nodes = []
        for i, stage in enumerate(stages):
            connector = '<div class="stage-connector"></div>' if i > 0 else ""
            nodes.append(f"""
                {connector}
                <div class="stage-node">
                    <div class="stage-value">{_esc(stage['value'])}</div>
                    <div class="stage-label">{_esc(stage['label'])}</div>
                    <div class="stage-sub">{_esc(stage['sub'])}</div>
                </div>
            """)
        return f'<div class="pipeline-schematic">{"".join(nodes)}</div>'

    def _render_donut(self, pass_rate: float) -> str:
        """Simple SVG ring showing pass rate. 0% -> all coral, 100% -> all cyan."""
        radius = 54
        circumference = 2 * 3.14159265 * radius
        offset = circumference * (1 - pass_rate / 100)
        return f"""
        <svg viewBox="0 0 140 140" class="donut" role="img" aria-label="Pass rate {pass_rate:.1f} percent">
            <circle cx="70" cy="70" r="{radius}" class="donut-track" />
            <circle cx="70" cy="70" r="{radius}" class="donut-fill"
                stroke-dasharray="{circumference:.1f}"
                stroke-dashoffset="{offset:.1f}" />
            <text x="70" y="64" class="donut-number">{pass_rate:.0f}%</text>
            <text x="70" y="84" class="donut-caption">PASS RATE</text>
        </svg>
        """

    def _render_test_table(self, execution_results: Optional[dict]) -> str:
        if not execution_results:
            return '<div class="empty-state">No execution results yet — run <code>python main.py execute</code>.</div>'

        results = execution_results.get("results", [])
        failures = {f["test_id"]: f for f in execution_results.get("failures", [])}
        all_rows = results + [f for tid, f in failures.items() if tid not in {r["test_id"] for r in results}]

        rows_html = []
        for r in sorted(all_rows, key=lambda x: x.get("test_id", "")):
            status = r.get("status", "unknown")
            status_class = "status-pass" if status == "passed" else "status-fail"
            dot = "●"
            ttype = r.get("test_type", "—")
            rows_html.append(f"""
                <tr class="{status_class}" data-status="{_esc(status)}">
                    <td class="mono dim">{dot}</td>
                    <td class="mono">{_esc(r.get('method', ''))}</td>
                    <td class="mono">{_esc(r.get('test_id', ''))}</td>
                    <td>{_esc(r.get('test_name', ''))}</td>
                    <td><span class="type-chip type-{_esc(ttype)}">{_esc(ttype)}</span></td>
                    <td class="mono">{_esc(r.get('actual_status_code', '—'))}</td>
                    <td class="mono dim">{_esc(r.get('response_time_ms', '—'))} ms</td>
                </tr>
            """)

        return f"""
        <div class="table-controls">
            <button class="filter-btn active" data-filter="all">All ({len(all_rows)})</button>
            <button class="filter-btn" data-filter="passed">Passed ({execution_results.get('passed', 0)})</button>
            <button class="filter-btn" data-filter="failed">Failed ({execution_results.get('failed', 0)})</button>
        </div>
        <table class="test-table" id="test-table">
            <thead>
                <tr>
                    <th></th><th>Method</th><th>Test ID</th><th>Name</th><th>Type</th><th>Status</th><th>Time</th>
                </tr>
            </thead>
            <tbody>{"".join(rows_html)}</tbody>
        </table>
        """

    def _render_failure_analysis(self, failure_analysis: Optional[dict]) -> str:
        if not failure_analysis or failure_analysis.get("status") == "no_failures":
            return '<div class="empty-state good">No failures to analyze — every test passed its contract check.</div>'

        analyses = failure_analysis.get("analyses", [])
        summary = failure_analysis.get("summary", {})
        breakdown = summary.get("severity_breakdown", {})

        bars = []
        max_count = max(breakdown.values()) if breakdown and max(breakdown.values()) > 0 else 1
        for sev in self.SEVERITY_ORDER:
            count = breakdown.get(sev, 0)
            width = (count / max_count) * 100 if count else 0
            bars.append(f"""
                <div class="sev-row">
                    <span class="sev-label">{sev}</span>
                    <div class="sev-track"><div class="sev-fill" style="width:{width:.0f}%;background:{self.SEVERITY_COLOR[sev]}"></div></div>
                    <span class="sev-count">{count}</span>
                </div>
            """)

        cards = []
        for a in analyses:
            sev = a.get("severity", "medium")
            actions = "".join(f'<span class="action-chip">{_esc(x)}</span>' for x in a.get("recommended_actions", [])[:4])
            method_badge = "AI (Gemini)" if a.get("analysis_method") == "ai_gemini" else "Rule-based"
            cards.append(f"""
            <details class="failure-card" style="border-left-color:{self.SEVERITY_COLOR.get(sev, 'var(--muted)')}">
                <summary>
                    <span class="sev-tag" style="background:{self.SEVERITY_COLOR.get(sev, 'var(--muted)')}">{_esc(sev)}</span>
                    <span class="mono">{_esc(a.get('test_id', ''))}</span>
                    <span class="method-badge">{_esc(method_badge)}</span>
                </summary>
                <div class="failure-body">
                    <p class="explanation">{_esc(a.get('explanation', ''))}</p>
                    <div class="detail-row"><strong>Root cause:</strong> {_esc(a.get('root_cause', '—'))}</div>
                    <div class="detail-row"><strong>Contract mismatch:</strong> {_esc(a.get('contract_mismatch') or 'None detected')}</div>
                    <div class="detail-row"><strong>Recommended actions:</strong> {actions or '—'}</div>
                </div>
            </details>
            """)

        return f"""
        <div class="sev-breakdown">{"".join(bars)}</div>
        <div class="failure-cards">{"".join(cards)}</div>
        """

    def _render_contract_validation(self, contract: Optional[dict]) -> str:
        if not contract:
            return '<div class="empty-state">No contract validation run yet — run <code>python main.py contract</code>.</div>'

        st = contract.get("schemathesis", {})
        dr = contract.get("dredd", {})

        def row(name, result):
            status = result.get("status", "unknown")
            css = {"passed": "status-pass", "failed": "status-fail"}.get(status, "status-skip")
            return f"""
            <div class="contract-row {css}">
                <span class="contract-tool">{_esc(name)}</span>
                <span class="contract-status">{_esc(status.upper())}</span>
            </div>
            """

        return f"""
        <div class="contract-panel">
            {row("Schemathesis (property-based)", st)}
            {row("Dredd (conformance)", dr)}
        </div>
        <div class="contract-overall">Overall: <strong>{_esc(contract.get('overall_status', 'unknown').upper())}</strong></div>
        """

    def _render_coverage(self, coverage_summary: Optional[dict]) -> str:
        if not coverage_summary:
            return '<div class="empty-state">No coverage data yet — run <code>pytest --cov=. --cov-report=json:output/coverage.json</code>.</div>'

        bars = []
        for f in coverage_summary["files"]:
            color = self._coverage_color(f["percent"])
            bars.append(f"""
                <div class="cov-row">
                    <span class="cov-path mono">{_esc(f['path'])}</span>
                    <div class="cov-track"><div class="cov-fill" style="width:{f['percent']:.0f}%;background:{color}"></div></div>
                    <span class="cov-pct mono">{f['percent']:.0f}%</span>
                </div>
            """)

        return f"""
        <div class="cov-total">
            <span class="cov-total-number" style="color:{self._coverage_color(coverage_summary['percent'])}">{coverage_summary['percent']:.1f}%</span>
            <span class="cov-total-label">overall statement coverage · {coverage_summary['covered_lines']}/{coverage_summary['num_statements']} lines</span>
        </div>
        <div class="cov-files">{"".join(bars)}</div>
        """

    # ------------------------------------------------------------------
    # Top-level generate
    # ------------------------------------------------------------------

    def generate(self, out_path: str = "output/dashboard.html") -> str:
        data = self.collect_data()

        health_label, health_class = self._overall_health(data)
        stages = self._pipeline_stages(data)
        er = data["execution_results"]
        pass_rate = 0.0
        if er and er.get("total_tests"):
            pass_rate = 100.0 * er.get("passed", 0) / er["total_tests"]

        coverage_summary = self._coverage_summary(data)
        api_title = (data["pipeline_result"] or {}).get("api_info", {}).get("title", "Target API")

        html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ContractIQ — Validation Dashboard</title>
<style>
{self._css()}
</style>
</head>
<body>
    <header class="topbar">
        <div class="brand">
            <span class="brand-mark">CIQ</span>
            <span class="brand-name">ContractIQ</span>
        </div>
        <div class="topbar-meta mono">
            <span>{_esc(api_title)}</span>
            <span class="sep">·</span>
            <span>generated {_esc(data['generated_at'])}</span>
        </div>
        <div class="status-pill {health_class}">{_esc(health_label)}</div>
    </header>

    <main>
        <section class="hero">
            {self._render_pipeline_schematic(stages)}
        </section>

        <section class="grid">
            <div class="col-main">
                <div class="panel">
                    <h2>Test Execution</h2>
                    {self._render_test_table(er)}
                </div>
            </div>

            <div class="col-side">
                <div class="panel donut-panel">
                    {self._render_donut(pass_rate)}
                </div>

                <div class="panel">
                    <h2>AI Failure Analysis</h2>
                    {self._render_failure_analysis(data['failure_analysis'])}
                </div>

                <div class="panel">
                    <h2>Contract Validation</h2>
                    {self._render_contract_validation(data['contract_validation'])}
                </div>

                <div class="panel">
                    <h2>Code Coverage</h2>
                    {self._render_coverage(coverage_summary)}
                </div>
            </div>
        </section>
    </main>

    <footer>
        <span>ContractIQ — Intelligent API Testing and Validation Suite</span>
        <span class="sep">·</span>
        <span>Generated locally, no external services required</span>
    </footer>

    <script>
{self._js()}
    </script>
</body>
</html>"""

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html_doc)
        return str(out.resolve())

    # ------------------------------------------------------------------
    # Static assets
    # ------------------------------------------------------------------

    @staticmethod
    def _css() -> str:
        return """
:root {
    --bg: #0B1E33;
    --bg-grid: rgba(255,255,255,0.035);
    --panel: #10263F;
    --panel-border: #1F3B57;
    --text: #EAF2F8;
    --muted: #82A0BA;
    --cyan: #5FD8CB;
    --amber: #E8604C;
    --amber-dim: #E3A857;
    --coral: #E8604C;
    --violet: #8098FF;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
    background: var(--bg);
    background-image:
        linear-gradient(var(--bg-grid) 1px, transparent 1px),
        linear-gradient(90deg, var(--bg-grid) 1px, transparent 1px);
    background-size: 28px 28px;
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.5;
    min-height: 100vh;
}
.mono { font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; }
.dim { color: var(--muted); }

.topbar {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 18px 28px;
    border-bottom: 1px solid var(--panel-border);
    background: rgba(16,38,63,0.6);
    backdrop-filter: blur(6px);
}
.brand { display: flex; align-items: baseline; gap: 8px; }
.brand-mark {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    background: var(--violet);
    color: #0B1E33;
    font-weight: 700;
    font-size: 13px;
    padding: 3px 7px;
    border-radius: 3px;
    letter-spacing: 0.03em;
}
.brand-name { font-size: 17px; font-weight: 600; letter-spacing: -0.01em; }
.topbar-meta { color: var(--muted); font-size: 13px; margin-left: 8px; }
.topbar-meta .sep { margin: 0 8px; opacity: 0.5; }
.status-pill {
    margin-left: auto;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    padding: 6px 12px;
    border-radius: 4px;
    border: 1px solid transparent;
}
.pill-good { background: rgba(95,216,203,0.12); color: var(--cyan); border-color: rgba(95,216,203,0.35); }
.pill-warn { background: rgba(227,168,87,0.12); color: var(--amber-dim); border-color: rgba(227,168,87,0.35); }
.pill-critical { background: rgba(232,96,76,0.14); color: var(--coral); border-color: rgba(232,96,76,0.4); }
.pill-muted { background: rgba(130,160,186,0.1); color: var(--muted); border-color: rgba(130,160,186,0.3); }

main { max-width: 1240px; margin: 0 auto; padding: 32px 28px 48px; }

.hero { margin-bottom: 32px; }
.pipeline-schematic {
    display: flex;
    align-items: stretch;
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    overflow-x: auto;
}
.stage-node {
    flex: 1;
    min-width: 150px;
    padding: 22px 18px;
    text-align: left;
}
.stage-value {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 28px;
    font-weight: 600;
    color: var(--cyan);
}
.stage-label { font-size: 12.5px; color: var(--text); margin-top: 4px; }
.stage-sub { font-size: 11.5px; color: var(--muted); margin-top: 2px; text-transform: lowercase; }
.stage-connector {
    width: 1px;
    background: var(--panel-border);
    align-self: center;
    height: 60%;
    margin: 0 2px;
}

.grid { display: grid; grid-template-columns: 1.6fr 1fr; gap: 20px; align-items: start; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }

.col-main, .col-side { display: flex; flex-direction: column; gap: 20px; }

.panel {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    padding: 20px 22px;
}
.panel h2 {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    margin: 0 0 14px;
    font-weight: 600;
}

.empty-state { color: var(--muted); font-size: 13.5px; padding: 8px 0; }
.empty-state.good { color: var(--cyan); }
.empty-state code { font-family: ui-monospace, monospace; background: rgba(255,255,255,0.06); padding: 2px 5px; border-radius: 3px; }

.table-controls { display: flex; gap: 8px; margin-bottom: 12px; }
.filter-btn {
    background: transparent;
    border: 1px solid var(--panel-border);
    color: var(--muted);
    font-size: 12px;
    font-family: ui-monospace, monospace;
    padding: 5px 10px;
    border-radius: 4px;
    cursor: pointer;
}
.filter-btn.active { color: var(--text); border-color: var(--violet); background: rgba(128,152,255,0.1); }

.test-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.test-table th {
    text-align: left;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
    padding: 8px 10px;
    border-bottom: 1px solid var(--panel-border);
}
.test-table td { padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.04); }
.status-pass td:first-child { color: var(--cyan); }
.status-fail td:first-child { color: var(--coral); }
.type-chip {
    font-size: 10.5px;
    padding: 2px 6px;
    border-radius: 3px;
    background: rgba(130,160,186,0.12);
    color: var(--muted);
    text-transform: capitalize;
}

.donut-panel { display: flex; justify-content: center; }
.donut { width: 160px; height: 160px; }
.donut-track { fill: none; stroke: rgba(255,255,255,0.08); stroke-width: 12; }
.donut-fill {
    fill: none;
    stroke: var(--cyan);
    stroke-width: 12;
    stroke-linecap: round;
    transform: rotate(-90deg);
    transform-origin: 70px 70px;
    transition: stroke-dashoffset 0.6s ease;
}
.donut-number { fill: var(--text); font-size: 26px; font-weight: 700; text-anchor: middle; font-family: ui-monospace, monospace; }
.donut-caption { fill: var(--muted); font-size: 9px; text-anchor: middle; letter-spacing: 0.08em; }

.sev-breakdown { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.sev-row { display: flex; align-items: center; gap: 10px; font-size: 12px; }
.sev-label { width: 56px; text-transform: capitalize; color: var(--muted); }
.sev-track { flex: 1; height: 6px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; }
.sev-fill { height: 100%; border-radius: 3px; }
.sev-count { width: 20px; text-align: right; font-family: ui-monospace, monospace; }

.failure-cards { display: flex; flex-direction: column; gap: 10px; }
.failure-card {
    border: 1px solid var(--panel-border);
    border-left: 3px solid var(--muted);
    border-radius: 4px;
    background: rgba(255,255,255,0.02);
}
.failure-card summary {
    list-style: none;
    cursor: pointer;
    padding: 10px 12px;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12.5px;
}
.failure-card summary::-webkit-details-marker { display: none; }
.sev-tag {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    color: #0B1E33;
    padding: 2px 6px;
    border-radius: 3px;
}
.method-badge { margin-left: auto; font-size: 10.5px; color: var(--muted); }
.failure-body { padding: 0 14px 14px; font-size: 12.5px; }
.explanation { color: var(--text); margin: 4px 0 10px; }
.detail-row { margin-bottom: 6px; color: var(--muted); }
.detail-row strong { color: var(--text); font-weight: 500; }
.action-chip {
    display: inline-block;
    background: rgba(128,152,255,0.12);
    color: var(--violet);
    font-size: 11px;
    padding: 2px 7px;
    border-radius: 3px;
    margin: 2px 4px 2px 0;
}

.contract-panel { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.contract-row {
    display: flex;
    justify-content: space-between;
    padding: 8px 10px;
    border-radius: 4px;
    background: rgba(255,255,255,0.02);
    font-size: 12.5px;
}
.contract-row.status-pass .contract-status { color: var(--cyan); }
.contract-row.status-fail .contract-status { color: var(--coral); }
.contract-row.status-skip .contract-status { color: var(--muted); }
.contract-status { font-family: ui-monospace, monospace; font-weight: 600; }
.contract-overall { font-size: 12.5px; color: var(--muted); }
.contract-overall strong { color: var(--text); }

.cov-total { margin-bottom: 14px; }
.cov-total-number { font-family: ui-monospace, monospace; font-size: 28px; font-weight: 700; }
.cov-total-label { font-size: 11.5px; color: var(--muted); margin-left: 8px; }
.cov-files { display: flex; flex-direction: column; gap: 7px; }
.cov-row { display: flex; align-items: center; gap: 8px; font-size: 11.5px; }
.cov-path { flex: 0 0 46%; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cov-track { flex: 1; height: 5px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; }
.cov-fill { height: 100%; }
.cov-pct { width: 34px; text-align: right; }

footer {
    text-align: center;
    color: var(--muted);
    font-size: 11.5px;
    padding: 24px 0 32px;
}
footer .sep { margin: 0 8px; opacity: 0.5; }
"""

    @staticmethod
    def _js() -> str:
        return """
document.querySelectorAll('.filter-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
        document.querySelectorAll('.filter-btn').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        var filter = btn.dataset.filter;
        document.querySelectorAll('#test-table tbody tr').forEach(function(row) {
            if (filter === 'all' || row.dataset.status === filter) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    });
});
"""
