#!/usr/bin/env python3
"""Print the ## Your Model Identity block for a given model alias.

Usage:
    python3 scripts/lib/model_identity.py --model <alias> --registry <path>

Exits 0 always -- even if the model is not found (caller decides whether to
gate on presence). Prints nothing when the model is absent from the registry.

Deprecated pricing fields (_official_before_discount, _pretax_reference) are
stripped from the Pricing line so this block can never leak list-price metadata
that confused the chat parent in the 2026-05-10 audit.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys as _sys

_sys.path.insert(0, str(pathlib.Path(__file__).parent))
from constants import DEPRECATED_PRICING_KEYS as _DEPRECATED_PRICING_KEYS  # noqa: E402


def _filtered_pricing(pricing: dict) -> dict:
    return {k: v for k, v in pricing.items() if k not in _DEPRECATED_PRICING_KEYS}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit ## Your Model Identity block.")
    parser.add_argument("--model", required=True, help="model alias from registry")
    parser.add_argument(
        "--registry",
        required=True,
        help="path to models.json (or models.example.json)",
    )
    args = parser.parse_args(argv)

    registry_path = pathlib.Path(args.registry)
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return 0  # silent -- caller gates on output presence

    m = registry.get("models", {}).get(args.model)
    if not m:
        return 0

    print("## Your Model Identity")
    print(f"You are operating as **{args.model}**.")
    if m.get("underlying"):
        print(f"- Underlying: {m['underlying']}")
    if m.get("benchmarks"):
        print(f"- Benchmarks: {m['benchmarks']}")
    if m.get("best_for"):
        print(f"- Best for: {', '.join(m['best_for'])}")
    pricing = m.get("pricing")
    if pricing:
        print(f"- Pricing: {_filtered_pricing(pricing)}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
