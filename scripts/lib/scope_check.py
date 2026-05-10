#!/usr/bin/env python3
"""scope_check.py - compare git diff against GOAL.md in-scope / out-of-scope rules.

Usage:
    python3 scripts/lib/scope_check.py --thread <slug> [--base <sha>] [--project <path>]

Exit codes:
    0  PASS   — all changed paths are in scope
    1  VIOLATION — at least one changed path is out of scope or explicitly forbidden
    2  NO_GOAL   — GOAL.md missing or its In-scope section is empty

Output (stdout):
    First line is machine-parseable: "PASS ...", "VIOLATION ...", or "NO_GOAL ...".
    Subsequent lines provide human-readable detail.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import pathlib
import re
import subprocess
import sys


_SECTION_IN_SCOPE = "## In-scope paths"
_SECTION_OUT_SCOPE = "## Out-of-scope"


def _die(msg: str, code: int) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _parse_goal_md(goal_path: pathlib.Path) -> tuple[list[str], list[str]]:
    """Return (in_scope_patterns, out_of_scope_patterns) parsed from GOAL.md."""
    if not goal_path.exists():
        return [], []

    text = goal_path.read_text(encoding="utf-8")
    in_scope: list[str] = []
    out_scope: list[str] = []

    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith(_SECTION_IN_SCOPE):
            current = in_scope
            continue
        if line.startswith(_SECTION_OUT_SCOPE):
            current = out_scope
            continue
        if line.startswith("## ") and current is not None:
            current = None
            continue
        if current is not None and line.startswith("- "):
            pattern = line[2:].strip()
            if pattern and not pattern.startswith("("):
                current.append(pattern)

    return in_scope, out_scope


def _changed_paths(project_root: pathlib.Path, base: str) -> list[str]:
    """Return list of paths changed between <base> and HEAD (relative to project_root)."""
    result = subprocess.run(
        ["git", "-C", str(project_root), "diff", "--name-only", f"{base}..HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _die(f"git diff failed: {result.stderr.strip()}", 2)
    return [p for p in result.stdout.splitlines() if p.strip()]


def _resolve_base(project_root: pathlib.Path, base: str | None) -> str:
    if base:
        return base
    # Fall back to the merge-base with the default branch, or just HEAD~1
    for branch in ("main", "master"):
        r = subprocess.run(
            ["git", "-C", str(project_root), "merge-base", "HEAD", branch],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    # Last resort: parent commit
    r = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "HEAD~1"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        return r.stdout.strip()
    _die("Cannot determine base SHA; pass --base explicitly.", 2)


def _matches_any(path: str, patterns: list[str]) -> bool:
    """True if path matches any of the given glob/prefix patterns."""
    for pat in patterns:
        # Support absolute-ish patterns by stripping leading slash
        pat_norm = pat.lstrip("/")
        if fnmatch.fnmatch(path, pat_norm):
            return True
        # prefix match: pattern ends without wildcard
        if path.startswith(pat_norm.rstrip("/")):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--thread", required=True, help="Thread slug (e.g. my-feature-20260511)")
    parser.add_argument("--base", default=None, help="Base git SHA to diff from")
    parser.add_argument("--project", default=None,
                        help="Project root (defaults to $ROUNDTABLE_PROJECT_ROOT or git toplevel)")
    args = parser.parse_args(argv)

    # Resolve project root
    project_root_str = args.project or os.environ.get("ROUNDTABLE_PROJECT_ROOT")
    if not project_root_str:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if r.returncode == 0:
            project_root_str = r.stdout.strip()
        else:
            _die("Cannot determine project root; set ROUNDTABLE_PROJECT_ROOT or run inside a git repo.", 2)
    project_root = pathlib.Path(project_root_str)

    # Locate thread dir
    thread_dir = project_root / ".roundtable" / "threads" / args.thread
    if not thread_dir.exists():
        _die(f"Thread directory not found: {thread_dir}", 2)

    goal_path = thread_dir / "GOAL.md"
    in_scope, out_scope = _parse_goal_md(goal_path)

    if not in_scope:
        print(f"NO_GOAL  GOAL.md missing or empty In-scope section: {goal_path}")
        return 2

    base = _resolve_base(project_root, args.base)
    changed = _changed_paths(project_root, base)

    if not changed:
        print("PASS  0 paths changed (nothing to check)")
        return 0

    violations: list[str] = []
    for path in changed:
        if _matches_any(path, out_scope):
            violations.append(f"  OUT-OF-SCOPE (explicit deny): {path}")
        elif not _matches_any(path, in_scope):
            violations.append(f"  OUT-OF-SCOPE (not in in-scope list): {path}")

    if violations:
        print(f"VIOLATION  {len(violations)} out-of-scope path(s):")
        for v in violations:
            print(v)
        print(f"\nIn-scope rules  : {in_scope}")
        print(f"Out-of-scope rules: {out_scope}")
        print(f"Base SHA        : {base}")
        return 1

    print(f"PASS  {len(changed)} path(s), all in scope (base: {base})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
