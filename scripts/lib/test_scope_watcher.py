"""Tests for scripts/lib/scope_watcher.py.

The watcher is a long-running tail loop; tests drive it through internal
helpers (parse, match, extract) plus a bounded `max_iterations` watch loop
that uses a fake live trace.jsonl.
"""
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import scope_watcher as sw  # noqa: E402


def _write_goal(thread_dir: pathlib.Path, in_scope: list[str], out_scope: list[str]) -> None:
    body = ["# Goal", "", "## In-scope paths"]
    for p in in_scope:
        body.append(f"- {p}")
    body += ["", "## Out-of-scope"]
    for p in out_scope:
        body.append(f"- {p}")
    (thread_dir / "GOAL.md").write_text("\n".join(body) + "\n")


def test_parse_goal_md_basic(tmp_path):
    thread = tmp_path
    _write_goal(thread, ["src/**/*.py"], ["secrets/**"])
    in_s, out_s = sw.parse_goal_md(thread / "GOAL.md")
    assert in_s == ["src/**/*.py"]
    assert out_s == ["secrets/**"]


def test_parse_goal_md_missing_is_fail_open(tmp_path):
    in_s, out_s = sw.parse_goal_md(tmp_path / "GOAL.md")
    assert in_s == []
    assert out_s == []


def test_matches_any_glob_and_prefix():
    assert sw.matches_any("src/foo/bar.py", ["src/**/*.py"]) is True
    assert sw.matches_any("docs/research/x.md", ["docs/research/"]) is True
    assert sw.matches_any("other/file", ["src/**/*.py"]) is False


def test_extract_paths_from_codex_event_shapes():
    # Top-level item.file_change
    evt = {"type": "item.completed", "item": {"type": "file_change", "path": "src/a.py"}}
    assert sw._extract_paths(evt) == ["src/a.py"]
    # Nested under msg
    evt2 = {"msg": {"type": "file_change", "path": "src/b.py"}}
    assert sw._extract_paths(evt2) == ["src/b.py"]
    # paths list
    evt3 = {"item": {"type": "file_changes", "paths": ["a", "b"]}}
    assert set(sw._extract_paths(evt3)) == {"a", "b"}
    # Unknown type ignored
    assert sw._extract_paths({"type": "noise", "path": "x"}) == []


def test_no_violation_with_pid_exit(tmp_path):
    thread = tmp_path
    _write_goal(thread, ["src/**/*.py"], ["secrets/**"])
    trace = thread / "trace.jsonl"
    trace.write_text("")
    # Spawn a tiny dummy process that exits quickly.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"])
    rc = sw.watch(
        pid=proc.pid,
        trace_path=trace,
        thread_dir=thread,
        idle_poll_s=0.05,
        grace_s=0.5,
        project_root=thread,
        max_iterations=200,
    )
    proc.wait()
    assert rc == 0
    assert not (thread / "SCOPE_VIOLATION_REALTIME.md").exists()


def test_violation_triggers_sigterm(tmp_path):
    thread = tmp_path
    _write_goal(thread, ["src/**/*.py"], ["secrets/**"])
    trace = thread / "trace.jsonl"
    # Spawn a long-sleeping process we expect the watcher to kill.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        # Write an out-of-scope file_change event into the trace.
        trace.write_text(json.dumps({
            "type": "item.completed",
            "item": {"type": "file_change", "path": "secrets/keys.txt"},
        }) + "\n")
        rc = sw.watch(
            pid=proc.pid,
            trace_path=trace,
            thread_dir=thread,
            idle_poll_s=0.05,
            grace_s=2.0,
            project_root=thread,
            max_iterations=200,
        )
        assert rc == 1, "watcher should report violation exit"
        assert (thread / "SCOPE_VIOLATION_REALTIME.md").exists()
        report = (thread / "SCOPE_VIOLATION_REALTIME.md").read_text()
        assert "secrets/keys.txt" in report
        # process should be terminated; if still alive after a moment, force kill.
        deadline = time.time() + 3.0
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                proc.kill()


def test_in_scope_unspecified_warns_but_does_not_kill(tmp_path, capsys):
    thread = tmp_path
    _write_goal(thread, ["src/**/*.py"], ["secrets/**"])
    trace = thread / "trace.jsonl"
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
    try:
        trace.write_text(json.dumps({
            "type": "item.completed",
            "item": {"type": "file_change", "path": "docs/x.md"},
        }) + "\n")
        rc = sw.watch(
            pid=proc.pid,
            trace_path=trace,
            thread_dir=thread,
            idle_poll_s=0.05,
            grace_s=0.5,
            project_root=thread,
            max_iterations=200,
        )
    finally:
        proc.wait()
    assert rc == 0
    assert not (thread / "SCOPE_VIOLATION_REALTIME.md").exists()


def test_goal_missing_fail_open(tmp_path):
    thread = tmp_path
    trace = thread / "trace.jsonl"
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"])
    try:
        trace.write_text(json.dumps({
            "type": "item.completed",
            "item": {"type": "file_change", "path": "secrets/keys.txt"},
        }) + "\n")
        rc = sw.watch(
            pid=proc.pid,
            trace_path=trace,
            thread_dir=thread,
            idle_poll_s=0.05,
            grace_s=0.5,
            project_root=thread,
            max_iterations=200,
        )
    finally:
        proc.wait()
    # No GOAL.md → fail-open: no kill, no report.
    assert rc == 0
    assert not (thread / "SCOPE_VIOLATION_REALTIME.md").exists()
