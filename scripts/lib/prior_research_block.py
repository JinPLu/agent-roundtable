#!/usr/bin/env python3
"""Emit markdown block listing thread artifacts/research/*.md for build_prompt."""
from __future__ import annotations

import pathlib
import re
import sys


def _queries_from_md(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[str] = []
    for m in re.finditer(r"^\*\*Query\*\*:\s*(.+)$", text, re.MULTILINE):
        q = m.group(1).strip()
        if q:
            out.append(q)
    return out[:5]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: prior_research_block.py <thread_dir>", file=sys.stderr)
        return 2
    td = pathlib.Path(sys.argv[1])
    rd = td / "artifacts" / "research"
    if not rd.is_dir():
        return 0
    mds = sorted(rd.glob("research-*.md"))
    if not mds:
        return 0
    print("## Prior research (cross-actor, in this thread)")
    print(
        "Earlier turns may have stored web/source notes under `artifacts/research/`. "
        "Open the files directly when you need citations; avoid re-querying the same question."
    )
    print()
    for p in mds:
        qs = _queries_from_md(p)
        qline = "; ".join(f'"{q}"' for q in qs[:3]) if qs else "(see file)"
        print(f"- `{p.relative_to(td)}` — {qline}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
