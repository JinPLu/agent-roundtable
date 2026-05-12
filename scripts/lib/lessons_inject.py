#!/usr/bin/env python3
"""Select recent project lessons relevant to the current turn."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _keywords(query: str) -> list[str]:
    toks = [tok.lower() for tok in re.findall(r"[A-Za-z0-9_./-]+", query)]
    return [tok for tok in toks if len(tok) >= 3]


def _score_row(row: dict[str, Any], keys: list[str]) -> int:
    hay = f"{row.get('tag', '')} {row.get('lesson', '')} {row.get('applies_when', '')}".lower()
    return sum(1 for key in keys if key in hay)


def select_lessons(
    project_root: pathlib.Path,
    query: str,
    *,
    now: str | None = None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    jsonl_path = project_root / ".roundtable" / "memory" / "lessons.jsonl"
    if not jsonl_path.exists():
        return []
    current = _parse_ts(now) if now else datetime.now(timezone.utc)
    if current is None:
        current = datetime.now(timezone.utc)
    cutoff = current - timedelta(days=7)
    keys = _keywords(query)
    rows: list[dict[str, Any]] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = _parse_ts(str(row.get("ts", "")))
        if ts is None or ts < cutoff:
            continue
        score = _score_row(row, keys)
        if keys and score == 0:
            continue
        row["_score"] = score
        rows.append(row)
    rows.sort(key=lambda row: (int(row.get("_score", 0)), str(row.get("ts", ""))), reverse=True)
    selected = rows[: max(top_k, 0)]
    for row in selected:
        row.pop("_score", None)
    return selected


def render_lessons(selected: list[dict[str, Any]]) -> str:
    if not selected:
        return ""
    lines = ["## Project lessons", ""]
    for row in selected:
        lines.append(f"- [{row.get('tag', 'lesson')}] {row.get('lesson', '')}")
        lines.append(f"  - applies when: {row.get('applies_when', '')}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--query-file", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)
    query = pathlib.Path(args.query_file).read_text(encoding="utf-8")
    text = render_lessons(
        select_lessons(pathlib.Path(args.project), query, now=args.now, top_k=args.top_k)
    )
    if text:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
