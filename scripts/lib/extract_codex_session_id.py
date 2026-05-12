#!/usr/bin/env python3
"""Extract Codex CLI session/thread id from a --json trace.jsonl (best-effort)."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys


def extract_session_id(trace_path: pathlib.Path) -> str | None:
    if not trace_path.exists():
        return None
    try:
        text = trace_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = evt.get("type") or evt.get("event_type")
        candidates: list[object] = []
        if isinstance(etype, str):
            lowered = etype.lower().replace("_", ".")
            if lowered in ("thread.started", "session.started", "thread.created"):
                candidates.extend(
                    [
                        evt.get("session_id"),
                        evt.get("thread_id"),
                        evt.get("id"),
                        (evt.get("thread") or {}).get("id")
                        if isinstance(evt.get("thread"), dict)
                        else None,
                        (evt.get("msg") or {}).get("session_id")
                        if isinstance(evt.get("msg"), dict)
                        else None,
                    ]
                )
        # Some builds nest everything under msg
        msg = evt.get("msg")
        if isinstance(msg, dict):
            candidates.extend(
                [
                    msg.get("session_id"),
                    msg.get("thread_id"),
                    (msg.get("thread") or {}).get("id")
                    if isinstance(msg.get("thread"), dict)
                    else None,
                ]
            )
        for c in candidates:
            if isinstance(c, str) and c.strip():
                return c.strip()
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("trace_jsonl", type=pathlib.Path)
    args = p.parse_args(argv)
    sid = extract_session_id(args.trace_jsonl)
    if sid:
        print(sid)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
