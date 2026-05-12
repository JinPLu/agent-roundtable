from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from oracle_runner import main, run_oracles  # noqa: E402


def _write_oracles(project: pathlib.Path, body: str) -> None:
    cfg = project / ".roundtable" / "oracles.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(body, encoding="utf-8")


def test_missing_config_skips_gracefully(tmp_path: pathlib.Path) -> None:
    thread = tmp_path / ".roundtable" / "threads" / "t1"
    thread.mkdir(parents=True)

    result = run_oracles(tmp_path, thread, event="before_review")

    assert result["status"] == "SKIPPED"
    assert result["results"] == []
    assert (thread / ".roundtable" / "last_oracle.json").is_file()


def test_must_pass_success_and_warn_failure(tmp_path: pathlib.Path) -> None:
    thread = tmp_path / ".roundtable" / "threads" / "t1"
    thread.mkdir(parents=True)
    _write_oracles(
        tmp_path,
        """
oracles:
  - name: pass
    cmd: python3 -c "print('ok')"
    must_pass: true
    timeout_s: 5
    on: [before_review]
  - name: warn
    cmd: python3 -c "import sys; print('warn fail'); sys.exit(3)"
    must_pass: false
    timeout_s: 5
    on: [before_review]
""",
    )

    result = run_oracles(tmp_path, thread, event="before_review")

    assert result["status"] == "PASS"
    assert [item["name"] for item in result["results"]] == ["pass", "warn"]
    assert result["results"][0]["exit_code"] == 0
    assert result["results"][1]["exit_code"] == 3
    assert result["must_pass_failed"] == []


def test_on_filter_skips_non_matching_oracles(tmp_path: pathlib.Path) -> None:
    thread = tmp_path / ".roundtable" / "threads" / "t1"
    thread.mkdir(parents=True)
    _write_oracles(
        tmp_path,
        """
oracles:
  - name: before-review
    cmd: python3 -c "print('run')"
    must_pass: true
    on: [before_review]
  - name: before-done
    cmd: python3 -c "print('skip')"
    must_pass: true
    on: [before_done]
""",
    )

    result = run_oracles(tmp_path, thread, event="before_review")

    assert [item["name"] for item in result["results"]] == ["before-review"]


def test_must_pass_failure_sets_fail_status(tmp_path: pathlib.Path) -> None:
    thread = tmp_path / ".roundtable" / "threads" / "t1"
    thread.mkdir(parents=True)
    _write_oracles(
        tmp_path,
        """
oracles:
  - name: fail
    cmd: python3 -c "import sys; print('bad'); sys.exit(7)"
    must_pass: true
    timeout_s: 5
""",
    )

    result = run_oracles(tmp_path, thread, event="before_review")

    assert result["status"] == "FAIL"
    assert result["must_pass_failed"] == ["fail"]
    assert result["results"][0]["stdout_tail"] == "bad"


def test_timeout_is_recorded_as_failure(tmp_path: pathlib.Path) -> None:
    thread = tmp_path / ".roundtable" / "threads" / "t1"
    thread.mkdir(parents=True)
    _write_oracles(
        tmp_path,
        """
oracles:
  - name: slow
    cmd: python3 -c "import time; time.sleep(2)"
    must_pass: true
    timeout_s: 0.1
""",
    )

    result = run_oracles(tmp_path, thread, event="before_review")

    assert result["status"] == "FAIL"
    assert result["results"][0]["timed_out"] is True
    assert result["results"][0]["exit_code"] == 124


def test_cli_writes_json_output(tmp_path: pathlib.Path, capsys) -> None:
    thread = tmp_path / ".roundtable" / "threads" / "t1"
    thread.mkdir(parents=True)

    rc = main(["--project", str(tmp_path), "--thread-dir", str(thread), "--event", "before_review"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "SKIPPED"
    saved = json.loads((thread / ".roundtable" / "last_oracle.json").read_text(encoding="utf-8"))
    assert saved["status"] == "SKIPPED"
