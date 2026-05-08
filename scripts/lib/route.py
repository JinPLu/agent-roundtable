#!/usr/bin/env python3
"""Signal-based model routing for agent-roundtable.

Starts from role_defaults ordering, filters by actor availability,
then applies optional signals to reorder/filter candidates.
"""
import argparse, json, os, pathlib, shutil, subprocess

REGISTRY = pathlib.Path(__file__).resolve().parents[2] / "models.json"
FALLBACKS = {
    "planner": ["gpt-5.5", "claude-opus"],
    "executor": ["gpt-5.5", "claude-opus"],
    "reviewer": ["gpt-5.5", "claude-opus", "cursor-claude-4.7-opus"],
    "discussant": ["gpt-5.5", "claude-opus"],
}


def ok(cmd, needle=None):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = f"{out.stdout}\n{out.stderr}"
    return out.returncode == 0 and (needle is None or needle in text)


def _claude_authed():
    try:
        out = subprocess.run(
            ["claude", "auth", "status"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if out.returncode != 0:
        return False
    text = f"{out.stdout}\n{out.stderr}"
    return "loggedIn: true" in text or '"loggedIn": true' in text


def detect_actors(cursor_subagent):
    actors = set()
    codex_env = os.environ.get("CODEX_AVAILABLE")
    claude_env = os.environ.get("CLAUDE_AVAILABLE")
    if codex_env == "1" or (
        codex_env != "0"
        and shutil.which("codex")
        and ok(["codex", "login", "status"])
    ):
        actors.add("codex")
    if claude_env == "1" or (
        claude_env != "0" and shutil.which("claude") and _claude_authed()
    ):
        actors.add("claude")
    if cursor_subagent or os.environ.get("CURSOR_SUBAGENT_AVAILABLE") == "1":
        actors.add("cursor-subagent")
    return actors


def _input_cost(model: dict) -> float:
    return model.get("pricing", {}).get("per_1m_input", 999)


def apply_signals(rows, *, budget=None, latency=None, output_heavy=False):
    """Filter and reorder candidates based on task signals."""
    filtered = list(rows)

    if latency == "fast":
        filtered = [r for r in filtered if r.get("actor") != "cursor-subagent"]

    if output_heavy:
        filtered = [
            r for r in filtered
            if (r.get("max_output_k") or 128) >= 128
        ]

    if budget == "cheap":
        filtered.sort(key=_input_cost)
    elif budget == "premium":
        # Sort by best available SWE-bench score descending; untested models last.
        def _quality(r):
            b = r.get("benchmarks", {})
            return max(
                b.get("swe_bench_verified", 0),
                b.get("swe_bench_pro", 0),
                b.get("terminal_bench_2", 0),
            )
        filtered.sort(key=_quality, reverse=True)

    return filtered


def recommend(role, top, json_out, cursor_subagent, budget, latency, output_heavy):
    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise SystemExit(f"failed to load {REGISTRY}: {exc}") from exc
    models = registry.get("models", {})
    available = detect_actors(cursor_subagent)
    aliases = registry.get("role_defaults", {}).get(role) or FALLBACKS.get(role)
    if not aliases:
        raise SystemExit(f"unknown role: {role}")

    rows = []
    for alias in aliases:
        model = models.get(alias)
        if model and model.get("actor") in available:
            rows.append({"alias": alias, **model})

    has_signals = budget or latency or output_heavy
    if has_signals:
        rows = apply_signals(
            rows, budget=budget, latency=latency, output_heavy=output_heavy
        )

    rows = rows[:top]

    if json_out:
        out = {
            "role": role,
            "available_actors": sorted(available),
            "candidates": rows,
        }
        if has_signals:
            out["signals"] = {
                "budget": budget,
                "latency": latency,
                "output_heavy": output_heavy,
            }
        print(json.dumps(out, indent=2))
    else:
        print(f"role={role}")
        print("available_actors=" + ",".join(sorted(available)))
        if has_signals:
            parts = []
            if budget:
                parts.append(f"budget={budget}")
            if latency:
                parts.append(f"latency={latency}")
            if output_heavy:
                parts.append("output_heavy")
            print("signals=" + ",".join(parts))
        for i, row in enumerate(rows, 1):
            benchmarks = row.get("benchmarks", {})
            bench_str = ""
            if benchmarks:
                top_scores = sorted(benchmarks.items(), key=lambda x: -x[1])[:2]
                bench_str = " | " + ", ".join(
                    f"{k}={v}" for k, v in top_scores
                )
            cost = _input_cost(row)
            print(
                f"{i}. {row['actor']}/{row['alias']}"
                f"  cli_arg={row.get('cli_arg')}"
                f"  ${cost:.4f}/M-in{bench_str}"
            )
    return 0 if rows else 1


def main():
    parser = argparse.ArgumentParser(
        description="Recommend models for a roundtable role, with optional task signals."
    )
    parser.add_argument("--role", required=True)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cursor-subagent", action="store_true")
    parser.add_argument(
        "--budget",
        choices=["cheap", "normal", "premium"],
        default=None,
        help="cheap=sort by cost asc; premium=sort by benchmark desc",
    )
    parser.add_argument(
        "--latency",
        choices=["fast", "normal"],
        default=None,
        help="fast=exclude cursor-subagent (unbounded queue)",
    )
    parser.add_argument(
        "--output-heavy",
        action="store_true",
        default=False,
        help="Exclude models with max_output_k < 128K",
    )
    args = parser.parse_args()
    return recommend(
        args.role,
        args.top,
        args.json,
        args.cursor_subagent,
        args.budget,
        args.latency,
        args.output_heavy,
    )


if __name__ == "__main__":
    raise SystemExit(main())
