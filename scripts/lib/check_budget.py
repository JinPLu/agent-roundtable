#!/usr/bin/env python3
"""Check if a thread's accumulated cost exceeds its budget.

Usage: check_budget.py <thread_dir> [--budget <max_usd>]
Reads .budget_ledger.jsonl and .budget (if exists).

CX2: prefers `real_usd` (LiteLLM-priced, derived from Codex trace.jsonl /
Claude stream.jsonl) when present, and falls back to `est_usd` for ledger
entries written before CX2 landed. The summary message labels the total
as real / estimated / mixed so operators can spot legacy entries at a
glance.
"""
import json
import pathlib
import sys


def _coerce_float(v) -> float | None:
    if v is None or v == "null":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def check_budget(thread_dir: pathlib.Path, max_usd: float | None = None) -> tuple[bool, float, str]:
    """Return (under_budget, total_usd, message)."""
    ledger = thread_dir / ".budget_ledger.jsonl"
    if not ledger.exists():
        return True, 0.0, "No ledger yet"
    total = 0.0
    count = 0
    n_real = 0
    n_est = 0
    for line in ledger.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        real = _coerce_float(rec.get("real_usd"))
        est = _coerce_float(rec.get("est_usd"))
        if real is not None:
            total += real
            n_real += 1
        elif est is not None:
            total += est
            n_est += 1
        count += 1
    budget_file = thread_dir / ".budget"
    if max_usd is None and budget_file.exists():
        try:
            max_usd = float(budget_file.read_text().strip())
        except ValueError:
            pass
    if n_real and not n_est:
        label = "real"
    elif n_est and not n_real:
        label = "estimated"
    elif n_real and n_est:
        label = f"mixed: {n_real} real / {n_est} estimated"
    else:
        label = "no-cost"
    if max_usd is None:
        return True, total, (
            f"Total spent: ${total:.4f} [{label}] over {count} turns (no budget cap set)"
        )
    if total >= max_usd:
        return False, total, (
            f"BUDGET EXCEEDED: ${total:.4f} [{label}] spent of ${max_usd:.2f} cap "
            f"over {count} turns. Dispatch refused. Increase budget or escalate to user."
        )
    remaining = max_usd - total
    return True, total, (
        f"Budget OK: ${total:.4f} [{label}] of ${max_usd:.2f} used ({remaining:.4f} remaining)"
    )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("thread_dir")
    p.add_argument("--budget", type=float, default=None)
    args = p.parse_args()
    ok, total, msg = check_budget(pathlib.Path(args.thread_dir), args.budget)
    print(msg)
    sys.exit(0 if ok else 1)
