#!/usr/bin/env python3
"""compact_thread.py — compact old THREAD.md turns into THREAD_SUMMARY.md.

Usage: python3 compact_thread.py <thread_md> <keep_k>

Reads <thread_md>, keeps the last <keep_k> turn blocks verbatim (prints them
to stdout as the new THREAD.md tail), and compacts older turns into a summary
printed to stderr prefixed with "SUMMARY:" so the caller can split the streams.

Compaction rules per turn block:
  - Drop the **Read**: field body (verbose file paths rarely needed in history).
  - Keep **Did**, **Verification** (first 300 chars), **Hand-off** verbatim.
  - Keep the turn header (## Turn N — actor/role — timestamp).
"""

import re
import sys
from pathlib import Path

# Shorter than ROUNDTABLE_VERIFICATION_LIMIT (1000) used for recent turns,
# because historical summary prioritises brevity over completeness.
_SUMMARY_VERIFICATION_LIMIT = 350


def split_turns(text: str) -> tuple[list[str], list[int]]:
    """Split THREAD.md into individual turn blocks and their byte offsets."""
    pattern = re.compile(r'^(## Turn \d+)', re.MULTILINE)
    positions = [m.start() for m in pattern.finditer(text)]
    if not positions:
        return [], []
    blocks = []
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        blocks.append(text[pos:end].rstrip())
    return blocks, positions


def compact_turn(block: str) -> str:
    """Return a compacted version of a single turn block."""
    lines = block.splitlines()
    output: list[str] = []
    in_read = False
    read_seen = False

    for line in lines:
        stripped = line.strip()

        # Turn header always kept.
        if stripped.startswith("## Turn "):
            output.append(line)
            in_read = False
            continue

        # Detect **Read**: field start.
        if re.match(r'\*\*Read\*\*\s*:', stripped):
            if not read_seen:
                output.append("**Read**: *(compacted)*")
                read_seen = True
            in_read = True
            continue

        # Detect next field start — exit Read mode.
        if re.match(r'\*\*(Did|Verification|Open questions|Hand-off)\*\*\s*:', stripped):
            in_read = False

        if in_read:
            continue  # drop Read body lines

        output.append(line)

    text = "\n".join(output).rstrip()

    # Truncate long Verification blocks (shorter limit for historical summary).
    m = re.search(
        r'(\*\*Verification\*\*\s*:)(.*?)(\*\*(?:Open questions|Hand-off)\*\*|\Z)',
        text, re.DOTALL,
    )
    if m and len(m.group(2)) > _SUMMARY_VERIFICATION_LIMIT:
        truncated = m.group(2)[:_SUMMARY_VERIFICATION_LIMIT].rstrip() + " *(truncated)*"
        tail = m.group(3) if m.group(3) else ""
        sep = "\n" if tail else ""
        text = text[:m.start(2)] + truncated + sep + tail + text[m.end(3):]

    return text


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: compact_thread.py <thread_md> <keep_k>", file=sys.stderr)
        sys.exit(1)

    thread_md = Path(sys.argv[1])
    keep_k = int(sys.argv[2])

    if not thread_md.exists():
        print(f"ERROR: {thread_md} not found", file=sys.stderr)
        sys.exit(1)

    text = thread_md.read_text(encoding="utf-8")
    turns, offsets = split_turns(text)

    if len(turns) <= keep_k:
        print(text, end="")
        return

    old_turns = turns[: len(turns) - keep_k]
    new_turns = turns[len(turns) - keep_k :]

    compacted_lines = [f"# Thread summary (turns 1\u2013{len(old_turns)}, compacted)\n"]
    for t in old_turns:
        compacted_lines.append(compact_turn(t))
        compacted_lines.append("\n---\n")

    summary = "\n".join(compacted_lines)
    for line in summary.splitlines():
        print(f"SUMMARY:{line}", file=sys.stderr)

    # Use the byte offset recorded during split_turns instead of str.find,
    # which could match header text inside an earlier turn body.
    cut_idx = offsets[len(turns) - keep_k]
    print(text[cut_idx:], end="")


if __name__ == "__main__":
    main()
