"""
ContractIQ - Contract Validation Engine
Uses Schemathesis for property-based contract testing and Dredd for
OpenAPI conformance validation.
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
import requests
import yaml


class SchemathesisValidator:
    """Property-based API contract testing using Schemathesis."""

    def __init__(self, spec_path: str, base_url: str = "http://localhost:8000"):
        self.spec_path = Path(spec_path)
        self.base_url = base_url.rstrip("/")
        self.results: list[dict] = []

    def _spec_declares_openapi_31(self) -> bool:
        """Detect whether the spec is OpenAPI 3.1.x, which needs the
        --experimental=openapi-3.1 flag on this Schemathesis version."""
        try:
            with open(self.spec_path, "r") as f:
                content = f.read(500)
            return "3.1" in content.split("openapi", 1)[-1][:20] if "openapi" in content else False
        except (FileNotFoundError, IndexError):
            return False

    def _resolve_schemathesis_binary(self) -> str:
        """Locate the schemathesis console-script.

        Plain "schemathesis" only resolves if PATH happens to include
        the environment it was installed into (e.g. an activated venv).
        Running via a differently-invoked interpreter — `/path/venv/bin/
        python main.py ...` without that venv's bin/ on PATH, which is
        exactly how CI and many IDEs invoke it — would otherwise report
        a false "skipped" even though schemathesis is installed right
        next to the interpreter running this code.
        
        On Windows, also check for .exe extension.
        """
        import shutil
        import platform
        
        found = shutil.which("schemathesis")
        if found:
            return found
        
        sibling_dir = Path(sys.executable).parent
        
        # On Windows, look for .exe extension
        if platform.system() == "Windows":
            sibling_exe = sibling_dir / "schemathesis.exe"
            if sibling_exe.exists():
                return str(sibling_exe)
        
        sibling = sibling_dir / "schemathesis"
        if sibling.exists():
            return str(sibling)
        return "schemathesis"

    def run_validation(self, output_dir: str = "output/schemathesis") -> dict:
        """Run Schemathesis contract validation via CLI."""
        import platform
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        report_file = output_path / "schemathesis_report.json"

        # Call the "schemathesis" console-script entry point directly.
        # `python -m schemathesis run ...` fails on this version because
        # schemathesis is a package, not a runnable module.
        cmd = [
            self._resolve_schemathesis_binary(), "run",
            str(self.spec_path),
            "--base-url", self.base_url,
            "--checks", "all",
            "--hypothesis-max-examples", "20",
            "--report", str(report_file),
        ]

        if self._spec_declares_openapi_31():
            cmd.append("--experimental=openapi-3.1")

        try:
            # On Windows, use shell=True for cmd wrappers
            use_shell = platform.system() == "Windows"
            
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, shell=use_shell
            )
            return {
                "status": "passed" if result.returncode == 0 else "failed",
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:2000],
                "report_path": str(report_file),
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "Validation timed out after 120s"}
        except FileNotFoundError:
            return {"status": "skipped", "error": "Schemathesis not installed"}

    def validate_schema_compliance(self, spec_path: str = None) -> dict:
        """Validate that the OpenAPI spec itself is well-formed."""
        spec_file = Path(spec_path) if spec_path else self.spec_path

        try:
            with open(spec_file) as f:
                if spec_file.suffix in ('.yaml', '.yml'):
                    spec = yaml.safe_load(f)
                else:
                    spec = json.load(f)

            issues = []

            # Check required fields
            if "openapi" not in spec:
                issues.append({"level": "error", "message": "Missing 'openapi' version field"})
            if "info" not in spec:
                issues.append({"level": "error", "message": "Missing 'info' section"})
            if "paths" not in spec:
                issues.append({"level": "error", "message": "Missing 'paths' section"})

            # Validate paths
            for path, methods in spec.get("paths", {}).items():
                for method, operation in methods.items():
                    if method not in ("get", "post", "put", "delete", "patch", "options", "head"):
                        continue
                    if "responses" not in operation:
                        issues.append({
                            "level": "warning",
                            "message": f"Missing responses for {method.upper()} {path}"
                        })
                    if "operationId" not in operation:
                        issues.append({
                            "level": "info",
                            "message": f"Missing operationId for {method.upper()} {path}"
                        })

            # Validate schemas
            for name, schema in spec.get("components", {}).get("schemas", {}).items():
                if "type" not in schema and "allOf" not in schema and "$ref" not in schema:
                    issues.append({
                        "level": "warning",
                        "message": f"Schema '{name}' missing type definition"
                    })

            return {
                "status": "valid" if not any(i["level"] == "error" for i in issues) else "invalid",
                "issues": issues,
                "total_paths": len(spec.get("paths", {})),
                "total_schemas": len(spec.get("components", {}).get("schemas", {})),
                "openapi_version": spec.get("openapi", "unknown"),
            }

        except Exception as e:
            return {"status": "error", "error": str(e)}


class DreddValidator:
    """API contract conformance validation using Dredd."""

    def __init__(self, spec_path: str, base_url: str = "http://localhost:8000"):
        self.spec_path = str(spec_path)
        self.base_url = base_url.rstrip("/")

    def _make_dredd_compatible_spec(self, output_path: str = "configs/openapi_spec_dredd.json") -> str:
        """Dredd's parser (as of v14.x) doesn't fully support OpenAPI 3.1
        and requires `example` directly on the parameter object rather
        than nested inside `schema.example`. Write a patched copy for
        Dredd only, leaving the real spec (used by Schemathesis/FastAPI)
        untouched. Equivalent to running qa/make_dredd_spec.py.
        """
        def fix_parameters(obj):
            if isinstance(obj, dict):
                if obj.get("in") in ("path", "query") and "schema" in obj:
                    schema = obj["schema"]
                    if isinstance(schema, dict) and "example" in schema and "example" not in obj:
                        obj["example"] = schema["example"]
                for v in obj.values():
                    fix_parameters(v)
            elif isinstance(obj, list):
                for item in obj:
                    fix_parameters(item)

        with open(self.spec_path, "r") as f:
            spec = yaml.safe_load(f) if str(self.spec_path).endswith((".yaml", ".yml")) else json.load(f)

        fix_parameters(spec)
        if spec.get("openapi", "").startswith("3.1"):
            spec["openapi"] = "3.0.3"

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump(spec, f, indent=2)

        return str(out.resolve())

    def generate_dredd_config(self, output_path: str = "configs/dredd.yml") -> str:
        """Generate Dredd configuration file."""
        config = {
            "color": True,
            "dry-run": None,
            "hookfiles": None,
            "language": "python",
            "require": None,
            "server": f"python -m uvicorn api.petstore_api:app --host 0.0.0.0 --port 8000",
            "server-wait": 5,
            "init": False,
            "custom": {
                "apiaryApiKey": "",
                "apiaryApiName": ""
            },
            "names": False,
            "only": [],
            "reporter": ["json"],
            "output": ["output/dredd_report.json"],
            "header": ["Content-Type: application/json"],
            "sorted": False,
            "user": None,
            "inline-errors": False,
            "details": False,
            "method": [],
            "loglevel": "warning",
            "path": [],
            "blueprint": self.spec_path,
            "endpoint": self.base_url
        }

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)

        return str(out.resolve())

    def run_validation(self, output_dir: str = "output/dredd") -> dict:
        """Run Dredd contract validation.

        Dredd's parser can't consume our OpenAPI 3.1 spec as-is (see
        _make_dredd_compatible_spec), so we generate a patched, Dredd-only
        copy first and point Dredd at that instead of the original.
        
        On Windows, Dredd is installed as a .cmd wrapper by npm, so we need
        shell=True and the full command string.
        """
        import platform
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        try:
            dredd_spec = self._make_dredd_compatible_spec()
        except Exception as e:
            return {"status": "error", "error": f"Failed to prepare Dredd-compatible spec: {e}"}

        cmd = [
            "dredd", dredd_spec, self.base_url,
            "--reporter", "json",
            "--output", str(output_path / "dredd_report.json"),
            "--hookfiles", "qa/dredd_hooks.js",
        ]

        try:
            # On Windows, npm .cmd wrappers don't work with subprocess unless shell=True
            use_shell = platform.system() == "Windows"
            
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, shell=use_shell
            )
            return {
                "status": "passed" if result.returncode == 0 else "failed",
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:2000],
                "return_code": result.returncode,
                "spec_used": dredd_spec,
            }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "Dredd timed out after 120s"}
        except FileNotFoundError:
            return {"status": "skipped", "error": "Dredd not installed (npm install -g dredd)"}


class ContractValidator:
    """Unified contract validation combining Schemathesis and Dredd."""

    def __init__(self, spec_path: str, base_url: str = "http://localhost:8000"):
        self.spec_path = spec_path
        self.base_url = base_url
        self.schemathesis = SchemathesisValidator(spec_path, base_url)
        self.dredd = DreddValidator(spec_path, base_url)

    def validate_spec_only(self) -> dict:
        """Validate the OpenAPI specification without running the API."""
        return self.schemathesis.validate_schema_compliance()

    def run_live_validation(self) -> dict:
        """Run both Schemathesis and Dredd against a live API."""
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "spec_path": self.spec_path,
            "base_url": self.base_url,
            "schemathesis": {},
            "dredd": {},
            "overall_status": "unknown",
        }

        # Run Schemathesis
        print("  Running Schemathesis validation...")
        results["schemathesis"] = self.schemathesis.run_validation()

        # Run Dredd
        print("  Running Dredd validation...")
        results["dredd"] = self.dredd.run_validation()

        # Determine overall status
        statuses = [
            results["schemathesis"].get("status", "unknown"),
            results["dredd"].get("status", "unknown"),
        ]
        if all(s == "passed" for s in statuses):
            results["overall_status"] = "passed"
        elif any(s == "failed" for s in statuses):
            results["overall_status"] = "failed"
        elif any(s == "skipped" for s in statuses):
            results["overall_status"] = "partial"
        else:
            results["overall_status"] = "unknown"

        return results

    def validate_response_against_schema(
        self, response: requests.Response, expected_schema: dict
    ) -> dict:
        """Validate a single API response against its expected schema."""
        issues = []

        try:
            body = response.json()
        except Exception:
            if expected_schema:
                issues.append("Response is not valid JSON but schema expected JSON body")
            return {"valid": len(issues) == 0, "issues": issues}

        # Validate required fields
        required_fields = expected_schema.get("required", [])
        for field in required_fields:
            if field not in body:
                issues.append(f"Missing required field: {field}")

        # Validate property types
        properties = expected_schema.get("properties", {})
        for prop_name, prop_def in properties.items():
            if prop_name in body:
                expected_type = prop_def.get("type", "")
                actual_value = body[prop_name]
                if not self._type_matches(actual_value, expected_type):
                    issues.append(
                        f"Type mismatch for '{prop_name}': expected {expected_type}, "
                        f"got {type(actual_value).__name__}"
                    )

                # Check enum constraints
                if "enum" in prop_def and actual_value not in prop_def["enum"]:
                    issues.append(
                        f"Invalid enum value for '{prop_name}': {actual_value}. "
                        f"Expected one of {prop_def['enum']}"
                    )

        return {"valid": len(issues) == 0, "issues": issues}

    @staticmethod
    def _type_matches(value: Any, expected_type: str) -> bool:
        """Check if a value matches the expected JSON schema type."""
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        expected = type_map.get(expected_type)
        if expected is None:
            return True
        return isinstance(value, expected)
