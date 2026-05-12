#!/usr/bin/env python3
"""extract_codex_usage.py — turn Codex `--json` trace.jsonl into a usage blob.

Reads the streaming Codex CLI trace (one JSON event per line) and rolls up
the LAST observed `usage` payload (multi-step turns aggregate as the trace
progresses; the last event reflects total spend). Costs are computed from
the bundled LiteLLM pricing snapshot (preferred) with a hard-coded gpt-5
family fallback so the script keeps working when the snapshot is missing.

Output JSON shape (printed to stdout, also written to <out> when --out set):

    {
      "input_tokens": int,
      "cached_input_tokens": int,
      "output_tokens": int,
      "reasoning_tokens": int,
      "cached_input_ratio": float,
      "real_usd": float,
      "real_usd_uncached_equivalent": float,
      "model": str,
      "source": "codex-trace"
    }

Stdlib only.

Exit codes
----------
0 — usage extracted (or trace empty / unparseable; we still emit zeros so
    downstream consumers don't choke on missing files)
2 — usage extraction failed in an unexpected way
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Optional

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    import pricing_snapshot  # type: ignore
except Exception:  # noqa: BLE001 — snapshot is optional
    pricing_snapshot = None  # type: ignore

# Hard-coded gpt-5-class pricing fallback (per 1M tokens).
# Source: https://platform.openai.com/docs/pricing (2026-02 snapshot;
# matches the plan's documented constants: cached $0.09 / M, uncached
# $0.42 / M, output $1.68 / M). Use when the LiteLLM snapshot lacks the
# model id or when pricing_snapshot import failed.
_GPT5_FALLBACK_PER_1M = {
    "per_1m_input": 0.42,
    "per_1m_cached_input": 0.09,
    "per_1m_output": 1.68,
}


def _iter_events(trace_path: pathlib.Path):
    if not trace_path.exists():
        return
    with trace_path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line[0] != "{":
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _walk_usage(trace_path: pathlib.Path) -> tuple[dict, str]:
    """Return (last_usage_dict, model_name).

    Codex emits several event shapes across versions:
      - `{"type": "turn.completed", "usage": {...}, "model": "..."}`
      - `{"msg": {"type": "token_count", "usage": {...}}}`
      - `{"info": {"total_token_usage": {...}}}`
    We take the LAST usage payload seen — `turn.completed` is preferred but
    not required.
    """
    last_usage: dict = {}
    model = ""
    for evt in _iter_events(trace_path):
        candidates = [evt]
        for k in ("msg", "payload", "data", "info"):
            v = evt.get(k)
            if isinstance(v, dict):
                candidates.append(v)
        for c in candidates:
            u = c.get("usage") or c.get("total_token_usage")
            if isinstance(u, dict):
                last_usage = u
            m = c.get("model") or c.get("model_name")
            if isinstance(m, str) and m:
                model = m
    return last_usage, model


def _to_int(v: object) -> int:
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str) and v.lstrip("-").isdigit():
        return int(v)
    return 0


def _resolve_pricing(model: str) -> dict:
    if pricing_snapshot is not None and model:
        try:
            p = pricing_snapshot.get_model_pricing(model)
            if p:
                return {
                    "per_1m_input": p.get("per_1m_input") or 0.0,
                    "per_1m_cached_input": p.get("per_1m_cached_input"),
                    "per_1m_output": p.get("per_1m_output") or 0.0,
                }
        except Exception:  # noqa: BLE001 — fall back silently
            pass
    return dict(_GPT5_FALLBACK_PER_1M)


def compute_usage(trace_path: pathlib.Path, model_hint: str = "") -> dict:
    raw, model = _walk_usage(trace_path)
    if not model:
        model = model_hint
    usage_found = bool(raw)

    # Codex usage shapes:
    #   {"input_tokens": N, "cached_input_tokens": M, "output_tokens": K,
    #    "reasoning_output_tokens": R}
    # OpenAI legacy:
    #   {"prompt_tokens": N, "prompt_tokens_details": {"cached_tokens": M},
    #    "completion_tokens": K,
    #    "completion_tokens_details": {"reasoning_tokens": R}}
    input_tokens = _to_int(raw.get("input_tokens") or raw.get("prompt_tokens"))
    cached_input_tokens = _to_int(
        raw.get("cached_input_tokens")
        or (raw.get("prompt_tokens_details") or {}).get("cached_tokens")
        or (raw.get("input_tokens_details") or {}).get("cached_tokens")
    )
    output_tokens = _to_int(raw.get("output_tokens") or raw.get("completion_tokens"))
    reasoning_tokens = _to_int(
        raw.get("reasoning_output_tokens")
        or (raw.get("completion_tokens_details") or {}).get("reasoning_tokens")
        or (raw.get("output_tokens_details") or {}).get("reasoning_tokens")
    )

    pricing = _resolve_pricing(model)
    per_in = float(pricing.get("per_1m_input") or 0.0)
    per_cached = pricing.get("per_1m_cached_input")
    per_cached = float(per_cached) if per_cached is not None else per_in
    per_out = float(pricing.get("per_1m_output") or 0.0)

    fresh_input = max(0, input_tokens - cached_input_tokens)
    real_usd = (
        (fresh_input * per_in / 1_000_000.0)
        + (cached_input_tokens * per_cached / 1_000_000.0)
        + (output_tokens * per_out / 1_000_000.0)
    )
    real_usd_uncached_equivalent = (
        (input_tokens * per_in / 1_000_000.0)
        + (output_tokens * per_out / 1_000_000.0)
    )
    ratio = 0.0
    if input_tokens > 0:
        ratio = cached_input_tokens / float(input_tokens)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_input_ratio": round(ratio, 4),
        "real_usd": round(real_usd, 6),
        "real_usd_uncached_equivalent": round(real_usd_uncached_equivalent, 6),
        "model": model or "unknown",
        "source": "codex-trace",
        "usage_found": usage_found,
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("trace", help="Path to trace.jsonl produced by `codex exec --json`.")
    # --write is the canonical name; --out is kept as a synonym.
    p.add_argument("--write", "--out", dest="out", default=None,
                   help="Path to write the JSON output to (also printed to stdout).")
    p.add_argument("--model", default="", help="Model hint when trace lacks one.")
    args = p.parse_args(argv)

    try:
        usage = compute_usage(pathlib.Path(args.trace), args.model)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN [extract_codex_usage]: {exc!r}", file=sys.stderr)
        return 2

    blob = json.dumps(usage, indent=2)
    print(blob)
    if args.out:
        try:
            pathlib.Path(args.out).write_text(blob + "\n")
        except OSError as exc:
            print(f"WARN [extract_codex_usage]: could not write {args.out}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
