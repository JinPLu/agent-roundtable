#!/usr/bin/env python3
"""scope_watcher.py — kill a Codex turn the instant it writes out of scope.

Background companion to ``codex_turn.sh`` for the ``executor`` role. Tails the
``--json`` event stream (``trace.jsonl``) and, whenever a ``file_change`` /
``item.completed`` event surfaces a file path, compares it against
``GOAL.md``'s In-scope / Out-of-scope sections (same parser as
``scope_check.py`` for consistency).

Policy
------
* Explicit **out-of-scope** match → write
  ``<thread>/SCOPE_VIOLATION_REALTIME.md``, SIGTERM the target pid, wait 30s,
  then SIGKILL. Exit 1.
* Path **not in In-scope** and In-scope is non-empty → log WARN to stderr but
  do NOT kill. Rationale: GOAL.md can be incomplete; killing here would be
  brittle and confuse first-time users. ``scope_check.py`` runs post-turn
  for the strict comparison.
* In-scope match → quiet (no-op).
* GOAL.md missing or both sections empty → fail-open: log WARN, run as a no-op.

The watcher exits 0 when the target pid disappears naturally.

Usage::

    python3 scope_watcher.py <pid> <trace_jsonl_path> <thread_dir> \
        [--idle-poll-s 2] [--grace-s 30]

Backward-compat: the watcher MUST fail-open on any malformed input. Tests
cover the negative paths (no GOAL.md, unparseable GOAL.md, missing trace,
permission denied) to make sure ``codex_turn.sh`` never blows up if this
script regresses.

Stdlib only.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import pathlib
import signal
import sys
import time
from typing import Iterable


_SECTION_IN_SCOPE = "## In-scope paths"
_SECTION_OUT_SCOPE = "## Out-of-scope"


def parse_goal_md(goal_path: pathlib.Path) -> tuple[list[str], list[str]]:
    """Return (in_scope_patterns, out_of_scope_patterns)."""
    if not goal_path.exists():
        return [], []
    try:
        text = goal_path.read_text(encoding="utf-8")
    except OSError:
        return [], []
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


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    """True if path matches any pattern (glob or prefix)."""
    for pat in patterns:
        pat_norm = pat.lstrip("/")
        if fnmatch.fnmatch(path, pat_norm):
            return True
        prefix = pat_norm.rstrip("/")
        if prefix and path.startswith(prefix):
            return True
    return False


def _norm(path: str, thread_dir: pathlib.Path, project_root: pathlib.Path | None) -> str:
    """Normalize a file path emitted by codex to project-root relative."""
    if not path:
        return path
    p = pathlib.Path(path)
    if p.is_absolute():
        try:
            if project_root is not None:
                return str(p.resolve().relative_to(project_root.resolve()))
        except ValueError:
            try:
                return str(p.resolve().relative_to(thread_dir.resolve()))
            except ValueError:
                return str(p)
    return path


def _extract_paths(evt: dict) -> list[str]:
    """Pull file paths out of a Codex JSON event.

    Codex emits several shapes across versions; we accept any ``item`` whose
    ``type`` includes ``file`` and look for ``path`` / ``paths`` / ``file``.
    Unknown shapes contribute nothing.
    """
    paths: list[str] = []
    candidates: list[dict] = []
    item = evt.get("item")
    if isinstance(item, dict):
        candidates.append(item)
    for k in ("msg", "payload", "data"):
        v = evt.get(k)
        if isinstance(v, dict):
            candidates.append(v)
            sub = v.get("item")
            if isinstance(sub, dict):
                candidates.append(sub)
    if not candidates:
        candidates.append(evt)
    for c in candidates:
        t = (c.get("type") or "") if isinstance(c, dict) else ""
        if "file" not in t and "patch" not in t and "edit" not in t:
            continue
        p = c.get("path") or c.get("file")
        if isinstance(p, str) and p:
            paths.append(p)
        ps = c.get("paths") or c.get("files")
        if isinstance(ps, list):
            for q in ps:
                if isinstance(q, str) and q:
                    paths.append(q)
        changes = c.get("changes")
        if isinstance(changes, list):
            for ch in changes:
                if isinstance(ch, dict):
                    q = ch.get("path") or ch.get("file")
                    if isinstance(q, str) and q:
                        paths.append(q)
    return paths


def _write_violation_report(thread_dir: pathlib.Path, violations: list[tuple[str, str]],
                            in_scope: list[str], out_scope: list[str], pid: int) -> pathlib.Path:
    out = thread_dir / "SCOPE_VIOLATION_REALTIME.md"
    lines = [
        "# Realtime scope violation",
        "",
        f"- pid: `{pid}`",
        f"- ts:  `{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}`",
        "",
        "## Violations",
    ]
    for path, reason in violations:
        lines.append(f"- `{path}` — {reason}")
    lines += [
        "",
        "## Rules in effect",
        "### In-scope patterns",
    ]
    if in_scope:
        for pat in in_scope:
            lines.append(f"- `{pat}`")
    else:
        lines.append("- _(none)_")
    lines.append("")
    lines.append("### Out-of-scope patterns")
    if out_scope:
        for pat in out_scope:
            lines.append(f"- `{pat}`")
    else:
        lines.append("- _(none)_")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _send_signal(pid: int, sig: int) -> bool:
    try:
        os.kill(pid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def watch(
    pid: int,
    trace_path: pathlib.Path,
    thread_dir: pathlib.Path,
    *,
    idle_poll_s: float = 2.0,
    grace_s: float = 30.0,
    project_root: pathlib.Path | None = None,
    max_iterations: int | None = None,
) -> int:
    """Tail trace_path until either pid exits or a violation kills it.

    ``max_iterations`` is a test hook — set to bound the loop. In production
    callers leave it None and the loop exits when the target pid dies.
    """
    goal_path = thread_dir / "GOAL.md"
    in_scope, out_scope = parse_goal_md(goal_path)
    if not in_scope and not out_scope:
        print(
            f"WARN [scope_watcher]: GOAL.md missing/unparseable at {goal_path}; "
            f"fail-open (running as no-op).",
            file=sys.stderr,
        )

    project_root = project_root or thread_dir.parent.parent.parent  # …/.roundtable/threads/<slug>/

    offset = 0
    iterations = 0
    while True:
        iterations += 1
        if max_iterations is not None and iterations > max_iterations:
            return 0
        if not _pid_alive(pid):
            return 0
        try:
            if trace_path.exists():
                with trace_path.open("rb") as f:
                    f.seek(offset)
                    chunk = f.read()
                    offset += len(chunk)
                if chunk:
                    for raw in chunk.splitlines():
                        line = raw.strip()
                        if not line or line[:1] != b"{":
                            continue
                        try:
                            evt = json.loads(line.decode("utf-8", errors="replace"))
                        except json.JSONDecodeError:
                            continue
                        paths = _extract_paths(evt)
                        if not paths:
                            continue
                        violations: list[tuple[str, str]] = []
                        for raw_path in paths:
                            norm = _norm(raw_path, thread_dir, project_root)
                            if out_scope and matches_any(norm, out_scope):
                                violations.append((norm, "explicit out-of-scope"))
                            elif in_scope and not matches_any(norm, in_scope):
                                # WARN-only: keep noise low; scope_check.py
                                # is the strict post-turn gate.
                                print(
                                    f"WARN [scope_watcher]: {norm} not in In-scope list; "
                                    f"not killing — see SCOPE_VIOLATION on turn end.",
                                    file=sys.stderr,
                                )
                        if violations:
                            try:
                                report = _write_violation_report(
                                    thread_dir, violations, in_scope, out_scope, pid,
                                )
                                print(
                                    f"FATAL [scope_watcher]: SIGTERM pid={pid} after "
                                    f"out-of-scope writes; report at {report}",
                                    file=sys.stderr,
                                )
                            except OSError as exc:
                                print(
                                    f"WARN [scope_watcher]: report write failed: {exc!r}; "
                                    f"signalling anyway.",
                                    file=sys.stderr,
                                )
                            _send_signal(pid, signal.SIGTERM)
                            deadline = time.time() + grace_s
                            while _pid_alive(pid) and time.time() < deadline:
                                time.sleep(0.5)
                            if _pid_alive(pid):
                                _send_signal(pid, signal.SIGKILL)
                            return 1
        except OSError as exc:
            print(
                f"WARN [scope_watcher]: trace read failed: {exc!r}; fail-open.",
                file=sys.stderr,
            )
        time.sleep(idle_poll_s)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("pid", type=int)
    p.add_argument("trace")
    p.add_argument("thread_dir")
    p.add_argument("--idle-poll-s", type=float, default=2.0)
    p.add_argument("--grace-s", type=float, default=30.0)
    p.add_argument("--project-root", default=None)
    args = p.parse_args(argv)
    project_root = pathlib.Path(args.project_root) if args.project_root else None
    return watch(
        pid=args.pid,
        trace_path=pathlib.Path(args.trace),
        thread_dir=pathlib.Path(args.thread_dir),
        idle_poll_s=args.idle_poll_s,
        grace_s=args.grace_s,
        project_root=project_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
