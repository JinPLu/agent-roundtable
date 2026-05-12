#!/usr/bin/env python3
"""Extract Claude Code session id from last.json (stream-json final result event)."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys


def extract_session_id(last_json: pathlib.Path) -> str | None:
    if not last_json.exists():
        return None
    try:
        data = json.loads(last_json.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    for key in ("session_id", "uuid", "sessionId"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    nested = data.get("session")
    if isinstance(nested, dict):
        sid = nested.get("id") or nested.get("uuid")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("last_json", type=pathlib.Path)
    args = p.parse_args(argv)
    sid = extract_session_id(args.last_json)
    if sid:
        print(sid)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
