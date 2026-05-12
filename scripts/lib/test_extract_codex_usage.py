"""Tests for scripts/lib/extract_codex_usage.py."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import extract_codex_usage as ecu  # noqa: E402


def _write_trace(p: pathlib.Path, events: list[dict]) -> None:
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def test_missing_trace_returns_zeros(tmp_path):
    out = ecu.compute_usage(tmp_path / "nope.jsonl")
    assert out["input_tokens"] == 0
    assert out["output_tokens"] == 0
    assert out["real_usd"] == 0.0
    assert out["usage_found"] is False


def test_turn_completed_event_is_picked_up(tmp_path):
    trace = tmp_path / "trace.jsonl"
    _write_trace(trace, [
        {"type": "thread.started", "session_id": "s1"},
        {"type": "turn.completed", "model": "gpt-5",
         "usage": {"input_tokens": 1000, "cached_input_tokens": 800, "output_tokens": 200}},
    ])
    out = ecu.compute_usage(trace)
    assert out["usage_found"] is True
    assert out["input_tokens"] == 1000
    assert out["cached_input_tokens"] == 800
    assert out["output_tokens"] == 200
    assert 0.79 < out["cached_input_ratio"] < 0.81
    # gpt-5 may have snapshot pricing; the value should be positive.
    assert out["real_usd"] > 0
    # uncached equivalent must be >= cached real (cache discount applied).
    assert out["real_usd_uncached_equivalent"] >= out["real_usd"]


def test_last_usage_wins_when_multiple_events(tmp_path):
    trace = tmp_path / "trace.jsonl"
    _write_trace(trace, [
        {"type": "token_count", "usage": {"input_tokens": 10, "output_tokens": 1}},
        {"type": "turn.completed", "usage": {"input_tokens": 200, "output_tokens": 50}},
    ])
    out = ecu.compute_usage(trace, model_hint="gpt-5")
    assert out["input_tokens"] == 200
    assert out["output_tokens"] == 50


def test_legacy_openai_shape_supported(tmp_path):
    trace = tmp_path / "trace.jsonl"
    _write_trace(trace, [
        {"type": "turn.completed", "model": "gpt-5",
         "usage": {"prompt_tokens": 500,
                   "prompt_tokens_details": {"cached_tokens": 100},
                   "completion_tokens": 80,
                   "completion_tokens_details": {"reasoning_tokens": 20}}},
    ])
    out = ecu.compute_usage(trace)
    assert out["input_tokens"] == 500
    assert out["cached_input_tokens"] == 100
    assert out["output_tokens"] == 80
    assert out["reasoning_tokens"] == 20


def test_cli_writes_usage_json(tmp_path):
    trace = tmp_path / "trace.jsonl"
    _write_trace(trace, [
        {"type": "turn.completed", "model": "gpt-5",
         "usage": {"input_tokens": 100, "output_tokens": 10}},
    ])
    out = tmp_path / "usage.json"
    ecu.main([str(trace), "--write", str(out)])
    data = json.loads(out.read_text())
    assert data["usage_found"] is True
    assert data["input_tokens"] == 100


def test_unparseable_lines_are_skipped(tmp_path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        "garbage not json\n"
        + json.dumps({"type": "turn.completed",
                      "usage": {"input_tokens": 7, "output_tokens": 3}}) + "\n"
        + "{broken\n"
    )
    out = ecu.compute_usage(trace)
    assert out["usage_found"] is True
    assert out["input_tokens"] == 7
