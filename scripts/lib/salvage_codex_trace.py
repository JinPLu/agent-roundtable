#!/usr/bin/env python3
"""Salvage the last `agent_message` text from a Codex `--json` trace.

Codex 0.128 only flushes `-o last.md` on a clean `turn.completed`. If the
agent stops mid-task (sandbox boundary, budget cap, …) the final
`item.completed/agent_message` event lands in the trace but never reaches
`last.md`. This helper writes that last message to `last.md`.

Usage:
    salvage_codex_trace.py <trace.jsonl> <out_path>

Exits 0 on success (best-effort), 2 on usage error. Writes nothing if no
agent_message is found.
"""
import json
import pathlib
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: salvage_codex_trace.py <trace.jsonl> <out>", file=sys.stderr)
        return 2
    trace_path, out_path = sys.argv[1], sys.argv[2]
    last = None
    for line in pathlib.Path(trace_path).read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue
        if evt.get("type") == "item.completed":
            item = evt.get("item", {}) or {}
            if item.get("type") == "agent_message":
                last = item.get("text", "")
    if last:
        pathlib.Path(out_path).write_text(last, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
