#!/usr/bin/env python3
"""Estimate USD from Claude Code last.json usage (coarse Anthropic-class rates)."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Fallback $/1M — sonnet-class ballpark; refine with estimate_cost later.
_INP = 3.0
_CACHE_READ = 0.30
_OUT = 15.0


def _usage_from_last(data: dict) -> dict:
    u = data.get("usage")
    if isinstance(u, dict):
        return u
    r = data.get("result")
    if isinstance(r, dict):
        u2 = r.get("usage")
        if isinstance(u2, dict):
            return u2
    return {}


def compute(last_path: pathlib.Path) -> dict:
    if not last_path.exists():
        return {"usage_found": False}
    try:
        data = json.loads(last_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {"usage_found": False}
    raw = _usage_from_last(data)
    if not raw:
        return {"usage_found": False}
    inp = int(raw.get("input_tokens") or 0)
    cr = int(raw.get("cache_read_input_tokens") or raw.get("cache_creation_input_tokens") or 0)
    out = int(raw.get("output_tokens") or 0)
    uncached = max(0, inp)
    real = (
        uncached / 1_000_000 * _INP
        + cr / 1_000_000 * _CACHE_READ
        + out / 1_000_000 * _OUT
    )
    return {
        "usage_found": True,
        "input_tokens": inp,
        "cache_read_input_tokens": cr,
        "output_tokens": out,
        "real_usd": round(real, 8),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("last_json", type=pathlib.Path)
    ap.add_argument("--write", type=pathlib.Path, default=None)
    args = ap.parse_args(argv)
    payload = compute(args.last_json)
    print(json.dumps(payload))
    if args.write:
        args.write.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0 if payload.get("usage_found") else 1


if __name__ == "__main__":
    raise SystemExit(main())
