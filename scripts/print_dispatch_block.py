#!/usr/bin/env python3
"""print_dispatch_block.py - mechanical Hard Rule #6 enforcement.

Emit the canonical Dispatch Confirmation block by reading models.json directly
+ delegating pricing/estimate to scripts/lib/route.py. The chat parent is
expected to invoke this and paste its stdout verbatim into the user-facing
confirmation - guessing pricing or quoting `_official_before_discount` /
`_pretax_reference` from memory has been the #1 source of dispatch-time
quote drift in this skill.

Usage:
    python3 scripts/print_dispatch_block.py \\
        --model gpt-5.5 --role executor [--effort medium] [--turns 1] \\
        [--multi "single turn"] [--budget "..."] \\
        [--thread <slug>] [--project <path>]

Exit codes:
    0  success
    2  unknown model / unreadable registry / pricing block missing
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

_SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
_MODELS_JSON = _SKILL_DIR / "models.json"
_ROUTE_PY = _SKILL_DIR / "scripts" / "lib" / "route.py"

_DEPRECATED_PRICING_KEYS = frozenset({"_official_before_discount", "_pretax_reference"})


def _err(msg: str, code: int = 2) -> int:
    print(f"ERROR [print_dispatch_block]: {msg}", file=sys.stderr)
    return code


def _load_registry() -> dict:
    try:
        return json.loads(_MODELS_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(_err(f"{_MODELS_JSON} not found; run scripts/backend.sh init"))
    except json.JSONDecodeError as e:
        sys.exit(_err(f"{_MODELS_JSON} is not valid JSON: {e}"))


def _resolve_model(registry: dict, alias: str) -> dict:
    m = (registry.get("models") or {}).get(alias)
    if not m:
        available = sorted(k for k in (registry.get("models") or {}) if not k.startswith("_"))
        sys.exit(_err(
            f"unknown model alias {alias!r}; available: {', '.join(available[:8])}"
            f"{' ...' if len(available) > 8 else ''}"
        ))
    return m


def _format_pricing(pricing: dict) -> str:
    """Build the price-per-1M segment, EXCLUDING deprecated keys."""
    if not pricing:
        return "no pricing in registry"
    safe = {k: v for k, v in pricing.items() if k not in _DEPRECATED_PRICING_KEYS}
    parts = []
    pin = safe.get("per_1m_input")
    pout = safe.get("per_1m_output")
    pcache = safe.get("per_1m_cached_input")
    if pin is not None:
        parts.append(f"${pin:.2f}/M-in")
    if pout is not None:
        parts.append(f"${pout:.2f}/M-out")
    if pcache is not None:
        parts.append(f"cache ${pcache:.2f}/M")
    return " ".join(parts) or "pricing block has no per_1m_* fields"


def _top_capabilities(capabilities: dict, n: int = 3) -> str:
    if not capabilities:
        return "no capability scores"
    items = sorted(capabilities.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return ", ".join(f"{k}={v}" for k, v in items)


def _best_for_first(best_for: list) -> str:
    if not best_for:
        return ""
    return f" | best_for: {best_for[0]}"


def _route_estimate(role: str, alias: str, effort: str, turns: int) -> str:
    """Call route.py and pluck the est line."""
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(_ROUTE_PY),
                "--role", role,
                "-m", alias,
                "--effort", effort,
                "--turns", str(turns),
                "--estimate",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return f"(route.py failed: {e!r})"
    out = (proc.stdout or "") + (proc.stderr or "")
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("est:"):
            return s
    return f"(no est: line in route.py output; rc={proc.returncode})"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Emit the canonical Dispatch Confirmation block. "
                    "Run by the chat parent and paste output verbatim per Hard Rule #6.",
    )
    p.add_argument("--model", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--effort", default="medium")
    p.add_argument("--turns", type=int, default=1)
    p.add_argument("--multi", default="single turn")
    p.add_argument("--budget", default="(default: 3 rounds, no clock cap)")
    p.add_argument("--thread", default="<not specified>")
    p.add_argument("--project", default="<not specified>")
    args = p.parse_args(argv)

    registry = _load_registry()
    m = _resolve_model(registry, args.model)
    actor = m.get("actor", "?")
    cli_arg = m.get("cli_arg", "?")
    endpoint = m.get("endpoint") or {}
    base_url = endpoint.get("base_url", "")

    # Route description disambiguates CLI vs Cursor subagent paths.
    # Two models with the same underlying vendor (e.g. Anthropic) may resolve to
    # different actor families with different prices, proxies, and failure modes.
    if actor == "cursor-subagent":
        route_str = f"Cursor subagent (Task in IDE)  →  cli_arg: {cli_arg}"
    elif actor == "claude":
        route_str = f"Claude Code CLI → {base_url or '?'}  →  cli_arg: {cli_arg}"
    elif actor == "codex":
        route_str = f"Codex CLI → {base_url or '?'}  →  cli_arg: {cli_arg}"
    else:
        route_str = f"actor={actor}  →  cli_arg: {cli_arg}"

    pricing_str = _format_pricing(m.get("pricing") or {})
    capability_str = _top_capabilities(m.get("capabilities") or {})
    best_for_str = _best_for_first(m.get("best_for") or [])
    specs = f"{pricing_str} | {capability_str}{best_for_str}"

    est = _route_estimate(args.role, args.model, args.effort, args.turns)

    block = [
        "Proposed dispatch",
        f"  Thread  : {args.thread}",
        f"  Project : {args.project}",
        f"  Role    : {args.role}",
        f"  Alias   : {args.model}  ({actor})",
        f"  Route   : {route_str}",
        f"  Specs   : {specs}",
        f"  Effort  : {args.effort}",
        f"  Est.    : {est}",
        f"  Multi?  : {args.multi}",
        f"  Budget  : {args.budget}",
    ]
    out = "\n".join(block)

    # Foot-gun guard: deprecated pricing keys must never appear in user-facing output.
    for forbidden in _DEPRECATED_PRICING_KEYS:
        if forbidden in out:
            return _err(f"output contains deprecated pricing key {forbidden!r}; this is a bug")

    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
