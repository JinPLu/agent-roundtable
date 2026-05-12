#!/usr/bin/env python3
"""Replay a previous turn's prompt and metadata."""

from __future__ import annotations

import argparse
import json
import pathlib


def _history_dirs(thread_dir: pathlib.Path) -> list[pathlib.Path]:
    hist = thread_dir / "history"
    if not hist.exists():
        return []
    dirs = [p for p in hist.glob("*/*") if p.is_dir()]
    dirs.sort(key=lambda p: (p.stat().st_mtime, str(p)))
    return dirs


def _turn_dir(thread_dir: pathlib.Path, turn_n: int) -> pathlib.Path | None:
    for candidate in _history_dirs(thread_dir):
        trace = candidate / "trace.json"
        if not trace.exists():
            continue
        try:
            data = json.loads(trace.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("turn_n") == turn_n:
            return candidate
    dirs = _history_dirs(thread_dir)
    if 1 <= turn_n <= len(dirs):
        return dirs[turn_n - 1]
    return None


def replay(thread_dir: pathlib.Path, turn_n: int) -> str:
    hist = _turn_dir(thread_dir, turn_n)
    if hist is None:
        return f"Turn {turn_n} not found under {thread_dir}"
    prompt = (hist / "prompt.md").read_text(encoding="utf-8") if (hist / "prompt.md").exists() else ""
    meta = json.loads((hist / "meta.json").read_text(encoding="utf-8")) if (hist / "meta.json").exists() else {}
    trace = json.loads((hist / "trace.json").read_text(encoding="utf-8")) if (hist / "trace.json").exists() else {}
    return "\n".join(
        [
            f"## Replay for {thread_dir.name} turn {turn_n}",
            "",
            "Replay is approximate; model outputs are not guaranteed to match.",
            "",
            "## Prompt",
            "```md",
            prompt,
            "```",
            "",
            "## Meta",
            "```json",
            json.dumps({"meta": meta, "trace": trace}, indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("thread")
    parser.add_argument("turn_n", type=int)
    parser.add_argument("--project", default=None)
    args = parser.parse_args(argv)
    project_root = pathlib.Path(args.project or pathlib.Path.cwd()).resolve()
    print(replay(project_root / ".roundtable" / "threads" / args.thread, args.turn_n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
