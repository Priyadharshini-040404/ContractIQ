"""
ContractIQ - Dredd Compatibility Spec Generator

Dredd's OpenAPI parser (as of v14.x) has two limitations that don't affect
Schemathesis or the FastAPI app itself:
  1. It doesn't fully support OpenAPI 3.1.x (only 3.0.x) - same issue we
     already fixed for Schemathesis via --experimental=openapi-3.1.
  2. It requires an `example` value directly on the parameter object
     (sibling to `schema`), not nested inside `schema.example` - even
     though nesting it under `schema` is perfectly valid OpenAPI 3.0/3.1.

This script reads the real spec (configs/openapi_spec.yaml) and writes a
Dredd-only compatibility copy with both issues patched, without touching
the original spec that Schemathesis/FastAPI/everything else uses.

Run this automatically before Dredd via: python qa/make_dredd_spec.py
"""
import yaml
import json
import sys
from pathlib import Path

SOURCE_SPEC = "configs/openapi_spec.yaml"
OUTPUT_SPEC = "configs/openapi_spec_dredd.json"


def fix_parameters(obj):
    """Recursively walk the spec and pull schema.example up to the
    parameter level wherever a path/query parameter has one nested."""
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


def main():
    with open(SOURCE_SPEC, "r") as f:
        spec = yaml.safe_load(f)

    # Fix 1: pull nested schema.example up to parameter level for Dredd
    fix_parameters(spec)

    # Fix 2: Dredd's parser only fully supports OpenAPI 3.0.x
    if spec.get("openapi", "").startswith("3.1"):
        spec["openapi"] = "3.0.3"

    Path(OUTPUT_SPEC).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_SPEC, "w") as f:
        json.dump(spec, f, indent=2)

    print(f"Dredd-compatible spec written to {OUTPUT_SPEC}")


if __name__ == "__main__":
    main()
