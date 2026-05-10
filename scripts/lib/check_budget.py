#!/usr/bin/env python3
"""Check if a thread's accumulated estimated cost exceeds its budget.

Usage: check_budget.py <thread_dir> [--budget <max_usd>]
Reads .budget_ledger.jsonl and .budget (if exists).
"""
import json
import pathlib
import sys


def check_budget(thread_dir: pathlib.Path, max_usd: float | None = None) -> tuple[bool, float, str]:
    """Return (under_budget, total_est_usd, message)."""
    ledger = thread_dir / ".budget_ledger.jsonl"
    if not ledger.exists():
        return True, 0.0, "No ledger yet"
    total = 0.0
    count = 0
    for line in ledger.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            val = rec.get("est_usd")
            if val is not None and val != "null":
                total += float(val)
            count += 1
        except (json.JSONDecodeError, ValueError):
            continue
    budget_file = thread_dir / ".budget"
    if max_usd is None and budget_file.exists():
        try:
            max_usd = float(budget_file.read_text().strip())
        except ValueError:
            pass
    if max_usd is None:
        return True, total, f"Total spent: ${total:.4f} over {count} turns (no budget cap set)"
    if total >= max_usd:
        return False, total, (
            f"BUDGET EXCEEDED: ${total:.4f} spent of ${max_usd:.2f} cap over {count} turns. "
            f"Dispatch refused. Increase budget or escalate to user."
        )
    remaining = max_usd - total
    return True, total, f"Budget OK: ${total:.4f} of ${max_usd:.2f} used ({remaining:.4f} remaining)"


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("thread_dir")
    p.add_argument("--budget", type=float, default=None)
    args = p.parse_args()
    ok, total, msg = check_budget(pathlib.Path(args.thread_dir), args.budget)
    print(msg)
    sys.exit(0 if ok else 1)
