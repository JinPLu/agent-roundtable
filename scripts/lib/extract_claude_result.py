#!/usr/bin/env python3
"""Extract the final assistant text from a `claude -p --output-format json` blob.

Usage:
    extract_claude_result.py <last.json>

Prints the extracted text to stdout (no trailing newline). Used as a fallback
for environments that do not have `jq`.
"""
import json
import pathlib
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: extract_claude_result.py <last.json>", file=sys.stderr)
        return 2
    data = json.loads(pathlib.Path(sys.argv[1]).read_text())
    out = data.get("result")
    if not out:
        msgs = data.get("messages") or []
        if msgs:
            content = msgs[-1].get("content")
            if isinstance(content, list):
                out = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            else:
                out = content or ""
    print(out or "", end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
