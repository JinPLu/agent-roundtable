#!/usr/bin/env python3
"""Wrapper-side helper: extract `usage` from a turn's JSON output and append
one line to `$ROUNDTABLE_PROJECT_ROOT/.roundtable/usage.log`.

Called from `codex_turn.sh` (trace.jsonl) and `claude_turn.sh` (last.json)
after the turn body has been parsed. NEVER changes the wrapper's exit
status — failures print a stderr warning and exit 0 (the wrapper checks
this).

Invocation
----------
    log_turn_usage.py
        --actor codex|claude
        --thread <slug>
        --model <cli_arg>
        --role <role>
        --effort <level>
        --exit-code <int>
        --elapsed-s <int>
        [--cost-estimated-usd <float>]   # what estimate_cost predicted
        [--source-file <path>]           # trace.jsonl (codex) or last.json (claude)

Stdlib only.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import usage_log  # noqa: E402


def _extract_codex_usage(trace_path: pathlib.Path) -> dict:
    """Walk Codex's `--json` event stream looking for the latest `usage`.

    The Codex CLI emits JSONL events; a `token_count` / `agent_message`
    event near end-of-turn contains a `usage` block. We pick the LAST
    one we see so multi-step turns roll up correctly.

    Returns {} when no usage payload is found (e.g. timeout before flush).
    """
    if not trace_path.exists():
        return {}
    last_usage: dict = {}
    try:
        for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line[0] != "{":
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Codex events nest payloads under 'msg' or expose 'usage' directly.
            for candidate in (evt, evt.get("msg") or {}, evt.get("payload") or {}):
                if isinstance(candidate, dict):
                    u = candidate.get("usage") or candidate.get("info", {}).get("total_token_usage")
                    if isinstance(u, dict):
                        last_usage = u
    except OSError:
        return {}
    return last_usage


def _extract_claude_usage(json_path: pathlib.Path) -> dict:
    """Pluck `usage` from Claude Code's `--output-format json` payload.

    Claude returns a top-level `usage` object on completion turns; some
    permission-mode shapes nest it under `result.usage`. We try both.
    """
    if not json_path.exists():
        return {}
    try:
        data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}
    for path in (("usage",), ("result", "usage"), ("messages", -1, "usage")):
        cur: object = data
        ok = True
        for key in path:
            if isinstance(key, int) and isinstance(cur, list) and -len(cur) <= key < len(cur):
                cur = cur[key]
                continue
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
                continue
            ok = False
            break
        if ok and isinstance(cur, dict):
            return cur
    return {}


def _normalize_usage(actor: str, raw: dict) -> dict:
    """Map provider-specific keys to our log schema.

    Accepts:
      OpenAI / Codex shape: prompt_tokens, completion_tokens, completion_tokens_details.reasoning_tokens
      Anthropic / Claude shape: input_tokens, output_tokens, cache_read_input_tokens
                               (no reasoning split — thinking tokens roll into output)
      Cursor (best-effort): same as upstream provider when surfaced

    Missing / unparseable values become None (logged as JSON null).
    """

    def _get_int(*keys: str) -> int | None:
        for k in keys:
            v = raw.get(k)
            if isinstance(v, int):
                return v
            if isinstance(v, str) and v.isdigit():
                return int(v)
        return None

    out: dict = {
        "prompt_tokens": _get_int("prompt_tokens", "input_tokens"),
        "completion_tokens": _get_int("completion_tokens", "output_tokens"),
        "reasoning_tokens": 0,
    }
    details = raw.get("completion_tokens_details") or raw.get("output_tokens_details")
    if isinstance(details, dict):
        rt = details.get("reasoning_tokens")
        if isinstance(rt, int):
            out["reasoning_tokens"] = rt
    return out


def _maybe_actual_cost(actor: str, raw: dict) -> float | None:
    """Some providers (OpenRouter, Aider via LiteLLM) return cost; Cursor
    pool models do not. We pluck the obvious keys and otherwise return None.
    """
    for key in ("cost", "total_cost_usd", "total_cost"):
        v = raw.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    cd = raw.get("cost_details")
    if isinstance(cd, dict):
        v = cd.get("upstream_inference_cost") or cd.get("total_cost")
        if isinstance(v, (int, float)):
            return float(v)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--actor", required=True, choices=["codex", "claude", "cursor-subagent"])
    parser.add_argument("--thread", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--effort", default=None)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--elapsed-s", type=int, default=0)
    parser.add_argument("--cost-estimated-usd", type=float, default=None)
    parser.add_argument("--source-file", default=None, help="trace.jsonl / last.json")
    parser.add_argument("--log", default=None, help="override usage.log path")
    args = parser.parse_args(argv)

    raw: dict = {}
    src_path = pathlib.Path(args.source_file) if args.source_file else None
    if src_path is not None and src_path.exists():
        if args.actor == "codex":
            raw = _extract_codex_usage(src_path)
        elif args.actor == "claude":
            raw = _extract_claude_usage(src_path)

    norm = _normalize_usage(args.actor, raw)
    actual = _maybe_actual_cost(args.actor, raw)
    record = {
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "thread": args.thread,
        "actor": args.actor,
        "model": args.model,
        "role": args.role,
        "effort": args.effort,
        "prompt_tokens": norm["prompt_tokens"],
        "completion_tokens": norm["completion_tokens"],
        "reasoning_tokens": norm["reasoning_tokens"] or 0,
        "cost_estimated_usd": args.cost_estimated_usd,
        "cost_actual_usd": actual,
        "elapsed_s": args.elapsed_s,
        "exit_code": args.exit_code,
    }
    try:
        usage_log.append_usage_record(record, log_path=args.log)
    except Exception as exc:  # noqa: BLE001 — wrapper hook MUST not propagate
        print(
            f"WARN [log_turn_usage.py]: usage append failed: {exc!r}",
            file=sys.stderr,
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
