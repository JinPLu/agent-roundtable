#!/usr/bin/env python3
"""Run project-local oracles and persist the result for the current thread."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
from datetime import datetime, timezone
from typing import Any


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strip_inline_comment(text: str) -> str:
    out: list[str] = []
    in_single = False
    in_double = False
    for ch in text:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
    return "".join(out).strip()


def _parse_scalar(text: str) -> Any:
    raw = _strip_inline_comment(text.strip())
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    if raw.startswith("[") and raw.endswith("]"):
        body = raw[1:-1].strip()
        if not body:
            return []
        return [chunk.strip().strip("'\"") for chunk in body.split(",") if chunk.strip()]
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    if len(raw) >= 2 and ((raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'"))):
        return raw[1:-1]
    return raw


def _parse_oracles_yaml(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    oracles: list[dict[str, Any]] = []
    in_oracles = False
    current: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "oracles:":
            in_oracles = True
            continue
        if not in_oracles:
            continue
        if stripped.startswith("- "):
            if current is not None:
                oracles.append(current)
            current = {}
            remainder = stripped[2:].strip()
            if remainder and ":" in remainder:
                key, value = remainder.split(":", 1)
                current[key.strip()] = _parse_scalar(value)
            continue
        if current is None or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        current[key.strip()] = _parse_scalar(value)
    if current is not None:
        oracles.append(current)
    return oracles


def _stdout_tail(text: str, max_lines: int = 20) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.rstrip()]
    return "\n".join(lines[-max_lines:]).strip()


def _match_event(oracle: dict[str, Any], event: str) -> bool:
    on = oracle.get("on")
    if not on:
        return True
    if isinstance(on, str):
        return on == event
    if isinstance(on, list):
        return event in on
    return False


def _run_one(oracle: dict[str, Any], project_root: pathlib.Path) -> dict[str, Any]:
    cmd = str(oracle.get("cmd", ""))
    timeout_s = oracle.get("timeout_s")
    timeout = float(timeout_s) if timeout_s not in (None, "") else None
    timed_out = False
    try:
        proc = subprocess.run(
            ["bash", "-lc", cmd],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        exit_code = proc.returncode
        stdout = proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
    return {
        "name": str(oracle.get("name", "")),
        "exit_code": int(exit_code),
        "must_pass": bool(oracle.get("must_pass", False)),
        "stdout_tail": _stdout_tail(stdout),
        "timed_out": timed_out,
        "on": oracle.get("on"),
    }


def run_oracles(
    project_root: pathlib.Path,
    thread_dir: pathlib.Path,
    *,
    event: str,
    config_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    config_path = config_path or (project_root / ".roundtable" / "oracles.yaml")
    out_path = thread_dir / ".roundtable" / "last_oracle.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "ts": _iso_now(),
        "event": event,
        "project_root": str(project_root),
        "thread_dir": str(thread_dir),
        "config_path": str(config_path),
    }
    if not config_path.exists():
        payload.update({"status": "SKIPPED", "results": [], "must_pass_failed": []})
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    oracles = _parse_oracles_yaml(config_path)
    results = [_run_one(oracle, project_root) for oracle in oracles if _match_event(oracle, event)]
    failures = [item["name"] for item in results if item["must_pass"] and item["exit_code"] != 0]
    payload.update(
        {
            "status": "FAIL" if failures else "PASS",
            "results": results,
            "must_pass_failed": failures,
        }
    )
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("ROUNDTABLE_PROJECT_ROOT"))
    parser.add_argument("--thread-dir", default=None)
    parser.add_argument("--thread", default=None)
    parser.add_argument("--event", required=True)
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    project_root = pathlib.Path(args.project or os.getcwd()).resolve()
    if args.thread_dir:
        thread_dir = pathlib.Path(args.thread_dir).resolve()
    elif args.thread:
        thread_dir = (project_root / ".roundtable" / "threads" / args.thread).resolve()
    else:
        raise SystemExit("--thread-dir or --thread is required")
    config_path = pathlib.Path(args.config).resolve() if args.config else None
    payload = run_oracles(project_root, thread_dir, event=args.event, config_path=config_path)
    print(json.dumps(payload, indent=2))
    return 1 if payload.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
