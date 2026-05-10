#!/usr/bin/env python3
"""import_plan.py — copy an external plan into thread artifacts/PLAN.md and sync GOAL.md.

Usage:
    python3 scripts/lib/import_plan.py <slug> <plan-file> [--reviewed yes|no|N/A]

Resolves thread dir from ROUNDTABLE_PROJECT_ROOT (or --project) at
<project>/.roundtable/threads/<slug>/.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
from datetime import datetime, timezone


def _err(msg: str, code: int = 2) -> None:
    print(f"ERROR [import_plan]: {msg}", file=sys.stderr)
    sys.exit(code)


def _plan_block(src_display: str, iso: str, reviewed: str) -> str:
    return f"""## Plan source

Bind an executable plan to this thread so the **executor** reads **`artifacts/PLAN.md`** end-to-end before coding (see `roles/executor.system.md`).

- **Authoritative copy in thread**: [`artifacts/PLAN.md`](artifacts/PLAN.md) — overwritten each time you run `import_plan.sh`; re-import after you edit the source file (e.g. Cursor `.plan.md`).
- **Original source path**: `{src_display}`
- **Last imported at**: `{iso}`
- **Cross-vendor review completed**: `{reviewed}` — set to `yes` after `roundtable-review` on the plan (or after merging review edits into `artifacts/PLAN.md`).
- **Executor MUST read plan in full before coding**: `yes` — implement steps **in order**; cite plan headings / step numbers in the executor **Did:** section.

To copy a Cursor plan into the thread (updates this section and refreshes `artifacts/PLAN.md`):

```bash
bash $SKILL/scripts/import_plan.sh <slug> /absolute/path/to/plan.md --reviewed no
```

If `artifacts/PLAN.md` was produced only by **`roundtable-plan`** Phase B, set **Original source path** to `roundtable-plan Phase B` and leave **Last imported at** as `N/A`.
"""


def update_goal_md(goal_path: pathlib.Path, block: str) -> None:
    text = goal_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Find ## Plan source
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## Plan source") or line.startswith("## Plan source\r"):
            start = i
            break

    if start is None:
        insert_at = None
        for i, line in enumerate(lines):
            if line.startswith("## Definition of done"):
                insert_at = i
                break
        if insert_at is None:
            _err(f"no '## Plan source' and no '## Definition of done' in {goal_path}")
        new_lines = lines[:insert_at] + ["\n", block, "\n"] + lines[insert_at:]
        goal_path.write_text("".join(new_lines), encoding="utf-8")
        return

    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.startswith("## "):
            break
        end += 1

    new_lines = lines[:start] + [block, "\n"] + lines[end:]
    goal_path.write_text("".join(new_lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", help="Thread slug")
    parser.add_argument("plan_file", type=pathlib.Path, help="Source plan file to copy")
    parser.add_argument(
        "--reviewed",
        choices=("yes", "no", "N/A"),
        default="no",
        help="Value for GOAL.md Cross-vendor review completed (default: no)",
    )
    parser.add_argument("--project", default=None, help="Project root (else ROUNDTABLE_PROJECT_ROOT or git toplevel)")
    args = parser.parse_args(argv)

    proj = args.project or os.environ.get("ROUNDTABLE_PROJECT_ROOT")
    if not proj:
        import subprocess

        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if r.returncode != 0:
            _err("set ROUNDTABLE_PROJECT_ROOT or run inside a git repo")
        proj = r.stdout.strip()
    proj_root = pathlib.Path(proj)
    thread_dir = proj_root / ".roundtable" / "threads" / args.slug
    if not thread_dir.is_dir():
        _err(f"thread not found: {thread_dir}")

    src = args.plan_file.expanduser()
    if not src.is_file():
        _err(f"not a file: {src}")

    goal = thread_dir / "GOAL.md"
    if not goal.is_file():
        _err(f"missing {goal}")

    artifacts = thread_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    dest = artifacts / "PLAN.md"

    abs_src = src.resolve()
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = (
        f"<!-- roundtable-import: source={abs_src} imported_at={iso} -->\n\n"
    )
    dest.write_text(header + src.read_text(encoding="utf-8"), encoding="utf-8")

    block = _plan_block(str(abs_src), iso, args.reviewed)
    update_goal_md(goal, block)

    print(f"OK  wrote {dest}")
    print(f"OK  updated {goal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
