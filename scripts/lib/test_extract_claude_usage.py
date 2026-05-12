"""Tests for scripts/lib/extract_claude_usage.py.

Covers both the minimal shipped implementation (`compute(last_json) -> dict`
with `usage_found`) and the documented CLI shape (`--write` flag, exit code).
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import extract_claude_usage as ecu  # noqa: E402


def test_missing_file_marks_usage_not_found(tmp_path):
    out = ecu.compute(tmp_path / "nope.json")
    assert out["usage_found"] is False


def test_no_usage_block_marks_not_found(tmp_path):
    src = tmp_path / "last.json"
    src.write_text(json.dumps({"result": "hi", "model": "claude-opus-4-7"}))
    out = ecu.compute(src)
    assert out["usage_found"] is False


def test_top_level_usage_is_priced(tmp_path):
    src = tmp_path / "last.json"
    src.write_text(json.dumps({
        "model": "claude-opus-4-7",
        "usage": {
            "input_tokens": 10000,
            "cache_read_input_tokens": 50000,
            "output_tokens": 2000,
        },
    }))
    out = ecu.compute(src)
    assert out["usage_found"] is True
    assert out["input_tokens"] == 10000
    assert out["cache_read_input_tokens"] == 50000
    assert out["output_tokens"] == 2000
    assert out["real_usd"] > 0


def test_nested_result_usage_supported(tmp_path):
    src = tmp_path / "last.json"
    src.write_text(json.dumps({
        "result": {"usage": {"input_tokens": 1, "output_tokens": 1}},
    }))
    out = ecu.compute(src)
    assert out["usage_found"] is True
    assert out["input_tokens"] == 1


def test_cli_writes_payload(tmp_path):
    src = tmp_path / "last.json"
    src.write_text(json.dumps({
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }))
    dst = tmp_path / "usage.json"
    rc = ecu.main([str(src), "--write", str(dst)])
    assert rc == 0
    data = json.loads(dst.read_text())
    assert data["usage_found"] is True


def test_cli_exit_code_when_usage_missing(tmp_path):
    src = tmp_path / "last.json"
    src.write_text(json.dumps({}))
    rc = ecu.main([str(src)])
    assert rc != 0
