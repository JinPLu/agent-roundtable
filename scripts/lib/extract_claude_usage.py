#!/usr/bin/env python3
"""Estimate USD from Claude Code last.json usage.

Verification pending — run smoke_claude_usage_extractor.py before
relying on this in production.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from pricing_snapshot import SnapshotError, get_model_pricing

# Fallback $/1M — sonnet-class ballpark when LiteLLM has no model entry.
_FALLBACK_PRICING = {
    "per_1m_input": 3.0,
    "per_1m_cache_creation": 3.75,
    "per_1m_cached_input": 0.30,
    "per_1m_output": 15.0,
}
_FALLBACK_SOURCE = "fallback-sonnet-ballpark"


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


def _model_from_last(data: dict) -> str:
    model = data.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    result = data.get("result")
    if isinstance(result, dict):
        nested = result.get("model")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return ""


def _int_usage(raw: dict, key: str) -> int:
    try:
        return max(0, int(raw.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def _pricing_for_model(model: str) -> tuple[dict, str]:
    pricing = None
    if model:
        try:
            pricing = get_model_pricing(model)
        except SnapshotError:
            pricing = None
    if not pricing:
        print(f"WARN [extract_claude_usage]: model {model or 'unknown'} not in snapshot, using sonnet-ballpark", file=sys.stderr)
        return dict(_FALLBACK_PRICING), _FALLBACK_SOURCE

    per_1m_input = float(pricing["per_1m_input"])
    per_1m_cache_creation = pricing.get("per_1m_cache_creation")
    per_1m_cached_input = pricing.get("per_1m_cached_input")
    return {
        "per_1m_input": per_1m_input,
        "per_1m_cache_creation": (
            float(per_1m_cache_creation)
            if per_1m_cache_creation is not None
            else per_1m_input * 1.25
        ),
        "per_1m_cached_input": (
            float(per_1m_cached_input)
            if per_1m_cached_input is not None
            else per_1m_input * 0.1
        ),
        "per_1m_output": float(pricing["per_1m_output"]),
    }, str(pricing.get("_source") or "litellm-snapshot")


def compute(last_path: pathlib.Path) -> dict:
    if not last_path.exists():
        return {"usage_found": False, "error": "file_missing"}
    try:
        data = json.loads(last_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {"usage_found": False, "error": "parse_error"}
    raw = _usage_from_last(data)
    if not raw:
        return {"usage_found": False, "error": "no_usage_block"}
    model = _model_from_last(data)
    pricing, pricing_source = _pricing_for_model(model)
    inp = _int_usage(raw, "input_tokens")
    cache_creation = _int_usage(raw, "cache_creation_input_tokens")
    cache_read = _int_usage(raw, "cache_read_input_tokens")
    out = _int_usage(raw, "output_tokens")
    total_input_like = inp + cache_creation + cache_read
    
    cache_creation_ratio = (
        round(cache_creation / total_input_like, 6)
        if total_input_like else 0.0
    )
    cache_read_ratio = (
        round(cache_read / total_input_like, 6)
        if total_input_like else 0.0
    )
    
    real = (
        inp / 1_000_000 * pricing["per_1m_input"]
        + cache_creation / 1_000_000 * pricing["per_1m_cache_creation"]
        + cache_read / 1_000_000 * pricing["per_1m_cached_input"]
        + out / 1_000_000 * pricing["per_1m_output"]
    )
    return {
        "usage_found": True,
        "model": model,
        "input_tokens": inp,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "output_tokens": out,
        "cache_creation_ratio": cache_creation_ratio,
        "cache_read_ratio": cache_read_ratio,
        "pricing_source": pricing_source,
        "real_usd": round(real, 6),
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
