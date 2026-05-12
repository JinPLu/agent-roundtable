#!/usr/bin/env python3
"""Merge roundtable-managed Codex profiles into ~/.codex/config.toml."""
from __future__ import annotations

import argparse
import pathlib
import re

_MARK_BEGIN = "# roundtable-managed begin"
_MARK_END = "# roundtable-managed end"


def _strip_managed_block(text: str) -> str:
    out: list[str] = []
    skip = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped == _MARK_BEGIN:
            skip = True
            continue
        if stripped == _MARK_END:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "".join(out).rstrip() + ("\n" if out else "")


def merge_profiles(config_path: pathlib.Path, snippet_path: pathlib.Path) -> str:
    snippet = snippet_path.read_text(encoding="utf-8")
    wanted = set(re.findall(r"^\[profiles\.([^\]]+)\]", snippet, re.MULTILINE))
    raw_existing = ""
    if config_path.exists():
        raw_existing = config_path.read_text(encoding="utf-8")
    stripped = _strip_managed_block(raw_existing)
    existing_profiles = set(re.findall(r"^\[profiles\.([^\]]+)\]", stripped, re.MULTILINE))
    conflicts = sorted(wanted & existing_profiles)
    if conflicts:
        raise SystemExit(
            f"Refusing merge: ~/.codex/config.toml already defines [profiles.{conflicts[0]}] "
            f"(and {len(conflicts) - 1} other conflicts outside roundtable-managed block)."
        )
    managed = f"{_MARK_BEGIN}\n{snippet.rstrip()}\n{_MARK_END}\n"
    if stripped.strip():
        return stripped.rstrip() + "\n\n" + managed
    return managed


def cmd_apply(snippet: pathlib.Path, config: pathlib.Path, *, dry_run: bool) -> int:
    merged = merge_profiles(config, snippet)
    if dry_run:
        print(merged)
        return 0
    config.parent.mkdir(parents=True, exist_ok=True)
    bak = config.with_suffix(config.suffix + ".roundtable-bak")
    if config.exists():
        bak.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    config.write_text(merged, encoding="utf-8")
    print(f"wrote {config} (backup: {bak})")
    return 0


def cmd_remove(config: pathlib.Path) -> int:
    if not config.exists():
        return 0
    raw = config.read_text(encoding="utf-8")
    cleaned = _strip_managed_block(raw)
    config.write_text(cleaned, encoding="utf-8")
    print(f"removed roundtable-managed block from {config}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_apply = sub.add_parser("apply", help="Merge templates/codex_profiles.toml.tmpl into ~/.codex/config.toml")
    p_apply.add_argument("--snippet", type=pathlib.Path, required=True)
    p_apply.add_argument("--config", type=pathlib.Path, default=pathlib.Path.home() / ".codex" / "config.toml")
    p_apply.add_argument("--dry-run", action="store_true")

    p_remove = sub.add_parser("remove", help="Strip roundtable-managed block only")
    p_remove.add_argument("--config", type=pathlib.Path, default=pathlib.Path.home() / ".codex" / "config.toml")

    args = ap.parse_args(argv)
    if args.cmd == "apply":
        return cmd_apply(args.snippet, args.config, dry_run=args.dry_run)
    return cmd_remove(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
