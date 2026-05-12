from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from trace_capture import capture_trace, main  # noqa: E402


def test_capture_codex_request_id(tmp_path: pathlib.Path) -> None:
    stderr = tmp_path / "cli_stderr.log"
    stderr.write_text("error: request_id=req_codex_123 extra\n", encoding="utf-8")

    payload = capture_trace(stderr, model_version="gpt-5.5", ts="2026-05-12T00:00:00Z")

    assert payload["request_ids"] == ["req_codex_123"]
    assert payload["model_version"] == "gpt-5.5"


def test_capture_claude_x_request_id(tmp_path: pathlib.Path) -> None:
    stderr = tmp_path / "cli_stderr.log"
    stderr.write_text("HTTP 529 x-request-id: claude-abc-999\n", encoding="utf-8")

    payload = capture_trace(stderr, model_version="claude-opus", ts="2026-05-12T00:00:00Z")

    assert payload["request_ids"] == ["claude-abc-999"]


def test_no_request_id_is_graceful(tmp_path: pathlib.Path) -> None:
    stderr = tmp_path / "cli_stderr.log"
    stderr.write_text("plain error without id\n", encoding="utf-8")

    payload = capture_trace(stderr, model_version="unknown", ts="2026-05-12T00:00:00Z")

    assert payload["request_ids"] == []


def test_cli_writes_json(tmp_path: pathlib.Path, capsys) -> None:
    stderr = tmp_path / "cli_stderr.log"
    out = tmp_path / "trace.json"
    stderr.write_text("x-request-id=abc123\n", encoding="utf-8")

    rc = main([str(stderr), "--out", str(out), "--model-version", "model-x", "--ts", "2026-05-12T00:00:00Z"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["request_ids"] == ["abc123"]
    assert json.loads(out.read_text(encoding="utf-8"))["request_ids"] == ["abc123"]
