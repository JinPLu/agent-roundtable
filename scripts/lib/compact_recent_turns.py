#!/usr/bin/env python3
"""Print the last K THREAD.md turns, optionally compacting top-level Read fields."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


TURN_RE = re.compile(r"(?=^## Turn \d+\b)", re.MULTILINE)


def tail_turn_blocks(text: str, k: int) -> list[str]:
    blocks = TURN_RE.split(text)
    turns = [block for block in blocks if re.match(r"^## Turn \d+\b", block.strip())]
    return turns[-k:] if k < len(turns) else turns


def basename_for_item(item: str) -> str | None:
    cleaned = item.strip().strip("`").strip()
    if not cleaned:
        return None
    pathish = cleaned.split()[0].strip("`")
    pathish = re.sub(r":\d+(?:-\d+)?$", "", pathish)
    pathish = pathish.rstrip("/")
    if not pathish:
        return None
    return os.path.basename(pathish) or pathish


def compact_read_line(line: str) -> str | None:
    newline = "\n" if line.endswith("\n") else ""
    content = line[len("**Read**:") :].strip()
    if ";" not in content:
        return None

    items = [part.strip() for part in content.split(";") if part.strip()]
    basenames = [basename_for_item(item) for item in items]
    if not items or any(name is None for name in basenames):
        return None

    first = basenames[:5]
    rendered = ", ".join(first)
    overflow = len(basenames) - len(first)
    if overflow > 0:
        rendered = f"{rendered}, ... +{overflow}"
    return (
        f"**Read**: {len(basenames)} opened items "
        f"(basenames: {rendered}). Full path list remains in THREAD.md.{newline}"
    )


try:
    VERIFICATION_CHAR_LIMIT = int(os.environ.get("ROUNDTABLE_VERIFICATION_LIMIT", "1000"))
except ValueError:
    VERIFICATION_CHAR_LIMIT = 1000


def _truncate_verification(lines: list[str]) -> list[str]:
    """Truncate **Verification** sections exceeding VERIFICATION_CHAR_LIMIT chars."""
    out: list[str] = []
    in_verif = False
    verif_chars = 0
    truncated = False

    for line in lines:
        stripped = line.lstrip()
        if re.match(r"\*\*(Did|Open questions|Hand-off)\*\*\s*:", stripped):
            in_verif = False
            truncated = False
        if re.match(r"\*\*Verification\*\*\s*:", stripped):
            in_verif = True
            verif_chars = 0
            truncated = False

        if in_verif and not truncated:
            verif_chars += len(line)
            if verif_chars > VERIFICATION_CHAR_LIMIT:
                out.append("*(truncated — full output in THREAD.md)*\n")
                truncated = True
                continue

        if in_verif and truncated:
            continue

        out.append(line)

    return out


def compact_turn_block(block: str) -> str:
    lines = block.splitlines(keepends=True)
    in_fence = False
    saw_read = False
    read_compacted = True
    out: list[str] = []

    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue

        if not in_fence and line.startswith("**Read**:"):
            if saw_read:
                read_compacted = False
                out.append(line)
                continue
            compacted = compact_read_line(line)
            if compacted is None:
                out.append(line)
                read_compacted = False
            else:
                out.append(compacted)
            saw_read = True
            continue

        out.append(line)

    if in_fence:
        return block

    out = _truncate_verification(out)
    return "".join(out)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: compact_recent_turns.py <THREAD.md> <tail_k>", file=sys.stderr)
        return 2

    thread_md = Path(argv[1])
    k = int(argv[2])
    turns = tail_turn_blocks(thread_md.read_text(encoding="utf-8"), k)
    if os.environ.get("ROUNDTABLE_COMPACT_READ", "1") == "0":
        print("".join(turns), end="")
    else:
        print("".join(compact_turn_block(turn) for turn in turns), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
