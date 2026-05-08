#!/usr/bin/env python3
"""Emit the latest prior reviewer verdict as a compact markdown block."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def latest_verdict(thread_dir: Path, current_history_dir: Path) -> Path | None:
    candidates: list[Path] = []
    history_root = (thread_dir / "history").resolve(strict=False)
    current = current_history_dir.resolve(strict=False)
    skip_current = current_history_dir != Path("") and is_inside(current, history_root)
    for path in thread_dir.glob("history/*/*/verdict.json"):
        resolved_parent = path.parent.resolve(strict=False)
        if skip_current and (resolved_parent == current or is_inside(resolved_parent, current)):
            continue
        candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p.parent.name, p.stat().st_mtime, str(p)))


def pruned_verdict(data: object) -> object:
    if not isinstance(data, dict):
        return data

    out: dict[str, object] = {}
    if "scope" in data:
        out["scope"] = data["scope"]
    if "blocking_issues" in data:
        out["blocking_issues"] = data["blocking_issues"]

    acceptance = data.get("acceptance")
    if isinstance(acceptance, list):
        kept = [
            item
            for item in acceptance
            if not (
                isinstance(item, dict)
                and str(item.get("verdict", "")).upper() == "COVERED"
            )
        ]
        if kept:
            out["acceptance"] = kept
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: latest_verdict_block.py <thread_dir> <current_history_dir>",
            file=sys.stderr,
        )
        return 2

    thread_dir = Path(argv[1])
    current_history_dir = Path(argv[2]) if argv[2] else Path("")
    verdict_path = latest_verdict(thread_dir, current_history_dir)
    if verdict_path is None:
        return 0

    data = json.loads(verdict_path.read_text())
    if os.environ.get("ROUNDTABLE_FULL_VERDICT") != "1":
        data = pruned_verdict(data)

    rel = verdict_path.relative_to(thread_dir)
    print("## Latest reviewer verdict")
    print(f"Source: `{rel}`")
    print("```json")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print("```")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
