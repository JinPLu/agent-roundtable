#!/usr/bin/env python3
"""Check that the last N reviewer turns come from different actor families.

Called by claude_turn.sh / codex_turn.sh when --role is reviewer-aggregator,
to warn before aggregation if all reviewers were from the same vendor.
"""
import json
import pathlib
import re
import sys


def _extract_reviewer_actors(thread_md: str, n: int = 2) -> list[str]:
    """Return actors of the last n reviewer/devils-advocate turns from THREAD.md."""
    pattern = re.compile(
        r"^## Turn \d+ — (\S+) / (reviewer|devils-advocate) —", re.MULTILINE
    )
    matches = pattern.findall(thread_md)
    return [actor for actor, _ in matches[-n:]]


def check_diversity(thread_dir: pathlib.Path, *, n: int = 2) -> tuple[bool, str]:
    """Return (diverse_ok, message). diverse_ok=False means same-vendor pair detected."""
    thread_md = thread_dir / "THREAD.md"
    if not thread_md.exists():
        return True, "THREAD.md not found; skipping diversity check"
    actors = _extract_reviewer_actors(thread_md.read_text(), n)
    if len(actors) < 2:
        return True, f"Fewer than 2 reviewer turns found ({len(actors)}); skipping"

    def family(actor: str) -> str:
        if "codex" in actor or "openai" in actor or "gpt" in actor:
            return "openai"
        if "claude" in actor or "anthropic" in actor or "haiku" in actor or "sonnet" in actor or "opus" in actor:
            return "anthropic"
        if "cursor" in actor:
            return "cursor"
        return actor  # unknown family; treat as distinct

    families = [family(a) for a in actors]
    if len(set(families)) < 2:
        return False, (
            f"WARN: Same-vendor reviewers detected: {actors} (both {families[0]}). "
            f"Cross-vendor blind review is required (Hard Rule #6). "
            f"Re-dispatch at least one reviewer from a different actor family."
        )
    return True, f"Diversity OK: {dict(zip(actors, families))}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: check_review_diversity.py <thread_dir>", file=sys.stderr)
        sys.exit(1)
    ok, msg = check_diversity(pathlib.Path(sys.argv[1]))
    print(msg)
    sys.exit(0 if ok else 2)  # exit 2 = warn but don't hard-fail
