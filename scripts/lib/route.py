#!/usr/bin/env python3
"""Signal-based model routing for agent-roundtable.

Starts from role_defaults ordering, filters by actor availability,
then applies optional signals to reorder/filter candidates.
"""
import argparse, json, os, pathlib, shutil, subprocess, sys

_SKILL_DIR = pathlib.Path(__file__).resolve().parents[2]
# Prefer the user's gitignored models.json; fall back to the shipped example
# catalog so route.sh works on a fresh clone before `backend.sh init`.
REGISTRY = _SKILL_DIR / "models.json"
if not REGISTRY.exists():
    REGISTRY = _SKILL_DIR / "models.example.json"

# No hardcoded fallbacks — the registry's role_defaults is the source of truth.
# When a role has no aliases registered, route_for_role() warns and returns [].
FALLBACKS: dict[str, list[str]] = {}


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


def apply_signals(rows, *, budget=None, latency=None, output_heavy=False, diversity=False):
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

    # Diversity: keep at most one candidate per distinct actor family. This
    # mechanises Hard Rule #7 — cross-vendor diversity is required for multi-reviewer
    # rounds (same-actor reviewers exhibit sycophantic conformity, L4 / arXiv 2605.00914).
    if diversity:
        seen: set = set()
        deduped = []
        for r in filtered:
            key = r.get("actor")
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        filtered = deduped

    return filtered


def suggest_companion(primary_row: dict, all_rows: list[dict]) -> dict | None:
    """Return the cheapest available model from a different actor than primary_row.

    Used to implement Principle A: every expensive dispatch should have a cheap
    cross-vendor companion running in parallel. The companion must be dispatched
    with --blind to prevent modal adoption sycophancy.
    """
    primary_actor = primary_row.get("actor")
    candidates = [r for r in all_rows if r.get("actor") != primary_actor]
    if not candidates:
        return None
    return min(candidates, key=_input_cost)


def recommend(
    role, top, json_out, cursor_subagent, budget, latency, output_heavy,
    diversity=False, blind=False, companion=None,
):
    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise SystemExit(f"failed to load {REGISTRY}: {exc}") from exc
    models = registry.get("models", {})
    available = detect_actors(cursor_subagent)
    aliases = registry.get("role_defaults", {}).get(role) or FALLBACKS.get(role)
    if not aliases:
        print(
            f"WARNING: no aliases registered for role {role!r} in role_defaults; "
            f"pass -m explicitly",
            file=sys.stderr,
        )
        aliases = []

    all_rows = []
    for alias in aliases:
        model = models.get(alias)
        if model and model.get("actor") in available:
            all_rows.append({"alias": alias, **model})

    has_signals = budget or latency or output_heavy or diversity
    if has_signals:
        rows = apply_signals(
            all_rows, budget=budget, latency=latency,
            output_heavy=output_heavy, diversity=diversity,
        )
    else:
        rows = list(all_rows)

    rows = rows[:top]

    # Resolve companion: either an explicit model name or auto-select cheapest
    # cross-actor model. Companion is always dispatched with --blind (Principle A).
    companion_row: dict | None = None
    if companion == "auto" and rows:
        companion_row = suggest_companion(rows[0], all_rows)
    elif companion and companion != "auto":
        m = models.get(companion)
        if m and m.get("actor") in available:
            companion_row = {"alias": companion, **m}
        else:
            print(
                f"WARN: --companion {companion!r} not found or unavailable; skipping",
                file=sys.stderr,
            )

    if json_out:
        out: dict = {
            "role": role,
            "available_actors": sorted(available),
            "candidates": rows,
        }
        signal_dict: dict = {}
        if budget:
            signal_dict["budget"] = budget
        if latency:
            signal_dict["latency"] = latency
        if output_heavy:
            signal_dict["output_heavy"] = output_heavy
        if diversity:
            signal_dict["diversity"] = True
        if blind:
            signal_dict["blind"] = True
        if signal_dict:
            out["signals"] = signal_dict
        if companion_row is not None:
            out["companion"] = {
                "model": companion_row,
                "dispatch_flags": ["--blind"],
                "note": (
                    "Cheap cross-vendor companion (Principle A). "
                    "Dispatch with --blind alongside the primary candidate."
                ),
            }
        print(json.dumps(out, indent=2))
    else:
        print(f"role={role}")
        print("available_actors=" + ",".join(sorted(available)))
        parts = []
        if budget:
            parts.append(f"budget={budget}")
        if latency:
            parts.append(f"latency={latency}")
        if output_heavy:
            parts.append("output_heavy")
        if diversity:
            parts.append("diversity")
        if blind:
            parts.append("blind")
        if parts:
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
        if companion_row is not None:
            cost = _input_cost(companion_row)
            print(
                f"companion (--blind): {companion_row['actor']}/{companion_row['alias']}"
                f"  cli_arg={companion_row.get('cli_arg')}"
                f"  ${cost:.4f}/M-in"
                "  [dispatch alongside primary with --blind; Principle A]"
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
    parser.add_argument(
        "--diversity",
        action="store_true",
        default=False,
        help=(
            "Return at most one candidate per distinct actor family, enforcing "
            "cross-vendor diversity (Hard Rule #7). Mechanises the requirement "
            "that multi-reviewer rounds use agents from different vendors."
        ),
    )
    parser.add_argument(
        "--blind",
        action="store_true",
        default=False,
        help=(
            "Tag routing output with blind=true. Signals that every dispatched "
            "reviewer turn must include --blind to prevent modal adoption sycophancy "
            "(85.5%% rate when agents see prior verdicts, per arXiv 2605.00914)."
        ),
    )
    parser.add_argument(
        "--companion",
        default=None,
        metavar="auto|MODEL",
        help=(
            "Suggest a cheap cross-vendor companion for the primary candidate "
            "(Principle A). 'auto' selects cheapest available other-actor model; "
            "MODEL specifies an explicit alias. Companion must be dispatched with "
            "--blind alongside the primary."
        ),
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
        diversity=args.diversity,
        blind=args.blind,
        companion=args.companion,
    )


if __name__ == "__main__":
    raise SystemExit(main())
