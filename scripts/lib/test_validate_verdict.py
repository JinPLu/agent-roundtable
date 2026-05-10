import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from validate_verdict import validate_verdict_file

_SCHEMA = pathlib.Path(__file__).resolve().parents[2] / "roles" / "reviewer.schema.json"


def _write_verdict(data: dict, tmp_path) -> pathlib.Path:
    p = pathlib.Path(tmp_path) / "verdict.json"
    p.write_text(json.dumps(data))
    return p


def test_empty_verdict_has_errors(tmp_path):
    p = _write_verdict({}, tmp_path)
    errs = validate_verdict_file(p, _SCHEMA)
    assert len(errs) > 0, "empty verdict should have required-field errors"


def test_invalid_json_file(tmp_path):
    p = pathlib.Path(tmp_path) / "verdict.json"
    p.write_text("not json")
    errs = validate_verdict_file(p, _SCHEMA)
    assert len(errs) > 0


def test_missing_schema_file(tmp_path):
    p = _write_verdict({}, tmp_path)
    errs = validate_verdict_file(p, pathlib.Path("/nonexistent/schema.json"))
    assert len(errs) > 0
