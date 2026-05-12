#!/usr/bin/env python3
"""Extract project lessons from a converged thread into project memory."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lesson_for_block(block: str) -> tuple[str, str, str] | None:
    lowered = block.lower()
    if "scope_check" in lowered or "violation" in lowered or "out-of-scope" in lowered:
        return (
            "scope",
            "Keep fixes inside the in-scope paths and re-check scope before review.",
            "scope_check / violation",
        )
    if "stalled" in lowered or "regressed" in lowered or "drift" in lowered:
        return (
            "drift",
            "When progress stalls, diagnose the cause before another executor rerun.",
            "stalled / regressed / drift",
        )
    if "blocking_issues" in lowered or "blocker" in lowered:
        return (
            "blocker",
            "Treat repeated blockers as a signal to narrow the next action and reduce ambiguity.",
            "blocking_issues / blocker",
        )
    return None


def _extract_from_thread(thread_dir: pathlib.Path) -> list[dict[str, Any]]:
    thread_md = thread_dir / "THREAD.md"
    if not thread_md.exists():
        return []
    blocks = re.split(r"(?=^## Turn \d+)", thread_md.read_text(encoding="utf-8"), flags=re.MULTILINE)
    lessons: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for block in (b for b in blocks if b.strip().startswith("## Turn")):
        lesson = _lesson_for_block(block)
        if not lesson:
            continue
        tag, text, applies_when = lesson
        key = (tag, text)
        if key in seen:
            continue
        seen.add(key)
        lessons.append(
            {
                "thread": thread_dir.name,
                "ts": _iso_now(),
                "tag": tag,
                "lesson": text,
                "evidence_path": str(thread_md),
                "applies_when": applies_when,
            }
        )
    return lessons


def extract_lessons(project_root: pathlib.Path, thread_dir: pathlib.Path) -> list[dict[str, Any]]:
    lessons = _extract_from_thread(thread_dir)
    if not lessons:
        return []
    memory_dir = project_root / ".roundtable" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    md_path = memory_dir / "lessons.md"
    jsonl_path = memory_dir / "lessons.jsonl"
    md_lines = [f"## Thread {thread_dir.name}", ""]
    for lesson in lessons:
        md_lines.append(f"- [{lesson['tag']}] {lesson['lesson']} (evidence: `{lesson['evidence_path']}`)")
    md_lines.append("")
    with md_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(md_lines))
    with jsonl_path.open("a", encoding="utf-8") as fh:
        for lesson in lessons:
            fh.write(json.dumps(lesson, ensure_ascii=False) + "\n")
    return lessons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=None)
    parser.add_argument("--thread-dir", required=True)
    args = parser.parse_args(argv)
    project_root = pathlib.Path(args.project or pathlib.Path.cwd()).resolve()
    thread_dir = pathlib.Path(args.thread_dir).resolve()
    lessons = extract_lessons(project_root, thread_dir)
    print(json.dumps({"count": len(lessons), "lessons": lessons}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
