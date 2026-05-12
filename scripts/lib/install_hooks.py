#!/usr/bin/env python3
"""Idempotently merge agent-roundtable's Cursor hooks into a target hooks.json.

The target defaults to ``~/.cursor/hooks.json`` (Cursor native, per
[docs](https://cursor.com/docs/hooks)).  The merge identifies roundtable
entries by the ``_roundtable_id`` field (prefix ``roundtable.``) so we can:

* Install fresh into an empty / nonexistent file.
* Re-install over an existing file without duplicating entries (replace
  any matching ``_roundtable_id``, leave non-roundtable entries alone).
* Uninstall — remove exactly the roundtable entries, leave everything
  else untouched.

The CLI wrapper at ``scripts/install_hooks.sh`` is the user-facing entry
point; this module is the merge engine and the unit-test surface.

Plan reference: §三 "Hook 双分发", §八 Phase A 1–3.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Any

ROUNDTABLE_ID_KEY = "_roundtable_id"
ROUNDTABLE_ID_PREFIX = "roundtable."

# Minimum codex CLI version that ships the `exec resume -o` fix
# (issue #12538, merged 2026-02).  Below this we WARN — do not abort.
MIN_CODEX_VERSION = (2026, 2)


# ── Template handling ────────────────────────────────────────────────────


def load_template(template_path: pathlib.Path, skill_dir: pathlib.Path) -> dict:
    """Read the template, replace ``<SKILL_DIR>`` placeholders, return dict.

    Drops the leading ``_comment`` documentation block before returning so
    the merged target stays compact.
    """
    raw = template_path.read_text(encoding="utf-8")
    expanded = raw.replace("<SKILL_DIR>", str(skill_dir.resolve()))
    parsed = json.loads(expanded)
    parsed.pop("_comment", None)
    return parsed


def is_roundtable_entry(entry: Any) -> bool:
    """True if ``entry`` is one of our managed entries (top-level or
    nested under a Claude-Code-style ``hooks: [{type, command}]`` block)."""
    if not isinstance(entry, dict):
        return False
    rid = entry.get(ROUNDTABLE_ID_KEY)
    return isinstance(rid, str) and rid.startswith(ROUNDTABLE_ID_PREFIX)


def roundtable_entries_from(template: dict) -> dict[str, list[dict]]:
    """Pull out the per-event roundtable entries from a parsed template."""
    out: dict[str, list[dict]] = {}
    for event, entries in (template.get("hooks") or {}).items():
        if isinstance(entries, list):
            out[event] = [e for e in entries if is_roundtable_entry(e)]
    return out


# ── Merge engine ─────────────────────────────────────────────────────────


def _own_hook_paths(template: dict) -> list[tuple[str, str]]:
    """Return [(rid, command), ...] for every roundtable entry in template."""
    out: list[tuple[str, str]] = []
    for entries in (template.get("hooks") or {}).values():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not is_roundtable_entry(e):
                continue
            cmd = e.get("command")
            if isinstance(cmd, str):
                out.append((e[ROUNDTABLE_ID_KEY], cmd))
    return out


def smoketest_hook_paths(template: dict) -> list[str]:
    """Return errors for any *roundtable-owned* hook script that is missing
    or non-executable.  We intentionally do not validate user-provided
    entries — that would block install whenever a user's pre-existing
    hook command is non-trivial."""
    errors: list[str] = []
    for rid, cmd in _own_hook_paths(template):
        # Plain path only — skip anything that looks like a shell line.
        if any(c in cmd for c in (" ", "\t", "|", ">", "<", ";", "&")):
            continue
        p = pathlib.Path(cmd)
        if not p.exists():
            errors.append(f"{rid}: hook script missing: {cmd}")
            continue
        if not os.access(p, os.X_OK):
            errors.append(f"{rid}: hook script not executable: {cmd}")
    return errors


def merge_install(existing: dict, template: dict) -> dict:
    """Return a new dict = ``existing`` with ``template``'s roundtable
    entries spliced in (replacing any existing entries with the same
    ``_roundtable_id``).  ``existing`` itself is not mutated."""
    result = json.loads(json.dumps(existing)) if existing else {"version": 1}
    result.setdefault("version", 1)
    result.setdefault("hooks", {})

    new_entries = roundtable_entries_from(template)
    for event, entries in new_entries.items():
        target_list = list(result["hooks"].get(event) or [])
        # Strip any roundtable entries already in the target — we'll
        # re-add them from the template so updates take effect.
        target_list = [e for e in target_list if not is_roundtable_entry(e)]
        target_list.extend(entries)
        result["hooks"][event] = target_list
    return result


def merge_uninstall(existing: dict) -> dict:
    """Return a new dict = ``existing`` with every roundtable entry
    removed.  Empty event lists are dropped to keep the file tidy."""
    if not existing:
        return {}
    result = json.loads(json.dumps(existing))
    if not isinstance(result.get("hooks"), dict):
        return result
    for event in list(result["hooks"].keys()):
        entries = result["hooks"][event]
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not is_roundtable_entry(e)]
        if kept:
            result["hooks"][event] = kept
        else:
            del result["hooks"][event]
    return result


# ── Summary / diff ───────────────────────────────────────────────────────


def _entry_ids(d: dict) -> set[str]:
    ids: set[str] = set()
    for entries in (d.get("hooks") or {}).values():
        if isinstance(entries, list):
            for e in entries:
                if is_roundtable_entry(e):
                    ids.add(e[ROUNDTABLE_ID_KEY])
    return ids


def summarise(before: dict, after: dict) -> dict[str, list[str]]:
    """Return added / removed / unchanged roundtable-id lists."""
    before_ids = _entry_ids(before)
    after_ids = _entry_ids(after)
    return {
        "added": sorted(after_ids - before_ids),
        "removed": sorted(before_ids - after_ids),
        "unchanged": sorted(before_ids & after_ids),
    }


# ── File I/O ─────────────────────────────────────────────────────────────


def read_target(target: pathlib.Path) -> dict:
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: {target} is not valid JSON: {exc}")


def write_target(target: pathlib.Path, data: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # Atomic-ish: write to tmp, then rename.  Avoids partial writes
    # tripping Cursor's auto-reloader.
    tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}.{int(time.time())}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)


def backup(target: pathlib.Path) -> pathlib.Path | None:
    """Create ``<target>.roundtable-bak`` before any write.  Returns the
    backup path, or None if there was nothing to back up."""
    if not target.exists():
        return None
    bak = target.with_suffix(target.suffix + ".roundtable-bak")
    shutil.copy2(target, bak)
    return bak


# ── Codex version probe ──────────────────────────────────────────────────


def codex_version_warn() -> str | None:
    """If codex is on PATH and reports a version < MIN_CODEX_VERSION,
    return a WARN string; otherwise None.  Never aborts — even a
    missing codex is fine (the user might not use codex)."""
    try:
        out = subprocess.run(
            ["codex", "--version"], capture_output=True, text=True, timeout=5, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr or "").strip()
    if not text:
        return None
    # Codex CLI version strings: try to pull YYYY.MM tokens from output.
    for token in text.replace(",", " ").split():
        bits = token.split(".")
        if len(bits) >= 2 and bits[0].isdigit() and bits[1].isdigit() and len(bits[0]) == 4:
            year, month = int(bits[0]), int(bits[1])
            if (year, month) < MIN_CODEX_VERSION:
                return (
                    f"codex CLI version {text!r} < 2026.02 — `exec resume -o` may "
                    "be buggy (issue #12538)."
                )
            return None
    return None


# ── Main entry point ─────────────────────────────────────────────────────


def run(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="install_hooks.py",
        description="Idempotently install / uninstall agent-roundtable hooks "
                    "into a Cursor hooks.json file.",
    )
    p.add_argument(
        "--template", type=pathlib.Path,
        default=None,
        help="Path to hooks.json.tmpl (default: <skill>/templates/hooks.json.tmpl)",
    )
    p.add_argument(
        "--skill-dir", type=pathlib.Path,
        default=None,
        help="Absolute path to replace <SKILL_DIR> with (default: parent of script).",
    )
    p.add_argument(
        "--target", type=pathlib.Path,
        default=pathlib.Path("~/.cursor/hooks.json").expanduser(),
        help="Target hooks.json (default: ~/.cursor/hooks.json).",
    )
    p.add_argument(
        "--uninstall", action="store_true",
        help="Remove roundtable entries from target instead of installing.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print what would change without writing.",
    )
    p.add_argument(
        "--no-smoketest", action="store_true",
        help="Skip the [[ -x <path> ]] check on hook scripts (for tests).",
    )
    args = p.parse_args(argv)

    # Resolve defaults that depend on the script location.
    script_dir = pathlib.Path(__file__).resolve().parent  # .../scripts/lib
    skill_dir = (args.skill_dir or script_dir.parent.parent).resolve()
    template_path = (args.template or (skill_dir / "templates" / "hooks.json.tmpl")).resolve()
    target = args.target.expanduser().resolve()

    if not template_path.exists() and not args.uninstall:
        print(f"ERROR: template not found: {template_path}", file=sys.stderr)
        return 2

    template = load_template(template_path, skill_dir) if template_path.exists() else {"hooks": {}}

    # Smoketest before we touch the target so a broken install aborts cleanly.
    if not args.uninstall and not args.no_smoketest:
        errs = smoketest_hook_paths(template)
        if errs:
            print("ERROR: hook script preflight failed — aborting:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 3

    existing = read_target(target)
    new = merge_uninstall(existing) if args.uninstall else merge_install(existing, template)
    summary = summarise(existing, new)

    # Codex version probe — WARN only, never aborts.
    warn = codex_version_warn()
    if warn:
        print(f"WARN [install_hooks]: {warn}", file=sys.stderr)

    print(f"target: {target}")
    print(f"action: {'uninstall' if args.uninstall else 'install'}")
    print(f"added:     {summary['added'] or '[]'}")
    print(f"removed:   {summary['removed'] or '[]'}")
    print(f"unchanged: {summary['unchanged'] or '[]'}")

    if args.dry_run:
        print("(dry-run — no files written)")
        return 0

    if new == existing:
        print("(no changes needed; target already matches)")
        return 0

    bak = backup(target)
    if bak:
        print(f"backup: {bak}")
    write_target(target, new)
    print(f"wrote:  {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
