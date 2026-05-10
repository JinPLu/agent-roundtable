#!/usr/bin/env python3
"""Validate a verdict.json against roles/reviewer.schema.json without jsonschema dep.

Uses a manual check covering: required fields, enum values, additionalProperties=false.
"""
import json
import pathlib
import sys

_SKILL_DIR = pathlib.Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _SKILL_DIR / "roles" / "reviewer.schema.json"


def _validate(verdict: dict, schema: dict, path: str = "root") -> list[str]:
    errors = []
    props = schema.get("properties", {})
    required = schema.get("required", [])
    additional_ok = schema.get("additionalProperties", True)

    for req in required:
        if req not in verdict:
            errors.append(f"{path}.{req}: missing required field")

    for key in verdict:
        if key not in props:
            if not additional_ok:
                errors.append(f"{path}.{key}: additional property not allowed")
        else:
            sub_schema = props[key]
            val = verdict[key]
            expected_type = sub_schema.get("type")
            if expected_type == "string" and not isinstance(val, str):
                errors.append(f"{path}.{key}: expected string, got {type(val).__name__}")
            elif expected_type == "array" and not isinstance(val, list):
                errors.append(f"{path}.{key}: expected array, got {type(val).__name__}")
            elif expected_type == "object" and not isinstance(val, dict):
                errors.append(f"{path}.{key}: expected object, got {type(val).__name__}")
            if "enum" in sub_schema and val not in sub_schema["enum"]:
                errors.append(f"{path}.{key}: {val!r} not in enum {sub_schema['enum']}")
            if expected_type == "object" and isinstance(val, dict):
                errors.extend(_validate(val, sub_schema, f"{path}.{key}"))
            if expected_type == "array" and isinstance(val, list) and "items" in sub_schema:
                for i, item in enumerate(val):
                    if isinstance(item, dict):
                        errors.extend(_validate(item, sub_schema["items"], f"{path}.{key}[{i}]"))
    return errors


def validate_verdict_file(verdict_path: pathlib.Path, schema_path: pathlib.Path = _SCHEMA_PATH) -> list[str]:
    """Return list of validation errors (empty = valid)."""
    try:
        verdict = json.loads(verdict_path.read_text())
    except (json.JSONDecodeError, FileNotFoundError) as e:
        return [f"Cannot read/parse verdict: {e}"]
    try:
        schema = json.loads(schema_path.read_text())
    except (json.JSONDecodeError, FileNotFoundError) as e:
        return [f"Cannot read/parse schema: {e}"]
    return _validate(verdict, schema)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: validate_verdict.py <verdict.json>", file=sys.stderr)
        sys.exit(1)
    errs = validate_verdict_file(pathlib.Path(sys.argv[1]))
    if errs:
        for e in errs:
            print(f"SCHEMA ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print("verdict.json: valid")
    sys.exit(0)
