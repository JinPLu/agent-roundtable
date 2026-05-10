#!/usr/bin/env python3
"""import_plan.py — copy an external plan into thread artifacts/PLAN.md and sync GOAL.md.

Usage:
    python3 scripts/lib/import_plan.py <plan-file> [--slug SLUG] [--reviewed yes|no|N/A]
    python3 scripts/lib/import_plan.py <slug> <plan-file>        # legacy form

If the thread directory does not exist yet it is auto-created via
new_thread.sh; slug + one-line goal are derived from the plan file when not
given. Resolves thread dir from ROUNDTABLE_PROJECT_ROOT (or --project) at
<project>/.roundtable/threads/<slug>/.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


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

To re-import (after editing the source file):

```bash
bash $SKILL/scripts/import_plan.sh /absolute/path/to/plan.md --reviewed no
```

If `artifacts/PLAN.md` was produced only by **`roundtable-plan`** Phase B, set **Original source path** to `roundtable-plan Phase B` and leave **Last imported at** as `N/A`.
"""


def update_goal_md(goal_path: pathlib.Path, block: str) -> None:
    text = goal_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

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


# ── slug + goal derivation ────────────────────────────────────────────────

def _derive_slug(plan_file: pathlib.Path) -> str:
    stem = plan_file.name
    for suffix in (".plan.md", ".md"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", stem).strip("-").lower()
    stem = stem or "thread"
    date = datetime.now().strftime("%Y%m%d")
    slug = f"{stem}-{date}"
    slug = slug[:64].rstrip(".-_") or "thread"
    if not _SLUG_RE.match(slug):
        slug = f"thread-{date}"
    return slug


def _derive_goal(plan_file: pathlib.Path) -> str:
    """Extract first-line summary from plan: YAML `overview:` value, then first `# H1`, else filename."""
    try:
        text = plan_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return plan_file.stem

    lines = text.splitlines()
    in_frontmatter = False
    for i, line in enumerate(lines):
        s = line.rstrip()
        if i == 0 and s == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if s == "---":
                in_frontmatter = False
                continue
            m = re.match(r"overview\s*:\s*(.+)$", s)
            if m:
                val = m.group(1).strip().strip('"').strip("'")
                if val:
                    return val[:200]

    for line in lines:
        s = line.strip()
        if s.startswith("# ") and not s.startswith("# Goal"):
            return s.lstrip("# ").strip()[:200]

    return f"Implement plan: {plan_file.name}"


def _ensure_thread(slug: str, plan_file: pathlib.Path, project_root: pathlib.Path) -> pathlib.Path:
    thread_dir = project_root / ".roundtable" / "threads" / slug
    if thread_dir.is_dir():
        return thread_dir

    skill_dir = pathlib.Path(__file__).resolve().parents[2]
    new_thread = skill_dir / "scripts" / "new_thread.sh"
    if not new_thread.exists():
        _err(f"missing {new_thread}")

    goal = _derive_goal(plan_file)
    env = {**os.environ, "ROUNDTABLE_PROJECT_ROOT": str(project_root)}
    proc = subprocess.run(
        ["bash", str(new_thread), slug, goal],
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        _err(f"new_thread.sh failed (slug={slug}):\n{proc.stderr.strip() or proc.stdout.strip()}")
    print(proc.stdout.rstrip())
    if not thread_dir.is_dir():
        _err(f"new_thread.sh ran but thread dir still missing: {thread_dir}")
    return thread_dir


# ── CLI ───────────────────────────────────────────────────────────────────

def _parse_positionals(positionals: list[str]) -> tuple[str | None, pathlib.Path]:
    """Return (explicit_slug, plan_file). Supports legacy `<slug> <plan-file>`."""
    if len(positionals) == 1:
        return None, pathlib.Path(positionals[0])
    if len(positionals) == 2:
        a, b = positionals
        if pathlib.Path(a).is_file():
            return None, pathlib.Path(a)
        return a, pathlib.Path(b)
    _err("usage: import_plan.py <plan-file> [--slug SLUG] [--reviewed yes|no|N/A]")
    return None, pathlib.Path()  # unreachable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("positionals", nargs="+", help="<plan-file> or legacy <slug> <plan-file>")
    parser.add_argument("--slug", default=None, help="Override thread slug (default: derived from plan filename)")
    parser.add_argument(
        "--reviewed",
        choices=("yes", "no", "N/A"),
        default="no",
        help="Value for GOAL.md Cross-vendor review completed (default: no)",
    )
    parser.add_argument("--project", default=None, help="Project root (else ROUNDTABLE_PROJECT_ROOT or git toplevel)")
    args = parser.parse_args(argv)

    explicit_slug, plan_file = _parse_positionals(args.positionals)
    if args.slug:
        explicit_slug = args.slug

    src = plan_file.expanduser()
    if not src.is_file():
        _err(f"not a file: {src}")

    proj = args.project or os.environ.get("ROUNDTABLE_PROJECT_ROOT")
    if not proj:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if r.returncode != 0:
            _err("set ROUNDTABLE_PROJECT_ROOT or run inside a git repo")
        proj = r.stdout.strip()
    proj_root = pathlib.Path(proj).resolve()

    slug = explicit_slug or _derive_slug(src)
    if not _SLUG_RE.match(slug):
        _err(f"invalid slug {slug!r}: must match {_SLUG_RE.pattern}")

    thread_dir = _ensure_thread(slug, src, proj_root)

    goal = thread_dir / "GOAL.md"
    if not goal.is_file():
        _err(f"missing {goal}")

    artifacts = thread_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    dest = artifacts / "PLAN.md"

    abs_src = src.resolve()
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = f"<!-- roundtable-import: source={abs_src} imported_at={iso} -->\n\n"
    dest.write_text(header + src.read_text(encoding="utf-8"), encoding="utf-8")

    block = _plan_block(str(abs_src), iso, args.reviewed)
    update_goal_md(goal, block)

    print(f"thread_dir={thread_dir}")
    print(f"slug={slug}")
    print(f"OK  wrote {dest}")
    print(f"OK  updated {goal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
