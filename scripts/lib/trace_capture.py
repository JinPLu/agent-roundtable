#!/usr/bin/env python3
"""Capture request-id traces from CLI stderr logs."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any


_PATTERNS = [
    re.compile(r"\b(?:x-)?request[_-]?id\b\s*[:=]\s*([A-Za-z0-9._:/-]+)", re.IGNORECASE),
    re.compile(r"\brequest_id=([A-Za-z0-9._:/-]+)", re.IGNORECASE),
]


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _locate_stderr(path: pathlib.Path) -> pathlib.Path:
    if path.exists():
        return path
    alt = path.with_name("stderr.log")
    if alt.exists():
        return alt
    return path


def capture_trace(
    stderr_path: pathlib.Path,
    *,
    model_version: str,
    ts: str | None = None,
    turn_n: int | None = None,
    source_file: str | None = None,
) -> dict[str, Any]:
    actual = _locate_stderr(stderr_path)
    request_ids: list[str] = []
    if actual.exists():
        for line in actual.read_text(encoding="utf-8", errors="replace").splitlines():
            for pattern in _PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                request_id = match.group(1)
                if request_id not in request_ids:
                    request_ids.append(request_id)
    return {
        "ts": ts or _iso_now(),
        "model_version": model_version,
        "turn_n": turn_n,
        "source_file": source_file,
        "stderr_path": str(actual),
        "request_ids": request_ids,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stderr_path")
    parser.add_argument("--out", default=None)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--ts", default=None)
    parser.add_argument("--turn-n", type=int, default=None)
    parser.add_argument("--source-file", default=None)
    args = parser.parse_args(argv)
    payload = capture_trace(
        pathlib.Path(args.stderr_path),
        model_version=args.model_version,
        ts=args.ts,
        turn_n=args.turn_n,
        source_file=args.source_file,
    )
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
